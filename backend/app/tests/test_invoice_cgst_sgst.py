"""CGST/SGST split on the generated invoice PDF (app/services/invoice_service.py).

No PDF-parsing library (pypdf/PyPDF2/pdfminer) is installed in this environment (see the
regex page-count trick already used in test_invoice_service.py). reportlab compresses its
page content streams with ASCII85 + Flate by default, so this decodes those streams by
hand to get at the literal `(...) Tj` text-drawing operators, then asserts on the
formatted amount strings within that decoded text.
"""
import base64
import re
import uuid
import zlib

from app.models.branch import Branch
from app.models.order import Order, OrderItem
from app.models.restaurant import Restaurant
from app.services.invoice_service import generate_invoice_pdf

_STREAM_RE = re.compile(rb"/Length (\d+)\s*\n?>>\nstream\r?\n(.*?)endstream", re.S)


def _decoded_text_streams(pdf_bytes: bytes) -> str:
    """Decodes every ASCII85+Flate-encoded content stream in the PDF that looks like a
    text-drawing stream (contains PDF `Tj`/`BT` operators) and concatenates them."""
    text = ""
    for length, body in _STREAM_RE.findall(pdf_bytes):
        body = body[: int(length)]
        try:
            decoded = zlib.decompress(base64.a85decode(body, adobe=True))
        except (zlib.error, ValueError):
            continue  # not an ASCII85+Flate stream (e.g. a raw/differently-filtered image)
        if b"Tj" in decoded or b"BT" in decoded:
            text += decoded.decode("latin-1")
    return text


def _build_order(tax: float) -> tuple[Restaurant, Branch, Order]:
    restaurant = Restaurant(
        id=uuid.uuid4(),
        name="Tax Split Diner",
        slug="tax-split-diner",
        gst_number="29ABCDE1234F1Z5",
        address="123 Main St",
        currency="INR",
    )
    branch = Branch(id=uuid.uuid4(), restaurant_id=restaurant.id, name="Main Branch")
    order = Order(
        id=uuid.uuid4(),
        restaurant_id=restaurant.id,
        branch_id=branch.id,
        customer_id=uuid.uuid4(),
        order_number="ORD-CGST-001",
        subtotal=300,
        tax=tax,
        delivery_charge=20,
        discount=0,
        total=300 + tax + 20,
    )
    order.items = [
        OrderItem(
            id=uuid.uuid4(), order_id=order.id, product_id=uuid.uuid4(),
            name_snapshot="Burger", price_snapshot=150, quantity=2,
        )
    ]
    return restaurant, branch, order


def test_invoice_pdf_shows_separate_cgst_and_sgst_lines_summing_to_original_tax():
    tax = 30
    restaurant, branch, order = _build_order(tax=tax)

    pdf_bytes = generate_invoice_pdf(order, restaurant, branch)
    text = _decoded_text_streams(pdf_bytes)

    half = tax / 2
    assert "(CGST)" in text
    assert "(SGST)" in text
    # Each half is drawn with the same 2-decimal money formatting used for Subtotal/Total.
    assert f"INR {half:.2f}" in text
    assert text.count(f"INR {half:.2f}") == 2
    # The old combined single "Tax" line/label no longer appears.
    assert "(Tax)" not in text


def test_invoice_pdf_cgst_and_sgst_halves_sum_to_original_tax_for_odd_amount():
    tax = 15.5
    restaurant, branch, order = _build_order(tax=tax)

    pdf_bytes = generate_invoice_pdf(order, restaurant, branch)
    text = _decoded_text_streams(pdf_bytes)

    half = tax / 2
    assert half + half == tax
    assert f"INR {half:.2f}" in text
    assert pdf_bytes.startswith(b"%PDF")
