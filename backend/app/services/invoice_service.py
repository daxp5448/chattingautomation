import io

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.models.branch import Branch
from app.models.order import Order
from app.models.restaurant import Restaurant

# Bottom margin below which a new page is started rather than drawing off the page.
_BOTTOM_MARGIN = 30 * mm
_TOP_MARGIN_Y_OFFSET = 20 * mm


def generate_invoice_pdf(order: Order, restaurant: Restaurant, branch: Branch) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    _, height = A4
    y = height - _TOP_MARGIN_Y_OFFSET

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, restaurant.name)
    y -= 8 * mm
    c.setFont("Helvetica", 9)
    if restaurant.gst_number:
        c.drawString(20 * mm, y, f"GSTIN: {restaurant.gst_number}")
        y -= 5 * mm
    if restaurant.address:
        c.drawString(20 * mm, y, restaurant.address)
        y -= 5 * mm

    y -= 5 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, y, f"Invoice {order.invoice_number or order.order_number}")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, f"Order: {order.order_number}")
    y -= 5 * mm
    c.drawString(20 * mm, y, f"Branch: {branch.name}")
    y -= 8 * mm

    def _ensure_room(current_y: float, needed: float = _BOTTOM_MARGIN, font: tuple[str, float] = ("Helvetica", 9)) -> float:
        """Starts a new page and resets to the top margin if there isn't enough room left
        to draw the next row/section above the bottom margin. `showPage()` resets the
        canvas's graphics state, so the font must be reapplied on the fresh page."""
        if current_y - needed < _BOTTOM_MARGIN:
            c.showPage()
            c.setFont(*font)
            return height - _TOP_MARGIN_Y_OFFSET
        return current_y

    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "Item")
    c.drawString(120 * mm, y, "Qty")
    c.drawString(140 * mm, y, "Price")
    c.drawString(165 * mm, y, "Total")
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    for item in order.items:
        y = _ensure_room(y, font=("Helvetica", 9))
        price = float(item.price_snapshot)
        c.drawString(20 * mm, y, item.name_snapshot[:50])
        c.drawString(120 * mm, y, str(item.quantity))
        c.drawString(140 * mm, y, f"{price:.2f}")
        c.drawString(165 * mm, y, f"{price * item.quantity:.2f}")
        y -= 5 * mm

    y = _ensure_room(y, needed=9 * mm, font=("Helvetica", 9))
    y -= 3 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    # Split the combined tax amount into CGST + SGST (each half of order.tax). This
    # assumes intra-state supply (restaurant and customer in the same state), which is
    # the overwhelming majority case for local restaurant delivery/pickup. Inter-state
    # supply would instead need a single IGST line equal to the full order.tax -- that
    # logic is intentionally NOT implemented here; see Restaurant.state (groundwork only,
    # not yet consumed) for where a future IGST branch would key off.
    tax_half = float(order.tax) / 2

    for label, value in [
        ("Subtotal", float(order.subtotal)),
        ("CGST", tax_half),
        ("SGST", tax_half),
        ("Delivery", float(order.delivery_charge)),
        ("Discount", -float(order.discount)),
    ]:
        y = _ensure_room(y, font=("Helvetica", 9))
        c.drawString(140 * mm, y, label)
        c.drawRightString(190 * mm, y, f"{restaurant.currency} {value:.2f}")
        y -= 5 * mm

    y = _ensure_room(y, font=("Helvetica-Bold", 11))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(140 * mm, y, "Total")
    c.drawRightString(190 * mm, y, f"{restaurant.currency} {float(order.total):.2f}")
    y -= 10 * mm

    y = _ensure_room(y, needed=25 * mm, font=("Helvetica", 9))
    qr_buffer = io.BytesIO()
    qrcode.make(order.order_number).save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    c.drawImage(ImageReader(qr_buffer), 20 * mm, y - 25 * mm, width=25 * mm, height=25 * mm)

    if restaurant.invoice_footer:
        c.setFont("Helvetica-Oblique", 8)
        # Footer intentionally stays pinned near the bottom of whatever the current page
        # is (rather than following `y`), matching its original fixed placement.
        c.drawString(20 * mm, 15 * mm, restaurant.invoice_footer[:150])

    c.showPage()
    c.save()
    return buffer.getvalue()
