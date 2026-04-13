import asyncio
import json
from abc import ABC, abstractmethod
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.models.automation_job import AutomationJob
from app.models.profile import Profile
from app.models.proxy import Proxy
from app.schemas.setting import AutomationSettings
from app.services.browser_runtime import (
    debug_endpoint_for_profile,
    is_debug_port_open,
    resolve_browser_executable,
)
from app.services.profile_storage import profile_storage


class BaseAutomationProvider(ABC):
    provider_name: str
    start_url: str
    supported_targets: tuple[str, ...] = ("image", "video")
    notes: str | None = None

    def _proxy_options(self, proxy: Proxy | None) -> dict | None:
        if not proxy or not proxy.enabled:
            return None
        options = {"server": f"{proxy.kind}://{proxy.server}:{proxy.port}"}
        if proxy.username:
            options["username"] = proxy.username
        if proxy.password:
            options["password"] = proxy.password
        return options

    def _cookie_payload(self, profile: Profile) -> list[dict]:
        if not profile.cookie_file:
            return []
        cookie_file = Path(profile.cookie_file)
        if not cookie_file.exists():
            return []
        payload = json.loads(cookie_file.read_text(encoding="utf-8"))
        return payload.get("cookies", [])

    async def _open_context(
        self,
        profile: Profile,
        proxy: Proxy | None,
        automation_settings: AutomationSettings,
        *,
        prefer_live_browser: bool = False,
    ) -> tuple[BrowserContext, object, bool, Browser | None]:
        if prefer_live_browser and is_debug_port_open(profile.id):
            playwright = await async_playwright().start()
            browser = await playwright.chromium.connect_over_cdp(debug_endpoint_for_profile(profile.id))
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            return context, playwright, True, browser

        playwright = await async_playwright().start()
        antidetect = profile.antidetect or {}
        viewport = None
        if antidetect.get("viewport_width") and antidetect.get("viewport_height"):
            viewport = {
                "width": antidetect["viewport_width"],
                "height": antidetect["viewport_height"],
            }
        launch_kwargs = {
            "headless": automation_settings.headless,
            "proxy": self._proxy_options(proxy),
            "viewport": viewport,
            "locale": antidetect.get("locale") or "en-US",
            "timezone_id": antidetect.get("timezone_id") or "UTC",
            "user_agent": antidetect.get("user_agent"),
            "color_scheme": antidetect.get("color_scheme") or "dark",
            "ignore_default_args": ["--enable-automation"],
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        executable_path = resolve_browser_executable()
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
        cookies = self._cookie_payload(profile)
        browser: Browser | None = None
        if cookies:
            browser = await playwright.chromium.launch(
                headless=automation_settings.headless,
                proxy=self._proxy_options(proxy),
                executable_path=executable_path,
                ignore_default_args=["--enable-automation"],
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                viewport=viewport,
                locale=antidetect.get("locale") or "en-US",
                timezone_id=antidetect.get("timezone_id") or "UTC",
                user_agent=antidetect.get("user_agent"),
                color_scheme=antidetect.get("color_scheme") or "dark",
            )
            await context.add_cookies(cookies)
        else:
            context = await playwright.chromium.launch_persistent_context(
                profile.user_data_dir,
                **launch_kwargs,
            )
        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'platform', { get: () => '%s' });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => %s });
            """
            % (
                antidetect.get("platform") or "Win32",
                antidetect.get("hardware_concurrency") or 8,
            )
        )
        return context, playwright, False, browser

    async def _close_context(
        self,
        context: BrowserContext,
        playwright: object,
        connected_live_browser: bool,
        browser: Browser | None,
    ) -> None:
        if connected_live_browser:
            with suppress(Exception):
                if browser:
                    await browser.close()
        else:
            with suppress(Exception):
                await context.close()
            if browser:
                with suppress(Exception):
                    await browser.close()
        with suppress(Exception):
            await playwright.stop()

    async def _prepare_page(self, page: Page, timeout_ms: int) -> None:
        page.set_default_timeout(timeout_ms)
        await page.goto(self.start_url, wait_until="domcontentloaded")

    async def _resolve_page(self, context: BrowserContext, timeout_ms: int) -> Page:
        start_host = urlparse(self.start_url).hostname or ""
        for page in context.pages:
            if start_host and start_host in page.url:
                page.set_default_timeout(timeout_ms)
                with suppress(Exception):
                    await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                return page
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(timeout_ms)
        return page

    async def _capture_debug(self, page: Page, output_dir: Path, suffix: str) -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"{suffix}.png"
        await page.screenshot(path=str(file_path), full_page=True)
        return str(file_path)

    async def _first_visible(self, page: Page, selectors: list[str]):
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                await locator.wait_for(state="visible", timeout=5000)
                return locator
            except Exception:  # noqa: BLE001
                if await locator.count() > 0:
                    return locator
        raise RuntimeError(f"No matching selector found: {selectors}")

    async def _fill_prompt(self, page: Page, selectors: list[str], value: str) -> None:
        locator = await self._first_visible(page, selectors)
        tag_name = await locator.evaluate("(element) => element.tagName.toLowerCase()")
        content_editable = await locator.evaluate("(element) => element.isContentEditable")
        if tag_name in {"textarea", "input"}:
            await locator.fill(value)
            return
        if content_editable:
            await locator.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.type(value)
            return
        await locator.fill(value)

    async def _extract_media_urls(self, page: Page, target: str) -> list[str]:
        if target == "image":
            return await page.locator("img").evaluate_all(
                "(elements) => elements.map((item) => item.currentSrc || item.src).filter(Boolean)"
            )
        return await page.locator("video").evaluate_all(
            """
            (elements) => elements
              .map((item) => item.currentSrc || item.src || item.querySelector('source')?.src)
              .filter(Boolean)
            """
        )

    async def _wait_for_media(self, page: Page, target: str) -> list[str]:
        attempts = 12 if target == "image" else 24
        delay_seconds = 4 if target == "image" else 5
        latest: list[str] = []
        for _ in range(attempts):
            latest = await self._extract_media_urls(page, target)
            if latest:
                return latest[:8]
            await asyncio.sleep(delay_seconds)
        return latest[:8]

    async def _body_preview(self, page: Page) -> str:
        try:
            text = await page.locator("body").inner_text(timeout=5000)
        except Exception:  # noqa: BLE001
            return ""
        return " ".join(text.split())[:500]

    def _contains_any(self, value: str, patterns: list[str]) -> list[str]:
        lowered = value.lower()
        return [pattern for pattern in patterns if pattern.lower() in lowered]

    async def _run_in_thread(self, callback):
        return await asyncio.to_thread(callback)

    async def run(
        self,
        profile: Profile,
        proxy: Proxy | None,
        job: AutomationJob,
        automation_settings: AutomationSettings,
    ) -> dict:
        context, playwright, connected_live_browser, browser = await self._open_context(
            profile,
            proxy,
            automation_settings,
            prefer_live_browser=True,
        )
        try:
            if connected_live_browser:
                page = await context.new_page()
                page.set_default_timeout(automation_settings.timeout_ms)
            else:
                page = await self._resolve_page(context, automation_settings.timeout_ms)
            await self._prepare_page(page, automation_settings.timeout_ms)
            result = await self.perform(page, profile, job, automation_settings)
            screenshot = await self._capture_debug(page, profile_storage.output_dir(profile.id), f"{job.id}-final")
            result["provider"] = self.provider_name
            result["start_url"] = self.start_url
            result["page_url"] = page.url
            result["debug_screenshot"] = screenshot
            return result
        finally:
            await self._close_context(context, playwright, connected_live_browser, browser)

    async def analyze_session(
        self,
        profile: Profile,
        proxy: Proxy | None,
        automation_settings: AutomationSettings,
    ) -> dict:
        context, playwright, connected_live_browser, browser = await self._open_context(
            profile,
            proxy,
            automation_settings,
            prefer_live_browser=True,
        )
        try:
            page = await self._resolve_page(context, automation_settings.timeout_ms)
            if not connected_live_browser or page.url in {"", "about:blank"}:
                await self._prepare_page(page, automation_settings.timeout_ms)
            else:
                with suppress(Exception):
                    await page.wait_for_load_state("domcontentloaded", timeout=automation_settings.timeout_ms)
            analysis = await self.inspect_session(page, profile, automation_settings)
            screenshot = await self._capture_debug(
                page,
                profile_storage.output_dir(profile.id),
                f"{profile.id}-session-check",
            )
            cookies = await context.cookies([self.start_url])
            analysis["provider"] = self.provider_name
            analysis["start_url"] = self.start_url
            analysis["page_url"] = page.url
            analysis["title"] = await page.title()
            analysis["screenshot_path"] = screenshot
            analysis["cookie_present"] = bool(cookies)
            analysis["live_browser_connected"] = connected_live_browser
            analysis.setdefault("requires_live_browser", False)
            analysis["cookies"] = cookies
            if cookies:
                cookie_path = profile_storage.cookie_state_path(profile.id)
                cookie_path.write_text(json.dumps({"cookies": cookies, "origins": []}, indent=2), encoding="utf-8")
                analysis["cookie_file"] = str(cookie_path)
            analysis["body_preview"] = await self._body_preview(page)
            return analysis
        finally:
            await self._close_context(context, playwright, connected_live_browser, browser)

    def capability_payload(self, category: str) -> dict:
        return {
            "category": category,
            "provider_name": self.provider_name,
            "targets": list(self.supported_targets),
            "supports_cookie_import": True,
            "supports_proxy": True,
            "supports_antidetect": True,
            "start_url": self.start_url,
            "notes": self.notes,
        }

    async def inspect_session(
        self,
        page: Page,
        profile: Profile,
        automation_settings: AutomationSettings,
    ) -> dict:
        del profile, automation_settings
        title = await page.title()
        preview = await self._body_preview(page)
        indicators = self._contains_any(
            f"{title} {preview}",
            ["sign in", "log in", "security verification", "just a moment"],
        )
        state = "unknown"
        if any(item in indicators for item in ["security verification", "just a moment"]):
            state = "security_verification"
        elif any(item in indicators for item in ["sign in", "log in"]):
            state = "login_required"
        return {
            "state": state,
            "indicators": indicators,
            "summary": "Generic provider session inspection",
        }

    @abstractmethod
    async def perform(
        self,
        page: Page,
        profile: Profile,
        job: AutomationJob,
        automation_settings: AutomationSettings,
    ) -> dict:
        raise NotImplementedError
