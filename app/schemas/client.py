from pydantic import BaseModel

from app.models.automation_job import JobTarget


class ClientJobCreate(BaseModel):
    profile_id: str | None = None
    target: JobTarget
    prompt: str
    negative_prompt: str | None = None
    count: int = 1
    provider_payload: dict | None = None
    reference_images: list[str] | None = None
    ratio: str | None = None
    quality: str | None = None
    duration: int | None = None
