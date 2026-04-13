from pydantic import BaseModel


class ProviderMeta(BaseModel):
    category: str
    provider_name: str
    targets: list[str]
    supports_cookie_import: bool
    supports_proxy: bool
    supports_antidetect: bool
    start_url: str | None = None
    notes: str | None = None


class MetaRead(BaseModel):
    categories: list[str]
    job_targets: list[str]
    job_statuses: list[str]
    providers: list[ProviderMeta]


class OverviewCount(BaseModel):
    total: int
    active: int | None = None


class CategoryCount(BaseModel):
    category: str
    total: int


class QueueSummary(BaseModel):
    pending: int
    running: int
    succeeded: int
    failed: int


class OverviewRead(BaseModel):
    profiles: OverviewCount
    proxies: OverviewCount
    api_keys: OverviewCount
    queue: QueueSummary
    categories: list[CategoryCount]
