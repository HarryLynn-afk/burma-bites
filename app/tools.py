# Copyright 2026 Burma Bites
#
# Business logic layer — pure Python tool functions shared by all agents.
#
# ── ARCHITECTURE POSITION ────────────────────────────────────────────────────
# tools.py sits BELOW the MCP layer and ABOVE the data layer:
#
#   LLM agents  →  mcp_server.py (validation)  →  tools.py (business logic)
#                                                       ↓
#                                                    menu.py (data/state)
#
# WHY NO INPUT VALIDATION IN THIS FILE?
# Input validation is the MCP server's responsibility (mcp_server.py).
# By the time execution reaches these functions, all inputs have been
# type-checked, length-capped, and allowlist-verified. This separation means:
#   1. These functions can be tested with clean, known-good inputs.
#   2. The validation rules live in exactly one place (mcp_server.py).
#   3. These functions remain simple and readable — no guard clauses cluttering
#      the business logic.
#
# ── ADK TOOL CONVENTIONS FOLLOWED HERE ──────────────────────────────────────
# Each function:
#   - Is fully type-hinted (ADK uses type hints to generate tool schemas).
#   - Has a docstring whose first line becomes the LLM-visible tool description.
#   - Returns a JSON-serialisable dict — ADK serializes tool outputs to JSON
#     before passing them back to the LLM as tool result parts.
#   - Uses {status: "success"|"error"} as the outer envelope so the LLM can
#     detect failures without parsing free-form text.
#   - Optionally accepts ToolContext as the LAST positional argument (ADK
#     convention) — omitted here since we use session state via menu.py globals.

from __future__ import annotations

import json
from typing import Any

from google.adk.tools import ToolContext

from .menu import (
    INVENTORY,
    MENU,
    MENU_BY_ID,
    ORDERS,
    SALES_TODAY,
    LOW_STOCK_THRESHOLD,
    create_order,
    get_low_stock_items,
    update_order_status,
)


# ============================================================
# CUSTOMER AGENT TOOLS
# ============================================================
# WHY THESE FOUR TOOLS FOR THE CUSTOMER AGENT?
# A front-of-house agent needs to:
#   1. Show the menu (list_menu) — browsing and menu questions
#   2. Describe individual dishes (get_item_details) — allergen queries,
#      "tell me more about mohinga"-style questions
#   3. Submit orders (place_order) — the core transaction
#   4. Check order progress (get_order_status) — "where is my food?" queries
#
# The customer agent deliberately CANNOT update kitchen statuses, see full
# inventory counts, or access sales data — that information belongs to staff.


def list_menu(category: str) -> dict[str, Any]:
    """Return all menu items, optionally filtered by category.

    Args:
        category: Filter by category. Use "all" for everything, or one of:
                  "food", "drink", "side".

    Returns:
        dict with "items" list containing name, price, and allergen info.
    """
    if category == "all":
        items = MENU
    else:
        # Simple category filter — the allowed category values are validated
        # upstream in mcp_server.py before this function is called.
        items = [i for i in MENU if i["category"] == category]

    result = []
    for item in items:
        result.append({
            "id":          item["id"],
            "name_en":     item["name_en"],
            "name_my":     item["name_my"],   # Burmese script for Burmese customers
            "name_th":     item["name_th"],   # Thai for Thai-speaking customers
            "category":    item["category"],
            "price_thb":   item["price_thb"],
            "description": item["description"],
            "allergens":   item["allergens"],
            # WHY EXPOSE in_stock AS A BOOLEAN INSTEAD OF THE COUNT?
            # The customer should know whether a dish is available, not how
            # many portions are left (that's the owner's data). A boolean
            # prevents information leakage about inventory levels.
            "in_stock":    INVENTORY.get(item["id"], 0) > 0,
        })

    return {"status": "success", "category": category, "items": result}


