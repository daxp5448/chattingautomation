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


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool
    restaurant_id: uuid.UUID | None
    branch_id: uuid.UUID | None
