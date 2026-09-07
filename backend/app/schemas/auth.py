import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    # Optional: the browser admin panel relies on the httpOnly refresh_token cookie
    # instead (it has no JS-readable access to that cookie's value to put here); a body
    # value is only needed by non-browser API clients that don't use cookies at all.
    refresh_token: str | None = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None
    role: UserRole
    restaurant_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None


class SetupCompleteRequest(BaseModel):
    """Body for POST /auth/setup -- completes the one-time setup-token flow started by
    POST /restaurants (see app/core/security.py:generate_setup_token)."""

    token: str
    password: str = Field(min_length=8, max_length=128)


class SignupRequest(BaseModel):
    """Body for POST /signup -- the public self-serve signup form. Deliberately narrow:
    unlike RestaurantCreate (used by the admin-only POST /restaurants), this schema has no
    is_demo/feature_package_id/whatsapp_*/razorpay_* fields at all, so there is no
    allowlist/excludelist to keep in sync -- a stranger simply cannot set them because the
    fields don't exist here."""

    business_name: str = Field(min_length=2, max_length=200)
    owner_email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    niche_code: str


class SignupResult(BaseModel):
    restaurant_id: uuid.UUID
    owner_email: EmailStr
    # Only populated outside production (see app/core/config.py::settings.ENVIRONMENT) --
    # mirrors the existing RestaurantCreateResult.setup_url convention of returning an
    # out-of-band secret directly in dev/test so nothing here depends on SMTP being
    # configured locally. Never populated in production; the OTP is only ever emailed then.
    debug_otp_code: str | None = None


class VerifyOtpRequest(BaseModel):
    # Keyed by restaurant_id (already in the frontend's hand from POST /signup's response),
    # not owner_email, so this endpoint doesn't become a second email-enumeration surface.
    restaurant_id: uuid.UUID
    code: str = Field(min_length=6, max_length=6)


class ResendOtpRequest(BaseModel):
    restaurant_id: uuid.UUID


class ResendOtpResult(BaseModel):
    sent: bool
    debug_otp_code: str | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool
    restaurant_id: uuid.UUID | None
    branch_id: uuid.UUID | None