def get_item_details(item_id: str) -> dict[str, Any]:
    """Get full details for a single menu item including stock availability.

    Args:
        item_id: The unique ID of the menu item (e.g. "mohinga", "laphet_thoke").

    Returns:
        dict with full item details and current stock count.
    """
    item = MENU_BY_ID.get(item_id)
    if not item:
        # Descriptive error message helps the LLM recover gracefully by
        # suggesting the correct tool (list_menu) to find valid IDs.
        return {"status": "error", "message": f"Item '{item_id}' not found. Use list_menu to see available items."}

    return {
        "status":      "success",
        "id":          item["id"],
        "name_en":     item["name_en"],
        "name_my":     item["name_my"],
        "name_th":     item["name_th"],
        "category":    item["category"],
        "price_thb":   item["price_thb"],
        "description": item["description"],
        "allergens":   item["allergens"],
        # For item details (unlike list_menu), we expose the actual stock count
        # so the agent can say "only 3 portions left — order quickly!" when useful.
        "stock":       INVENTORY.get(item["id"], 0),
    }


def place_order(items_json: str, table_number: str) -> dict[str, Any]:
    """Place a confirmed customer order and send it to the kitchen.

    Call this ONLY after the customer has verbally confirmed their full order.
    Do NOT call this speculatively — always confirm with the customer first.

    WHY ACCEPT items_json AS A STRING INSTEAD OF A LIST?
    ADK tool parameters are passed as JSON from the LLM. When the LLM builds
    a list argument, some versions of Gemini serialize it as a JSON string
    rather than a native JSON array. Accepting a string and parsing it here
    ensures compatibility across model versions without schema gymnastics.

    Args:
        items_json: JSON string of a list of objects, each with "item_id" and
                    "quantity". Example: '[{"item_id": "mohinga", "quantity": 2}]'
        table_number: Table number or identifier (e.g. "3", "takeaway").

    Returns:
        dict with the created order including order_id, items, and total price.
    """
    try:
        items = json.loads(items_json)
    except json.JSONDecodeError as exc:
        return {"status": "error", "message": f"Invalid items_json: {exc}"}

    # Pre-flight stock check BEFORE calling create_order.
    # WHY NOT LET create_order HANDLE THIS?
    # create_order raises ValueError on unknown items but does NOT check stock
    # levels before deducting. If we let it run, it might partially deduct
    # inventory for valid items before hitting an out-of-stock item — leaving
    # inventory in an inconsistent state. This check prevents partial mutations.
    for line in items:
        item_id  = line.get("item_id", "")
        quantity = int(line.get("quantity", 1))
        if item_id not in MENU_BY_ID:
            return {"status": "error", "message": f"Unknown item: {item_id}"}
        stock = INVENTORY.get(item_id, 0)
        if stock < quantity:
            name = MENU_BY_ID[item_id]["name_en"]
            return {
                "status":  "error",
                "message": f"Not enough stock for {name}. Available: {stock}, requested: {quantity}.",
            }

    try:
        order = create_order(items, table_number)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    return {
        "status":    "success",
        "message":   f"Order #{order['order_id']} placed successfully!",
        "order":     order,
    }


def get_order_status(order_id: str) -> dict[str, Any]:
    """Check the current status of a customer's order.

    Args:
        order_id: The 8-character order ID returned when the order was placed.

    Returns:
        dict with order details including current status.
    """
    # .upper() normalizes IDs since customers might type lowercase.
    order = ORDERS.get(order_id.upper())
    if not order:
        return {"status": "error", "message": f"Order '{order_id}' not found."}
    return {"status": "success", "order": order}


# ============================================================
# KITCHEN AGENT TOOLS
# ============================================================
# WHY THESE THREE TOOLS FOR THE KITCHEN AGENT?
# Kitchen staff need an operational view, not a business intelligence view:
#   1. list_pending_orders — the work queue: what needs to be cooked right now?
#   2. update_kitchen_order_status — the core action: mark orders as done
#   3. get_all_orders — full history for shift handover or dispute resolution
#
# The Kitchen Agent cannot see inventory counts or sales totals — that is
# the owner's domain. It also cannot place new orders — that bypasses the
# customer confirmation flow and creates accountability issues.


def list_pending_orders() -> dict[str, Any]:
    """List all orders that are received or currently being prepared.

    WHY ONLY THESE TWO STATUSES?
    "ready" orders are finished — they just need to be picked up by service
    staff. Including them in the pending queue would clutter the kitchen display
    with orders the kitchen has already completed. The kitchen cares about
    what still needs work, not what's done.

    Returns:
        dict with "orders" list of active orders, sorted oldest-first (FIFO).
    """
    active_statuses = {"received", "preparing"}
    active = [o for o in ORDERS.values() if o["status"] in active_statuses]
    # FIFO ordering — the oldest order should be cooked first to prevent
    # starvation (newer orders getting cooked while older ones wait).
    active.sort(key=lambda o: o["created_at"])
    return {"status": "success", "count": len(active), "orders": active}


