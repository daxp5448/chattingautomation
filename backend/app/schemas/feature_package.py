import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.feature_registry import FEATURE_REGISTRY


def _validate_codes(codes: list[str]) -> list[str]:
    unknown = [c for c in codes if c not in FEATURE_REGISTRY]
    if unknown:
        raise ValueError(f"Unknown feature code(s): {', '.join(unknown)}")
    return codes


class FeaturePackageBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    feature_codes: list[str] = []
    is_default: bool = False

    @field_validator("feature_codes")
    @classmethod
    def _codes_are_known(cls, v: list[str]) -> list[str]:
        return _validate_codes(v)


class FeaturePackageCreate(FeaturePackageBase):
    pass


class FeaturePackageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    feature_codes: list[str] | None = None
    is_default: bool | None = None

    @field_validator("feature_codes")
    @classmethod
    def _codes_are_known(cls, v: list[str] | None) -> list[str] | None:
        return v if v is None else _validate_codes(v)


class FeaturePackageRead(FeaturePackageBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
