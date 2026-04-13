from playwright.async_api import Page

from app.models.automation_job import AutomationJob
from app.models.profile import Profile
from app.schemas.setting import AutomationSettings
from app.services.automation.base import BaseAutomationProvider


class FlowAutomationProvider(BaseAutomationProvider):
    provider_name = "flow"
    start_url = "https://labs.google/fx/fil/tools/flow"

    async def inspect_session(
        self,
        page: Page,
        profile: Profile,
        automation_settings: AutomationSettings,
    ) -> dict:
        del profile, automation_settings
        title = await page.title()
        preview = await self._body_preview(page)
        combined = f"{title} {preview}"
        indicators = self._contains_any(
            combined,
            [
                "sign in",
                "choose an account",
                "verify it",
                "flow",
                "generate",
                "create",
                "security verification",
            ],
        )
        state = "unknown"
        summary = "Flow page loaded but auth state is not conclusive."
        if any(item in indicators for item in ["sign in", "choose an account", "verify it"]):
            state = "login_required"
            summary = "Google Flow still requires account authentication."
        elif "security verification" in indicators:
            state = "security_verification"
            summary = "Flow is blocked by a verification step."
        elif any(item in indicators for item in ["flow", "generate", "create"]):
            state = "authenticated"
            summary = "Flow session appears ready for generation."
        return {
            "state": state,
            "indicators": indicators,
            "summary": summary,
            "requires_live_browser": True,
        }

    async def perform(
        self,
        page: Page,
        profile: Profile,
        job: AutomationJob,
        automation_settings: AutomationSettings,
    ) -> dict:
        del profile, automation_settings
        await self._fill_prompt(
            page,
            [
                "textarea",
                "[contenteditable='true']",
                "textarea[placeholder*='Describe']",
            ],
            job.prompt,
        )

        submit_locator = await self._first_visible(
            page,
            [
                "button:has-text('Generate')",
                "button:has-text('Create')",
                "button[type='submit']",
            ],
        )
        await submit_locator.click()

        media_urls = await self._wait_for_media(page, job.target.value)
        return {
            "target": job.target.value,
            "media_urls": media_urls,
        }


flow_provider = FlowAutomationProvider()