def update_kitchen_order_status(order_id: str, new_status: str) -> dict[str, Any]:
    """Update the kitchen status of an order.

    Valid transitions:
      received  → preparing   (kitchen picks up the ticket)
      preparing → ready       (food is plated and ready to serve)
      ready     → served      (service staff delivered to the table)
      any       → cancelled   (for error recovery or customer changes)

    WHY DOES THE KITCHEN AGENT ALSO UPDATE "served"?
    In a small restaurant there may not be separate service staff with their
    own tablet. The kitchen/counter staff can mark served when food goes out.
    In a larger deployment, create a separate "server" agent role.

    Args:
        order_id:   The 8-character order ID.
        new_status: New status — validated upstream in mcp_server.py.

    Returns:
        dict with the updated order.
    """
    try:
        order = update_order_status(order_id.upper(), new_status)
        return {
            "status":  "success",
            "message": f"Order #{order_id} updated to '{new_status}'.",
            "order":   order,
        }
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}


def get_all_orders(include_served: bool) -> dict[str, Any]:
    """Retrieve all orders, optionally including served and cancelled ones.

    WHY HAVE THIS SEPARATE FROM list_pending_orders?
    At shift handover, the kitchen manager may want a complete picture of all
    orders that passed through. During service, they only want pending. Having
    two tools with explicit semantics lets the LLM choose appropriately based
    on the question asked.

    Args:
        include_served: If True, include served and cancelled orders too.

    Returns:
        dict with "orders" list sorted by creation time.
    """
    if include_served:
        orders = list(ORDERS.values())
    else:
        # Exclude terminal statuses — served and cancelled orders are "closed".
        orders = [o for o in ORDERS.values() if o["status"] not in {"served", "cancelled"}]
    orders.sort(key=lambda o: o["created_at"])
    return {"status": "success", "count": len(orders), "orders": orders}


# ============================================================
# OWNER AGENT TOOLS
# ============================================================
# WHY THESE FOUR TOOLS FOR THE OWNER AGENT?
# The owner's job is business management, not front-of-house or kitchen ops:
#   1. check_inventory — see current stock levels and low-stock flags
#   2. get_sales_summary — daily revenue, top sellers, order count
#   3. suggest_daily_special — proactive upsell recommendation
#   4. restock_item — record a restocking action (updates the inventory count)
#
# The owner deliberately CANNOT place customer orders (would bypass order flow),
# update kitchen statuses (kitchen accountability), or get_order_status for
# individual customers (not their role in this system).


def check_inventory() -> dict[str, Any]:
    """Return the full current inventory with low-stock flags.

    WHY INCLUDE low_stock_items AS A PRE-COMPUTED LIST?
    The LLM could filter inventory_list itself, but pre-computing the list
    reduces the chance of the LLM making arithmetic errors on stock comparisons.
    The threshold value (LOW_STOCK_THRESHOLD = 5) is a business rule that
    should be centrally enforced, not computed independently by the LLM.

    Returns:
        dict with inventory levels for all menu items and a low_stock_items list.
    """
    inventory_list = []
    for item_id, stock in INVENTORY.items():
        menu_item = MENU_BY_ID.get(item_id, {})
        inventory_list.append({
            "item_id":   item_id,
            "name_en":   menu_item.get("name_en", item_id),
            "stock":     stock,
            # Pre-computed flag so the LLM doesn't have to compare numbers.
            "low_stock": stock <= LOW_STOCK_THRESHOLD,
        })
    low_stock = get_low_stock_items()
    return {
        "status":          "success",
        "inventory":       inventory_list,
        "low_stock_items": low_stock,           # Filtered list for quick alerting
        "low_stock_count": len(low_stock),      # Count for the LLM to summarize
    }


