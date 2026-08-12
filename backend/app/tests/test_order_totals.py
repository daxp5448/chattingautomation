from app.models.restaurant import Restaurant
from app.services.order_service import compute_totals


def _restaurant(delivery_charge: float = 30) -> Restaurant:
    return Restaurant(name="Test", slug="test", delivery_charge=delivery_charge)


def test_compute_totals_single_item():
    restaurant = _restaurant(delivery_charge=30)
    cart = [{"price": 100, "qty": 2, "gst_percent": 5}]

    totals = compute_totals(restaurant, cart)

    assert totals["subtotal"] == 200
    assert totals["tax"] == 10
    assert totals["delivery_charge"] == 30
    assert totals["discount"] == 0
    assert totals["total"] == 240


def test_compute_totals_multiple_items_no_gst():
    restaurant = _restaurant(delivery_charge=0)
    cart = [
        {"price": 50, "qty": 1, "gst_percent": 0},
        {"price": 75.5, "qty": 3, "gst_percent": 0},
    ]

    totals = compute_totals(restaurant, cart)

    assert totals["subtotal"] == 276.5
    assert totals["tax"] == 0
    assert totals["total"] == 276.5


def test_compute_totals_empty_cart():
    restaurant = _restaurant()
    totals = compute_totals(restaurant, [])
    assert totals["subtotal"] == 0
    assert totals["total"] == restaurant.delivery_charge
