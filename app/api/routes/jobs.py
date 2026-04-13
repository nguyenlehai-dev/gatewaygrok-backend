from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.config import settings
from app.models.automation_job import AutomationJob, JobStatus
from app.models.profile import Profile
from app.schemas.job import JobCreate, JobRead
from app.services.job_runner import job_runner
from app.services.session_guard import ensure_profile_session_ready

router = APIRouter()


def _collect_job_files(job: AutomationJob) -> list[str]:
    result = job.result_payload or {}
    files: list[str] = []
    media = result.get("media_urls")
    if isinstance(media, list):
        files.extend([item for item in media if isinstance(item, str) and item])
    debug_screenshot = result.get("debug_screenshot")
    if isinstance(debug_screenshot, str) and debug_screenshot:
        files.append(debug_screenshot)
    return files


def _safe_delete_paths(paths: list[str]) -> None:
    if not paths:
        return
    allowed_roots = {
        settings.storage_root.resolve(),
        settings.profiles_root.resolve(),
    }
    for raw_path in paths:
        if not raw_path or raw_path.startswith(("http://", "https://", "data:")):
            continue
        normalized = raw_path.replace("\\", "/")
        try:
            candidate = Path(normalized)
            candidate = (Path.cwd() / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        except Exception:  # noqa: BLE001
            continue
        if not any(candidate.is_relative_to(root) for root in allowed_roots):
            continue
        if candidate.exists() and candidate.is_file():
            try:
                candidate.unlink()
            except OSError:
                continue


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


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: str, db: Session = Depends(db_session)):
    job = db.get(AutomationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {JobStatus.PENDING, JobStatus.RUNNING}:
        raise HTTPException(status_code=409, detail="Cannot delete a running job")
    _safe_delete_paths(_collect_job_files(job))
    db.delete(job)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
