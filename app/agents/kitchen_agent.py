# Copyright 2026 Burma Bites
#
# Kitchen Agent — operational order lifecycle manager.
#
# ── ROLE IN THE SYSTEM ──────────────────────────────────────────────────────
# This agent represents the kitchen staff (cooks, kitchen manager). It never
# talks to customers — it talks to whoever is managing the kitchen: a tablet
# mounted on the pass, a kitchen display system, or the owner checking tickets.
#
# It is activated when the router (agent.py) detects kitchen-staff vocabulary:
# "preparing", "ready", "kitchen", "mark order", etc.
#
# ── WHY THESE THREE TOOLS AND NO OTHERS? ─────────────────────────────────────
# | Tool                         | Why the kitchen needs it                  |
# |------------------------------|-------------------------------------------|
# | list_pending_orders          | See the active work queue (FIFO)          |
# | update_kitchen_order_status  | The core kitchen action — progress orders |
# | get_all_orders               | Full history for shift handover/disputes  |
#
# The kitchen agent CANNOT:
#   - place_order        → bypasses customer confirmation; creates audit problems
#   - check_inventory    → not kitchen's responsibility in this system
#   - restock_item       → owner-only action (business authorization required)
#   - get_sales_summary  → owner-level business data; kitchen staff don't need it
#
# Tool scoping in agent.py (McpToolset.tool_filter) enforces these restrictions
# at the MCP layer — the LLM never even sees those tool signatures.
#
# ── WHY output_schema? ───────────────────────────────────────────────────────
# Structured output lets the format_kitchen_response node in agent.py extract
# the "summary" field (a short human-readable description of what happened)
# and the updated_order_id/new_status fields for downstream processing or
# eval grading (e.g., "did the agent correctly transition order X to 'ready'?").

from google.adk.agents import LlmAgent
from pydantic import BaseModel

# Direct tool imports for IDE support and test environments.
# Overridden in agent.py with McpToolset after module import.
from ..tools import (
    get_all_orders,
    list_pending_orders,
    update_kitchen_order_status,
)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class KitchenAgentOutput(BaseModel):
    """Structured result from the Kitchen Agent.

    The summary field is surfaced to the kitchen staff (or whoever triggered
    the kitchen agent) via format_kitchen_response. The other fields support
    eval grading and downstream automation.
    """
    action: str
    """One of: "status_updated", "orders_listed", "no_action".
    Used by eval graders to verify the agent took the expected action."""

    updated_order_id: str | None = None
    """The order ID that was updated, if any. Enables downstream systems
    (e.g., a customer notification service) to react to status changes."""

    new_status: str | None = None
    """The new status of the updated order ("preparing", "ready", "served",
    "cancelled"). Used by eval graders to verify correct status transitions."""

    summary: str
    """Human-readable summary of what the kitchen agent did this turn.
    This is the only field shown to the user via format_kitchen_response."""


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------
# WHY gemini-3.1-flash-lite?
# Kitchen operations are structured and well-defined — there is very little
# ambiguity about what "mark order A1B2 as ready" means. Flash-Lite handles
# this with low latency, which matters for kitchen throughput during busy
# service periods when multiple status updates may arrive in quick succession.

kitchen_agent = LlmAgent(
    name="kitchen_agent",
    model="gemini-3.1-flash-lite",
    description=(
        "Kitchen-side agent for Burma Bites. Receives new orders, updates "
        "preparation status, and keeps the order queue organised."
    ),
    instruction="""
You are the **Kitchen Manager** for Burma Bites (ဗမာဘိုက်).

## Your responsibilities
1. Monitor incoming orders using list_pending_orders.
2. Update order statuses as the kitchen progresses:
   - **received** → kitchen has seen the ticket
   - **preparing** → cooking has started  
   - **ready**     → food is plated and ready for service
   - **served**    → food has been delivered to the table
3. Confirm status changes concisely.

## Workflow
- Do NOT automatically update new orders (status = "received") to "preparing". Wait for the kitchen staff to explicitly instruct you to start preparing an order (e.g., when they say "start preparing order #12345678").
- When a dish is ready, update the order to "ready".
- When the order is delivered, update to "served".
- If an order must be cancelled (unavailable ingredient, etc.), update to 
  "cancelled" and note the reason in your summary.

## Status transition rules
  received  → preparing  (kitchen starts cooking)
  preparing → ready      (food is plated)
  ready     → served     (delivered to table)
  any       → cancelled  (only if necessary)

## Tools
- list_pending_orders   — see all active orders (FIFO, oldest first)
- get_all_orders        — see full order history (for shift handover)
- update_kitchen_order_status — change an order's status

## Tone
- Professional, concise, focused on speed and accuracy.
- Use short confirmations like "Order #A1B2C3D4 → preparing ✅".
- Alert if an order has been in "received" state for more than the time 
  shown without being acknowledged.

## Rules
- NEVER skip a status step (e.g., cannot jump from received to served).
- NEVER mark an order ready without actually cooking it.
- Always use the exact 8-character order ID returned by the system.
""",
    output_schema=KitchenAgentOutput,
    # output_key stores structured output in session state for format_kitchen_response.
    output_key="kitchen_result",
    mode="chat",
    # Tools are overridden in agent.py with McpToolset after this module loads.
    tools=[list_pending_orders, update_kitchen_order_status, get_all_orders],
)
