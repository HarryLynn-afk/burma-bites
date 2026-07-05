# Copyright 2026 Burma Bites
#
# Standalone Model Context Protocol (MCP) Server for Burma Bites.
#
# ── WHY A SEPARATE MCP SERVER? ──────────────────────────────────────────────
# Rather than injecting tool functions directly into each LlmAgent, we route
# all tool calls through this centralized MCP server. This design gives us:
#
#   1. SINGLE VALIDATION LAYER (STRIDE: Tampering / DoS)
#      Input validation happens here — once — before any business logic runs.
#      If we validated inside each agent instead, we'd need to duplicate the
#      logic across customer_agent.py, kitchen_agent.py, and owner_agent.py.
#      Centralizing it means a fix or rule change applies to all agents at once.
#
#   2. PROCESS BOUNDARY
#      The MCP server runs as a subprocess (stdio transport). This isolates
#      tool execution: a crash or memory leak in a tool does not kill the
#      ADK workflow process. In production, this process could be promoted
#      to a remote HTTP server with no changes to the agent code.
#
#   3. TOOL SCOPING VIA tool_filter
#      ADK's McpToolset accepts a tool_filter list. Each agent only "sees"
#      the tools it's allowed to call. The MCP server registers all 11 tools
#      but exposes only the relevant subset to each agent's LLM context,
#      preventing Elevation of Privilege (STRIDE E).
#
#   4. CLEAR SEPARATION OF CONCERNS
#      app/tools.py = business logic (pure Python, easily unit-tested)
#      app/mcp_server.py = validation + protocol adapter (this file)
#      This means tools.py tests never need to mock MCP infrastructure.
#
# ── TRANSPORT: stdio ────────────────────────────────────────────────────────
# We use stdio transport rather than HTTP/SSE because:
#   - No port allocation needed for local development
#   - ADK's McpToolset manages the subprocess lifecycle automatically
#   - Zero network configuration for development or CI
# For production, swap StdioConnectionParams for StreamableHTTPConnectionParams.
#
# See .agents/CONTEXT.md Rules 2 & 3 for the input validation policy.

import re

from mcp.server.fastmcp import FastMCP
# All tool implementations live in app/tools.py (pure business logic).
# We import them with underscore-prefixed aliases to make it clear that
# the MCP-registered versions (below) are the validated public interface.
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
# WHY VALIDATE HERE INSTEAD OF INSIDE TOOLS?
# The tools in app/tools.py are designed to be pure business logic — they
# trust their inputs. The MCP layer is the boundary between the untrusted
# LLM output and the trusted application core. Validating at this boundary
# follows the "validate at trust boundaries" principle from secure design.

# 500-char cap: an LLM hallucinating a massive string could exhaust memory
# or cause downstream JSON parse timeouts. This is a DoS mitigation.
_MAX_STR_LEN = 500

# Allowlists are more secure than denylists — we explicitly enumerate
# what IS valid rather than trying to block what is NOT.
_ALLOWED_CATEGORIES = {"all", "food", "drink", "side"}
_ALLOWED_STATUSES   = {"preparing", "ready", "served", "cancelled"}

# Order IDs are generated as UUID[:8].upper() — exactly 8 uppercase alphanumeric.
# Rejecting anything that doesn't match this prevents probing for order IDs
# via partial matches or SQL-like patterns.
_ORDER_ID_RE = re.compile(r"^[A-Z0-9]{8}$")

# Item IDs use snake_case (e.g. "laphet_thoke"). Rejecting other characters
# prevents injection of path traversal or shell metacharacters into any
# future DB query that uses item_id as a key.
_ITEM_ID_RE  = re.compile(r"^[a-z_]{1,50}$")

# Table numbers are 1-99 only. This prevents injection of SQL fragments,
# shell commands, or excessively long strings into the table field.
_TABLE_RE    = re.compile(r"^\d{1,2}$")


def _err(message: str) -> dict:
    """Return a standard error dict. All tools use the same shape for errors."""
    return {"status": "error", "message": message}


def _check_str(value: str, field: str, max_len: int = _MAX_STR_LEN) -> str | None:
    """Common string guard: type check, empty check, length cap.

    Returns an error message string if invalid, or None if valid.
    Using None-as-success (rather than raising) keeps the call sites
    clean with Python 3.8+ walrus operator:  `if err := _check_str(...)`.
    """
    if not isinstance(value, str):
        return f"{field} must be a string."
    stripped = value.strip()
    if not stripped:
        return f"{field} must not be empty or whitespace."
    if len(stripped) > max_len:
        return f"{field} exceeds maximum length of {max_len} characters."
    return None


def _validate_table_number(table_number: str) -> str | None:
    """Validate table_number is a digit-only string in the range 1-99.

    WHY DIGITS-ONLY AND NOT ALPHANUMERIC?
    Real restaurant tables are numbered 1–99. Allowing letters would open
    the door to injection strings like "1; DROP TABLE orders" slipping through.
    The regex enforces the physical constraint of the restaurant layout.
    """
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
    """Validate order_id matches the format generated by create_order().

    WHY ENFORCE THE EXACT FORMAT?
    Loose validation (e.g., just checking length) would allow crafted IDs
    like "../../etc" or SQL fragments. Anchored regex against the known
    generation format (UUID[:8].upper()) is both correct and secure.
    """
    err = _check_str(order_id, "order_id")
    if err:
        return err
    if not _ORDER_ID_RE.match(order_id.strip().upper()):
        return "order_id must be exactly 8 alphanumeric uppercase characters."
    return None


