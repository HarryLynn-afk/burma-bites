# Copyright 2026 Burma Bites
#
# Kitchen Agent — receives confirmed orders, manages their lifecycle status
# (received → preparing → ready → served).

from google.adk.agents import LlmAgent
from pydantic import BaseModel

from ..tools import (
    get_all_orders,
    list_pending_orders,
    update_kitchen_order_status,
)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class KitchenAgentOutput(BaseModel):
    """Structured result from the Kitchen Agent."""
    action: str
    """One of: "status_updated", "orders_listed", "no_action"."""

    updated_order_id: str | None = None
    """The order ID that was updated, if any."""

    new_status: str | None = None
    """The new status of the updated order, if any."""

    summary: str
    """Human-readable summary of what was done (for logs/owner visibility)."""


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

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
- When a new order arrives (status = "received"), acknowledge it and 
  update it to "preparing" immediately to signal the kitchen has started.
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
- list_pending_orders   — see all active orders
- get_all_orders        — see full order history
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
    output_key="kitchen_result",
    tools=[list_pending_orders, update_kitchen_order_status, get_all_orders],
)
