from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str
    rate_limit_per_minute: int = Field(default=30, ge=1, le=10000)
    allowed_categories: list[str] = Field(default_factory=list)
    notes: str | None = None


class ApiKeyUpdate(BaseModel):
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10000)
    allowed_categories: list[str] | None = None
    is_active: bool | None = None
    notes: str | None = None


class ApiKeyRead(BaseModel):
    id: str
    name: str
    key_prefix: str
    rate_limit_per_minute: int
    is_active: bool
    allowed_categories: list[str]
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyRead):
    plain_key: str
