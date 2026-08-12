import re
import uuid

from app.models.branch import Branch
from app.models.order import Order, OrderItem
from app.models.restaurant import Restaurant
from app.services.invoice_service import generate_invoice_pdf


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Counts `/Type /Page` object dicts in the raw PDF bytes (excluding `/Type /Pages`,
    the single container object). No PDF-parsing library (pypdf/PyPDF2) is installed in
    this environment, so this regex-based count is the pragmatic fallback."""
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf_bytes))


def test_generate_invoice_pdf_produces_valid_pdf_bytes():
    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Test Diner",
        slug="test-diner",
        gst_number="29ABCDE1234F1Z5",
        address="123 Main St",
        currency="INR",
        invoice_footer="Thank you for your order!",
    )
    branch = Branch(id=uuid.uuid4(), restaurant_id=restaurant.id, name="Main Branch")
    order = Order(
        id=uuid.uuid4(),
        restaurant_id=restaurant.id,
        branch_id=branch.id,
        customer_id=uuid.uuid4(),
        order_number="ORD-001",
        subtotal=300,
        tax=15,
        delivery_charge=20,
        discount=10,
        total=325,
    )
    order.items = [
        OrderItem(id=uuid.uuid4(), order_id=order.id, product_id=uuid.uuid4(), name_snapshot="Burger", price_snapshot=150, quantity=2)
    ]

    pdf_bytes = generate_invoice_pdf(order, restaurant, branch)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_generate_invoice_pdf_handles_missing_optional_fields():
    restaurant = Restaurant(id=uuid.uuid4(), name="Minimal Diner", slug="minimal-diner", currency="INR")
    branch = Branch(id=uuid.uuid4(), restaurant_id=restaurant.id, name="Only Branch")
    order = Order(
        id=uuid.uuid4(),
        restaurant_id=restaurant.id,
        branch_id=branch.id,
        customer_id=uuid.uuid4(),
        order_number="ORD-002",
        subtotal=100,
        tax=0,
        delivery_charge=0,
        discount=0,
        total=100,
    )
    order.items = []

    pdf_bytes = generate_invoice_pdf(order, restaurant, branch)

    assert pdf_bytes.startswith(b"%PDF")


def test_generate_invoice_pdf_paginates_when_many_line_items():
    """An order with many line items must overflow onto additional PDF pages instead of
    drawing rows off the bottom of a single page."""
    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Big Order Diner",
        slug="big-order-diner",
        gst_number="29ABCDE1234F1Z5",
        address="123 Main St",
        currency="INR",
        invoice_footer="Thank you for your order!",
    )
    branch = Branch(id=uuid.uuid4(), restaurant_id=restaurant.id, name="Main Branch")
    order = Order(
        id=uuid.uuid4(),
        restaurant_id=restaurant.id,
        branch_id=branch.id,
        customer_id=uuid.uuid4(),
        order_number="ORD-003",
        subtotal=6000,
        tax=300,
        delivery_charge=20,
        discount=0,
        total=6320,
    )
    order.items = [
        OrderItem(
            id=uuid.uuid4(),
            order_id=order.id,
            product_id=uuid.uuid4(),
            name_snapshot=f"Item {i}",
            price_snapshot=100,
            quantity=1,
        )
        for i in range(60)
    ]

    pdf_bytes = generate_invoice_pdf(order, restaurant, branch)

    assert pdf_bytes.startswith(b"%PDF")
    assert _count_pdf_pages(pdf_bytes) > 1
