# Copyright 2026 Burma Bites
#
# Shared in-memory menu and inventory store for Burma Bites restaurant system.
# In production, replace with a database (e.g., Firestore, Cloud SQL).

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Menu definition
# ---------------------------------------------------------------------------
# Each item has:
#   id           – unique short key
#   name_en      – English name
#   name_my      – Burmese name (Unicode)
#   name_th      – Thai name
#   category     – food | drink | side
#   price_thb    – price in Thai Baht
#   description  – short English description
#   allergens    – list of common allergens

MENU: list[dict[str, Any]] = [
    # ── MAIN DISHES ────────────────────────────────────────────────────────
    {
        "id": "mohinga",
        "name_en": "Mohinga",
        "name_my": "မုန့်ဟင်းခါး",
        "name_th": "โมฮิงกา",
        "category": "food",
        "price_thb": 80,
        "description": "Traditional Burmese fish noodle soup with lemongrass and banana stem.",
        "allergens": ["fish", "gluten"],
    },
    {
        "id": "laphet_thoke",
        "name_en": "Lahpet Thoke",
        "name_my": "လက်ဖက်သုပ်",
        "name_th": "สลัดใบชาหมัก",
        "category": "food",
        "price_thb": 90,
        "description": "Pickled tea leaf salad with crunchy nuts, sesame, and lime.",
        "allergens": ["nuts", "sesame"],
    },
    {
        "id": "shan_noodles",
        "name_en": "Shan Noodles",
        "name_my": "ရှမ်းခေါက်ဆွဲ",
        "name_th": "ชาโน",
        "category": "food",
        "price_thb": 75,
        "description": "Shan-style rice noodles in a mild tomato-chicken broth.",
        "allergens": ["gluten"],
    },
    {
        "id": "mont_di",
        "name_en": "Mont Di",
        "name_my": "မုန့်တီ",
        "name_th": "มอนตี",
        "category": "food",
        "price_thb": 70,
        "description": "Mandalay-style rice noodles with chicken gravy and crispy toppings.",
        "allergens": ["gluten"],
    },
    {
        "id": "penneh_gyaw",
        "name_en": "Pe Hmwe Jaw",
        "name_my": "ပဲမွေ့ကြော်",
        "name_th": "ถั่วทอดพม่า",
        "category": "food",
        "price_thb": 60,
        "description": "Crispy Burmese split-pea fritters, served with tamarind dip.",
        "allergens": ["legumes"],
    },
    {
        "id": "htamin_jin",
        "name_en": "Htamin Jin",
        "name_my": "ထမင်းကြမ်း",
        "name_th": "ข้าวหมักพม่า",
        "category": "food",
        "price_thb": 65,
        "description": "Fermented rice with shrimp paste, lime, and fresh toppings.",
        "allergens": ["shellfish"],
    },
    # ── DRINKS ─────────────────────────────────────────────────────────────
    {
        "id": "laphet_yay",
        "name_en": "Lahpet Yay",
        "name_my": "လက်ဖက်ရည်",
        "name_th": "ชาพม่า",
        "category": "drink",
        "price_thb": 35,
        "description": "Traditional Burmese milk tea, sweet and creamy.",
        "allergens": ["dairy"],
    },
    {
        "id": "sugarcane_juice",
        "name_en": "Sugarcane Juice",
        "name_my": "ကြံသီးရည်",
        "name_th": "น้ำอ้อย",
        "category": "drink",
        "price_thb": 30,
        "description": "Fresh-pressed sugarcane juice, served chilled.",
        "allergens": [],
    },
    {
        "id": "young_coconut",
        "name_en": "Young Coconut",
        "name_my": "အုန်းသီးရည်",
        "name_th": "มะพร้าวอ่อน",
        "category": "drink",
        "price_thb": 45,
        "description": "Fresh young coconut water with coconut flesh.",
        "allergens": [],
    },
    # ── SIDES ──────────────────────────────────────────────────────────────
    {
        "id": "balachaung",
        "name_en": "Balachaung",
        "name_my": "ပဲကြော်",
        "name_th": "กุ้งแห้งทอด",
        "category": "side",
        "price_thb": 40,
        "description": "Crispy dried shrimp condiment with garlic and chilli.",
        "allergens": ["shellfish"],
    },
    {
        "id": "samosa",
        "name_en": "Burmese Samosa",
        "name_my": "ဆမူဆာ",
        "name_th": "ซาโมซ่าพม่า",
        "category": "side",
        "price_thb": 50,
        "description": "Crispy pastry filled with spiced potato and peas.",
        "allergens": ["gluten", "legumes"],
    },
]

