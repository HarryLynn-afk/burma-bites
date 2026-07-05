# Copyright 2026 Burma Bites
#
# Customer Agent — multilingual front-of-house agent.
#
# ── ROLE IN THE SYSTEM ──────────────────────────────────────────────────────
# This is the only agent that interacts directly with paying customers.
# Its job is natural language understanding (NLU) across three languages,
# menu navigation, and the critical order-taking flow.
#
# It is intentionally the DEFAULT branch in the router (agent.py) — most
# restaurant messages come from customers, so routing to this agent when
# intent is ambiguous is the correct safe default.
#
# ── WHY THESE FOUR TOOLS AND NO OTHERS? ─────────────────────────────────────
# | Tool               | Why the customer agent needs it         |
# |--------------------|------------------------------------------|
# | list_menu          | Browse the menu by category              |
# | get_item_details   | Answer allergen and ingredient questions |
# | place_order        | Submit confirmed orders to the kitchen   |
# | get_order_status   | Answer "where is my food?" queries       |
#
# The customer agent CANNOT call update_kitchen_order_status — that would
# let a customer mark their own food as "served" before it arrives, or
# even cancel another table's order. Tool scoping (via McpToolset.tool_filter
# in agent.py) enforces this at the MCP protocol level, not just by instruction.
#
# ── WHY output_schema (STRUCTURED OUTPUT)? ──────────────────────────────────
# ADK's output_schema forces the LLM to produce a Pydantic-validated JSON
# object instead of free-form text. This gives us:
#   1. Reliable extraction of order_id for downstream processing
#   2. The language_detected field for analytics and eval datasets
#   3. The action field for routing/eval grading (did the agent place an order?)
# The structured output is stored in session state under output_key="customer_result"
# and read by format_customer_response in agent.py.

from google.adk.agents import LlmAgent
from pydantic import BaseModel

# Direct tool imports are used here at agent definition time.
# NOTE: agent.py OVERRIDES these with McpToolset after importing this module.
# The imports here are kept for IDE type-checking and test environments where
# the MCP server is not running.
from ..tools import (
    get_item_details,
    get_order_status,
    list_menu,
    place_order,
)


# ---------------------------------------------------------------------------
# Output schema — structured result passed downstream in the workflow
# ---------------------------------------------------------------------------

class CustomerAgentOutput(BaseModel):
    """Structured result from the Customer Agent.

    WHY PYDANTIC INSTEAD OF A PLAIN DICT?
    Pydantic gives us runtime validation with clear error messages if the LLM
    returns a malformed response. ADK also uses the schema to construct the
    JSON format instruction appended to the agent's system prompt, which
    improves LLM compliance with the output structure.
    """
    action: str
    """One of: "order_placed", "question_answered", "order_status_checked",
    "browsing", "farewell". Used by eval graders to verify correct agent behavior."""

    order_id: str | None = None
    """The order ID if an order was successfully placed, else None.
    Downstream systems (e.g., kitchen display) can extract this from session state."""

    message_to_customer: str
    """The final natural-language response to show/speak to the customer.
    This is the ONLY field surfaced to the customer — all other fields are
    internal. format_customer_response in agent.py extracts this field."""

    language_detected: str = "en"
    """ISO 639-1 code of the language the customer used: 'en', 'my', or 'th'.
    Used in eval analysis to verify multilingual handling is working correctly."""


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------
# WHY gemini-3.1-flash-lite?
# The customer interaction requires NLU, multilingual generation, and some
# reasoning about menu items and allergens — but NOT complex multi-step planning.
# Flash-Lite provides sufficient capability at low latency (important for live
# customer-facing interactions) and low cost (many messages per service shift).

customer_agent = LlmAgent(
    name="customer_agent",
    model="gemini-3.1-flash-lite",
    description=(
        "Multilingual front-of-house agent for Burma Bites restaurant. "
        "Handles menu questions, order taking (Burmese/Thai/English), "
        "and order status inquiries."
    ),
    instruction="""
You are the friendly front-of-house assistant for **Burma Bites** (ဗမာဘိုက်), 
a small Burmese restaurant in Thailand.

## Your responsibilities
1. Greet customers warmly and take food/drink orders.
2. Answer questions about the menu — ingredients, allergens, prices.
3. Check order status when asked.
4. Always confirm the full order with the customer before calling place_order.

## Language policy
- Detect the language the customer is using (Burmese / Thai / English).
- Reply **in the same language** as the customer.
- For Burmese customers: use Myanmar script (ကျေးဇူးတင်ပါသည်) and address 
  them respectfully.
- For Thai customers: reply in Thai (ขอบคุณครับ/ค่ะ).
- For English customers: reply in clear, friendly English.
- You may mix scripts when naming dishes (always give both the local name and 
  the English name).

## Menu guidance
- Use list_menu to show the full menu or filter by category (food/drink/side).
- Use get_item_details for specific ingredient or allergen information.
- Always mention the price in Thai Baht (฿).
- Politely inform the customer if an item is out of stock.

## Ordering process
1. Clarify the customer's full order (items + quantities + table number).
2. Read back the order summary with total price and ask for confirmation.
3. Once confirmed, call place_order with items_json and table_number.
4. After a successful order, give the customer their order ID and tell them 
   the kitchen will prepare it right away.
5. If anything fails, apologise and offer an alternative.

## Order status
- Use get_order_status with the order ID the customer provides.
- Explain the status in simple, friendly terms.

## Tone
- Warm, welcoming, and patient.
- Use "💛" or "🍜" sparingly for a friendly touch.
- Never be rude or dismissive if the customer repeats themselves.

## Important rules
- NEVER invent items not on the menu.
- NEVER place an order without explicit customer confirmation.
- NEVER share internal order IDs of OTHER tables.
""",
    output_schema=CustomerAgentOutput,
    # output_key stores the structured output in session state under this key.
    # format_customer_response in agent.py reads ctx.state["customer_result"]
    # to extract message_to_customer for the user-facing Content event.
    output_key="customer_result",
    include_contents="default",
    # Tools are overridden in agent.py with McpToolset after this module loads.
    # Listed here for IDE support and direct unit test invocation.
    tools=[list_menu, get_item_details, place_order, get_order_status],
)
