# ruff: noqa
# Copyright 2026 Burma Bites
#
# Root agent: ADK 2.0 Graph Workflow wiring together the three Burma Bites agents.
#
# Architecture:
#
#   START
#     │
#     ▼
#   route_request   ← detects intent: customer | kitchen | owner
#     │
#     ├──(customer)──► customer_agent  ──► format_customer_response
#     │
#     ├──(kitchen)───► kitchen_agent   ──► format_kitchen_response
#     │
#     └──(owner)─────► owner_agent     ──► format_owner_response
#
# The Owner Agent also runs a parallel proactive monitor branch that fires
# whenever there are low-stock items, independent of user intent.

from __future__ import annotations

import json
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.workflow import JoinNode, Workflow
from google.genai import types

from .agents.customer_agent import customer_agent
from .agents.kitchen_agent import kitchen_agent
from .agents.owner_agent import owner_agent
from .menu import INVENTORY, LOW_STOCK_THRESHOLD

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

# Configure agents to use MCP server instead of direct imports
mcp_connection = StdioConnectionParams(
    server_params=StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "app.mcp_server"],
    )
)

customer_agent.tools = [
    McpToolset(
        connection_params=mcp_connection,
        tool_filter=["list_menu", "get_item_details", "place_order", "get_order_status"],
    )
]

kitchen_agent.tools = [
    McpToolset(
        connection_params=mcp_connection,
        tool_filter=["list_pending_orders", "update_kitchen_order_status", "get_all_orders"],
    )
]

owner_agent.tools = [
    McpToolset(
        connection_params=mcp_connection,
        tool_filter=["check_inventory", "get_sales_summary", "suggest_daily_special", "restock_item"],
    )
]


# ============================================================
# Router node — classifies incoming requests
# ============================================================

def route_request(ctx: Context, node_input: Any) -> Event:
    """Classify the incoming message and route to the correct agent.

    Routing logic (keyword-based for speed; LLM agents refine in their own
    instructions):
      - Messages mentioning order management, kitchen, status updates  → kitchen
      - Messages mentioning inventory, sales, restock, specials, owner → owner
      - Everything else (menu questions, orders, greetings)             → customer
    """
    # node_input is types.Content when there is no input_schema
    if hasattr(node_input, "parts"):
        text = " ".join(p.text for p in node_input.parts if hasattr(p, "text")).lower()
    else:
        text = str(node_input).lower()

    kitchen_keywords = {
        "preparing", "ready", "served", "kitchen", "cook", "ticket",
        "order status update", "mark order", "update order",
    }
    owner_keywords = {
        "inventory", "stock", "restock", "sales", "revenue", "special",
        "specials", "daily", "low stock", "out of stock", "owner", "report",
        "analytics", "profit", "alert",
    }

    if any(kw in text for kw in kitchen_keywords):
        route = "kitchen"
    elif any(kw in text for kw in owner_keywords):
        route = "owner"
    else:
        route = "customer"  # default

    return Event(output=text, route=route, state={"detected_route": route})


# ============================================================
# Response formatter nodes
# ============================================================

def format_customer_response(ctx: Context, customer_result: dict) -> Event:
    """Format the customer agent output as a user-facing content event."""
    if not customer_result:
        customer_result = {}
    message = customer_result.get("message_to_customer", "How can I help you today?")
    content = types.Content(
        role="model",
        parts=[types.Part.from_text(text=message)],
    )
    return Event(
        content=content,
        output={"agent": "customer", "result": customer_result},
    )


def format_kitchen_response(ctx: Context, kitchen_result: dict) -> Event:
    """Format the kitchen agent output as a user-facing content event."""
    if not kitchen_result:
        kitchen_result = {}
    message = kitchen_result.get("summary", "Kitchen update processed.")
    content = types.Content(
        role="model",
        parts=[types.Part.from_text(text=f"🍳 Kitchen: {message}")],
    )
    return Event(
        content=content,
        output={"agent": "kitchen", "result": kitchen_result},
    )


def format_owner_response(ctx: Context, owner_result: dict) -> Event:
    """Format the owner agent output as a user-facing content event."""
    if not owner_result:
        owner_result = {}

    lines = []

    # Alerts (most important, always first)
    alerts = owner_result.get("alerts", [])
    if alerts:
        lines.append("**⚠️ ALERTS**")
        lines.extend(f"  {a}" for a in alerts)
        lines.append("")

    # Sales summary
    sales = owner_result.get("sales_summary", "")
    if sales:
        lines.append(f"**📊 Sales**: {sales}")
        lines.append("")

    # Daily specials
    specials = owner_result.get("daily_specials", [])
    if specials:
        lines.append("**🍽️ Today's Specials**")
        lines.extend(f"  • {s}" for s in specials)
        lines.append("")

    # Recommendations
    recs = owner_result.get("recommendations", [])
    if recs:
        lines.append("**💡 Recommendations**")
        lines.extend(f"  • {r}" for r in recs)

    message = "\n".join(lines) if lines else "Owner report processed."
    content = types.Content(
        role="model",
        parts=[types.Part.from_text(text=message)],
    )
    return Event(
        content=content,
        output={"agent": "owner", "result": owner_result},
    )


# ============================================================
# Proactive low-stock monitor (runs every invocation on owner branch)
# ============================================================

def proactive_stock_check(ctx: Context) -> Event:
    """Check for low-stock items and inject an alert into state.

    This node runs automatically whenever the owner branch is triggered.
    It stores a low_stock_alert in state so the owner agent sees it too.
    """
    from .menu import get_low_stock_items
    low = get_low_stock_items()
    if low:
        names = ", ".join(f"{i['name_en']} ({i['stock']})" for i in low)
        alert_msg = f"LOW STOCK DETECTED: {names}"
    else:
        alert_msg = ""

    return Event(
        output=alert_msg or "stock_ok",
        state={"proactive_stock_alert": alert_msg},
    )


# ============================================================
# Root Workflow (ADK 2.0 graph)
# ============================================================

root_agent = Workflow(
    name="burma_bites",
    description=(
        "Multi-agent restaurant ordering system for Burma Bites — a Burmese "
        "restaurant in Thailand. Routes between Customer, Kitchen, and Owner agents."
    ),
    edges=[
        # Entry point: route_request emits route="customer"|"kitchen"|"owner"
        ("START", route_request),

        # Routing map: from route_request, dispatch to the correct branch
        (
            route_request,
            {
                "customer": customer_agent,
                "kitchen":  kitchen_agent,
                "owner":    proactive_stock_check,
            },
        ),

        # ── Customer branch ──────────────────────────────────────────────
        (customer_agent, format_customer_response),

        # ── Kitchen branch ───────────────────────────────────────────────
        (kitchen_agent, format_kitchen_response),

        # ── Owner branch (proactive stock check → owner_agent → format) ──
        (proactive_stock_check, owner_agent),
        (owner_agent, format_owner_response),
    ],
)

# ============================================================
# App
# ============================================================

app = App(
    root_agent=root_agent,
    name="app",
)
