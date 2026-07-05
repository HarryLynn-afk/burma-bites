# Copyright 2026 Burma Bites
#
# Tool functions shared across Customer, Kitchen, and Owner agents.
# All tools follow ADK conventions: type-hinted, docstrings for the LLM,
# return JSON-serialisable dicts, accept optional ToolContext last.

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
        items = [i for i in MENU if i["category"] == category]

    result = []
    for item in items:
        result.append({
            "id":          item["id"],
            "name_en":     item["name_en"],
            "name_my":     item["name_my"],
            "name_th":     item["name_th"],
            "category":    item["category"],
            "price_thb":   item["price_thb"],
            "description": item["description"],
            "allergens":   item["allergens"],
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
        "stock":       INVENTORY.get(item["id"], 0),
    }


def place_order(items_json: str, table_number: str) -> dict[str, Any]:
    """Place a confirmed customer order and send it to the kitchen.

    Call this ONLY after the customer has verbally confirmed their full order.
    Do NOT call this speculatively — always confirm with the customer first.

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

    # Validate stock before placing
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
    order = ORDERS.get(order_id.upper())
    if not order:
        return {"status": "error", "message": f"Order '{order_id}' not found."}
    return {"status": "success", "order": order}


# ============================================================
# KITCHEN AGENT TOOLS
# ============================================================


def list_pending_orders() -> dict[str, Any]:
    """List all orders that are received or currently being prepared.

    Returns:
        dict with "orders" list of active (non-served, non-cancelled) orders.
    """
    active_statuses = {"received", "preparing"}
    active = [o for o in ORDERS.values() if o["status"] in active_statuses]
    # Sort oldest first
    active.sort(key=lambda o: o["created_at"])
    return {"status": "success", "count": len(active), "orders": active}


def update_kitchen_order_status(order_id: str, new_status: str) -> dict[str, Any]:
    """Update the kitchen status of an order.

    Valid transitions:
      received  → preparing
      preparing → ready
      ready     → served
      any       → cancelled

    Args:
        order_id:   The 8-character order ID.
        new_status: New status. Must be one of: "preparing", "ready", "served", "cancelled".

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

    Args:
        include_served: If True, include served and cancelled orders too.

    Returns:
        dict with "orders" list sorted by creation time.
    """
    if include_served:
        orders = list(ORDERS.values())
    else:
        orders = [o for o in ORDERS.values() if o["status"] not in {"served", "cancelled"}]
    orders.sort(key=lambda o: o["created_at"])
    return {"status": "success", "count": len(orders), "orders": orders}


# ============================================================
# OWNER AGENT TOOLS
# ============================================================


def check_inventory() -> dict[str, Any]:
    """Return the full current inventory with low-stock flags.

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
            "low_stock": stock <= LOW_STOCK_THRESHOLD,
        })
    low_stock = get_low_stock_items()
    return {
        "status":          "success",
        "inventory":       inventory_list,
        "low_stock_items": low_stock,
        "low_stock_count": len(low_stock),
    }


def get_sales_summary() -> dict[str, Any]:
    """Return today's sales summary including revenue and top-selling items.

    Returns:
        dict with total_revenue_thb, total_orders, items_sold breakdown, and top sellers.
    """
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

    items_sold.sort(key=lambda x: x["qty_sold"], reverse=True)
    top_sellers = items_sold[:3]

    return {
        "status":            "success",
        "total_revenue_thb": total_revenue,
        "total_orders":      total_orders,
        "top_sellers":       top_sellers,
        "items_sold":        items_sold,
    }


def suggest_daily_special() -> dict[str, Any]:
    """Suggest today's daily special based on high inventory levels.

    Recommends items with the most stock to help move inventory.

    Returns:
        dict with suggested daily specials.
    """
    # Score items: higher stock = better candidate for promotion
    candidates = []
    for item_id, stock in INVENTORY.items():
        if stock > LOW_STOCK_THRESHOLD:
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
    candidates.sort(key=lambda x: x["stock"], reverse=True)
    specials = candidates[:2]  # Top 2 with most stock

    return {
        "status":   "success",
        "specials": specials,
        "reason":   "Selected based on highest current inventory to maximize turnover.",
    }


def restock_item(item_id: str, quantity: int) -> dict[str, Any]:
    """Restock a menu item by adding units to inventory.

    Args:
        item_id:  The menu item ID to restock.
        quantity: Number of units to add to current stock.

    Returns:
        dict with updated stock level.
    """
    if item_id not in MENU_BY_ID:
        return {"status": "error", "message": f"Unknown item: {item_id}"}
    if quantity <= 0:
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
        "message":   f"Restocked {MENU_BY_ID[item_id]['name_en']}: {old_stock} → {new_stock} units.",
    }
