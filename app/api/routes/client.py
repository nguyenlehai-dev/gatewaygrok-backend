from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

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

async def _select_profile_from_pool(
    db: Session,
    *,
    allowed_categories: set[str] | None,
) -> Profile:
    query = db.query(Profile).filter(Profile.is_active.is_(True))
    if allowed_categories:
        query = query.filter(Profile.category.in_(sorted(allowed_categories)))
    profiles = query.order_by(desc(Profile.updated_at)).all()

    last_error: HTTPException | None = None
    for profile in profiles:
        try:
            await ensure_profile_session_ready(db, profile)
            return profile
        except HTTPException as exc:  # noqa: PERF203
            last_error = exc
            continue

    detail = {
        "message": "No available profile in pool",
        "categories": sorted(allowed_categories) if allowed_categories else None,
    }
    if last_error is not None:
        detail["last_error"] = last_error.detail
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.post("/generate", response_model=JobRead, status_code=status.HTTP_201_CREATED)
@router.post("/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_client_job(
    payload: ClientJobCreate,
    api_key_record: ApiKey = Depends(require_api_key),
    db: Session = Depends(db_session),
):
    allowed_categories = api_key_service.parse_categories(api_key_record)
    profile: Profile | None = None
    if payload.profile_id:
        profile = db.get(Profile, payload.profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        if allowed_categories and profile.category.value not in allowed_categories:
            raise HTTPException(status_code=403, detail="API key cannot use this profile category")
        await ensure_profile_session_ready(db, profile)
    else:
        profile = await _select_profile_from_pool(db, allowed_categories=allowed_categories)

    job_payload = payload.model_dump()
    job_payload["profile_id"] = profile.id
    job = AutomationJob(**job_payload)
    db.add(job)
    db.commit()
    db.refresh(job)
    await job_runner.enqueue(job.id)
    return job


@router.get("/tasks/{task_id}", response_model=JobRead)
@router.get("/jobs/{task_id}", response_model=JobRead)
async def get_client_job(
    task_id: str,
    api_key_record: ApiKey = Depends(require_api_key),
    db: Session = Depends(db_session),
):
    job = db.get(AutomationJob, task_id)
    if not job:
        raise HTTPException(status_code=404, detail="Task not found")

    profile = db.get(Profile, job.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    allowed_categories = api_key_service.parse_categories(api_key_record)
    if allowed_categories and profile.category.value not in allowed_categories:
        raise HTTPException(status_code=403, detail="API key cannot access this task")

    return job
