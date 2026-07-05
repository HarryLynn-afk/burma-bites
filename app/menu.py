# Copyright 2026 Burma Bites
#
# Shared in-memory data layer for the Burma Bites restaurant system.
#
# ── DESIGN DECISION: IN-MEMORY STORE ────────────────────────────────────────
# All state (menu, inventory, orders, sales) is kept in module-level Python
# dicts and lists. This is intentional for a prototype/course demo:
#   - Zero infrastructure dependency — no DB to spin up for local testing
#   - Instant reset between playground sessions (process restart = clean state)
#   - Trivial to inspect and modify during demos
#
# In production, these should be replaced:
#   MENU       → Cloud Firestore or Cloud SQL (with admin UI for editing)
#   INVENTORY  → Firestore (with real-time listeners for low-stock alerts)
#   ORDERS     → Firestore (for multi-instance consistency)
#   SALES_TODAY → BigQuery (for historical analytics and reporting)
#
# ── WHY SHARED MODULE-LEVEL STATE INSTEAD OF A CLASS? ───────────────────────
# All three agents (customer, kitchen, owner) need to read and write the
# same order book and inventory. Since they all run inside a single Python
# process (the ADK playground), module-level globals are the simplest shared
# memory mechanism. In a distributed deployment, replace with a real DB.

from __future__ import annotations

import collections
import fcntl
import json
import os
from typing import Any

