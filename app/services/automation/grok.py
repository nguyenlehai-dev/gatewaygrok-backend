import base64
import re
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

    async def _body_marker(self, page: Page) -> str:
        with suppress(Exception):
            preview = await self._body_preview(page)
            return " ".join(preview.split()).lower()
        return ""

    async def _submit_from_editor(self, page: Page, selectors: list[str]) -> None:
        before = await self._body_marker(page)

        with suppress(Exception):
            await self._submit_generation(page, selectors)
            return

        with suppress(Exception):
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1500)

        after_enter = await self._body_marker(page)
        if after_enter and after_enter != before:
            return

        await self._submit_generation(page, selectors)

    async def _ensure_imagine_page(self, page: Page) -> None:
        if page.url.startswith("https://grok.com/imagine/post"):
            await page.goto("https://grok.com/imagine", wait_until="domcontentloaded")
            return

        if page.url.rstrip("/") == "https://grok.com/imagine":
            return

        title = ""
        preview = ""
        with suppress(Exception):
            title = await page.title()
        with suppress(Exception):
            preview = await self._body_preview(page)

        combined = f"{title} {preview}".lower()
        if "security verification" in combined or "just a moment" in combined:
            await page.goto("https://grok.com/imagine", wait_until="domcontentloaded")
            return

        nav_selectors = [
            "a[href='/imagine']",
            "a[href='https://grok.com/imagine']",
            "[role='link'][href='/imagine']",
            "button:has-text('Imagine')",
            "[role='button']:has-text('Imagine')",
            "text=Imagine",
        ]
        for selector in nav_selectors:
            locator = page.locator(selector).first
            try:
                if await locator.count() == 0:
                    continue
                await locator.click(timeout=2000)
                with suppress(Exception):
                    await page.wait_for_url("**/imagine**", timeout=8000)
                if "/imagine" in page.url:
                    return
            except Exception:  # noqa: BLE001
                continue

        await page.goto("https://grok.com/imagine", wait_until="domcontentloaded")

    async def _extract_image_candidates(self, page: Page) -> list[dict]:
        return await page.evaluate(
            r"""
            () => {
              const normalize = (value) => (typeof value === "string" ? value.trim().toLowerCase() : "");
              const prompt = normalize(document.title.replace(/\s*-\s*grok$/i, ""));
              const images = Array.from(document.querySelectorAll("img"));
              const candidates = [];
              const seen = new Set();
              const pushCandidate = (candidate) => {
                if (!candidate.src || seen.has(candidate.src)) {
                  return;
                }
                seen.add(candidate.src);
                candidates.push(candidate);
              };

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

                if (!src) {
                  continue;
                }

                if (image.naturalWidth < 320 || image.naturalHeight < 320) {
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

                pushCandidate({
                  index,
                  src,
                  score,
                  promptMatch,
                  comparePanel,
                  rectY: rect.y,
                  rectX: rect.x,
                });
              }

              const backgroundNodes = Array.from(document.querySelectorAll("div, button, a, section, article"));
              for (const [index, node] of backgroundNodes.entries()) {
                const rect = node.getBoundingClientRect();
                if (rect.width < 280 || rect.height < 280 || rect.bottom <= 0 || rect.right <= 0) {
                  continue;
                }
                const style = window.getComputedStyle(node);
                if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || "1") <= 0.05) {
                  continue;
                }
                const bg = style.backgroundImage || "";
                const match = bg.match(/url\((['"]?)(.*?)\1\)/i);
                const src = match?.[2] || "";
                if (!src) {
                  continue;
                }

                const text = normalize(node.textContent || "");
                const promptMatch = Boolean(prompt) && text.includes(prompt);
                let score = Math.round((rect.width * rect.height) / 1000) + 180;
                if (promptMatch) {
                  score += 1000;
                }
                if (src.startsWith("data:image/")) {
                  score += 80;
                }
                if (src.startsWith("blob:")) {
                  score += 60;
                }

                pushCandidate({
                  index: images.length + index,
                  src,
                  score,
                  promptMatch,
                  comparePanel: false,
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

    async def _extract_image_panels(self, page: Page) -> list[dict]:
        return await page.evaluate(
            r"""
            () => {
              const items = [];
              const seen = new Set();
              const pushItem = (rect, score) => {
                const key = [Math.round(rect.x), Math.round(rect.y), Math.round(rect.width), Math.round(rect.height)].join(':');
                if (seen.has(key)) {
                  return;
                }
                seen.add(key);
                items.push({
                  x: Math.max(0, rect.x),
                  y: Math.max(0, rect.y),
                  width: Math.max(1, rect.width),
                  height: Math.max(1, rect.height),
                  score,
                });
              };

              for (const node of Array.from(document.querySelectorAll('img, div, button, a, section, article'))) {
                const rect = node.getBoundingClientRect();
                if (rect.width < 240 || rect.height < 240 || rect.bottom <= 0 || rect.right <= 0) {
                  continue;
                }
                const style = window.getComputedStyle(node);
                if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || '1') <= 0.05) {
                  continue;
                }

                const src = node.currentSrc || node.src || '';
                const bg = style.backgroundImage || '';
                const hasMedia =
                  src.startsWith('data:image/') ||
                  src.startsWith('blob:') ||
                  src.startsWith('http://') ||
                  src.startsWith('https://') ||
                  /url\(/i.test(bg);

                if (!hasMedia) {
                  continue;
                }

                const score = Math.round((rect.width * rect.height) / 1000);
                pushItem(rect, score);
              }

              return items.sort((a, b) => b.score - a.score || a.y - b.y || a.x - b.x).slice(0, 6);
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
                if normalized.startswith("blob:"):
                    seen.add(normalized)
                    filtered.append(normalized)
                    continue
                if not normalized.startswith("http://") and not normalized.startswith("https://"):
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
                try:
                    await locator.wait_for(state="visible", timeout=min(delay_ms, 1500))
                    return locator
                except Exception:  # noqa: BLE001
                    with suppress(Exception):
                        if await locator.count() > 0 and await locator.is_visible():
                            return locator
            await page.wait_for_timeout(delay_ms)
        raise RuntimeError(f"No matching selector found: {selectors}")

    async def _try_click_matching_option(self, page: Page, values: list[str]) -> bool:
        normalized_values = [value.strip() for value in values if value and value.strip()]
        if not normalized_values:
            return False

        if await self._click_exact_option(page, normalized_values):
            return True

        selectors: list[str] = []
        for value in normalized_values:
            selectors.extend(
                [
                    f"button[role='option']:has-text('{value}')",
                    f"button[role='radio']:has-text('{value}')",
                    f"[role='option']:has-text('{value}')",
                    f"[role='menuitemradio']:has-text('{value}')",
                    f"label:has-text('{value}')",
                    f"button:has-text('{value}')",
                    f"text='{value}'",
                ]
            )

        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if await locator.count() > 0:
                    await locator.click(timeout=1500)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    async def _click_exact_option(self, page: Page, values: list[str]) -> bool:
        normalized_values = {value.strip().lower() for value in values if value and value.strip()}
        if not normalized_values:
            return False

        candidate_selectors = [
            "button",
            "[role='option']",
            "[role='radio']",
            "[role='menuitemradio']",
            "label",
            "[role='button']",
        ]

        for selector in candidate_selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Exception:  # noqa: BLE001
                continue

            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if not await candidate.is_visible():
                        continue
                    text = await candidate.inner_text()
                except Exception:  # noqa: BLE001
                    continue

                normalized_text = re.sub(r"\s+", " ", text).strip().lower()
                if normalized_text not in normalized_values:
                    continue

                try:
                    await candidate.click(timeout=1500)
                    return True
                except Exception:  # noqa: BLE001
                    continue

        return False

    async def _submit_generation(self, page: Page, selectors: list[str]) -> None:
        submit = None
        for _ in range(30):
            try:
                submit = await self._first_visible(page, selectors)
                await submit.wait_for(state="visible", timeout=1500)
                disabled = await submit.get_attribute("disabled")
                aria_disabled = await submit.get_attribute("aria-disabled")
                is_enabled = await submit.is_enabled()
            except Exception:  # noqa: BLE001
                disabled = None
                aria_disabled = None
                is_enabled = True

            if disabled is None and aria_disabled not in {"true", "True"} and is_enabled:
                break
            await page.wait_for_timeout(1000)
        else:
            raise RuntimeError("Submit button stayed disabled. Grok did not accept the current prompt/input state.")

        try:
            await submit.click(timeout=5000)
            return
        except Exception:  # noqa: BLE001
            pass

        await page.evaluate(
            """
            (selectorList) => {
              const findButton = (selector) => {
                const textMatch = selector.match(/^(.*):has-text\\((['"])(.*)\\2\\)$/);
                if (textMatch) {
                  const base = textMatch[1] || "*";
                  const expected = textMatch[3].toLowerCase();
                  return Array.from(document.querySelectorAll(base))
                    .find((node) => (node.innerText || node.textContent || "").toLowerCase().includes(expected));
                }
                return document.querySelector(selector);
              };

              for (const selector of selectorList) {
                const button = findButton(selector);
                if (!button) {
                  continue;
                }
                if (button.hasAttribute('disabled') || button.getAttribute('aria-disabled') === 'true') {
                  continue;
                }
                button.click();
                button.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                return true;
              }
              return false;
            }
            """,
            selectors,
        )

    async def _try_open_dropdown(self, page: Page, labels: list[str]) -> bool:
        selectors: list[str] = []
        for label in labels:
            selectors.extend(
                [
                    f"button[aria-label*='{label}' i]",
                    f"[aria-label*='{label}' i] button",
                    f"button:has-text('{label}')",
                    f"label:has-text('{label}')",
                    f"[role='button']:has-text('{label}')",
                    f"text='{label}'",
                ]
            )

        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if await locator.count() > 0:
                    await locator.click(timeout=1500)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    async def _apply_generation_options(
        self,
        page: Page,
        *,
        ratio: str | None = None,
        quality: str | None = None,
        duration: int | str | None = None,
    ) -> dict:
        applied: dict[str, str | int] = {}

        if ratio:
            ratio_value = str(ratio).strip()
            ratio_candidates = [ratio_value]
            ratio_aliases = {
                "1:1": ["1x1", "square"],
                "9:16": ["9x16", "portrait", "vertical"],
                "16:9": ["16x9", "landscape", "horizontal"],
                "3:4": ["3x4", "portrait"],
                "4:3": ["4x3", "classic"],
                "2:3": ["2x3", "portrait"],
                "3:2": ["3x2", "landscape"],
            }
            ratio_candidates.extend(ratio_aliases.get(ratio_value, []))
            if await self._try_click_matching_option(page, ratio_candidates):
                applied["ratio"] = ratio_value
            elif await self._try_open_dropdown(page, ["Aspect ratio", "Ratio"]):
                await page.wait_for_timeout(400)
                if await self._try_click_matching_option(page, ratio_candidates):
                    applied["ratio"] = ratio_value

        if quality:
            quality_value = str(quality).strip()
            quality_candidates = [quality_value, quality_value.title(), quality_value.upper()]
            if await self._try_click_matching_option(page, quality_candidates):
                applied["quality"] = quality_value
            elif await self._try_open_dropdown(page, ["Quality"]):
                await page.wait_for_timeout(400)
                if await self._try_click_matching_option(page, quality_candidates):
                    applied["quality"] = quality_value

        if duration is not None and str(duration).strip():
            duration_value = str(duration).strip()
            duration_candidates = [
                duration_value,
                f"{duration_value}s",
                f"{duration_value} sec",
                f"{duration_value} seconds",
            ]
            if await self._try_click_matching_option(page, duration_candidates):
                applied["duration"] = duration_value
            elif await self._try_open_dropdown(page, ["Duration", "Length"]):
                await page.wait_for_timeout(400)
                if await self._try_click_matching_option(page, duration_candidates):
                    applied["duration"] = duration_value

        return applied

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

    async def _localize_video_media(self, page: Page, profile: Profile, job: AutomationJob, media_urls: list[str]) -> list[str]:
        output_dir = profile_storage.output_dir(profile.id)
        localized: list[str] = []
        for index, url in enumerate(media_urls, start=1):
            if not url.startswith("http://") and not url.startswith("https://"):
                localized.append(url)
                continue

            suffix = Path(urlparse(url).path).suffix.lower() or ".mp4"
            target_path = output_dir / f"{job.id}-video-{index}{suffix}"
            try:
                localized.append(await self._download_remote_media(page, url, target_path))
            except Exception:  # noqa: BLE001
                localized.append(url)
        return localized

    async def _capture_image_panel_fallback(self, page: Page, profile: Profile, job: AutomationJob) -> list[str]:
        panels = await self._extract_image_panels(page)
        if not panels:
            return []

        output_dir = profile_storage.output_dir(profile.id)
        captured: list[str] = []
        viewport = page.viewport_size or {"width": 1440, "height": 900}

        for index, panel in enumerate(panels[:4], start=1):
            x = max(0, int(panel.get("x", 0)))
            y = max(0, int(panel.get("y", 0)))
            width = max(1, int(panel.get("width", 1)))
            height = max(1, int(panel.get("height", 1)))
            if x + width > viewport["width"]:
                width = max(1, viewport["width"] - x)
            if y + height > viewport["height"]:
                height = max(1, viewport["height"] - y)
            target_path = output_dir / f"{job.id}-image-{index}.png"
            await page.screenshot(path=str(target_path), clip={"x": x, "y": y, "width": width, "height": height})
            captured.append(str(target_path))
        return captured

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

    async def _open_imagine_video_flow(
        self,
        page: Page,
        prompt: str,
        source_asset_path: str | None,
        *,
        ratio: str | None = None,
        quality: str | None = None,
        duration: int | str | None = None,
    ) -> dict:
        await self._ensure_imagine_page(page)
        await self._dismiss_consent_overlays(page)
        video_selectors = [
            "[aria-label='Generation mode'] button[role='radio']:has-text('Video')",
            "[aria-label='Generation mode'] >> text=Video",
            "button[role='radio']:has-text('Video')",
            "[role='tab']:has-text('Video')",
            "button:has-text('Video')",
        ]
        upload_trigger_selectors = [
            "button:has-text('Upload')",
            "button:has-text('Add image')",
            "button:has-text('Add reference')",
            "[aria-label*='Upload' i]",
            "[aria-label*='Add image' i]",
        ]
        uploaded_state_selectors = [
            "button:has-text('Remove')",
            "button[aria-label*='Remove' i]",
            "img[src^='blob:']",
            "img[src^='data:image']",
        ]
        try:
            video_mode = await self._wait_for_action_button(
                page,
                video_selectors,
                attempts=8,
                delay_ms=2000,
            )
            if await video_mode.get_attribute("aria-checked") != "true":
                await video_mode.click()
        except Exception:  # noqa: BLE001
            await page.goto("https://grok.com/imagine", wait_until="domcontentloaded")
            await self._dismiss_consent_overlays(page)
            with suppress(Exception):
                video_mode = await self._wait_for_action_button(
                    page,
                    video_selectors,
                    attempts=6,
                    delay_ms=1500,
                )
                if await video_mode.get_attribute("aria-checked") != "true":
                    await video_mode.click()

        if source_asset_path:
            source_file = Path(source_asset_path)
            if not source_file.exists():
                raise RuntimeError(f"Source asset not found: {source_asset_path}")
            upload_input = await self._first_visible(page, ["input[type='file']"], allow_hidden=True)
            await upload_input.set_input_files(str(source_file))
            upload_registered = False
            for _ in range(12):
                if await self._first_visible(page, uploaded_state_selectors, raise_on_empty=False):
                    upload_registered = True
                    break
                with suppress(Exception):
                    submit_probe = await self._first_visible(
                        page,
                        [
                            "button[aria-label='Submit']",
                            "button[type='submit']",
                        ],
                        raise_on_empty=False,
                    )
                    if submit_probe and await submit_probe.is_enabled():
                        upload_registered = True
                        break
                await page.wait_for_timeout(500)
            if not upload_registered:
                for selector in upload_trigger_selectors:
                    with suppress(Exception):
                        trigger = page.locator(selector).first
                        if await trigger.count() > 0 and await trigger.is_visible():
                            await trigger.click(timeout=1500)
                            break
                await upload_input.set_input_files(str(source_file))
                await page.wait_for_timeout(1500)
            await page.wait_for_timeout(1000)

        applied_options = await self._apply_generation_options(
            page,
            ratio=ratio,
            quality=quality,
            duration=duration,
        )

        if prompt.strip():
            await self._fill_prompt(
                page,
                [
                    "[contenteditable='true']",
                    "div[contenteditable='true']",
                    "[contenteditable='true'][data-placeholder*='Type' i]",
                    "div[contenteditable='true'][data-placeholder*='Type' i]",
                    "textarea",
                    "textarea[placeholder*='Type' i]",
                    "input[placeholder*='Type' i]",
                ],
                prompt,
            )

        await self._dismiss_consent_overlays(page)
        with suppress(Exception):
            editor = await self._first_visible(
                page,
                [
                    "[contenteditable='true']",
                    "div[contenteditable='true']",
                    "[contenteditable='true'][data-placeholder*='Type' i]",
                    "div[contenteditable='true'][data-placeholder*='Type' i]",
                    "textarea",
                    "textarea[placeholder*='Type' i]",
                    "input[placeholder*='Type' i]",
                ],
                raise_on_empty=False,
            )
            if editor:
                await editor.click()
                await page.keyboard.type(" ")
                await page.keyboard.press("Backspace")
        await self._submit_generation(
            page,
            [
                "button[aria-label='Submit']",
                "button[type='submit']",
            ],
        )
        return applied_options

    async def _open_imagine_image_flow(
        self,
        page: Page,
        prompt: str,
        source_asset_path: str | None = None,
        *,
        ratio: str | None = None,
        quality: str | None = None,
    ) -> dict:
        await self._ensure_imagine_page(page)
        await self._dismiss_consent_overlays(page)
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
            upload_input = await self._first_visible(page, ["input[type='file']"], allow_hidden=True)
            await upload_input.set_input_files(str(source_file))
            await page.wait_for_timeout(2500)

        applied_options = await self._apply_generation_options(
            page,
            ratio=ratio,
            quality=quality,
        )

        if prompt.strip():
            await self._fill_prompt(
                page,
                [
                    "[contenteditable='true']",
                    "div[contenteditable='true']",
                    "p[data-placeholder='Ask Grok']",
                    "[contenteditable='true'][data-placeholder*='Type' i]",
                    "div[contenteditable='true'][data-placeholder*='Type' i]",
                    "textarea",
                    "textarea[placeholder*='Ask']",
                    "textarea[placeholder*='Type' i]",
                    "input[placeholder*='Type' i]",
                ],
                prompt,
            )

        await self._submit_from_editor(
            page,
            [
                "button[aria-label='Submit']",
                "button[type='submit']",
                "button:has-text('Create image')",
                "button:has-text('Generate')",
            ],
        )
        return applied_options

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
        patterns = [
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
        ]
        title = ""
        preview = ""
        indicators: list[str] = []
        for _ in range(4):
            try:
                title = await page.title()
                preview = await self._body_preview(page)
                indicators = self._contains_any(f"{title} {preview}", patterns)
                if indicators:
                    break
            except Exception:  # noqa: BLE001
                with suppress(Exception):
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
            with suppress(Exception):
                await page.wait_for_timeout(1000)

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
        ratio = provider_payload.get("ratio") or provider_payload.get("aspect_ratio")
        quality = provider_payload.get("quality")
        duration = provider_payload.get("duration")

        if job.target.value == "video":
            video_mode = str(provider_payload.get("video_mode") or "text_to_video")
            if video_mode in {"text_to_video", "image_to_video"}:
                applied_options = await self._open_imagine_video_flow(
                    page,
                    job.prompt,
                    source_asset_path if video_mode == "image_to_video" else None,
                    ratio=str(ratio) if ratio else None,
                    quality=str(quality) if quality else None,
                    duration=duration,
                )
                media_urls = await self._wait_for_filtered_media(page, "video", attempts=36, delay_ms=5000)
                media_urls = await self._localize_video_media(page, profile, job, media_urls)
                if not media_urls:
                    media_urls = await self._download_file(page, profile, job, "video")
                return {
                    "target": job.target.value,
                    "video_mode": video_mode,
                    "source_asset_path": source_asset_path,
                    "ratio": ratio,
                    "quality": quality,
                    "duration": duration,
                    "applied_options": applied_options,
                    "media_urls": media_urls,
                }

        applied_options = await self._open_imagine_image_flow(
            page,
            job.prompt,
            source_asset_path,
            ratio=str(ratio) if ratio else None,
            quality=str(quality) if quality else None,
        )

        media_urls = await self._wait_for_filtered_media(page, job.target.value)
        media_urls = await self._localize_image_media(page, profile, job, media_urls)
        if not media_urls:
            media_urls = await self._capture_image_panel_fallback(page, profile, job)
        return {
            "target": job.target.value,
            "source_asset_path": source_asset_path,
            "ratio": ratio,
            "quality": quality,
            "applied_options": applied_options,
            "media_urls": media_urls,
        }


grok_provider = GrokAutomationProvider()