def get_sales_summary() -> dict[str, Any]:
    """Return today's sales summary including revenue and top-selling items.

    WHY PRE-COMPUTE TOP SELLERS INSTEAD OF RETURNING RAW DATA?
    The LLM would need to sort and slice items_sold to find top sellers —
    an operation it could do correctly but inconsistently. By sorting here
    and returning top_sellers[:3], we get deterministic output that the LLM
    can directly narrate without additional computation.

    Returns:
        dict with total_revenue_thb, total_orders, items_sold breakdown, top sellers.
    """
    # Cancelled orders are excluded from revenue — they were not fulfilled.
    total_revenue = sum(o["total_thb"] for o in ORDERS.values() if o["status"] != "cancelled")
    total_orders  = sum(1 for o in ORDERS.values() if o["status"] != "cancelled")

    items_sold = []
    for item_id, qty in SALES_TODAY.items():
        menu_item = MENU_BY_ID.get(item_id, {})
        revenue   = qty * menu_item.get("price_thb", 0)
        items_sold.append({
            "item_id":     item_id,
            "name_en":     menu_item.get("name_en", item_id),
            "qty_sold":    qty,
            "revenue_thb": revenue,
        })

    # Sort by quantity sold descending — most popular items first.
    items_sold.sort(key=lambda x: x["qty_sold"], reverse=True)
    top_sellers = items_sold[:3]  # Top 3 is enough for a daily summary narrative

    return {
        "status":            "success",
        "total_revenue_thb": total_revenue,
        "total_orders":      total_orders,
        "top_sellers":       top_sellers,
        "items_sold":        items_sold,
    }


def suggest_daily_special() -> dict[str, Any]:
    """Suggest today's daily special based on high inventory levels.

    WHY PROMOTE HIGH-STOCK ITEMS AS SPECIALS?
    Items with high stock are at risk of going to waste (food spoilage) or
    tying up cash in unsold inventory. Promoting them as "daily specials"
    drives demand toward those items, reducing waste and improving inventory
    turnover — a standard restaurant yield management technique.

    WHY EXCLUDE LOW-STOCK ITEMS?
    Promoting a near-out-of-stock item as a special would create customer
    disappointment when it sells out within minutes of being recommended.

    Returns:
        dict with suggested daily specials and the reasoning behind the selection.
    """
    # Score candidates: only items above the low-stock threshold qualify.
    candidates = []
    for item_id, stock in INVENTORY.items():
        if stock > LOW_STOCK_THRESHOLD:  # Only promote items with healthy stock
            menu_item = MENU_BY_ID.get(item_id, {})
            candidates.append({
                "item_id":   item_id,
                "name_en":   menu_item.get("name_en", item_id),
                "name_my":   menu_item.get("name_my", ""),
                "name_th":   menu_item.get("name_th", ""),
                "price_thb": menu_item.get("price_thb", 0),
                "stock":     stock,
                "description": menu_item.get("description", ""),
            })
    # Highest stock = strongest candidate (most need to move inventory).
    candidates.sort(key=lambda x: x["stock"], reverse=True)
    specials = candidates[:2]  # Two specials per day — manageable for a small restaurant

    return {
        "status":   "success",
        "specials": specials,
        # Include the reason so the LLM can explain the recommendation to the owner.
        "reason":   "Selected based on highest current inventory to maximize turnover.",
    }


def restock_item(item_id: str, quantity: int) -> dict[str, Any]:
    """Restock a menu item by adding units to inventory.

    WHY RETURN old_stock AND new_stock?
    The owner can verify the restocking operation was applied correctly and
    that the starting value was what they expected (e.g., catching a
    discrepancy between physical count and system count).

    Args:
        item_id:  The menu item ID to restock.
        quantity: Number of units to add to current stock.

    Returns:
        dict with updated stock level and a human-readable confirmation message.
    """
    if item_id not in MENU_BY_ID:
        return {"status": "error", "message": f"Unknown item: {item_id}"}
    if quantity <= 0:
        # This guard is redundant with mcp_server.py validation, but kept here
        # as defence-in-depth in case the function is called directly in tests.
        return {"status": "error", "message": "Quantity must be positive."}

    old_stock = INVENTORY.get(item_id, 0)
    INVENTORY[item_id] = old_stock + quantity
    new_stock = INVENTORY[item_id]

    return {
        "status":    "success",
        "item_id":   item_id,
        "name_en":   MENU_BY_ID[item_id]["name_en"],
        "old_stock": old_stock,
        "added":     quantity,
        "new_stock": new_stock,
        # Human-readable summary for the LLM to relay to the owner.
        "message":   f"Restocked {MENU_BY_ID[item_id]['name_en']}: {old_stock} → {new_stock} units.",
    }
