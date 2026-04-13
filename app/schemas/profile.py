from datetime import datetime

from pydantic import BaseModel, Field

from app.models.profile import ProfileCategory


class AntidetectConfig(BaseModel):
    user_agent: str | None = None
    locale: str | None = "en-US"
    timezone_id: str | None = "UTC"
    color_scheme: str | None = "dark"
    viewport_width: int | None = 1440
    viewport_height: int | None = 900
    platform: str | None = "Win32"
    hardware_concurrency: int | None = 8


class ProfileBase(BaseModel):
    name: str
    category: ProfileCategory
    description: str | None = None
    is_active: bool = True
    proxy_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    antidetect: AntidetectConfig | None = None
    concurrency_limit: int = 1


class ProfileCreate(ProfileBase):
    pass


class ProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    proxy_id: str | None = None
    tags: list[str] | None = None
    antidetect: AntidetectConfig | None = None
    concurrency_limit: int | None = None


class ProfileRead(ProfileBase):
    id: str
    cookie_file: str | None = None
    cache_dir: str
    user_data_dir: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
