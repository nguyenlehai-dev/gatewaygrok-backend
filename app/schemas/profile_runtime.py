from pydantic import BaseModel


class ProfileRuntimeLaunchRequest(BaseModel):
    start_url: str | None = None
    display: str | None = None


class ProfileRuntimeLaunchRead(BaseModel):
    launched: bool
    profile_id: str
    provider: str
    debug_port: int
    debug_endpoint: str
    log_path: str
    display: str | None = None
    message: str


class ProfileRuntimeStatusRead(BaseModel):
    profile_id: str
    provider: str
    requires_live_browser: bool
    running: bool
    debug_port: int
    debug_endpoint: str
    debug_port_open: bool
    browser_process_count: int
    log_path: str
    display: str | None = None


class ProfileRuntimeStopRequest(BaseModel):
    display: str | None = None


class ProfileRuntimeStopRead(BaseModel):
    stopped: bool
    profile_id: str
    provider: str
    log_path: str
    display: str | None = None
    message: str
