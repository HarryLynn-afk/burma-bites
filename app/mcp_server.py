# Copyright 2026 Burma Bites
#
# Standalone Model Context Protocol (MCP) Server for Burma Bites.
# Exposes the restaurant tools using the MCP Python SDK.
#
# Security: All tool endpoints validate inputs before passing to business logic.
# See .agents/CONTEXT.md Rules 2 & 3 for the full policy.

import re

from mcp.server.fastmcp import FastMCP
from app.tools import (
    list_menu as _list_menu,
    get_item_details as _get_item_details,
    place_order as _place_order,
    get_order_status as _get_order_status,
    list_pending_orders as _list_pending_orders,
    update_kitchen_order_status as _update_kitchen_order_status,
    check_inventory as _check_inventory,
    get_sales_summary as _get_sales_summary,
    suggest_daily_special as _suggest_daily_special,
    get_all_orders as _get_all_orders,
    restock_item as _restock_item,
)

mcp = FastMCP("Burma Bites Server")

# ============================================================
# Validation helpers (STRIDE: Tampering / DoS mitigations)
# ============================================================

_MAX_STR_LEN = 500  # Reject strings longer than this (DoS / memory guard)

_ALLOWED_CATEGORIES = {"all", "food", "drink", "side"}
_ALLOWED_STATUSES   = {"preparing", "ready", "served", "cancelled"}
_ORDER_ID_RE        = re.compile(r"^[A-Z0-9]{8}$")
_ITEM_ID_RE         = re.compile(r"^[a-z_]{1,50}$")
_TABLE_RE           = re.compile(r"^\d{1,2}$")  # digits only, 1-99


def _err(message: str) -> dict:
    """Shorthand for a validation error response."""
    return {"status": "error", "message": message}


def _check_str(value: str, field: str, max_len: int = _MAX_STR_LEN) -> str | None:
    """Return an error message string if value fails basic string checks, else None."""
    if not isinstance(value, str):
        return f"{field} must be a string."
    stripped = value.strip()
    if not stripped:
        return f"{field} must not be empty or whitespace."
    if len(stripped) > max_len:
        return f"{field} exceeds maximum length of {max_len} characters."
    return None


def _validate_table_number(table_number: str) -> str | None:
    """Return error string if table_number is invalid, else None."""
    err = _check_str(table_number, "table_number")
    if err:
        return err
    t = table_number.strip()
    if not _TABLE_RE.match(t):
        return "table_number must be a number between 1 and 99."
    if not (1 <= int(t) <= 99):
        return "table_number must be between 1 and 99."
    return None


def _validate_order_id(order_id: str) -> str | None:
    """Return error string if order_id format is invalid, else None."""
    err = _check_str(order_id, "order_id")
    if err:
        return err
    if not _ORDER_ID_RE.match(order_id.strip().upper()):
        return "order_id must be exactly 8 alphanumeric uppercase characters."
    return None


# ============================================================
# MCP tool endpoints
# ============================================================


@mcp.tool()
def list_menu(category: str) -> dict:
    """Return all menu items, optionally filtered by category.

    Args:
        category: Filter by category. Use "all" for everything, or one of:
                  "food", "drink", "side".
    """
    if err := _check_str(category, "category"):
        return _err(err)
    cat = category.strip().lower()
    if cat not in _ALLOWED_CATEGORIES:
        return _err(f"Invalid category '{cat}'. Must be one of: {sorted(_ALLOWED_CATEGORIES)}.")
    return _list_menu(cat)


@mcp.tool()
def get_item_details(item_id: str) -> dict:
    """Get full details for a single menu item including stock availability.

    Args:
        item_id: The unique ID of the menu item (e.g. "mohinga", "laphet_thoke").
    """
    if err := _check_str(item_id, "item_id"):
        return _err(err)
    item_id_clean = item_id.strip().lower()
    if not _ITEM_ID_RE.match(item_id_clean):
        return _err("item_id may only contain lowercase letters and underscores (max 50 chars).")
    return _get_item_details(item_id_clean)


