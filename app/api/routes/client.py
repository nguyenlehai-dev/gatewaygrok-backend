import mimetypes
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest, urlopen
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_api_key
from app.core.config import settings
from app.models.api_key import ApiKey
from app.models.automation_job import AutomationJob, JobTarget
from app.models.profile import Profile
from app.schemas.client import ClientJobCreate
from app.schemas.job import JobRead
from app.services.api_key_service import api_key_service
from app.services.job_runner import job_runner
from app.services.session_guard import ensure_profile_session_ready
from app.services.profile_storage import profile_storage

router = APIRouter()

MAX_REFERENCE_IMAGE_BYTES = 15 * 1024 * 1024
INTERNAL_STORAGE_HOSTS = {
    "flowgrok.plxeditor.com",
    "www.flowgrok.plxeditor.com",
    "testflowgrok.plxeditor.com",
}


def _is_remote_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _resolve_internal_storage_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in INTERNAL_STORAGE_HOSTS:
        return None
    if not parsed.path.startswith("/storage/"):
        return None

    storage_root = settings.storage_root.resolve()
    relative_path = parsed.path.removeprefix("/storage/")
    candidate = (storage_root / relative_path).resolve()
    if not candidate.is_file():
        return None
    if not candidate.is_relative_to(storage_root):
        return None
    return str(candidate)


def _download_reference_image(url: str, profile_id: str) -> str:
    internal_storage_path = _resolve_internal_storage_url(url)
    if internal_storage_path:
        return internal_storage_path

    try:
        request = UrlRequest(url, headers={"User-Agent": "GatewayGrok/1.0"})
        with urlopen(request, timeout=30) as response:  # noqa: S310
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip()
            if not content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="reference_images must be image URLs")
            chunks: list[bytes] = []
            total_size = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_REFERENCE_IMAGE_BYTES:
                    raise HTTPException(status_code=413, detail="reference_images file too large")
                chunks.append(chunk)
            data = b"".join(chunks)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to download reference image: {exc}") from exc

    ext = mimetypes.guess_extension(content_type) or Path(urlparse(url).path).suffix or ".png"
    asset_path = profile_storage.asset_dir(profile_id) / f"{uuid4()}{ext}"
    asset_path.write_bytes(data)
    return str(asset_path)

