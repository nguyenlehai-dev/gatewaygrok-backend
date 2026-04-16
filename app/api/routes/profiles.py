import base64
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.models.common import generate_uuid
from app.models.profile import Profile, ProfileCategory
from app.schemas.profile import ProfileCreate, ProfileRead, ProfileUpdate
from app.schemas.interactive_login import InteractiveLoginLaunchRead
from app.schemas.profile_asset import ProfileAssetRead
from app.schemas.session_check import SessionCheckRead
from app.services.automation.registry import get_provider
from app.services.cookie_importer import cookie_importer
from app.services.profile_storage import profile_storage
from app.services.settings_service import settings_service

router = APIRouter()

default_domains = {
    ProfileCategory.GROK: ".grok.com",
    ProfileCategory.FLOW: ".google.com",
    ProfileCategory.DREAMINA: ".dreamina.capcut.com",
}


@router.get("", response_model=list[ProfileRead])
def list_profiles(db: Session = Depends(db_session)):
    return db.query(Profile).order_by(Profile.created_at.desc()).all()


@router.post("", response_model=ProfileRead, status_code=status.HTTP_201_CREATED)
def create_profile(payload: ProfileCreate, db: Session = Depends(db_session)):
    profile = Profile(id=generate_uuid(), name=payload.name, category=payload.category)
    paths = profile_storage.prepare(profile.id)
    profile.cache_dir = paths["cache_dir"]
    profile.user_data_dir = paths["user_data_dir"]
    profile.description = payload.description
    profile.is_active = payload.is_active
    profile.proxy_id = payload.proxy_id
    profile.tags = payload.tags
    profile.antidetect = payload.antidetect.model_dump() if payload.antidetect else None
    profile.concurrency_limit = payload.concurrency_limit
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/{profile_id}", response_model=ProfileRead)
def get_profile(profile_id: str, db: Session = Depends(db_session)):
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.put("/{profile_id}", response_model=ProfileRead)
def update_profile(profile_id: str, payload: ProfileUpdate, db: Session = Depends(db_session)):
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    data = payload.model_dump(exclude_unset=True)
    if "antidetect" in data and payload.antidetect is not None:
        data["antidetect"] = payload.antidetect.model_dump()
    for key, value in data.items():
        setattr(profile, key, value)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: str, db: Session = Depends(db_session)):
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(profile)
    db.commit()
    profile_storage.delete(profile_id)


@router.post("/{profile_id}/cookies", response_model=ProfileRead)
async def import_cookies(profile_id: str, file: UploadFile = File(...), db: Session = Depends(db_session)):
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    content = await file.read()
    cookie_path = profile_storage.cookie_state_path(profile.id)
    cookie_importer.import_file(
        content=content,
        filename=file.filename or "cookies.txt",
        default_domain=default_domains[profile.category],
        target_path=Path(cookie_path),
    )
    profile.cookie_file = str(cookie_path)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/{profile_id}/assets", response_model=ProfileAssetRead, status_code=status.HTTP_201_CREATED)
async def upload_profile_asset(profile_id: str, file: UploadFile = File(...), db: Session = Depends(db_session)):
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    content = await file.read()
    suffix = Path(file.filename or "asset.bin").suffix or ".bin"
    asset_path = profile_storage.asset_dir(profile.id) / f"{uuid4()}{suffix}"
    asset_path.write_bytes(content)
    return ProfileAssetRead(
        profile_id=profile.id,
        original_filename=file.filename or asset_path.name,
        stored_path=str(asset_path),
        content_type=file.content_type,
        size=len(content),
    )


@router.post("/{profile_id}/session-check", response_model=SessionCheckRead)
async def session_check(profile_id: str, db: Session = Depends(db_session)):
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    provider = get_provider(profile.category)
    if provider is None:
        raise HTTPException(status_code=400, detail="Provider not available for profile category")

    automation_settings = settings_service.get_settings(db).automation
    result = await provider.analyze_session(profile, profile.proxy, automation_settings)
    exported_cookie_file = result.pop("cookie_file", None)
    exported_cookies = result.pop("cookies", [])
    if exported_cookie_file:
        profile.cookie_file = exported_cookie_file
        db.add(profile)
        db.commit()
        db.refresh(profile)
    elif exported_cookies:
        cookie_path = profile_storage.cookie_state_path(profile.id)
        cookie_path.write_text(json.dumps({"cookies": exported_cookies, "origins": []}, indent=2), encoding="utf-8")
        profile.cookie_file = str(cookie_path)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    screenshot_path = Path(result["screenshot_path"])
    if screenshot_path.exists():
        encoded = base64.b64encode(screenshot_path.read_bytes()).decode("utf-8")
        result["screenshot_data_url"] = f"data:image/png;base64,{encoded}"
    return SessionCheckRead(**result)


@router.post("/{profile_id}/launch-login", response_model=InteractiveLoginLaunchRead)
def launch_login(profile_id: str, db: Session = Depends(db_session)):
    profile = db.get(Profile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    provider = get_provider(profile.category)
    if provider is None:
        raise HTTPException(status_code=400, detail="Provider not available for profile category")

    script_path = Path("scripts/profile_login_bootstrap.py").resolve()
    log_path = Path("storage") / f"launch-login-{profile_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    log_file.write(f"Launching interactive login for {profile_id} ({provider.provider_name})\n")
    log_file.flush()
    subprocess.Popen(  # noqa: S603
        [sys.executable, str(script_path), "--profile-id", profile_id],
        cwd=Path.cwd(),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return InteractiveLoginLaunchRead(
        launched=True,
        profile_id=profile_id,
        provider=provider.provider_name,
        message=f"Interactive login browser launched. Complete login manually, then close the window. Log: {log_path}",
    )
