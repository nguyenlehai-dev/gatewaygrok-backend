from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.models.automation_job import AutomationJob, JobStatus
from app.models.profile import Profile
from app.schemas.job import JobCreate, JobRead
from app.services.job_runner import job_runner
from app.services.session_guard import ensure_profile_session_ready

router = APIRouter()


@router.get("", response_model=list[JobRead])
def list_jobs(db: Session = Depends(db_session)):
    return db.query(AutomationJob).order_by(AutomationJob.created_at.desc()).all()


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(db_session)):
    job = db.get(AutomationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, db: Session = Depends(db_session)):
    profile = db.get(Profile, payload.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    await ensure_profile_session_ready(db, profile)
    job = AutomationJob(**payload.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    await job_runner.enqueue(job.id)
    return job


@router.post("/{job_id}/retry", response_model=JobRead)
async def retry_job(job_id: str, db: Session = Depends(db_session)):
    job = db.get(AutomationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {JobStatus.FAILED, JobStatus.SUCCEEDED}:
        raise HTTPException(status_code=409, detail="Only completed jobs can be retried")
    await ensure_profile_session_ready(db, job.profile)

    job.status = JobStatus.PENDING
    job.result_payload = None
    job.error_message = None
    db.add(job)
    db.commit()
    db.refresh(job)
    await job_runner.enqueue(job.id)
    return job