class SharedDict(collections.UserDict):
    """A dictionary-like object that persists its data to a JSON file on disk.
    Uses file locking via fcntl to be process-safe and thread-safe.
    """
    def __init__(self, filename: str, default_factory: Any = None):
        self.filename = os.path.abspath(filename)
        # Create directory automatically if it doesn't exist
        os.makedirs(os.path.dirname(self.filename), exist_ok=True)
        # Initialize file if it doesn't exist or is empty/default-empty
        needs_init = not os.path.exists(self.filename)
        if not needs_init:
            try:
                with open(self.filename, 'r') as f:
                    content = f.read().strip()
                    if not content or content == '{}':
                        needs_init = True
            except Exception:
                needs_init = True

        if needs_init:
            initial_data = default_factory() if default_factory else {}
            with open(self.filename, 'w') as f:
                json.dump(initial_data, f)
        super().__init__()

    def _load(self) -> dict[str, Any]:
        if not os.path.exists(self.filename):
            return {}
        try:
            with open(self.filename, 'r') as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    return json.load(f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except Exception:
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        try:
            with open(self.filename, 'r+') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    json.dump(data, f)
                    f.truncate()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except Exception:
            with open(self.filename, 'w') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    json.dump(data, f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

    def __getitem__(self, key: str) -> Any:
        return self._load()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        try:
            with open(self.filename, 'r+') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    d = json.load(f)
                except Exception:
                    d = {}
                d[key] = value
                f.seek(0)
                json.dump(d, f)
                f.truncate()
                fcntl.flock(f, fcntl.LOCK_UN)
        except Exception:
            d = self._load()
            d[key] = value
            self._save(d)

    def __delitem__(self, key: str) -> None:
        try:
            with open(self.filename, 'r+') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    d = json.load(f)
                except Exception:
                    d = {}
                if key in d:
                    del d[key]
                f.seek(0)
                json.dump(d, f)
                f.truncate()
                fcntl.flock(f, fcntl.LOCK_UN)
        except Exception:
            d = self._load()
            if key in d:
                del d[key]
            self._save(d)

    def setdefault(self, key: str, default: Any = None) -> Any:
        try:
            with open(self.filename, 'r+') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    d = json.load(f)
                except Exception:
                    d = {}
                if key not in d:
                    d[key] = default
                    f.seek(0)
                    json.dump(d, f)
                    f.truncate()
                    val = default
                else:
                    val = d[key]
                fcntl.flock(f, fcntl.LOCK_UN)
                return val
        except Exception:
            d = self._load()
            val = d.setdefault(key, default)
            self._save(d)
            return val

    def pop(self, key: str, *args: Any) -> Any:
        try:
            with open(self.filename, 'r+') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    d = json.load(f)
                except Exception:
                    d = {}
                if key in d:
                    val = d.pop(key)
                    f.seek(0)
                    json.dump(d, f)
                    f.truncate()
                else:
                    if args:
                        val = args[0]
                    else:
                        raise KeyError(key)
                fcntl.flock(f, fcntl.LOCK_UN)
                return val
        except Exception:
            d = self._load()
            val = d.pop(key, *args)
            self._save(d)
            return val

    def get(self, key: str, default: Any = None) -> Any:
        return self._load().get(key, default)

    def __contains__(self, key: Any) -> bool:
        return key in self._load()

    def __len__(self) -> int:
        return len(self._load())

    def __iter__(self) -> Any:
        return iter(self._load())

    def keys(self) -> Any:
        return self._load().keys()

    def values(self) -> Any:
        return self._load().values()

    def items(self) -> Any:
        return self._load().items()

    def clear(self) -> None:
        self._save({})

    @property
    def data(self) -> dict[str, Any]:
        return self._load()

    @data.setter
    def data(self, value: dict[str, Any]) -> None:
        self._save(value)


# ---------------------------------------------------------------------------
# Menu definition
# ---------------------------------------------------------------------------
# Each item has:
#   id          – snake_case unique key, used as the foreign key in orders/inventory
#   name_en     – English name for the LLM and English-speaking staff
#   name_my     – Burmese name in Myanmar Unicode script (for Burmese customers)
#   name_th     – Thai name (for Thai-speaking customers and menus)
#   category    – "food" | "drink" | "side" (used for menu filtering)
#   price_thb   – price in Thai Baht (the operating currency for Thailand)
#   description – short English description fed to the customer agent for Q&A
#   allergens   – list of allergen tags for customer safety queries
#
# WHY THREE-LANGUAGE NAMES?
# Burma Bites serves a mixed customer base in Thailand. Burmese expat workers
# may order in Burmese (မြန်မာဘာသာ), Thai locals in Thai (ภาษาไทย), and
# tourists in English. Including all three names lets the Customer Agent
# respond accurately in any language without hallucinating translations.

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
        "allergens": [],  # No common allergens
    },
    {
        "id": "young_coconut",
        "name_en": "Young Coconut",
        "name_my": "အုန်းသီးရည်",
        "name_th": "มะพร้าวอ่อน",
        "category": "drink",
        "price_thb": 45,
        "description": "Fresh young coconut water with coconut flesh.",
        "allergens": [],  # No common allergens
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

# Fast O(1) lookup by item ID — avoids linear scan of MENU on every order line.
# Built once at module load; not mutated at runtime.
MENU_BY_ID: dict[str, dict[str, Any]] = {item["id"]: item for item in MENU}

# ---------------------------------------------------------------------------
# In-memory inventory (units available to sell today)
# ---------------------------------------------------------------------------
# Keys must exactly match MENU item IDs — any mismatch causes silent "sold out"
# responses from the Customer Agent (INVENTORY.get(item_id, 0) returns 0).
# In production: load from Firestore and subscribe to real-time updates.
INVENTORY = SharedDict(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "inventory.json"),
    default_factory=lambda: {
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
)

# WHY 5 AS THE LOW_STOCK_THRESHOLD?
# 5 portions is roughly one busy lunch rush for a single dish at a small
# restaurant. Alerting at 5 gives the owner time to restock before running out.
# This is a business rule, not a technical constant — make it configurable
# (e.g., via env var or Firebase Remote Config) before going to production.
LOW_STOCK_THRESHOLD = 5

# ---------------------------------------------------------------------------
# Order book  {order_id → order_dict}
# ---------------------------------------------------------------------------
import uuid
from datetime import datetime

# Status constants — defined here so they can be imported by tools.py and
# referenced without hardcoding string literals throughout the codebase.
# WHY NOT AN ENUM? The MCP layer and LLM both work with plain strings.
# Converting to/from an Enum adds overhead and complexity for no safety gain
# in a string-dominated protocol like MCP.
STATUS_RECEIVED  = "received"    # Order placed, not yet seen by kitchen
STATUS_PREPARING = "preparing"   # Kitchen has acknowledged and started cooking
STATUS_READY     = "ready"       # Food is plated, waiting for service staff
STATUS_SERVED    = "served"      # Food delivered to the customer's table
STATUS_CANCELLED = "cancelled"   # Order cancelled (e.g. item unavailable)

ORDERS = SharedDict(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "orders.json")
)

# SALES_TODAY accumulates item quantities sold within the current process session.
# Used by get_sales_summary() and suggest_daily_special() (high stock = promote it).
# Resets on process restart — for real persistence, write to a daily BigQuery table.
SALES_TODAY = SharedDict(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sales.json")
)


def create_order(items: list[dict[str, Any]], table_number: str | None = None) -> dict[str, Any]:
    """Create a new order, deduct from inventory, and record the sale.

    WHY DEDUCT INVENTORY HERE (IN THE DATA LAYER) RATHER THAN IN TOOLS?
    Inventory deduction is an atomic side effect of placing an order. Doing it
    here ensures it happens exactly once, regardless of which code path called
    create_order. If we did it in tools.py or mcp_server.py, a future caller
    of create_order might forget to deduct, causing inventory inconsistency.

    CONCURRENCY NOTE: Python's GIL makes simple dict updates effectively atomic
    for our single-process in-memory store. In a production DB, use a
    transaction to prevent double-deduction on concurrent order placement.
    """
    # UUID[:8] gives an 8-char hex ID. Short enough for staff to read aloud
    # ("Order A1B2C3D4 is ready") but long enough to avoid collisions in a
    # small restaurant context (~4 billion combinations).
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
        # Deduct from inventory — floor at 0 to prevent negative stock counts.
        INVENTORY[item_id] = max(0, INVENTORY.get(item_id, 0) - quantity)
        # Accumulate in the daily sales ledger for analytics.
        SALES_TODAY[item_id] = SALES_TODAY.get(item_id, 0) + quantity

    order = {
        "order_id":    order_id,
        "table":       table_number or "walk-in",
        "items":       line_items,
        "total_thb":   total_thb,
        "status":      STATUS_RECEIVED,  # All new orders start in "received" state
        "created_at":  datetime.now().isoformat(),
        "updated_at":  datetime.now().isoformat(),
    }
    ORDERS[order_id] = order
    return order


def update_order_status(order_id: str, new_status: str) -> dict[str, Any]:
    """Update the status of an existing order and record the change timestamp.

    WHY STORE updated_at?
    The Kitchen Agent can use this to identify stale orders (e.g., an order
    that has been in "received" state for > N minutes). In the current demo
    this is a display field; in production it would drive SLA alerts.
    """
    if order_id not in ORDERS:
        raise ValueError(f"Order {order_id} not found.")
    valid = {STATUS_RECEIVED, STATUS_PREPARING, STATUS_READY, STATUS_SERVED, STATUS_CANCELLED}
    if new_status not in valid:
        raise ValueError(f"Invalid status: {new_status}. Valid: {valid}")
    order = ORDERS[order_id]
    order["status"] = new_status
    order["updated_at"] = datetime.now().isoformat()
    ORDERS[order_id] = order
    return order


def get_low_stock_items(threshold: int = LOW_STOCK_THRESHOLD) -> list[dict[str, Any]]:
    """Return all menu items whose current stock is at or below threshold.

    WHY IS THIS A FREE FUNCTION (NOT INLINED IN tools.py)?
    It is called by both the owner tools (check_inventory) and the proactive
    stock check node in agent.py. Centralizing the logic here ensures both
    callers use identical threshold logic and return the same data shape.
    """
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