def _absolute_url(request: Request, value: str) -> str:
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip()

    def _with_public_scheme(url: str) -> str:
        if forwarded_proto in {"http", "https"}:
            return url.replace(f"{request.url.scheme}://", f"{forwarded_proto}://", 1)
        return url

    if not value:
        return value
    if value.startswith(("http://", "https://", "data:")):
        return value

    storage_root = settings.storage_root.resolve()
    normalized = value.replace("\\", "/")
    try:
        candidate = Path(normalized)
        candidate = (Path.cwd() / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if candidate.is_relative_to(storage_root):
            relative = candidate.relative_to(storage_root).as_posix()
            return _with_public_scheme(str(request.url_for("storage", path=relative)))
    except Exception:  # noqa: BLE001
        pass

    storage_prefix = f"{settings.storage_root.as_posix().rstrip('/')}/"
    if normalized.startswith(storage_prefix):
        relative = normalized.removeprefix(storage_prefix).lstrip("/")
        return _with_public_scheme(str(request.url_for("storage", path=relative)))

    base = str(request.base_url).rstrip("/")
    if forwarded_proto in {"http", "https"}:
        base = base.replace(f"{request.url.scheme}://", f"{forwarded_proto}://", 1)
    if value.startswith("/"):
        return f"{base}{value}"
    return f"{base}/{value.lstrip('/')}"


def _serialize_job(job: AutomationJob, request: Request) -> dict:
    payload = JobRead.model_validate(job).model_dump()
    result = payload.get("result_payload")
    if not isinstance(result, dict):
        return payload
    media = result.get("media_urls")
    if isinstance(media, list):
        result["media_urls"] = [_absolute_url(request, item) for item in media if isinstance(item, str)]
    debug_screenshot = result.get("debug_screenshot")
    if isinstance(debug_screenshot, str):
        result["debug_screenshot"] = _absolute_url(request, debug_screenshot)
    payload["result_payload"] = result
    return payload


def _lite_payload(job: AutomationJob, request: Request) -> dict:
    payload = JobRead.model_validate(job).model_dump()
    result = payload.get("result_payload") or {}
    media_urls = result.get("media_urls") if isinstance(result, dict) else None
    url = None
    if isinstance(media_urls, list):
        for item in media_urls:
            if isinstance(item, str) and item:
                url = _absolute_url(request, item)
                break
    success = payload.get("status") == "succeeded"
    message = payload.get("error_message") or payload.get("status")
    return {
        "task_id": payload.get("id"),
        "status": payload.get("status"),
        "success": success,
        "message": message,
        "url": url,
    }

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
    request: Request = None,
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
    provider_payload = job_payload.pop("provider_payload") or {}
    reference_images = job_payload.pop("reference_images", None)
    ratio = job_payload.pop("ratio", None)
    quality = job_payload.pop("quality", None)
    duration = job_payload.pop("duration", None)

    if reference_images:
        resolved_refs: list[str] = []
        for item in reference_images:
            if isinstance(item, str) and _is_remote_url(item):
                resolved_refs.append(_download_reference_image(item, profile.id))
            else:
                resolved_refs.append(item)
        provider_payload.setdefault("reference_images", resolved_refs)
        if resolved_refs:
            provider_payload.setdefault("source_asset_path", resolved_refs[0])

    if ratio:
        provider_payload.setdefault("ratio", ratio)
    if quality:
        provider_payload.setdefault("quality", quality)
    if duration is not None:
        provider_payload.setdefault("duration", duration)

    if payload.target == JobTarget.VIDEO:
        provider_payload.setdefault(
            "video_mode",
            "image_to_video" if reference_images else "text_to_video",
        )

    job_payload["profile_id"] = profile.id
    job_payload["provider_payload"] = provider_payload or None
    job = AutomationJob(**job_payload)
    db.add(job)
    db.commit()
    db.refresh(job)
    await job_runner.enqueue(job.id)
    if request is None:
        return job
    return _serialize_job(job, request)


@router.post("/generate/status", status_code=status.HTTP_201_CREATED)
@router.post("/jobs/status", status_code=status.HTTP_201_CREATED)
async def create_client_job_lite(
    payload: ClientJobCreate,
    api_key_record: ApiKey = Depends(require_api_key),
    db: Session = Depends(db_session),
    request: Request = None,
):
    job = await create_client_job(payload, api_key_record, db, request)
    if request is None:
        return job
    if isinstance(job, AutomationJob):
        return _lite_payload(job, request)
    return _lite_payload(JobRead.model_validate(job), request)


@router.get("/tasks/{task_id}", response_model=JobRead)
@router.get("/jobs/{task_id}", response_model=JobRead)
async def get_client_job(
    task_id: str,
    api_key_record: ApiKey = Depends(require_api_key),
    db: Session = Depends(db_session),
    request: Request = None,
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

    if request is None:
        return job
    return _serialize_job(job, request)


@router.get("/tasks/{task_id}/status")
@router.get("/jobs/{task_id}/status")
async def get_client_job_lite(
    task_id: str,
    api_key_record: ApiKey = Depends(require_api_key),
    db: Session = Depends(db_session),
    request: Request = None,
):
    job = await get_client_job(task_id, api_key_record, db, request)
    if request is None:
        return job
    if isinstance(job, AutomationJob):
        return _lite_payload(job, request)
    return _lite_payload(JobRead.model_validate(job), request)
@router.get("/verify")
def verify_client_key(api_key_record: ApiKey = Depends(require_api_key)):
    return {
        "status": "ok",
        "name": api_key_record.name,
        "key_prefix": api_key_record.key_prefix,
    }
