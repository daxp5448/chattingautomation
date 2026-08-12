import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.customer_repository import CustomerRepository
from app.repositories.loyalty_repository import LoyaltyTransactionRepository
from app.schemas.customer import CustomerRead, CustomerReadLimited, CustomerUpdate
from app.schemas.loyalty import LoyaltyTransactionRead

router = APIRouter(prefix="/restaurants/{restaurant_id}/customers", tags=["customers"])


# No response_model on list_customers below: which of these two shapes comes back is a
# per-request, role-dependent decision (see _serialize_customer), and pinning a single
# static response_model (or a Union of the two) risks FastAPI/Pydantic reshaping -- and
# silently dropping fields from -- whichever schema it picks first.
def _serialize_customer(customer, role: UserRole) -> CustomerRead | CustomerReadLimited:
    """The `kitchen` role has no operational need for a customer's phone/email/address,
    so it never leaves the server for that role -- served as CustomerReadLimited instead
    of CustomerRead. Every other staff role (owner/manager/cashier) and super_admin keep
    getting the full record, unchanged from before."""
    if role == UserRole.KITCHEN:
        return CustomerReadLimited.model_validate(customer)
    return CustomerRead.model_validate(customer)


@router.get("")
async def list_customers(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CustomerRepository(db)
    customers = await repo.list(restaurant_id=tenant_id)
    return [_serialize_customer(c, user.role) for c in customers]


@router.patch("/{customer_id}", response_model=CustomerRead)
async def update_customer(
    restaurant_id: uuid.UUID, customer_id: uuid.UUID, payload: CustomerUpdate, db: DbSession, user: CurrentUser
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CustomerRepository(db)
    customer = await repo.get(customer_id, tenant_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    await repo.commit()
    return customer


@router.get("/{customer_id}/loyalty", response_model=list[LoyaltyTransactionRead])
async def get_customer_loyalty_ledger(restaurant_id: uuid.UUID, customer_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = LoyaltyTransactionRepository(db)
    return await repo.list_for_customer(tenant_id, customer_id)


@router.post("/{customer_id}/anonymize", response_model=CustomerRead)
async def anonymize_customer(
    restaurant_id: uuid.UUID,
    customer_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
):
    """Right-to-erasure, done as anonymization rather than deletion.

    Indian GST law requires a business to retain invoices and other financial records
    for several years (typically 6+, counted from the relevant annual return) -- so a
    literal "delete this customer" would destroy legally-required tax records and create
    a compliance problem instead of solving a privacy one. The correct fix here is to
    blank the customer's directly-identifying PII (name, phone, email, address) while
    leaving every `Order`, `OrderItem`, and `Message` row this customer is linked to
    completely untouched: those are the GST-relevant financial/communication records,
    they stay intact, queryable, and attributable to this same (now-anonymized) customer
    row exactly as before. Nothing here deletes or modifies Order/OrderItem/Message.

    `phone` carries a NOT NULL + unique-per-restaurant constraint (see
    uq_customer_restaurant_phone on the Customer model), so it can't simply be nulled
    out -- it's replaced with a clearly-redacted placeholder derived from the customer's
    own id, which is guaranteed unique.
    """
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = CustomerRepository(db)
    customer = await repo.get(customer_id, tenant_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    customer.name = "Anonymized Customer"
    customer.phone = f"anonymized-{customer.id.hex[:8]}"
    customer.email = None
    customer.address = {}
    # Customer has no dedicated is_anonymized column; the `tags` JSON list already on the
    # model is the least invasive place to leave a marker that this row was anonymized.
    if "anonymized" not in customer.tags:
        customer.tags = [*customer.tags, "anonymized"]

    await repo.commit()
    return customer
