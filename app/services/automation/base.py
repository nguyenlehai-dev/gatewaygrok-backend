import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.core.config import settings
from app.models.automation_job import AutomationJob
from app.models.profile import Profile
from app.models.proxy import Proxy
from app.schemas.setting import AutomationSettings
from app.services.browser_runtime import (
    cancel_scheduled_profile_browser_stop,
    debug_endpoint_for_profile,
    is_debug_port_open,
    launch_profile_browser,
    live_browser_idle_timeout_seconds,
    schedule_profile_browser_stop,
    resolve_browser_executable,
    wait_for_debug_port,
    warm_browser_reuse_enabled,
)
from app.services.profile_storage import profile_storage

logger = logging.getLogger("uvicorn.error")


def _emit_runtime_log(message: str) -> None:
    print(message, flush=True)
    logger.info(message)
    try:
        runtime_dir = Path("/app/storage/runtime")
        runtime_dir.mkdir(parents=True, exist_ok=True)
        with (runtime_dir / "browser-jobs.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        logger.exception("browser_runtime_log_write_failed")


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

    def _storage_state_path(self, profile: Profile) -> str | None:
        if not profile.cookie_file:
            return None
        cookie_file = Path(profile.cookie_file)
        if not cookie_file.exists():
            return None
        return str(cookie_file)

    async def _open_context(
        self,
        profile: Profile,
        proxy: Proxy | None,
        automation_settings: AutomationSettings,
        *,
        prefer_live_browser: bool = False,
    ) -> tuple[BrowserContext, object, bool, Browser | None]:
        if prefer_live_browser:
            cancel_scheduled_profile_browser_stop(profile.id)
            launched_live_browser = False
            if not is_debug_port_open(profile.id):
                launched_live_browser = launch_profile_browser(profile.id)
                if launched_live_browser:
                    _emit_runtime_log(
                        "profile_browser_launch_requested "
                        f"profile_id={profile.id} provider={self.provider_name}"
                    )
                wait_for_debug_port(profile.id, timeout_seconds=20.0)
            if is_debug_port_open(profile.id):
                try:
                    playwright = await async_playwright().start()
                    browser = await playwright.chromium.connect_over_cdp(debug_endpoint_for_profile(profile.id))
                    context = browser.contexts[0] if browser.contexts else await browser.new_context()
                    _emit_runtime_log(
                        "profile_browser_connected "
                        f"profile_id={profile.id} provider={self.provider_name} launched={launched_live_browser}"
                    )
                    return context, playwright, True, browser
                except Exception:  # noqa: BLE001
                    with suppress(Exception):
                        await playwright.stop()

        playwright = await async_playwright().start()
        antidetect = profile.antidetect or {}
        viewport = None
        if antidetect.get("viewport_width") and antidetect.get("viewport_height"):
            viewport = {
                "width": antidetect["viewport_width"],
                "height": antidetect["viewport_height"],
            }
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--enable-unsafe-swiftshader",
            "--use-angle=swiftshader",
        ]
        launch_kwargs = {
            "headless": automation_settings.headless,
            "proxy": self._proxy_options(proxy),
            "viewport": viewport,
            "locale": antidetect.get("locale") or "en-US",
            "timezone_id": antidetect.get("timezone_id") or "UTC",
            "user_agent": antidetect.get("user_agent"),
            "color_scheme": antidetect.get("color_scheme") or "dark",
            "ignore_default_args": ["--enable-automation"],
            "args": launch_args,
        }
        if not automation_settings.headless:
            launch_env = os.environ.copy()
            launch_env["DISPLAY"] = launch_env.get("DISPLAY") or ":99"
            launch_kwargs["env"] = launch_env
            xvfb_wrapper_path = Path("/app/scripts/chromium_xvfb_wrapper.sh")
            if xvfb_wrapper_path.exists():
                launch_kwargs["executable_path"] = str(xvfb_wrapper_path)
        else:
            executable_path = resolve_browser_executable()
            if executable_path:
                launch_kwargs["executable_path"] = executable_path
        cookies = self._cookie_payload(profile)
        storage_state_path = self._storage_state_path(profile)
        browser: Browser | None = None
        context = await playwright.chromium.launch_persistent_context(
            profile.user_data_dir,
            **launch_kwargs,
        )
        if cookies:
            with suppress(Exception):
                await context.add_cookies(cookies)
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
        profile: Profile,
        context: BrowserContext,
        playwright: object,
        connected_live_browser: bool,
        browser: Browser | None,
    ) -> None:
        if connected_live_browser:
            scheduled_timeout = schedule_profile_browser_stop(profile.id, live_browser_idle_timeout_seconds())
            _emit_runtime_log(
                "profile_browser_idle_scheduled "
                f"profile_id={profile.id} provider={self.provider_name} idle_timeout_seconds={scheduled_timeout}"
            )
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

    async def _resolve_page(
        self,
        context: BrowserContext,
        timeout_ms: int,
        *,
        connected_live_browser: bool,
    ) -> Page:
        if not connected_live_browser:
            page = await context.new_page()
            page.set_default_timeout(timeout_ms)
            return page

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
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            for selector in selectors:
                locator = frame.locator(selector).first
                try:
                    await locator.wait_for(state="visible", timeout=5000)
                    return locator
                except Exception:  # noqa: BLE001
                    if await locator.count() > 0:
                        return locator
        raise RuntimeError(f"No matching selector found: {selectors}")

    async def _fill_prompt(self, page: Page, selectors: list[str], value: str) -> None:
        try:
            locator = await self._first_visible(page, selectors)
        except RuntimeError:
            locator = None
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    locator = await self._first_visible(frame, selectors)
                    break
                except Exception:
                    continue
            if locator is None:
                await page.click("body")
                await page.keyboard.type(value)
                return
        tag_name = await locator.evaluate("(element) => element.tagName.toLowerCase()")
        content_editable = await locator.evaluate("(element) => element.isContentEditable")
        if tag_name in {"textarea", "input"}:
            await locator.fill(value, timeout=5000)
            return
        if content_editable:
            with suppress(Exception):
                await locator.click(timeout=2000)
            try:
                is_active = await locator.evaluate("el => el === document.activeElement")
            except Exception:
                is_active = False
            if not is_active:
                with suppress(Exception):
                    await locator.evaluate(
                        """
                        (el) => {
                          if (!(el instanceof HTMLElement)) return false;
                          el.focus();
                          const selection = window.getSelection();
                          const range = document.createRange();
                          range.selectNodeContents(el);
                          selection?.removeAllRanges();
                          selection?.addRange(range);
                          return el === document.activeElement;
                        }
                        """
                    )
            try:
                is_active = await locator.evaluate("el => el === document.activeElement")
            except Exception:
                is_active = False
            if not is_active:
                with suppress(Exception):
                    await page.keyboard.press("Escape")
                with suppress(Exception):
                    await locator.click(force=True, timeout=2000)
            try:
                is_active = await locator.evaluate("el => el === document.activeElement")
            except Exception:
                is_active = False
            if not is_active:
                with suppress(Exception):
                    await locator.evaluate(
                        """
                        (el, prompt) => {
                          if (!(el instanceof HTMLElement)) return false;
                          el.focus();
                          el.textContent = '';
                          document.execCommand('insertText', false, prompt);
                          el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: prompt }));
                          return true;
                        }
                        """,
                        value,
                    )
                return
            await page.keyboard.press("Control+A")
            await page.keyboard.type(value)
            return
        await locator.fill(value, timeout=5000)

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

    def _should_retry_without_live_browser(self, exc: Exception) -> bool:
        message = str(exc).lower()
        patterns = [
            "target page, context or browser has been closed",
            "connection refused",
            "browser has been closed",
            "context has been closed",
            "page has been closed",
            "session closed",
            "closed unexpectedly",
            "submit button stayed disabled before click",
        ]
        return any(pattern in message for pattern in patterns)

    async def _run_once(
        self,
        profile: Profile,
        proxy: Proxy | None,
        job: AutomationJob,
        automation_settings: AutomationSettings,
        *,
        prefer_live_browser: bool,
    ) -> dict:
        started_at = time.perf_counter()
        launch_mode = "live-browser" if prefer_live_browser else ("headed" if not automation_settings.headless else "headless")
        _emit_runtime_log(
            "browser_job_start "
            f"provider={self.provider_name} job_id={job.id} profile_id={profile.id} "
            f"target={job.target.value} mode={launch_mode}"
        )
        context, playwright, connected_live_browser, browser = await self._open_context(
            profile,
            proxy,
            automation_settings,
            prefer_live_browser=prefer_live_browser,
        )
        page: Page | None = None
        try:
            _emit_runtime_log(
                "browser_context_opened "
                f"provider={self.provider_name} job_id={job.id} profile_id={profile.id} "
                f"live={connected_live_browser}"
            )
            page = await self._resolve_page(
                context,
                automation_settings.timeout_ms,
                connected_live_browser=connected_live_browser,
            )
            await self._prepare_page(page, automation_settings.timeout_ms)
            result = await self.perform(page, profile, job, automation_settings)
            screenshot = await self._capture_debug(page, profile_storage.output_dir(profile.id), f"{job.id}-final")
            result["provider"] = self.provider_name
            result["start_url"] = self.start_url
            result["page_url"] = page.url
            result["debug_screenshot"] = screenshot
            result["used_live_browser"] = connected_live_browser
            _emit_runtime_log(
                "browser_job_succeeded "
                f"provider={self.provider_name} job_id={job.id} profile_id={profile.id} "
                f"duration_ms={int((time.perf_counter() - started_at) * 1000)} "
                f"media_count={len(result.get('media_urls') or [])}"
            )
            return result
        except Exception as exc:
            if page is not None:
                with suppress(Exception):
                    failure_screenshot = await self._capture_debug(
                        page,
                        profile_storage.output_dir(profile.id),
                        f"{job.id}-failed",
                    )
                    _emit_runtime_log(
                        "browser_job_failure_screenshot "
                        f"provider={self.provider_name} job_id={job.id} profile_id={profile.id} "
                        f"path={failure_screenshot}"
                    )
            _emit_runtime_log(
                "browser_job_failed "
                f"provider={self.provider_name} job_id={job.id} profile_id={profile.id} "
                f"duration_ms={int((time.perf_counter() - started_at) * 1000)}"
            )
            logger.exception(
                "browser_job_failed provider=%s job_id=%s profile_id=%s duration_ms=%s",
                self.provider_name,
                job.id,
                profile.id,
                int((time.perf_counter() - started_at) * 1000),
            )
            raise exc
        finally:
            if page is not None and not connected_live_browser:
                with suppress(Exception):
                    await page.close()
            await self._close_context(profile, context, playwright, connected_live_browser, browser)
            _emit_runtime_log(
                "browser_context_closed "
                f"provider={self.provider_name} job_id={job.id} profile_id={profile.id} "
                f"live={connected_live_browser} duration_ms={int((time.perf_counter() - started_at) * 1000)}"
            )

    async def run(
        self,
        profile: Profile,
        proxy: Proxy | None,
        job: AutomationJob,
        automation_settings: AutomationSettings,
    ) -> dict:
        prefer_live_browser = settings.reuse_live_browser_for_jobs
        if self.provider_name == "grok" and warm_browser_reuse_enabled():
            prefer_live_browser = True
        try:
            return await self._run_once(
                profile,
                proxy,
                job,
                automation_settings,
                prefer_live_browser=prefer_live_browser,
            )
        except Exception as exc:  # noqa: BLE001
            if not self._should_retry_without_live_browser(exc):
                raise
            return await self._run_once(
                profile,
                proxy,
                job,
                automation_settings,
                prefer_live_browser=False,
            )

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
        page: Page | None = None
        try:
            page = await self._resolve_page(
                context,
                automation_settings.timeout_ms,
                connected_live_browser=connected_live_browser,
            )
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
                await context.storage_state(path=str(cookie_path))
                analysis["cookie_file"] = str(cookie_path)
            analysis["body_preview"] = await self._body_preview(page)
            return analysis
        finally:
            if page is not None and not connected_live_browser:
                with suppress(Exception):
                    await page.close()
            await self._close_context(profile, context, playwright, connected_live_browser, browser)

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