# Build a quick lookup dict by id
MENU_BY_ID: dict[str, dict[str, Any]] = {item["id"]: item for item in MENU}

# ---------------------------------------------------------------------------
# In-memory inventory (units available to sell today)
# ---------------------------------------------------------------------------
# Keys match MENU item IDs. Values are current stock counts.
INVENTORY: dict[str, int] = {
    "mohinga": 30,
    "laphet_thoke": 25,
    "shan_noodles": 20,
    "mont_di": 15,
    "penneh_gyaw": 40,
    "htamin_jin": 10,
    "laphet_yay": 50,
    "sugarcane_juice": 60,
    "young_coconut": 20,
    "balachaung": 35,
    "samosa": 30,
}

# Threshold below which the owner agent should raise a low-stock alert
LOW_STOCK_THRESHOLD = 5

# ---------------------------------------------------------------------------
# In-memory order book  {order_id -> order_dict}
# ---------------------------------------------------------------------------
import uuid
from datetime import datetime

# Order statuses
STATUS_RECEIVED  = "received"
STATUS_PREPARING = "preparing"
STATUS_READY     = "ready"
STATUS_SERVED    = "served"
STATUS_CANCELLED = "cancelled"

ORDERS: dict[str, dict[str, Any]] = {}

# Cumulative sales ledger  {item_id -> total_sold_today}
SALES_TODAY: dict[str, int] = {}


def create_order(items: list[dict[str, Any]], table_number: str | None = None) -> dict[str, Any]:
    """Create a new order and deduct from inventory."""
    order_id = str(uuid.uuid4())[:8].upper()
    total_thb = 0
    line_items = []

    for line in items:
        item_id  = line["item_id"]
        quantity = int(line.get("quantity", 1))
        menu_item = MENU_BY_ID.get(item_id)
        if not menu_item:
            raise ValueError(f"Unknown menu item: {item_id}")
        subtotal = menu_item["price_thb"] * quantity
        total_thb += subtotal
        line_items.append({
            "item_id":  item_id,
            "name_en":  menu_item["name_en"],
            "quantity": quantity,
            "price_thb": menu_item["price_thb"],
            "subtotal_thb": subtotal,
        })
        # Deduct inventory
        INVENTORY[item_id] = max(0, INVENTORY.get(item_id, 0) - quantity)
        # Record sale
        SALES_TODAY[item_id] = SALES_TODAY.get(item_id, 0) + quantity

    order = {
        "order_id":    order_id,
        "table":       table_number or "walk-in",
        "items":       line_items,
        "total_thb":   total_thb,
        "status":      STATUS_RECEIVED,
        "created_at":  datetime.now().isoformat(),
        "updated_at":  datetime.now().isoformat(),
    }
    ORDERS[order_id] = order
    return order


def update_order_status(order_id: str, new_status: str) -> dict[str, Any]:
    """Update the status of an existing order."""
    if order_id not in ORDERS:
        raise ValueError(f"Order {order_id} not found.")
    valid = {STATUS_RECEIVED, STATUS_PREPARING, STATUS_READY, STATUS_SERVED, STATUS_CANCELLED}
    if new_status not in valid:
        raise ValueError(f"Invalid status: {new_status}. Valid: {valid}")
    ORDERS[order_id]["status"] = new_status
    ORDERS[order_id]["updated_at"] = datetime.now().isoformat()
    return ORDERS[order_id]


def get_low_stock_items(threshold: int = LOW_STOCK_THRESHOLD) -> list[dict[str, Any]]:
    """Return menu items whose inventory is at or below threshold."""
    low = []
    for item_id, count in INVENTORY.items():
        if count <= threshold:
            menu_item = MENU_BY_ID.get(item_id, {})
            low.append({
                "item_id":  item_id,
                "name_en":  menu_item.get("name_en", item_id),
                "stock":    count,
                "threshold": threshold,
            })
    return low