# ============================================================
# MCP tool endpoints — public interface for agents
# ============================================================
# Each function below is the validated public MCP endpoint.
# It validates, then delegates to the corresponding _private function
# from app/tools.py. This two-layer design means:
#   - Tools can be unit-tested without MCP infrastructure.
#   - Validation logic can be changed without touching business logic.


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
    # Allowlist check: rejects unknown categories before they reach the business layer.
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
    # Regex check ensures only valid menu ID characters are passed downstream.
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
    # WHY VALIDATE items_json LENGTH SEPARATELY FROM _check_str?
    # _check_str uses _MAX_STR_LEN=500 for most fields. items_json could
    # legitimately reach ~300 chars for a large order, so we reuse the same
    # 500-char cap but call it explicitly for clarity.
    if err := _check_str(items_json, "items_json"):
        return _err(err)
    if len(items_json) > _MAX_STR_LEN:
        return _err(f"items_json exceeds maximum length of {_MAX_STR_LEN} characters.")

    # Table number validation: digits 1-99 only, preventing injection attacks.
    if err := _validate_table_number(table_number):
        return _err(err)

    # Parse and validate the JSON structure before passing to business logic.
    # WHY NOT LET tools.py PARSE THE JSON?
    # tools.py already does a json.loads — but the MCP layer validates the
    # *structure* (each item has the right fields and types) before it reaches
    # the shared state. This prevents partial orders from corrupting inventory.
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
        # Quantity cap of 50: prevents a customer from ordering 9999 mohinga
        # and exhausting inventory in a single malicious call.
        if not isinstance(qty, int) or qty <= 0 or qty > 50:
            return _err(f"Item {i}: 'quantity' must be a positive integer between 1 and 50.")

    return _place_order(items_json, table_number.strip())


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """Check the current status of a customer's order.

    Args:
        order_id: The 8-character alphanumeric order ID returned when the order was placed.
    """
    # Strict format validation prevents scanning for order IDs via fuzzing.
    if err := _validate_order_id(order_id):
        return _err(err)
    return _get_order_status(order_id.strip().upper())


@mcp.tool()
def list_pending_orders() -> dict:
    """List all orders that are received or currently being prepared.

    Returns a dict with "orders" list of active (non-served, non-cancelled) orders.
    No input parameters — this is a read-only query with no injection surface.
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
    # Allowlist validation: strictly enumerate valid states.
    # WHY NOT VALIDATE TRANSITIONS HERE?
    # Transition logic (e.g., cannot jump from received to served) is enforced
    # by the Kitchen Agent's instructions and the LLM's understanding of valid
    # workflows. The MCP layer only enforces that the value is a known status —
    # not the business-level ordering of those statuses.
    if status_clean not in _ALLOWED_STATUSES:
        return _err(f"Invalid status '{status_clean}'. Must be one of: {sorted(_ALLOWED_STATUSES)}.")
    return _update_kitchen_order_status(order_id.strip().upper(), status_clean)


@mcp.tool()
def check_inventory() -> dict:
    """Return the full current inventory with low-stock flags.

    No input parameters — read-only, no injection surface.
    """
    return _check_inventory()


@mcp.tool()
def get_sales_summary() -> dict:
    """Return today's sales summary including revenue and top-selling items.

    No input parameters — aggregates from the in-memory order book.
    """
    return _get_sales_summary()


@mcp.tool()
def suggest_daily_special() -> dict:
    """Suggest today's daily special based on high inventory levels.

    Recommends items with the most stock to help move inventory.
    No input parameters — the algorithm reads current inventory automatically.
    """
    return _suggest_daily_special()


@mcp.tool()
def get_all_orders(include_served: bool) -> dict:
    """Retrieve all orders, optionally including served and cancelled ones.

    Args:
        include_served: If True, include served and cancelled orders too.
    """
    # Boolean type check — LLMs sometimes pass "true" as a string.
    if not isinstance(include_served, bool):
        return _err("include_served must be a boolean (true or false).")
    return _get_all_orders(include_served)


@mcp.tool()
def restock_item(item_id: str, quantity: int) -> dict:
    """Restock a menu item by adding units to inventory.

    WHY IS THIS AN OWNER-ONLY TOOL?
    Restocking changes the authoritative inventory count, which affects
    what the customer agent tells customers ("sold out") and what the owner
    sees in reports. Only the owner should be able to authorize inventory
    changes — it's a business decision, not a kitchen or customer action.

    Args:
        item_id:  The menu item ID to restock.
        quantity: Number of units to add to current stock (1–500).
    """
    if err := _check_str(item_id, "item_id"):
        return _err(err)
    item_id_clean = item_id.strip().lower()
    if not _ITEM_ID_RE.match(item_id_clean):
        return _err("item_id may only contain lowercase letters and underscores.")
    # 500-unit cap per restock call: prevents accidental or malicious inflation
    # of inventory that would hide real stock levels from the owner dashboard.
    if not isinstance(quantity, int) or quantity <= 0 or quantity > 500:
        return _err("quantity must be a positive integer between 1 and 500.")
    return _restock_item(item_id_clean, quantity)


if __name__ == "__main__":
    # stdio transport: ADK's McpToolset spawns this process and communicates
    # via stdin/stdout JSON-RPC. No port binding required for local development.
    mcp.run("stdio")
