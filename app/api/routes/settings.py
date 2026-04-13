from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.schemas.setting import SettingsRead, SettingsUpdate
from app.services.job_runner import job_runner
from app.services.settings_service import settings_service

router = APIRouter()


@router.get("", response_model=SettingsRead)
def get_settings(db: Session = Depends(db_session)):
    return settings_service.get_settings(db)


@router.put("", response_model=SettingsRead)
async def update_settings(payload: SettingsUpdate, db: Session = Depends(db_session)):
    current = settings_service.update_settings(db, SettingsRead(automation=payload.automation))
    await job_runner.set_concurrency(current.automation.concurrency)
    return current
