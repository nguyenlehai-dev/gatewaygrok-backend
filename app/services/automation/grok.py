import base64
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page

from app.models.automation_job import AutomationJob
from app.models.profile import Profile
from app.schemas.setting import AutomationSettings
from app.services.automation.base import BaseAutomationProvider
from app.services.profile_storage import profile_storage


class GrokAutomationProvider(BaseAutomationProvider):
    provider_name = "grok"
    start_url = "https://grok.com/"

    async def _extract_image_candidates(self, page: Page) -> list[dict]:
        return await page.evaluate(
            r"""
            () => {
              const normalize = (value) => (typeof value === "string" ? value.trim().toLowerCase() : "");
              const prompt = normalize(document.title.replace(/\s*-\s*grok$/i, ""));
              const images = Array.from(document.querySelectorAll("img"));
              const candidates = [];
              const seen = new Set();

              for (const [index, image] of images.entries()) {
                const rect = image.getBoundingClientRect();
                const style = window.getComputedStyle(image);
                const src = image.currentSrc || image.src || "";
                const alt = (image.getAttribute("alt") || "").trim();
                const altNormalized = normalize(alt);
                const parent = image.parentElement;
                const grandParent = parent?.parentElement;
                const parentClass = String(parent?.className || "");
                const grandParentClass = String(grandParent?.className || "");
                const visible =
                  rect.width >= 280 &&
                  rect.height >= 280 &&
                  rect.bottom > 0 &&
                  rect.right > 0 &&
                  style.display !== "none" &&
                  style.visibility !== "hidden" &&
                  Number(style.opacity || "1") > 0.05;

                if (!src || seen.has(src) || !visible) {
                  continue;
                }

                if (!src.startsWith("data:image/") && !src.includes("assets.grok.com")) {
                  continue;
                }

                if (image.naturalWidth < 700 || image.naturalHeight < 900) {
                  continue;
                }

                const promptMatch = Boolean(prompt) && (altNormalized === prompt || altNormalized.includes(prompt));
                const generatedImage = altNormalized === "generated image";
                const comparePanel =
                  parentClass.includes("w-1/2") ||
                  grandParentClass.includes("max-h-[calc(100dvh-250px)]") ||
                  grandParentClass.includes("gap-4");

                let score = 0;
                if (promptMatch) {
                  score += 1000;
                }
                if (comparePanel) {
                  score += 300;
                }
                if (generatedImage) {
                  score += 120;
                }
                if (src.startsWith("data:image/")) {
                  score += 80;
                }
                score += Math.round((rect.width * rect.height) / 1000);

                seen.add(src);
                candidates.push({
                  index,
                  src,
                  score,
                  promptMatch,
                  comparePanel,
                  rectY: rect.y,
                  rectX: rect.x,
                });
              }

              const sortByPriority = (left, right) => {
                if (right.score !== left.score) {
                  return right.score - left.score;
                }
                if (left.rectY !== right.rectY) {
                  return left.rectY - right.rectY;
                }
                if (left.rectX !== right.rectX) {
                  return left.rectX - right.rectX;
                }
                return left.index - right.index;
              };

              const promptMatches = candidates.filter((item) => item.promptMatch).sort(sortByPriority);
              if (promptMatches.length) {
                return promptMatches;
              }

              const comparePanelImages = candidates.filter((item) => item.comparePanel).sort(sortByPriority);
              if (comparePanelImages.length) {
                return comparePanelImages;
              }

              return candidates.sort(sortByPriority).slice(0, 8);
            }
            """
        )

    async def _extract_media_urls(self, page: Page, target: str) -> list[str]:
        if target != "image":
            return await super()._extract_media_urls(page, target)

        candidates = await self._extract_image_candidates(page)
        return [str(item.get("src", "")).strip() for item in candidates if item.get("src")]

    def _normalize_media_urls(self, media_urls: list[str], target: str) -> list[str]:
        filtered: list[str] = []
        seen: set[str] = set()
        image_lengths: list[int] = [len(url.strip()) for url in media_urls if url.strip().startswith("data:image/")]
        max_image_length = max(image_lengths, default=0)
        min_acceptable_length = max(60000, int(max_image_length * 0.45)) if max_image_length else 0
        for url in media_urls:
            normalized = url.strip()
            if not normalized or normalized in seen:
                continue
            if target == "image":
                if normalized.startswith("data:image/"):
                    if max_image_length >= 120000 and len(normalized) < min_acceptable_length:
                        continue
                    seen.add(normalized)
                    filtered.append(normalized)
                    continue
                if "assets.grok.com" not in normalized:
                    continue
                if not any(ext in normalized.lower() for ext in [".png", ".jpg", ".jpeg", ".webp"]):
                    continue
            elif target == "video":
                if not any(ext in normalized.lower() for ext in [".mp4", ".webm", ".mov"]):
                    continue
            seen.add(normalized)
            filtered.append(normalized)
        return filtered

    async def _wait_for_action_button(self, page: Page, selectors: list[str], attempts: int = 18, delay_ms: int = 5000):
        for _ in range(attempts):
            for selector in selectors:
                locator = page.locator(selector).first
                if await locator.count() > 0:
                    return locator
            await page.wait_for_timeout(delay_ms)
        raise RuntimeError(f"No matching selector found: {selectors}")

    async def _dismiss_quality_popup(self, page: Page) -> None:
        popup_label = "Choose quality for detailed generations"
        with suppress(Exception):
            popup = page.locator(f"text={popup_label}").first
            if await popup.count() == 0:
                return

            close_selectors = [
                "button:has-text('Got it')",
                "button:has-text('Close')",
                "button:has-text('Dismiss')",
                "button[aria-label='Close']",
                "div[data-radix-popper-content-wrapper] button",
            ]
            for selector in close_selectors:
                locator = page.locator(selector).first
                if await locator.count() > 0:
                    with suppress(Exception):
                        await locator.click()
                        await page.wait_for_timeout(300)
                        return

            with suppress(Exception):
                await page.keyboard.press("Escape")
            with suppress(Exception):
                await page.mouse.click(10, 10)
            await page.wait_for_timeout(300)

    async def _wait_for_filtered_media(self, page: Page, target: str, attempts: int = 18, delay_ms: int = 4000) -> list[str]:
        latest: list[str] = []
        best_complete: list[str] = []
        previous_signature: tuple[tuple[int, str], ...] | None = None
        stable_ready_hits = 0
        required_stable_hits = 3 if target == "image" else 1
        for _ in range(attempts):
            latest = self._normalize_media_urls(await self._extract_media_urls(page, target), target)
            if latest:
                signature = tuple((len(item), item[:96]) for item in latest)
                if len(latest) >= len(best_complete):
                    best_complete = latest

                if signature == previous_signature:
                    stable_ready_hits += 1
                else:
                    stable_ready_hits = 1
                    previous_signature = signature

                if stable_ready_hits >= required_stable_hits:
                    return latest
            await page.wait_for_timeout(delay_ms)
        return best_complete or latest

    async def _download_remote_media(self, page: Page, url: str, target_path: Path) -> str:
        payload = await page.evaluate(
            """
            async (assetUrl) => {
                const response = await fetch(assetUrl, { credentials: "include" });
              if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
              }
              const buffer = await response.arrayBuffer();
              return Array.from(new Uint8Array(buffer));
            }
            """,
            url,
        )

        data = bytes(payload)

        def _write() -> str:
            target_path.write_bytes(data)
            return str(target_path)

        return await self._run_in_thread(_write)

    async def _save_data_url(self, data_url: str, target_path: Path) -> str:
        header, encoded = data_url.split(",", 1)
        payload = base64.b64decode(encoded)

        def _write() -> str:
            target_path.write_bytes(payload)
            return str(target_path)

        return await self._run_in_thread(_write)

    async def _localize_image_media(self, page: Page, profile: Profile, job: AutomationJob, media_urls: list[str]) -> list[str]:
        output_dir = profile_storage.output_dir(profile.id)
        localized: list[str] = []
        for index, url in enumerate(media_urls, start=1):
            if url.startswith("data:image/"):
                mime = url.split(";", 1)[0].split(":", 1)[1]
                suffix_map = {
                    "image/jpeg": ".jpg",
                    "image/jpg": ".jpg",
                    "image/png": ".png",
                    "image/webp": ".webp",
                    "image/gif": ".gif",
                }
                suffix = suffix_map.get(mime, ".png")
                target_path = output_dir / f"{job.id}-image-{index}{suffix}"
                localized.append(await self._save_data_url(url, target_path))
                continue

            if not url.startswith("http://") and not url.startswith("https://"):
                localized.append(url)
                continue

            suffix = Path(urlparse(url).path).suffix.lower() or ".jpg"
            target_path = output_dir / f"{job.id}-image-{index}{suffix}"
            try:
                localized.append(await self._download_remote_media(page, url, target_path))
            except Exception:  # noqa: BLE001
                localized.append(url)
        return localized

    async def _open_imagine_video_flow(self, page: Page, prompt: str, source_asset_path: str | None) -> None:
        await page.goto("https://grok.com/imagine", wait_until="domcontentloaded")
        video_mode = await self._wait_for_action_button(
            page,
            [
                "[aria-label='Generation mode'] button[role='radio']:has-text('Video')",
                "[aria-label='Generation mode'] >> text=Video",
            ],
            attempts=12,
            delay_ms=2000,
        )
        if await video_mode.get_attribute("aria-checked") != "true":
            await video_mode.click()

        if source_asset_path:
            source_file = Path(source_asset_path)
            if not source_file.exists():
                raise RuntimeError(f"Source asset not found: {source_asset_path}")
            upload_input = await self._first_visible(page, ["input[type='file']"])
            await upload_input.set_input_files(str(source_file))
            await page.wait_for_timeout(2000)

        if prompt.strip():
            await self._dismiss_quality_popup(page)
            await self._fill_prompt(
                page,
                [
                    "[contenteditable='true']",
                    "div[contenteditable='true']",
                    "textarea",
                ],
                prompt,
            )

        submit = await self._first_visible(
            page,
            [
                "button[aria-label='Submit']",
                "button[type='submit']",
            ],
        )
        await submit.click()

    async def _open_imagine_image_flow(self, page: Page, prompt: str, source_asset_path: str | None = None) -> None:
        await page.goto("https://grok.com/imagine", wait_until="domcontentloaded")
        with suppress(Exception):
            image_mode = await self._wait_for_action_button(
                page,
                [
                    "[aria-label='Generation mode'] button[role='radio']:has-text('Image')",
                    "[aria-label='Generation mode'] >> text=Image",
                ],
                attempts=6,
                delay_ms=1500,
            )
            if await image_mode.get_attribute("aria-checked") != "true":
                await image_mode.click()

        if source_asset_path:
            source_file = Path(source_asset_path)
            if not source_file.exists():
                raise RuntimeError(f"Source asset not found: {source_asset_path}")
            upload_input = await self._first_visible(page, ["input[type='file']"])
            await upload_input.set_input_files(str(source_file))
            await page.wait_for_timeout(2500)

        if prompt.strip():
            await self._dismiss_quality_popup(page)
            await self._fill_prompt(
                page,
                [
                    "[contenteditable='true']",
                    "div[contenteditable='true']",
                    "p[data-placeholder='Ask Grok']",
                    "textarea",
                    "textarea[placeholder*='Ask']",
                ],
                prompt,
            )

        submit_locator = await self._first_visible(
            page,
            [
                "button[aria-label='Submit']",
                "button[type='submit']",
                "button:has-text('Create image')",
                "button:has-text('Generate')",
            ],
        )
        await submit_locator.click()

    async def _download_file(self, page: Page, profile: Profile, job: AutomationJob, suffix_label: str) -> list[str]:
        download_button = await self._wait_for_action_button(
            page,
            [
                "button[aria-label='Download']",
                "button:has-text('Download')",
            ],
            attempts=24,
            delay_ms=5000,
        )

        output_dir = profile_storage.output_dir(profile.id)
        for attempt in range(8):
            try:
                async with page.expect_download(timeout=30000) as download_info:
                    await download_button.click()
                download = await download_info.value
            except Exception:  # noqa: BLE001
                await page.wait_for_timeout(5000)
                continue

            suggested = download.suggested_filename
            suffix = Path(suggested).suffix.lower()
            target_path = output_dir / f"{job.id}-{suffix_label}-{attempt + 1}{suffix or '.bin'}"
            await download.save_as(str(target_path))
            return [str(target_path)]
        return []

    async def _download_video_asset(self, page: Page, profile: Profile, job: AutomationJob) -> list[str]:
        make_video_button = await self._wait_for_action_button(
            page,
            [
                "button[aria-label='Make video']",
                "button:has-text('Make video')",
            ],
        )
        await make_video_button.click()

        try:
            await page.wait_for_url("**/imagine/post/**", timeout=90000)
        except Exception:  # noqa: BLE001
            pass

        return await self._download_file(page, profile, job, "video")

    async def inspect_session(
        self,
        page: Page,
        profile: Profile,
        automation_settings: AutomationSettings,
    ) -> dict:
        del profile, automation_settings
        title = ""
        preview = ""
        for _ in range(2):
            try:
                title = await page.title()
                preview = await self._body_preview(page)
                break
            except Exception:  # noqa: BLE001
                with suppress(Exception):
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
        combined = f"{title} {preview}"
        indicators = self._contains_any(
            combined,
            [
                "security verification",
                "just a moment",
                "sign in",
                "log in",
                "create image",
                "generate",
                "ask anything",
                "ask grok",
                "imagine",
                "private",
                "supergrok",
            ],
        )
        state = "unknown"
        summary = "Grok page loaded but no stable auth marker detected."
        if any(item in indicators for item in ["security verification", "just a moment"]):
            state = "security_verification"
            summary = "Grok is blocked behind Cloudflare verification."
        elif any(item in indicators for item in ["sign in", "log in"]):
            state = "login_required"
            summary = "Grok session is not authenticated."
        elif any(item in indicators for item in ["create image", "generate", "ask anything", "ask grok", "imagine", "private", "supergrok"]):
            state = "authenticated"
            summary = "Grok session appears ready for prompt submission."
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
        del automation_settings
        provider_payload = job.provider_payload or {}
        source_asset_path = provider_payload.get("source_asset_path")

        if job.target.value == "video":
            video_mode = str(provider_payload.get("video_mode") or "text_to_video")
            if video_mode in {"text_to_video", "image_to_video"}:
                await self._open_imagine_video_flow(page, job.prompt, source_asset_path if video_mode == "image_to_video" else None)
                media_urls = await self._download_file(page, profile, job, "video")
                if not media_urls and source_asset_path is None:
                    media_urls = await self._download_video_asset(page, profile, job)
                return {
                    "target": job.target.value,
                    "video_mode": video_mode,
                    "source_asset_path": source_asset_path,
                    "media_urls": media_urls,
                }

        await self._open_imagine_image_flow(page, job.prompt, source_asset_path)

        media_urls = await self._wait_for_filtered_media(page, job.target.value)
        media_urls = await self._localize_image_media(page, profile, job, media_urls)
        return {
            "target": job.target.value,
            "source_asset_path": source_asset_path,
            "media_urls": media_urls,
        }


grok_provider = GrokAutomationProvider()