@mcp.tool()
def place_order(items_json: str, table_number: str) -> dict:
    """Place a confirmed customer order and send it to the kitchen.

    Call this ONLY after the customer has verbally confirmed their full order.
    Do NOT call this speculatively — always confirm with the customer first.

    Args:
        items_json: JSON string of a list of objects, each with "item_id" and
                    "quantity". Example: '[{"item_id": "mohinga", "quantity": 2}]'
        table_number: Table number. Must be a number between 1 and 99.
    """
    # Validate items_json length (DoS guard)
    if err := _check_str(items_json, "items_json"):
        return _err(err)
    if len(items_json) > _MAX_STR_LEN:
        return _err(f"items_json exceeds maximum length of {_MAX_STR_LEN} characters.")

    # Validate table_number (injection guard: digits 1-99 only)
    if err := _validate_table_number(table_number):
        return _err(err)

    # Validate item_id and quantity fields inside the JSON before passing onward
    import json
    try:
        items = json.loads(items_json)
    except json.JSONDecodeError as exc:
        return _err(f"items_json is not valid JSON: {exc}")

    if not isinstance(items, list) or len(items) == 0:
        return _err("items_json must be a non-empty JSON array.")

    for i, line in enumerate(items):
        if not isinstance(line, dict):
            return _err(f"Item {i}: each entry must be a JSON object with 'item_id' and 'quantity'.")
        raw_id = line.get("item_id", "")
        if not isinstance(raw_id, str) or not raw_id.strip():
            return _err(f"Item {i}: 'item_id' must be a non-empty string.")
        if not _ITEM_ID_RE.match(raw_id.strip().lower()):
            return _err(f"Item {i}: 'item_id' contains invalid characters.")
        qty = line.get("quantity", 0)
        if not isinstance(qty, int) or qty <= 0 or qty > 50:
            return _err(f"Item {i}: 'quantity' must be a positive integer between 1 and 50.")

    return _place_order(items_json, table_number.strip())


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """Check the current status of a customer's order.

    Args:
        order_id: The 8-character alphanumeric order ID returned when the order was placed.
    """
    if err := _validate_order_id(order_id):
        return _err(err)
    return _get_order_status(order_id.strip().upper())


@mcp.tool()
def list_pending_orders() -> dict:
    """List all orders that are received or currently being prepared.

    Returns a dict with "orders" list of active (non-served, non-cancelled) orders.
    """
    return _list_pending_orders()


@mcp.tool()
def update_kitchen_order_status(order_id: str, new_status: str) -> dict:
    """Update the kitchen status of an order.

    Valid transitions:
      received  → preparing
      preparing → ready
      ready     → served
      any       → cancelled

    Args:
        order_id:   The 8-character order ID.
        new_status: New status. Must be one of: "preparing", "ready", "served", "cancelled".
    """
    if err := _validate_order_id(order_id):
        return _err(err)
    if err := _check_str(new_status, "new_status"):
        return _err(err)
    status_clean = new_status.strip().lower()
    if status_clean not in _ALLOWED_STATUSES:
        return _err(f"Invalid status '{status_clean}'. Must be one of: {sorted(_ALLOWED_STATUSES)}.")
    return _update_kitchen_order_status(order_id.strip().upper(), status_clean)


@mcp.tool()
def check_inventory() -> dict:
    """Return the full current inventory with low-stock flags."""
    return _check_inventory()


@mcp.tool()
def get_sales_summary() -> dict:
    """Return today's sales summary including revenue and top-selling items."""
    return _get_sales_summary()


@mcp.tool()
def suggest_daily_special() -> dict:
    """Suggest today's daily special based on high inventory levels.

    Recommends items with the most stock to help move inventory.
    """
    return _suggest_daily_special()


@mcp.tool()
def get_all_orders(include_served: bool) -> dict:
    """Retrieve all orders, optionally including served and cancelled ones.

    Args:
        include_served: If True, include served and cancelled orders too.
    """
    if not isinstance(include_served, bool):
        return _err("include_served must be a boolean (true or false).")
    return _get_all_orders(include_served)


@mcp.tool()
def restock_item(item_id: str, quantity: int) -> dict:
    """Restock a menu item by adding units to inventory.

    Args:
        item_id:  The menu item ID to restock.
        quantity: Number of units to add to current stock (1–500).
    """
    if err := _check_str(item_id, "item_id"):
        return _err(err)
    item_id_clean = item_id.strip().lower()
    if not _ITEM_ID_RE.match(item_id_clean):
        return _err("item_id may only contain lowercase letters and underscores.")
    if not isinstance(quantity, int) or quantity <= 0 or quantity > 500:
        return _err("quantity must be a positive integer between 1 and 500.")
    return _restock_item(item_id_clean, quantity)


if __name__ == "__main__":
    mcp.run("stdio")
