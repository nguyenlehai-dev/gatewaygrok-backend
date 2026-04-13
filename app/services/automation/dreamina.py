from playwright.async_api import Page

from app.models.automation_job import AutomationJob
from app.models.profile import Profile
from app.schemas.setting import AutomationSettings
from app.services.automation.base import BaseAutomationProvider


class DreaminaAutomationProvider(BaseAutomationProvider):
    provider_name = "dreamina"
    start_url = "https://dreamina.capcut.com/"
    supported_targets = ("image",)
    notes = "Category is registered for gateway management, but Dreamina automation is not implemented yet."

    async def inspect_session(
        self,
        page: Page,
        profile: Profile,
        automation_settings: AutomationSettings,
    ) -> dict:
        del page, profile, automation_settings
        return {
            "state": "unsupported",
            "indicators": [],
            "summary": "Dreamina session check is not implemented yet.",
        }

    async def perform(
        self,
        page: Page,
        profile: Profile,
        job: AutomationJob,
        automation_settings: AutomationSettings,
    ) -> dict:
        del page, profile, job, automation_settings
        raise RuntimeError("Dreamina automation is not implemented yet")


dreamina_provider = DreaminaAutomationProvider()
