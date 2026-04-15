from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.config import settings
from app.models.automation_job import AutomationJob, JobStatus
from app.models.profile import Profile
from app.schemas.job import JobCreate, JobRead
from app.services.job_runner import job_runner

router = APIRouter()


def _absolute_url(request: Request, value: str) -> str:
    if not value:
        return value
    if value.startswith(("http://", "https://", "data:")):
        return value

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip()
    normalized = value.replace("\\", "/")
    storage_root = settings.storage_root.resolve()

    def _with_public_scheme(url: str) -> str:
        if forwarded_proto in {"http", "https"}:
            return url.replace(f"{request.url.scheme}://", f"{forwarded_proto}://", 1)
        return url

    try:
        candidate = Path(normalized)
        candidate = (Path.cwd() / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if candidate.is_relative_to(storage_root):
            relative = candidate.relative_to(storage_root).as_posix()
            return _with_public_scheme(str(request.url_for("storage", path=relative)))
    except Exception:  # noqa: BLE001
        pass

    storage_prefixes = [
        f"{settings.storage_root.as_posix().rstrip('/')}/",
        "storage-test/",
    ]
    for prefix in storage_prefixes:
        if normalized.startswith(prefix):
            relative = normalized.removeprefix(prefix).lstrip("/")
            return _with_public_scheme(str(request.url_for("storage", path=relative)))

    base = str(request.base_url).rstrip("/")
    if forwarded_proto in {"http", "https"}:
        base = base.replace(f"{request.url.scheme}://", f"{forwarded_proto}://", 1)
    if value.startswith("/"):
        return f"{base}{value}"
    return f"{base}/{value.lstrip('/')}"


def _serialize_job(job: AutomationJob, request: Request) -> AutomationJob:
    result = job.result_payload or {}
    if not isinstance(result, dict):
        return job

    cloned = dict(result)
    media = cloned.get("media_urls")
    if isinstance(media, list):
        cloned["media_urls"] = [_absolute_url(request, item) for item in media if isinstance(item, str)]
    debug_screenshot = cloned.get("debug_screenshot")
    if isinstance(debug_screenshot, str):
        cloned["debug_screenshot"] = _absolute_url(request, debug_screenshot)

    job.result_payload = cloned
    return job


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
def list_jobs(request: Request, db: Session = Depends(db_session)):
    jobs = db.query(AutomationJob).order_by(AutomationJob.created_at.desc()).all()
    return [_serialize_job(job, request) for job in jobs]


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, request: Request, db: Session = Depends(db_session)):
    job = db.get(AutomationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(job, request)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, db: Session = Depends(db_session)):
    profile = db.get(Profile, payload.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
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
