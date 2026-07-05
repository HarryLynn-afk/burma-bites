# Copyright 2026 Burma Bites
import pytest

from app.menu import (
    INVENTORY,
    MENU_BY_ID,
    ORDERS,
    STATUS_RECEIVED,
    STATUS_PREPARING,
    create_order,
    update_order_status,
    get_low_stock_items,
)

def test_create_order_success():
    """Test that creating a valid order deducts inventory and sets status."""
    # Reset inventory for test
    INVENTORY["mohinga"] = 10
    
    items = [{"item_id": "mohinga", "quantity": 2}]
    order = create_order(items, table_number="5")
    
    assert order["table"] == "5"
    assert order["status"] == STATUS_RECEIVED
    assert len(order["items"]) == 1
    assert order["items"][0]["quantity"] == 2
    assert INVENTORY["mohinga"] == 8
    assert order["order_id"] in ORDERS

def test_create_order_invalid_item():
    """Test that creating an order with an unknown item raises ValueError."""
    items = [{"item_id": "not_a_real_item", "quantity": 1}]
    with pytest.raises(ValueError, match="Unknown menu item: not_a_real_item"):
        create_order(items, table_number="1")

def test_update_order_status():
    """Test that order statuses update correctly and validate inputs."""
    INVENTORY["laphet_thoke"] = 10
    items = [{"item_id": "laphet_thoke", "quantity": 1}]
    order = create_order(items, table_number="2")
    order_id = order["order_id"]
    
    # Valid transition
    updated = update_order_status(order_id, STATUS_PREPARING)
    assert updated["status"] == STATUS_PREPARING
    
    # Invalid transition
    with pytest.raises(ValueError, match="Invalid status: fake_status"):
        update_order_status(order_id, "fake_status")

def test_get_low_stock_items():
    """Test that the low stock threshold accurately flags items."""
    INVENTORY["shan_noodles"] = 2  # Below default threshold of 5
    INVENTORY["samosa"] = 50       # Above threshold
    
    low_stock = get_low_stock_items(threshold=5)
    
    # Verify shan_noodles is in the list
    assert any(item["item_id"] == "shan_noodles" for item in low_stock)
    # Verify samosa is NOT in the list
    assert not any(item["item_id"] == "samosa" for item in low_stock)
