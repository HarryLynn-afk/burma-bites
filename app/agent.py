# ruff: noqa
# Copyright 2026 Burma Bites
#
# Root agent: ADK 2.0 Graph Workflow wiring together the three Burma Bites agents.
#
# ── WHY A GRAPH WORKFLOW INSTEAD OF A SINGLE AGENT? ────────────────────────
# A single LlmAgent could theoretically handle all three roles, but would:
#   1. Require all tools to be visible to all intents — violating least-privilege.
#   2. Force the model to decide routing on every token — wasting inference.
#   3. Make the system harder to test and evaluate per-role.
#
# The ADK 2.0 Workflow (graph) solves this with fast, deterministic keyword-
# based routing at the Python layer, delegating LLM reasoning only where needed.
#
# ── ROUTING PATTERN: KEYWORD → LLM (DUAL-LAYER ROUTING) ───────────────────
# The route_request function node runs first — it is a pure Python function
# with no LLM call and completes in microseconds. Only after a branch is
# selected does an LLM agent run (consuming tokens and latency).
# This "keyword → LLM" two-layer routing pattern is intentional:
#   - Fast: no LLM round-trip for routing decisions
#   - Predictable: keyword sets are version-controlled and auditable
#   - Graceful: LLM agents refine behavior within their domain
#
# ── WHY THE OWNER BRANCH HAS AN EXTRA PROACTIVE_STOCK_CHECK NODE? ──────────
# The Owner Agent should ALWAYS report low-stock items, even when the owner
# has not asked about inventory. Injecting a deterministic Python check before
# the LLM ensures the alert always fires — we cannot rely on the LLM to
# spontaneously check inventory without being asked. The check writes
# "proactive_stock_alert" into session state so the LLM can reference it.
#
# ── ARCHITECTURE DIAGRAM ────────────────────────────────────────────────────
#
#   START
#     │
#     ▼
#   route_request   ← pure Python node; no LLM call; emits route value
#     │
#     ├──(customer)──► customer_agent  ──► format_customer_response
#     │
#     ├──(kitchen)───► kitchen_agent   ──► format_kitchen_response
#     │
#     └──(owner)─────► proactive_stock_check ──► owner_agent ──► format_owner_response
#                      (deterministic Python)    (LLM)
#
# ── MCP TOOL ISOLATION: WHY EACH AGENT GETS DIFFERENT TOOLS ────────────────
# All 11 tools are registered on a single MCP server, but each agent connects
# to it with a `tool_filter` that restricts visible tools. This enforces
# Elevation-of-Privilege prevention from our STRIDE threat model:
#   - The Customer Agent CANNOT call update_kitchen_order_status.
#   - The Kitchen Agent CANNOT call restock_item or see sales data.
#   - The Owner Agent CANNOT place customer orders.
# The LLM will never even see those tool signatures, so it cannot misuse them.

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

# McpToolset connects each agent to the standalone app/mcp_server.py process.
# WHY MCP OVER DIRECT IMPORTS? The MCP layer adds:
#   1. Input validation (STRIDE Tampering/DoS guards) before any tool runs.
#   2. A process boundary — the tool server can be restarted without reloading
#      all agents, and can be swapped for a remote HTTP server in production.
#   3. Tool-level scoping via tool_filter, enforcing least-privilege per agent.
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

# A single shared StdioConnectionParams object is reused across all three agents.
# The ADK runtime spawns one subprocess per McpToolset session (not per call),
# so the MCP server process lifecycle is managed automatically.
mcp_connection = StdioConnectionParams(
    server_params=StdioServerParameters(
        command="uv",
        # Running via `uv run` ensures the correct .venv Python is used,
        # regardless of the system Python version on the host machine.
        args=["run", "python", "-m", "app.mcp_server"],
    )
)

# ── CUSTOMER AGENT: front-of-house tools only ────────────────────────────────
# The customer agent needs to browse the menu, look up item details, place
# orders, and check status. It deliberately CANNOT update kitchen statuses
# (that would let a customer mark their own food as "served") or see inventory
# levels (that is the owner's business data).
customer_agent.tools = [
    McpToolset(
        connection_params=mcp_connection,
        tool_filter=["list_menu", "get_item_details", "place_order", "get_order_status"],
    )
]

# ── KITCHEN AGENT: order-lifecycle tools only ─────────────────────────────────
# The kitchen only needs to see what needs cooking and update statuses.
# It cannot place new orders (that would bypass the customer confirmation flow)
# or access sales/inventory reports (owner-only data).
kitchen_agent.tools = [
    McpToolset(
        connection_params=mcp_connection,
        tool_filter=["list_pending_orders", "update_kitchen_order_status", "get_all_orders"],
    )
]

