# Copyright 2026 Burma Bites
#
# Customer Agent — takes natural language orders in Burmese, Thai, or English,
# answers menu questions, and places orders.

from google.adk.agents import LlmAgent
from pydantic import BaseModel

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
    """Structured result from the Customer Agent."""
    action: str
    """One of: "order_placed", "question_answered", "order_status_checked",
    "browsing", "farewell"."""

    order_id: str | None = None
    """The order ID if an order was successfully placed, else None."""

    message_to_customer: str
    """The final natural-language response to show/speak to the customer."""

    language_detected: str = "en"
    """ISO 639-1 code of the language the customer used: 'en', 'my', or 'th'."""


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

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
    output_key="customer_result",
    tools=[list_menu, get_item_details, place_order, get_order_status],
)
