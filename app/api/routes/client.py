from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_api_key
from app.models.api_key import ApiKey
from app.models.automation_job import AutomationJob
from app.models.profile import Profile
from app.schemas.client import ClientJobCreate
from app.schemas.job import JobRead
from app.services.api_key_service import api_key_service
from app.services.job_runner import job_runner
from app.services.session_guard import ensure_profile_session_ready

router = APIRouter()


@router.post("/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_client_job(
    payload: ClientJobCreate,
    api_key_record: ApiKey = Depends(require_api_key),
    db: Session = Depends(db_session),
):
    profile = db.get(Profile, payload.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    allowed_categories = api_key_service.parse_categories(api_key_record)
    if allowed_categories and profile.category.value not in allowed_categories:
        raise HTTPException(status_code=403, detail="API key cannot use this profile category")
    await ensure_profile_session_ready(db, profile)

    job = AutomationJob(**payload.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    await job_runner.enqueue(job.id)
    return job