# ── OWNER AGENT: business intelligence + restocking tools only ────────────────
# The owner sees inventory, sales, and specials. restock_item is included here
# because it is an owner-approved action — but note the agent is instructed
# to require explicit confirmation before calling it (see owner_agent.py Rule).
owner_agent.tools = [
    McpToolset(
        connection_params=mcp_connection,
        tool_filter=["check_inventory", "get_sales_summary", "suggest_daily_special", "restock_item"],
    )
]


# ============================================================
# Router node — pure Python intent classification
# ============================================================

def route_request(ctx: Context, node_input: Any) -> Event:
    """Classify the incoming message and route to the correct agent branch.

    WHY keyword matching instead of an LLM classifier?
    Using a small LLM just to classify intent would add 300-600ms of latency
    and consume tokens on every message. Keyword sets are fast, auditable, and
    easy to extend without model calls. The chosen agent then does the actual
    deep NLU within its domain.

    WHY customer as the default branch?
    In a restaurant, the vast majority of messages come from customers —
    orders, menu questions, greetings. Kitchen and owner interactions are
    less frequent and use distinctive vocabulary, so they are safe to test
    explicitly. Defaulting to customer prevents unintended owner/kitchen
    agent invocations from ambiguous input.

    The route value is written into Event.route, which ADK's graph engine
    uses to select which outgoing edge (from the routing-map dict) to follow.
    It is also stored in session state for observability/debugging.
    """
    # node_input arrives as types.Content (ADK wraps user messages in Content).
    # We extract the plain text before keyword matching.
    if hasattr(node_input, "parts"):
        text = " ".join(p.text for p in node_input.parts if hasattr(p, "text")).lower()
    else:
        text = str(node_input).lower()

    # Kitchen vocabulary: operational terms that only staff use.
    kitchen_keywords = {
        "preparing", "ready", "served", "kitchen", "cook", "ticket",
        "order status update", "mark order", "update order",
    }
    # Owner vocabulary: business intelligence and management terms.
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
        route = "customer"  # default — handles menu questions, orders, greetings

    # Storing detected_route in state lets downstream nodes and evals read it
    # without re-parsing the message.
    return Event(output=text, route=route, state={"detected_route": route})


# ============================================================
# Response formatter nodes
# ============================================================
# WHY SEPARATE FORMATTER NODES INSTEAD OF FORMATTING INSIDE AGENTS?
# LlmAgents with output_schema produce structured dicts (not natural language).
# Formatters translate those dicts into types.Content that the ADK runner
# surfaces to the caller as a model turn. Keeping this logic here (not inside
# the agents) means the agents stay pure domain logic without UI concerns.

def format_customer_response(ctx: Context, customer_result: dict) -> Event:
    """Unwrap the CustomerAgentOutput schema and create a user-facing Content event.

    The customer_result dict comes from the agent's output_key="customer_result"
    in session state. We extract message_to_customer — the field the agent was
    instructed to write its final reply into — so it appears as a model turn.
    """
    if not customer_result:
        customer_result = {}
    # message_to_customer is the only field that should be shown to the customer.
    # Other fields (action, order_id, language_detected) are for downstream processing.
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
    """Unwrap the KitchenAgentOutput schema and create a staff-facing Content event.

    The 🍳 prefix visually differentiates kitchen messages from customer-facing
    messages in the ADK playground UI, aiding in demo readability.
    """
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
    """Unwrap the OwnerAgentOutput schema into a structured owner-facing report.

    WHY priority ordering (alerts → sales → specials → recommendations)?
    The owner is busy and may only read the top of the response. Critical
    operational alerts (low stock, out of stock) must appear first so they
    are never missed. Sales and specials follow in descending urgency.
    """
    if not owner_result:
        owner_result = {}

    lines = []

    # Alerts first — these are time-sensitive operational issues.
    # An empty alerts list means all stock is healthy.
    alerts = owner_result.get("alerts", [])
    if alerts:
        lines.append("**⚠️ ALERTS**")
        lines.extend(f"  {a}" for a in alerts)
        lines.append("")

    # Sales summary — daily revenue narrative from the LLM.
    sales = owner_result.get("sales_summary", "")
    if sales:
        lines.append(f"**📊 Sales**: {sales}")
        lines.append("")

    # Daily specials — suggested dishes to promote based on high stock levels.
    specials = owner_result.get("daily_specials", [])
    if specials:
        lines.append("**🍽️ Today's Specials**")
        lines.extend(f"  • {s}" for s in specials)
        lines.append("")

    # Strategic recommendations — lowest urgency, owner can read when time permits.
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
# Proactive low-stock monitor
# ============================================================

