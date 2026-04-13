from datetime import datetime

from pydantic import BaseModel


class ProxyBase(BaseModel):
    name: str
    server: str
    port: int
    username: str | None = None
    password: str | None = None
    kind: str = "http"
    country: str | None = None
    sticky_session: bool = False
    enabled: bool = True


class ProxyCreate(ProxyBase):
    pass


class ProxyUpdate(BaseModel):
    name: str | None = None
    server: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    kind: str | None = None
    country: str | None = None
    sticky_session: bool | None = None
    enabled: bool | None = None


class ProxyRead(ProxyBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
