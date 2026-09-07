"""DEMO billing only -- see app/api/v1/routers/billing.py's module docstring."""

from datetime import datetime

from pydantic import BaseModel


class BillingStatus(BaseModel):
    trial_ends_at: datetime | None
    # Computed server-side (trial_ends_at < now) so the frontend never does its own date
    # math against a possibly-stale/timezone-mismatched clock.
    trial_expired: bool
    is_demo_billing_paid: bool