def proactive_stock_check(ctx: Context) -> Event:
    """Deterministically check inventory and inject alerts into session state.

    WHY THIS NODE EXISTS BEFORE THE OWNER LLM AGENT:
    The Owner Agent's instructions say "always run check_inventory", but LLMs
    can be unpredictable — they might skip tool calls when they "feel" they
    already know the answer, or when context is long. A deterministic Python
    node runs unconditionally and costs nothing (no LLM call, no API tokens).

    By writing proactive_stock_alert into session state, we give the LLM a
    pre-computed fact it can reference directly in its response, making alerts
    reliable and latency-free — even if the LLM skips the tool call.

    WHY NOT JUST ALWAYS CALL THE TOOL INSIDE THE LLM?
    Tool calls require a full LLM round-trip (~300ms). This node executes in
    microseconds and guarantees the alert appears in every owner session, even
    if the LLM hallucinates or omits the tool call due to context length limits.
    """
    # Local import avoids circular dependency during module loading —
    # menu.py is imported by both tools.py and agent.py.
    from .menu import get_low_stock_items
    low = get_low_stock_items()
    if low:
        names = ", ".join(f"{i['name_en']} ({i['stock']})" for i in low)
        alert_msg = f"LOW STOCK DETECTED: {names}"
    else:
        alert_msg = ""

    # output drives the next edge in the graph (to owner_agent).
    # state is merged into the session so owner_agent can read it via ctx.state.
    return Event(
        output=alert_msg or "stock_ok",
        state={"proactive_stock_alert": alert_msg},
    )


# ============================================================
# Root Workflow (ADK 2.0 graph definition)
# ============================================================
# WHY ADK 2.0 WORKFLOW INSTEAD OF ADK 1.x SEQUENTIAL/PARALLEL AGENT?
# ADK 2.0 Workflow allows conditional branching via routing maps — something
# SequentialAgent cannot do. We need to dispatch to different agents based on
# intent, not always run them in sequence. The Workflow graph compiles to a
# validated directed graph at startup, catching structural errors early.
#
# EDGE FORMAT: ADK 2.0 uses two tuple formats:
#   (A, B)          → unconditional edge: A always leads to B
#   (A, {"r": B})   → routing map: A leads to B only when Event.route == "r"
# The routing map is set as a dict in the edges list, NOT as a 3-tuple.
# (3-tuples were rejected by Pydantic validation — see bug history.)

root_agent = Workflow(
    name="burma_bites",
    description=(
        "Burma Bites — AI agent system that replaces chaotic LINE group chat "
        "ordering for small Burmese restaurants in Bangkok. Built with ADK 2.0 "
        "multi-agent graph workflow, MCP server, and STRIDE security. Serves a "
        "community of ~400 Burmese students near Rangsit University."
    ),
    edges=[
        # Step 1: Every message passes through the router first.
        # "START" is the ADK-reserved entry-point sentinel.
        ("START", route_request),

        # Step 2: Routing map — the dict value tells ADK which node to activate
        # based on the route string emitted by route_request.
        (
            route_request,
            {
                "customer": customer_agent,
                "kitchen":  kitchen_agent,
                # Owner branch goes to proactive check FIRST, not directly to agent.
                "owner":    proactive_stock_check,
            },
        ),

        # ── Customer branch: agent → formatter ───────────────────────────────
        # No intermediate nodes — customer requests are pure conversational NLU.
        (customer_agent, format_customer_response),

        # ── Kitchen branch: agent → formatter ────────────────────────────────
        # No intermediate nodes — kitchen requests are operational status updates.
        (kitchen_agent, format_kitchen_response),

        # ── Owner branch: proactive check → agent → formatter ─────────────────
        # The extra proactive_stock_check node guarantees inventory alerts appear
        # in every owner report, even when the LLM skips the check_inventory call.
        (proactive_stock_check, owner_agent),
        (owner_agent, format_owner_response),
    ],
)

# ============================================================
# App — ADK application wrapper
# ============================================================
# App.name MUST match the directory name ("app") so the ADK CLI and eval
# framework can locate session data, artifacts, and eval results correctly.
# A mismatch causes silent failures in agents-cli playground and eval generate.
app = App(
    root_agent=root_agent,
    name="app",  # Must match the module directory name — do not rename.
)
