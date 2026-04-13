from pydantic import BaseModel


class InteractiveLoginLaunchRead(BaseModel):
    launched: bool
    profile_id: str
    provider: str
    message: str
