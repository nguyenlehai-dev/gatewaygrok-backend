from datetime import datetime

from pydantic import BaseModel, Field

from app.models.automation_job import JobStatus, JobTarget


class JobCreate(BaseModel):
    profile_id: str
    target: JobTarget
    prompt: str
    negative_prompt: str | None = None
    count: int = Field(default=1, ge=1, le=10)
    provider_payload: dict | None = None


class JobRead(BaseModel):
    id: str
    profile_id: str
    target: JobTarget
    prompt: str
    negative_prompt: str | None
    count: int
    status: JobStatus
    provider_payload: dict | None
    result_payload: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
