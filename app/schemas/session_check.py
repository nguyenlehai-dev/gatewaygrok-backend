from pydantic import BaseModel


class SessionCheckRead(BaseModel):
    provider: str
    state: str
    start_url: str
    page_url: str
    title: str
    screenshot_path: str
    cookie_present: bool
    live_browser_connected: bool = False
    requires_live_browser: bool = False
    indicators: list[str]
    summary: str
    body_preview: str
    screenshot_data_url: str | None = None
