from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.setting import Setting
from app.schemas.setting import AutomationSettings, SettingsRead


class SettingsService:
    automation_key = "automation"

    def ensure_defaults(self, db: Session) -> None:
        if db.get(Setting, self.automation_key) is None:
            record = Setting(
                key=self.automation_key,
                value=AutomationSettings(
                    headless=settings.browser_headless,
                    concurrency=settings.default_concurrency,
                    timeout_ms=settings.default_timeout_ms,
                ).model_dump(),
            )
            db.add(record)
            db.commit()

    def get_settings(self, db: Session) -> SettingsRead:
        self.ensure_defaults(db)
        record = db.get(Setting, self.automation_key)
        return SettingsRead(automation=AutomationSettings(**record.value))

    def update_settings(self, db: Session, payload: SettingsRead) -> SettingsRead:
        self.ensure_defaults(db)
        record = db.get(Setting, self.automation_key)
        record.value = payload.automation.model_dump()
        db.add(record)
        db.commit()
        db.refresh(record)
        return SettingsRead(automation=AutomationSettings(**record.value))


settings_service = SettingsService()
