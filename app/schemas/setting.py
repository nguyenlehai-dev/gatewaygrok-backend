from pydantic import BaseModel, Field


class AutomationSettings(BaseModel):
    headless: bool = True
    concurrency: int = Field(default=2, ge=1, le=20)
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)


class SettingsRead(BaseModel):
    automation: AutomationSettings


class SettingsUpdate(BaseModel):
    automation: AutomationSettings
