# Copyright 2026 Burma Bites
#
# Owner Agent — proactive business intelligence agent.
#
# ── ROLE IN THE SYSTEM ──────────────────────────────────────────────────────
# This agent is the "always-on manager" of the restaurant. Unlike the customer
# and kitchen agents (which are purely reactive — they respond when called),
# the Owner Agent is designed to be PROACTIVE: it reports key business metrics
# and raises critical alerts on every invocation, regardless of what the owner
# asked.
#
# ── WHY "PROACTIVE" IS IMPLEMENTED AS A GRAPH NODE, NOT JUST AN INSTRUCTION ─
# The owner_agent's instructions say "always run check_inventory, get_sales_summary,
# and suggest_daily_special without being asked." But LLMs are probabilistic —
# they can skip tool calls when context is long, when the question seems narrow,
# or when they "feel" they already know the answer from prior turns.
#
# To make the proactive behavior RELIABLE, agent.py inserts a deterministic
# Python node (proactive_stock_check) BEFORE this agent runs. That node
# directly checks inventory and writes any low-stock alerts into session state.
# This guarantees alerts appear in every owner report — even if this LLM agent
# happens to skip the check_inventory tool call.
#
# In other words: the Python node provides the GUARANTEE, the LLM provides the
# NARRATIVE. Both run on every owner branch invocation.
#
# ── WHY THESE FOUR TOOLS AND NO OTHERS? ─────────────────────────────────────
# | Tool                  | Why the owner needs it                          |
# |-----------------------|-------------------------------------------------|
# | check_inventory       | Know current stock levels and low-stock items   |
# | get_sales_summary     | Daily revenue, top sellers, slow movers         |
# | suggest_daily_special | Data-driven upsell suggestions (inventory-led)  |
# | restock_item          | Execute restocking decisions the owner approves |
#
# The owner CANNOT:
#   - place_order          → bypasses customer flow; creates fraud risk
#   - update_kitchen_order_status → kitchen accountability (agent separation)
#   - get_order_status     → individual order lookup is customer/kitchen domain
#   - list_pending_orders  → kitchen operational view, not owner's dashboard
#
# ── WHY output_schema WITH FIVE FIELDS? ─────────────────────────────────────
# The OwnerAgentOutput schema produces a structured dict that format_owner_response
# in agent.py renders into a prioritized report: alerts first, then sales,
# then specials, then recommendations. This ordering is intentional — the owner
# is busy and may only read the top of the report. Critical alerts must come first.
# The structured schema also enables eval grading: "did the agent correctly
# identify low-stock items?" can be checked by inspecting the alerts list.

from google.adk.agents import LlmAgent
from pydantic import BaseModel

# Direct tool imports for IDE support and test environments.
# Overridden in agent.py with McpToolset after module import.
from ..tools import (
    check_inventory,
    get_sales_summary,
    restock_item,
    suggest_daily_special,
)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class OwnerAgentOutput(BaseModel):
    """Structured result from the Owner Agent.

    WHY FIVE SEPARATE FIELDS INSTEAD OF A SINGLE "report" STRING?
    Structured fields let format_owner_response render them in priority order
    (alerts → sales → specials → recommendations). A free-form string would
    require regex parsing to extract individual alerts or recommendations for
    downstream automation (e.g., sending low-stock Slack alerts).
    """
    alerts: list[str]
    """Proactive alerts such as low-stock or out-of-stock warnings.
    Rendered FIRST in the owner report (highest urgency).
    Can be empty [] when all stock levels are healthy."""

    daily_specials: list[str]
    """Suggested daily specials with business rationale (inventory-led).
    Each entry is a formatted string ready for the chalkboard or LINE message."""

    sales_summary: str
    """2-3 sentence narrative of today's revenue and top sellers.
    Written in a direct, data-driven style for a busy owner."""

    actions_taken: list[str]
    """Audit trail of actions the agent performed this turn
    (e.g., "Checked inventory", "Ran sales summary", "Restocked mohinga x20").
    Used for observability and eval grading."""

    recommendations: list[str]
    """Strategic tips for the owner (lowest urgency, read when time permits).
    Rendered LAST in the report. Examples: combo deal suggestions, scheduling tips."""


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------
# WHY gemini-3.1-flash-lite?
# The owner agent needs to: run 3 tool calls, synthesize the results into a
# structured business report, and generate alert language. Flash-Lite handles
# this well. A more capable (and expensive) model would only benefit if the
# owner starts asking complex multi-step analytical questions — at which point
# the model parameter can be upgraded here without any other code changes.

owner_agent = LlmAgent(
    name="owner_agent",
    model="gemini-3.1-flash-lite",
    description=(
        "Proactive owner/manager intelligence agent for Burma Bites. "
        "Monitors inventory, tracks sales, suggests specials, and raises "
        "alerts automatically without waiting to be asked."
    ),
    instruction="""
You are the **Business Intelligence Assistant** for Burma Bites (ဗမာဘိုက်),
reporting directly to the restaurant owner.

## Your core mandate — ALWAYS run these checks without being asked:
1. Call check_inventory → flag any items with low stock (≤ 5 units).
2. Call get_sales_summary → compute revenue, top sellers, slow movers.
3. Call suggest_daily_special → recommend 1-2 dishes to promote today.

You run these three checks **every time you are invoked**, regardless of 
what the owner says, and always include the results in your output.

## Low-stock alerts
- For any item with stock ≤ 5, raise an urgent alert in the "alerts" list.
- Format: "⚠️ LOW STOCK: [item name] — only [n] portions left. Consider 
  restocking or removing from menu."
- If stock = 0, escalate: "🚨 OUT OF STOCK: [item name] — remove from menu 
  immediately!"

## Sales analysis
- Identify the top 3 best-selling items today.
- Identify any items with 0 sales today (potential menu dead weight).
- Compute estimated daily revenue.
- Write a 2-3 sentence narrative for the owner.

## Daily specials suggestion
- Choose dishes from the suggest_daily_special results.
- Provide a brief rationale (e.g., "High stock of Sugarcane Juice — 
  promote as a combo with Mohinga at ฿100 for 10% savings").
- Format for a chalkboard sign in Burmese + English + Thai.

## Restocking
- Only call restock_item if the owner explicitly requests it.
- Confirm the quantity and item before restocking.

## Tone
- Direct and data-driven. The owner is busy — be concise.
- Use emojis sparingly to flag priority (⚠️ = warning, 🚨 = critical, 
  ✅ = good, 📊 = data).
- Speak in English unless the owner writes in another language.

## Output format
Always fill in ALL fields of your output schema:
- alerts:          list of alert strings (can be empty [])
- daily_specials:  list of formatted special strings
- sales_summary:   short paragraph
- actions_taken:   list of actions you performed (e.g. "Checked inventory")
- recommendations: strategic tips for the owner

## Rules
- NEVER restock without explicit owner instruction.
- NEVER modify order statuses (that is the Kitchen Agent's job).
- ALWAYS run the three mandatory checks, even if the owner just says "hello".
""",
    output_schema=OwnerAgentOutput,
    # output_key writes the structured result into session state under "owner_result".
    # format_owner_response in agent.py reads this key and renders the prioritized
    # report in the order: alerts → sales → specials → recommendations.
    output_key="owner_result",
    mode="chat",
    # Tools are overridden in agent.py with McpToolset after this module loads.
    # Listed here for IDE type-checking and direct unit test invocation.
    tools=[check_inventory, get_sales_summary, suggest_daily_special, restock_item],
)
