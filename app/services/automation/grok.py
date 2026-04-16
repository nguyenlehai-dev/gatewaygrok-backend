import asyncio
import base64
import re
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page

from app.core.config import settings
from app.models.automation_job import AutomationJob
from app.models.profile import Profile
from app.schemas.setting import AutomationSettings
from app.services.automation.base import BaseAutomationProvider
from app.services.profile_storage import profile_storage


class ContentPolicyBlockedError(RuntimeError):
    """Raised when Grok rejects the prompt due to safety/content policy."""


class SubmitButtonDisabledError(RuntimeError):
    """Raised when Grok never enables the submit button for the current form state."""


class InvalidVideoOutputError(RuntimeError):
    """Raised when a video generation flow returns non-video output."""


class GrokAutomationProvider(BaseAutomationProvider):
    provider_name = "grok"
    start_url = "https://grok.com/"

    def _log_job_step(self, job: AutomationJob, step: str) -> None:
        print(
            f"grok_job_step job_id={job.id} profile_id={job.profile_id} target={job.target.value} step={step}",
            flush=True,
        )

    def _coerce_image_to_video_prompt(self, prompt: str) -> str:
        normalized = " ".join((prompt or "").split()).strip()
        if not normalized:
            return (
                "Create a short cinematic video from the attached reference image. "
                "Preserve the face and identity exactly, and animate the scene naturally."
            )

        lowered = normalized.lower()
        video_markers = [
            "video",
            "animate",
            "animation",
            "camera movement",
            "motion",
            "cinematic shot",
            "clip",
        ]
        if any(marker in lowered for marker in video_markers):
            return normalized

        return (
            "Create a short cinematic video from the attached reference image. "
            "Keep the face and identity exactly the same as the reference image. "
            "Animate the subject naturally with subtle motion and realistic camera movement. "
            f"Follow these appearance and scene details: {normalized}"
        )

    async def _prompt_present(self, page: Page, prompt: str) -> bool:
        normalized_prompt = " ".join((prompt or "").split()).strip().lower()
        prefix = normalized_prompt[:32]
        words = [word for word in re.findall(r"[0-9a-zA-Z_]+", normalized_prompt) if len(word) >= 3][:6]
        return bool(
            await page.evaluate(
                r"""
                ({ prefix, words }) => {
                  if (!prefix && (!words || !words.length)) return true;
                  const fields = Array.from(
                    document.querySelectorAll("[contenteditable='true'], [role='textbox'], textarea, input")
                  );
                  return fields.some((el) => {
                    const value = el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement
                      ? el.value
                      : el.innerText;
                    const normalized = (value || "").replace(/\s+/g, " ").trim().toLowerCase();
                    if (!normalized) return false;
                    if (prefix && normalized.includes(prefix)) return true;
                    const matchedWords = (words || []).filter((word) => normalized.includes(word));
                    return matchedWords.length >= Math.min(3, (words || []).length || 0);
                  });
                }
                """,
                {"prefix": prefix, "words": words},
            )
        )

    async def _prepare_image_to_video_form(
        self,
        page: Page,
        prompt: str,
        source_asset_path: str | None,
        *,
        reset_page: bool = False,
    ) -> None:
        if reset_page:
            await page.goto("https://grok.com/imagine", wait_until="domcontentloaded")
            await page.wait_for_timeout(1200)
        try:
            video_mode_button = await self._wait_for_action_button(
                page,
                [
                    "[aria-label='Generation mode'] button[role='radio']:has-text('Video')",
                    "[aria-label='Generation mode'] >> text=Video",
                ],
                attempts=8,
                delay_ms=1200,
            )
        except RuntimeError:
            if not reset_page:
                await page.goto("https://grok.com/imagine", wait_until="domcontentloaded")
                await page.wait_for_timeout(1200)
                video_mode_button = await self._wait_for_action_button(
                    page,
                    [
                        "[aria-label='Generation mode'] button[role='radio']:has-text('Video')",
                        "[aria-label='Generation mode'] >> text=Video",
                    ],
                    attempts=8,
                    delay_ms=1200,
                )
            else:
                raise
        if await video_mode_button.get_attribute("aria-checked") != "true":
            await video_mode_button.click(timeout=3000)
            await page.wait_for_timeout(600)

        with suppress(Exception):
            await self._select_video_submode(page, "image_to_video")
        with suppress(Exception):
            await self._click_composer_video_mode(page)

        if source_asset_path:
            source_file = Path(source_asset_path)
            if source_file.exists():
                upload_input = await self._first_visible(page, ["input[type='file']"])
                await upload_input.set_input_files(str(source_file))
                await page.wait_for_timeout(1800)
                with suppress(Exception):
                    await self._select_video_submode(page, "image_to_video")
                with suppress(Exception):
                    await self._click_composer_video_mode(page)

        await self._fill_grok_prompt(page, prompt, edit_mode=False)

    async def _ensure_video_generation_state(
        self,
        page: Page,
        prompt: str,
        source_asset_path: str | None = None,
    ) -> None:
        expected = prompt.strip().lower()[:80]
        for attempt in range(4):
            state = await page.evaluate(
                r"""
                (expected) => {
                  const visible = (el) => {
                    if (!(el instanceof HTMLElement)) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                      rect.width > 0 &&
                      rect.height > 0 &&
                      rect.bottom > 0 &&
                      rect.right > 0 &&
                      style.display !== "none" &&
                      style.visibility !== "hidden" &&
                      Number(style.opacity || "1") > 0.05
                    );
                  };
                  const fields = Array.from(
                    document.querySelectorAll("[contenteditable='true'], [role='textbox'], textarea, input")
                  ).filter(visible);
                  const field = fields
                    .sort((left, right) => right.getBoundingClientRect().bottom - left.getBoundingClientRect().bottom)[0];
                  const fieldText = field instanceof HTMLTextAreaElement || field instanceof HTMLInputElement
                    ? field.value || ""
                    : field?.innerText || "";
                  const placeholder = [
                    field?.getAttribute("data-placeholder") || "",
                    field?.getAttribute("placeholder") || "",
                    field?.getAttribute("aria-label") || "",
                  ].join(" ").toLowerCase();
                  const videoRadio = Array.from(document.querySelectorAll("button[role='radio']"))
                    .find((button) => (button.innerText || "").trim().toLowerCase() === "video");
                  const videoChecked = videoRadio?.getAttribute("aria-checked") === "true";
                  const promptPresent = !expected || fieldText.trim().toLowerCase().includes(expected);
                  return {
                    videoChecked,
                    placeholder,
                    promptPresent,
                    editMode: placeholder.includes("edit image") || placeholder.includes("describe your edit"),
                  };
                }
                """,
                expected,
            )
            if (
                isinstance(state, dict)
                and state.get("videoChecked")
                and not state.get("editMode")
                and state.get("promptPresent")
            ):
                return
            if isinstance(state, dict) and state.get("editMode") and attempt >= 1:
                await self._prepare_image_to_video_form(
                    page,
                    prompt,
                    source_asset_path,
                    reset_page=True,
                )
                await page.wait_for_timeout(800)
                continue
            with suppress(Exception):
                await self._click_composer_video_mode(page)
            with suppress(Exception):
                video_mode_button = page.locator("[aria-label='Generation mode'] button[role='radio']:has-text('Video')").first
                if await video_mode_button.count() > 0:
                    await video_mode_button.click(timeout=2000)
                    await page.wait_for_timeout(500)
            if source_asset_path and attempt >= 2:
                await self._prepare_image_to_video_form(
                    page,
                    prompt,
                    source_asset_path,
                    reset_page=True,
                )
            else:
                await self._fill_grok_prompt(page, prompt, edit_mode=False)
            await page.wait_for_timeout(600)
        raise SubmitButtonDisabledError(
            "Grok stayed in image-edit mode instead of video mode for this image-to-video job."
        )

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
                  rect.width >= 160 &&
                  rect.height >= 180 &&
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

                if (image.naturalWidth < 400 || image.naturalHeight < 400) {
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
        if target == "video":
            video_urls = await page.evaluate(
                r"""
                () => {
                  const visible = (el) => {
                    if (!(el instanceof HTMLElement)) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                      rect.width >= 120 &&
                      rect.height >= 120 &&
                      rect.bottom > 0 &&
                      rect.right > 0 &&
                      rect.top < window.innerHeight &&
                      rect.left < window.innerWidth &&
                      style.display !== "none" &&
                      style.visibility !== "hidden" &&
                      Number(style.opacity || "1") > 0.05
                    );
                  };
                  const candidates = Array.from(document.querySelectorAll("video"))
                    .filter(visible)
                    .map((video) => {
                      const rect = video.getBoundingClientRect();
                      return {
                        src: video.currentSrc || video.src || "",
                        score: Math.round(rect.width * rect.height) + Math.round(rect.height * 10),
                      };
                    })
                    .filter((item) => item.src);
                  candidates.sort((left, right) => right.score - left.score);
                  return candidates.map((item) => item.src);
                }
                """
            )
            if isinstance(video_urls, list) and any(str(url).strip() for url in video_urls):
                return [str(url).strip() for url in video_urls if str(url).strip()]
            return await super()._extract_media_urls(page, target)

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
        if target == "video":
            preferred = [
                url
                for url in filtered
                if "share-videos/" in url.lower() or "generated_video" in url.lower()
            ]
            if preferred:
                filtered = preferred
            if len(filtered) > 4:
                filtered = filtered[:4]
        return filtered

    async def _detect_content_policy_block(self, page: Page, target: str) -> str | None:
        text = await page.evaluate(
            r"""
            () => {
              const nodes = Array.from(
                document.querySelectorAll('[role="alert"], [role="status"], [role="dialog"], [aria-live], main, body')
              );
              const joined = nodes
                .map((node) => (node instanceof HTMLElement ? node.innerText || "" : ""))
                .join("\n")
                .replace(/\s+/g, " ")
                .trim();
              return joined.slice(0, 12000);
            }
            """
        )
        normalized = str(text or "").lower()
        if not normalized:
            return None

        direct_phrases = [
            "content policy",
            "safety policy",
            "violates our policy",
            "violates our policies",
            "can't help with that",
            "cannot help with that",
            "can't generate that",
            "cannot generate that",
            "can't create that",
            "cannot create that",
            "request was blocked",
            "request has been blocked",
            "sensitive content",
            "sexual content",
            "sexually explicit",
            "nudity",
            "adult content",
            "18+",
            "nsfw",
        ]
        if any(phrase in normalized for phrase in direct_phrases):
            return (
                f"Grok stopped this {target} job because the prompt appears to be restricted by safety/content policy. "
                "If this is 18+ or explicit content, stop and revise the prompt."
            )

        token_groups = [
            ("policy", "violat"),
            ("safety", "violat"),
            ("content", "restricted"),
            ("content", "blocked"),
            ("sexual", "not allowed"),
            ("explicit", "not allowed"),
            ("adult", "not allowed"),
        ]
        if any(all(token in normalized for token in group) for group in token_groups):
            return (
                f"Grok rejected this {target} job due to content restrictions. "
                "If the request is 18+ or explicit, stop the job and change the prompt."
            )

        return None

    async def _detect_hidden_media_block(self, page: Page, target: str) -> str | None:
        details = await page.evaluate(
            r"""
            () => {
              const isVisible = (el) => {
                if (!(el instanceof HTMLElement)) return false;
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return (
                  rect.width >= 180 &&
                  rect.height >= 180 &&
                  rect.bottom > 0 &&
                  rect.right > 0 &&
                  style.display !== "none" &&
                  style.visibility !== "hidden" &&
                  Number(style.opacity || "1") > 0.05
                );
              };

              const images = Array.from(document.querySelectorAll("img"))
                .filter((img) => isVisible(img))
                .map((img) => {
                  const rect = img.getBoundingClientRect();
                  const style = window.getComputedStyle(img);
                  return {
                    width: rect.width,
                    height: rect.height,
                    filter: String(style.filter || ""),
                    className: String(img.className || ""),
                  };
                });

              const blurredLargeImage = images.some((img) => {
                const text = `${img.filter} ${img.className}`.toLowerCase();
                return img.width >= 320 && img.height >= 320 && (text.includes("blur") || text.includes("hidden"));
              });

              const bodyText = (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 3000).toLowerCase();
              const eyeSlashIcon = Array.from(document.querySelectorAll("svg"))
                .some((svg) => {
                  const rect = svg.getBoundingClientRect();
                  return rect.width >= 36 && rect.height >= 36 && rect.width <= 140 && rect.height <= 140;
                });

              return {
                blurredLargeImage,
                eyeSlashIcon,
                bodyText,
              };
            }
            """
        )
        if not isinstance(details, dict):
            return None

        body_text = str(details.get("bodyText") or "")
        blocked_phrases = [
            "sensitive",
            "not available",
            "not visible",
            "cannot be shown",
            "can't be shown",
            "hidden",
            "blocked",
        ]
        if any(phrase in body_text for phrase in blocked_phrases):
            return (
                f"Grok hid or blocked this {target} result before the next action became available. "
                "This is likely due to safety/content restrictions."
            )

        if details.get("blurredLargeImage") and details.get("eyeSlashIcon"):
            return (
                f"Grok blurred or hid the generated {target} result before video conversion. "
                "This is likely a sensitive-content or policy restriction."
            )

        return None

    async def _wait_for_action_button(
        self,
        page: Page,
        selectors: list[str],
        attempts: int = 18,
        delay_ms: int = 5000,
        *,
        policy_target: str | None = None,
    ):
        for _ in range(attempts):
            for selector in selectors:
                locator = page.locator(selector).first
                if await locator.count() > 0:
                    return locator
            if policy_target:
                blocked_message = await self._detect_content_policy_block(page, policy_target)
                if blocked_message:
                    raise ContentPolicyBlockedError(blocked_message)
                hidden_message = await self._detect_hidden_media_block(page, policy_target)
                if hidden_message:
                    raise ContentPolicyBlockedError(hidden_message)
            await page.wait_for_timeout(delay_ms)
        raise RuntimeError(f"No matching selector found: {selectors}")

    async def _try_click_matching_option(self, page: Page, values: list[str]) -> bool:
        normalized_values = [value.strip() for value in values if value and value.strip()]
        if not normalized_values:
            return False

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

    async def _read_submit_disabled_reason(self, page: Page) -> str:
        return await page.evaluate(
            r"""
            () => {
              const button =
                document.querySelector("button[aria-label='Submit']") ||
                document.querySelector("button[type='submit']");
              if (!(button instanceof HTMLButtonElement)) {
                return "submit button not found";
              }
              const hints = [];
              if (button.disabled) {
                hints.push("submit button is disabled");
              }
              const text = (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 3000).toLowerCase();
              const phrases = [
                "add a prompt",
                "enter a prompt",
                "type a prompt",
                "upload",
                "image",
                "unsupported",
                "not available",
                "try again",
              ];
              for (const phrase of phrases) {
                if (text.includes(phrase)) {
                  hints.push(`page contains: ${phrase}`);
                }
              }
              return hints.join("; ") || "submit button stayed disabled";
            }
            """
        )

    async def _find_submit_button(self, page: Page):
        selectors = [
            "button[aria-label='Submit']",
            "button[aria-label*='Submit' i]",
            "button[aria-label*='Send' i]",
            "button[aria-label*='Generate' i]",
            "button[aria-label*='Create' i]",
            "button[aria-label*='Imagine' i]",
            "button[title*='Submit' i]",
            "button[title*='Send' i]",
            "button[title*='Generate' i]",
            "button:has-text('Generate')",
            "button:has-text('Create')",
            "button:has-text('Make')",
            "button:has-text('Submit')",
            "button[type='submit']",
        ]
        with suppress(Exception):
            return await self._first_visible(page, selectors)

        candidate_index = await page.evaluate(
            r"""
            () => {
              const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
              const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return (
                  rect.width >= 24 &&
                  rect.height >= 24 &&
                  rect.bottom > 0 &&
                  rect.right > 0 &&
                  style.display !== 'none' &&
                  style.visibility !== 'hidden' &&
                  Number(style.opacity || '1') > 0.05
                );
              };
              const scoreButton = (button) => {
                if (!(button instanceof HTMLElement) || !isVisible(button)) {
                  return -1;
                }
                const rect = button.getBoundingClientRect();
                const text = [
                  button.innerText || '',
                  button.getAttribute('aria-label') || '',
                  button.getAttribute('title') || '',
                ].join(' ').toLowerCase();
                const disabled =
                  (button instanceof HTMLButtonElement && button.disabled) ||
                  button.getAttribute('aria-disabled') === 'true';
                let score = 0;
                if (button instanceof HTMLButtonElement && button.type === 'submit') score += 300;
                if (button.getAttribute('role') === 'button') score += 80;
                if (text.includes('submit')) score += 250;
                if (text.includes('send')) score += 220;
                if (text.includes('generate')) score += 220;
                if (text.includes('create')) score += 180;
                if (text.includes('imagine')) score += 160;
                if (!text.trim()) score += 80;
                if (disabled) score -= 120;
                if (rect.bottom >= window.innerHeight - 220) score += 120;
                if (rect.right >= window.innerWidth - 260) score += 80;
                if (rect.width <= 80 && rect.height <= 80) score += 30;
                if (button.closest("form")) score += 70;
                if (button.closest("[role='toolbar']")) score -= 40;
                if (button.closest("aside")) score -= 120;
                return score;
              };
              let bestIndex = -1;
              let bestScore = -1;
              buttons.forEach((button, index) => {
                const score = scoreButton(button);
                if (score > bestScore) {
                  bestScore = score;
                  bestIndex = index;
                }
              });
              return bestScore >= 180 ? bestIndex : -1;
            }
            """
        )
        if isinstance(candidate_index, int) and candidate_index >= 0:
            locator = page.locator('button, [role="button"]').nth(candidate_index)
            if await locator.count() > 0:
                return locator
        raise RuntimeError("submit button not found")

    async def _wait_for_enabled_submit_button(self, page: Page, flow_label: str, attempts: int = 12, delay_ms: int = 1000):
        submit = await self._find_submit_button(page)
        for _ in range(attempts):
            blocked_message = await self._detect_content_policy_block(page, flow_label)
            if blocked_message:
                raise ContentPolicyBlockedError(blocked_message)
            enabled = False
            with suppress(Exception):
                enabled = await submit.is_enabled(timeout=1000)
            if enabled:
                return submit
            await page.wait_for_timeout(delay_ms)
        reason = await self._read_submit_disabled_reason(page)
        raise RuntimeError(f"submit button stayed disabled before click for {flow_label}. {reason}.")

    async def _fill_grok_prompt(self, page: Page, prompt: str, *, edit_mode: bool = False) -> None:
        prompt = prompt.strip()
        if not prompt:
            return

        placeholder_selectors = [
            "[contenteditable='true'][data-placeholder*='Describe' i]",
            "div[contenteditable='true'][data-placeholder*='Describe' i]",
            "p[data-placeholder*='Describe' i]",
            "[role='textbox'][aria-label*='Describe' i]",
            "[aria-label*='Describe' i]",
            "[contenteditable='true'][data-placeholder*='Ask' i]",
            "div[contenteditable='true'][data-placeholder*='Ask' i]",
            "p[data-placeholder*='Ask' i]",
            "[contenteditable='true'][data-placeholder*='Type' i]",
            "div[contenteditable='true'][data-placeholder*='Type' i]",
            "[role='textbox']",
            "div[role='textbox']",
            "[contenteditable='true']",
            "div[contenteditable='true']",
            "textarea[placeholder*='imagine' i]",
            "input[placeholder*='imagine' i]",
            "textarea[placeholder*='Ask' i]",
            "textarea[placeholder*='Type' i]",
            "input[placeholder*='Type' i]",
            "textarea",
        ]

        for attempt in range(3):
            filled = await page.evaluate(
                r"""
                ({ prompt, editMode }) => {
                  const isVisible = (el) => {
                    if (!(el instanceof HTMLElement)) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                      rect.width >= 120 &&
                      rect.height >= 18 &&
                      rect.bottom > 0 &&
                      rect.right > 0 &&
                      style.display !== "none" &&
                      style.visibility !== "hidden" &&
                      Number(style.opacity || "1") > 0.05
                    );
                  };
                  const textOf = (el) => [
                    el.getAttribute("data-placeholder") || "",
                    el.getAttribute("aria-label") || "",
                    el.getAttribute("placeholder") || "",
                    el.innerText || "",
                  ].join(" ").toLowerCase();
                  const candidates = Array.from(
                    document.querySelectorAll("[contenteditable='true'], [role='textbox'], textarea, input")
                  ).filter(isVisible);
                  const score = (el) => {
                    const rect = el.getBoundingClientRect();
                    const text = textOf(el);
                    let value = 0;
                    if (editMode && text.includes("describe your edit")) value += 500;
                    if (editMode && text.includes("describe")) value += 260;
                    if (editMode && text.includes("edit")) value += 180;
                    if (!editMode && text.includes("type to imagine")) value += 520;
                    if (!editMode && text.includes("imagine")) value += 300;
                    if (!editMode && text.includes("ask grok")) value += 220;
                    if (!editMode && text.includes("ask anything")) value += 180;
                    if (text.includes("type")) value += 80;
                    if (el.isContentEditable) value += 80;
                    if (el.getAttribute("role") === "textbox") value += 50;
                    if (rect.bottom >= window.innerHeight - 260) value += 160;
                    if (el.closest("aside, nav, header")) value -= 240;
                    if (rect.width < 180) value -= 80;
                    return value;
                  };
                  candidates.sort((left, right) => score(right) - score(left));
                  const target = candidates[0];
                  if (!(target instanceof HTMLElement) || score(target) < 120) {
                    return false;
                  }
                  target.focus();
                  target.click?.();
                  if (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement) {
                    target.value = prompt;
                    target.dispatchEvent(new Event("input", { bubbles: true }));
                    target.dispatchEvent(new Event("change", { bubbles: true }));
                    return true;
                  }
                  target.textContent = "";
                  document.execCommand("selectAll", false);
                  document.execCommand("insertText", false, prompt);
                  if (!target.innerText?.trim()) {
                    target.textContent = prompt;
                  }
                  target.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: prompt }));
                  return true;
                }
                """,
                {"prompt": prompt, "editMode": edit_mode},
            )
            if filled:
                await page.wait_for_timeout(250)
            if await self._prompt_present(page, prompt):
                return
            with suppress(Exception):
                await page.keyboard.press("Escape")
            await page.wait_for_timeout(250)

        with suppress(Exception):
            await self._fill_prompt(page, placeholder_selectors, prompt)
        if not await self._prompt_present(page, prompt):
            raise RuntimeError("Grok prompt field did not retain the requested prompt text.")

    async def _click_submit_fallback(self, page: Page) -> bool:
        return bool(
            await page.evaluate(
                r"""
                () => {
                  const selectors = 'button, [role="button"], [tabindex], div, span';
                  const elements = Array.from(document.querySelectorAll(selectors));
                  const isVisible = (el) => {
                    if (!(el instanceof HTMLElement)) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                      rect.width >= 28 &&
                      rect.height >= 28 &&
                      rect.width <= 96 &&
                      rect.height <= 96 &&
                      rect.bottom > window.innerHeight - 120 &&
                      rect.right > window.innerWidth - 220 &&
                      rect.bottom <= window.innerHeight + 2 &&
                      rect.right <= window.innerWidth + 2 &&
                      style.display !== "none" &&
                      style.visibility !== "hidden" &&
                      Number(style.opacity || "1") > 0.05
                    );
                  };
                  const scoreElement = (el) => {
                    if (!(el instanceof HTMLElement) || !isVisible(el)) return -1;
                    if (el.closest("aside")) return -1;
                    const rect = el.getBoundingClientRect();
                    const text = [
                      el.innerText || "",
                      el.getAttribute("aria-label") || "",
                      el.getAttribute("title") || "",
                    ].join(" ").toLowerCase();
                    const disabled =
                      (el instanceof HTMLButtonElement && el.disabled) ||
                      el.getAttribute("aria-disabled") === "true";
                    let score = 0;
                    if (disabled) score -= 500;
                    if (el.querySelector("svg")) score += 180;
                    if (text.includes("submit") || text.includes("send") || text.includes("generate")) score += 220;
                    if (!text.trim()) score += 80;
                    if (rect.right >= window.innerWidth - 80) score += 180;
                    if (rect.bottom >= window.innerHeight - 80) score += 180;
                    if (rect.width >= 40 && rect.height >= 40) score += 80;
                    const radius = window.getComputedStyle(el).borderRadius || "";
                    if (radius.includes("999") || radius.includes("50%")) score += 80;
                    return score;
                  };
                  let best = null;
                  let bestScore = -1;
                  for (const el of elements) {
                    const score = scoreElement(el);
                    if (score > bestScore) {
                      best = el;
                      bestScore = score;
                    }
                  }
                  if (!best || bestScore < 260) {
                    return false;
                  }
                  best.click();
                  return true;
                }
                """
            )
        )

    async def _apply_generation_options(
        self,
        page: Page,
        *,
        ratio: str | None = None,
        quality: str | None = None,
        duration: int | str | None = None,
    ) -> dict:
        applied: dict[str, str | int] = {}
        requested: dict[str, str | int] = {}

        if ratio:
            requested["ratio"] = str(ratio).strip()
        if quality:
            requested["quality"] = str(quality).strip()
        if duration is not None and str(duration).strip():
            requested["duration"] = str(duration).strip()

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

        unapplied = {
            key: value for key, value in requested.items() if str(applied.get(key, "")).strip() != str(value).strip()
        }
        return {
            "requested": requested,
            "applied": applied,
            "unapplied": unapplied,
        }

    async def _select_video_submode(self, page: Page, video_mode: str) -> None:
        target_label = "Image to video" if video_mode == "image_to_video" else "Text to video"
        other_label = "Text to video" if video_mode == "image_to_video" else "Image to video"
        selectors = [
            f"[aria-label='Video mode'] button[role='radio']:has-text('{target_label}')",
            f"[aria-label='Video mode'] >> text={target_label}",
            f"button[role='radio']:has-text('{target_label}')",
            f"[role='tab']:has-text('{target_label}')",
            f"button:has-text('{target_label}')",
            f"text='{target_label}'",
        ]

        for _ in range(4):
            for selector in selectors:
                locator = page.locator(selector).first
                try:
                    if await locator.count() == 0:
                        continue
                    with suppress(Exception):
                        if await locator.get_attribute("aria-checked") == "true":
                            return
                    with suppress(Exception):
                        if await locator.get_attribute("aria-selected") == "true":
                            return
                    await locator.click(timeout=2000)
                    await page.wait_for_timeout(700)
                    with suppress(Exception):
                        if await locator.get_attribute("aria-checked") == "true":
                            return
                    with suppress(Exception):
                        if await locator.get_attribute("aria-selected") == "true":
                            return
                    page_text = str(await page.text_content("body") or "").lower()
                    if target_label.lower() in page_text and other_label.lower() in page_text:
                        return
                except Exception:  # noqa: BLE001
                    continue
            with suppress(Exception):
                await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)

        raise RuntimeError(f"Could not switch Grok video mode to '{target_label}'.")

    async def _click_composer_video_mode(self, page: Page) -> bool:
        clicked = await page.evaluate(
            r"""
            () => {
              const isVisible = (el) => {
                if (!(el instanceof HTMLElement)) return false;
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return (
                  rect.width >= 24 &&
                  rect.height >= 24 &&
                  rect.bottom > window.innerHeight - 160 &&
                  rect.right > window.innerWidth * 0.55 &&
                  style.display !== "none" &&
                  style.visibility !== "hidden" &&
                  Number(style.opacity || "1") > 0.05
                );
              };
              const buttons = Array.from(document.querySelectorAll("button, [role='button']")).filter(isVisible);
              const scoreButton = (button) => {
                const rect = button.getBoundingClientRect();
                const text = [
                  button.innerText || "",
                  button.getAttribute("aria-label") || "",
                  button.getAttribute("title") || "",
                ].join(" ").toLowerCase();
                let score = 0;
                if (text.includes("video")) score += 500;
                if (text.includes("camera")) score += 120;
                if (button.querySelector("svg")) score += 100;
                if (rect.right >= window.innerWidth - 140) score += 120;
                if (rect.bottom >= window.innerHeight - 90) score += 120;
                if (rect.width <= 80 && rect.height <= 80) score += 40;
                if (text.includes("submit") || text.includes("send")) score -= 300;
                if (text.includes("image") || text.includes("photo")) score -= 80;
                if (button.closest("aside, nav, header")) score -= 300;
                return score;
              };
              buttons.sort((left, right) => scoreButton(right) - scoreButton(left));
              const target = buttons[0];
              if (!(target instanceof HTMLElement) || scoreButton(target) < 220) {
                return false;
              }
              target.click();
              return true;
            }
            """
        )
        if clicked:
            await page.wait_for_timeout(800)
        return bool(clicked)

    async def _wait_for_filtered_media(self, page: Page, target: str, attempts: int = 18, delay_ms: int = 4000) -> list[str]:
        latest: list[str] = []
        best_complete: list[str] = []
        previous_signature: tuple[tuple[int, str], ...] | None = None
        stable_ready_hits = 0
        required_stable_hits = 3 if target == "image" else 1
        for _ in range(attempts):
            blocked_message = await self._detect_content_policy_block(page, target)
            if blocked_message:
                raise ContentPolicyBlockedError(blocked_message)
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

    async def _video_generation_state(self, page: Page) -> dict:
        return await page.evaluate(
            r"""
            () => {
              const body = (document.body?.innerText || "").replace(/\s+/g, " ").trim();
              const html = (document.documentElement?.innerHTML || "").slice(0, 200000);
              const normalized = body.toLowerCase();
              const hasDownload = Array.from(document.querySelectorAll("button"))
                .some((button) => {
                  const label = [
                    button.getAttribute("aria-label") || "",
                    button.innerText || "",
                    button.getAttribute("title") || "",
                  ].join(" ").toLowerCase();
                  return label.includes("download");
                });
              const hasVideo = Array.from(document.querySelectorAll("video")).some((video) => {
                const src = video.currentSrc || video.src || "";
                return Boolean(src);
              });
              const htmlHasVideoUrl =
                html.includes(".mp4") ||
                html.includes("generated_video") ||
                html.includes("share-videos/");
              const generating =
                normalized.includes("cancel video") ||
                normalized.includes("generating") ||
                /generating\s+\d{1,3}%/i.test(body);
              const percentMatch = body.match(/Generating\s+(\d{1,3})%/i);
              return {
                generating,
                progress: percentMatch ? percentMatch[1] : null,
                hasDownload,
                hasVideo,
                htmlHasVideoUrl,
                body: body.slice(0, 1000),
              };
            }
            """
        )

    async def _extract_ready_video_urls(self, page: Page) -> list[str]:
        urls = await page.evaluate(
            r"""
            () => {
              const values = [];
              const push = (value) => {
                if (typeof value === "string" && value.trim()) {
                  values.push(value.trim());
                }
              };

              for (const video of Array.from(document.querySelectorAll("video"))) {
                push(video.currentSrc || video.src || "");
                for (const source of Array.from(video.querySelectorAll("source"))) {
                  push(source.src || "");
                }
              }

              for (const anchor of Array.from(document.querySelectorAll("a[href]"))) {
                push(anchor.href || "");
              }

              for (const media of Array.from(document.querySelectorAll("[src], [data-url], [data-href]"))) {
                if (!(media instanceof HTMLElement)) continue;
                push(media.getAttribute("src") || "");
                push(media.getAttribute("data-url") || "");
                push(media.getAttribute("data-href") || "");
              }

              const html = document.documentElement?.innerHTML || "";
              const regex = /https?:\/\/[^"'\\s<>]+(?:generated_video[^"'\\s<>]*|share-videos\/[^"'\\s<>]+\.mp4[^"'\\s<>]*)/gi;
              for (const match of html.matchAll(regex)) {
                push(match[0] || "");
              }

              const looseMp4Regex = /https?:\/\/[^"'\\s<>]+\.mp4[^"'\\s<>]*/gi;
              for (const match of html.matchAll(looseMp4Regex)) {
                push(match[0] || "");
              }

              return values;
            }
            """
        )
        if not isinstance(urls, list):
            return []
        normalized = [str(url).strip() for url in urls if str(url).strip()]
        return self._normalize_media_urls(normalized, "video")

    async def _wait_for_video_ready(
        self,
        page: Page,
        job: AutomationJob,
        *,
        timeout_ms: int = 480000,
        poll_ms: int = 4000,
    ) -> list[str]:
        elapsed = 0
        while elapsed < timeout_ms:
            blocked_message = await self._detect_content_policy_block(page, "video")
            if blocked_message:
                raise ContentPolicyBlockedError(blocked_message)

            media_urls = self._normalize_media_urls(await super()._extract_media_urls(page, "video"), "video")
            if not media_urls:
                media_urls = await self._extract_ready_video_urls(page)
            if media_urls:
                self._log_job_step(job, f"video_ready_media_detected media_count={len(media_urls)}")
                return media_urls

            state = await self._video_generation_state(page)
            if isinstance(state, dict):
                if state.get("hasVideo") or state.get("htmlHasVideoUrl"):
                    self._log_job_step(job, "video_ready_download_visible")
                    return []
                if state.get("hasDownload"):
                    self._log_job_step(job, "video_download_visible_without_video")
                if state.get("generating"):
                    progress = state.get("progress") or "unknown"
                    self._log_job_step(job, f"video_generation_in_progress progress={progress}")

            await page.wait_for_timeout(poll_ms)
            elapsed += poll_ms
        self._log_job_step(job, "video_ready_timeout")
        return []

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

    async def _open_imagine_video_flow(
        self,
        page: Page,
        prompt: str,
        source_asset_path: str | None,
        video_mode: str,
        *,
        ratio: str | None = None,
        quality: str | None = None,
        duration: int | str | None = None,
    ) -> dict:
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                await page.goto("https://grok.com/imagine", wait_until="domcontentloaded")
                video_mode_button = await self._wait_for_action_button(
                    page,
                    [
                        "[aria-label='Generation mode'] button[role='radio']:has-text('Video')",
                        "[aria-label='Generation mode'] >> text=Video",
                    ],
                    attempts=12,
                    delay_ms=2000,
                )
                if await video_mode_button.get_attribute("aria-checked") != "true":
                    await video_mode_button.click()
                await page.wait_for_timeout(800)
                with suppress(Exception):
                    await self._select_video_submode(page, video_mode)
                if video_mode == "image_to_video":
                    with suppress(Exception):
                        await self._click_composer_video_mode(page)

                if source_asset_path:
                    source_file = Path(source_asset_path)
                    if not source_file.exists():
                        raise RuntimeError(f"Source asset not found: {source_asset_path}")
                    upload_input = await self._first_visible(page, ["input[type='file']"])
                    await upload_input.set_input_files(str(source_file))
                    await page.wait_for_timeout(2000)
                    if video_mode == "image_to_video":
                        with suppress(Exception):
                            await self._click_composer_video_mode(page)
                        with suppress(Exception):
                            await self._select_video_submode(page, video_mode)

                option_state = await self._apply_generation_options(
                    page,
                    ratio=ratio,
                    quality=quality,
                    duration=duration,
                )

                if video_mode == "image_to_video":
                    await self._prepare_image_to_video_form(page, prompt, source_asset_path, reset_page=False)
                    await self._ensure_video_generation_state(page, prompt, source_asset_path)
                else:
                    await self._fill_grok_prompt(page, prompt, edit_mode=False)

                try:
                    submit = await self._find_submit_button(page)
                except RuntimeError as exc:
                    page_url = page.url
                    body_preview = await self._body_preview(page)
                    raise SubmitButtonDisabledError(
                        f"Grok did not render a detectable submit button for {video_mode.replace('_', '-')}. "
                        f"page_url={page_url}. body_preview={body_preview[:300]}"
                    ) from exc
                try:
                    submit = await self._wait_for_enabled_submit_button(
                        page,
                        video_mode.replace("_", "-"),
                        attempts=30 if video_mode == "image_to_video" else 15,
                        delay_ms=1000,
                    )
                except RuntimeError as exc:
                    if video_mode == "image_to_video" and await self._click_submit_fallback(page):
                        await page.wait_for_timeout(1500)
                        blocked_message = await self._detect_content_policy_block(page, "video")
                        if blocked_message:
                            raise ContentPolicyBlockedError(blocked_message) from exc
                        return option_state
                    reason = await self._read_submit_disabled_reason(page)
                    raise SubmitButtonDisabledError(
                        f"Grok did not enable the submit button for {video_mode.replace('_', '-')}. {reason}."
                    ) from exc
                await submit.click(timeout=3000)
                await page.wait_for_timeout(1500)
                blocked_message = await self._detect_content_policy_block(page, "video")
                if blocked_message:
                    raise ContentPolicyBlockedError(blocked_message)
                return option_state
            except SubmitButtonDisabledError as exc:
                last_exc = exc
                if video_mode != "image_to_video" or attempt == 1:
                    raise
                await page.wait_for_timeout(1200)
                continue

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Grok video flow could not be prepared.")

    async def _open_imagine_image_flow(
        self,
        page: Page,
        prompt: str,
        source_asset_path: str | None = None,
        *,
        ratio: str | None = None,
        quality: str | None = None,
    ) -> dict:
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

        option_state = await self._apply_generation_options(
            page,
            ratio=ratio,
            quality=quality,
        )

        await self._fill_grok_prompt(page, prompt, edit_mode=bool(source_asset_path))

        submit_locator = await self._wait_for_enabled_submit_button(page, "image")
        await submit_locator.click(timeout=3000)
        await page.wait_for_timeout(1500)
        blocked_message = await self._detect_content_policy_block(page, "image")
        if blocked_message:
            raise ContentPolicyBlockedError(blocked_message)
        return option_state

    async def _download_file(self, page: Page, profile: Profile, job: AutomationJob, suffix_label: str) -> list[str]:
        download_button = await self._wait_for_action_button(
            page,
            [
                "button[aria-label='Download']",
                "button:has-text('Download')",
            ],
            attempts=24,
            delay_ms=5000,
            policy_target=suffix_label,
        )

        output_dir = profile_storage.output_dir(profile.id)
        for attempt in range(8):
            try:
                async with page.expect_download(timeout=30000) as download_info:
                    await download_button.click()
                download = await download_info.value
            except Exception:  # noqa: BLE001
                blocked_message = await self._detect_content_policy_block(page, suffix_label)
                if blocked_message:
                    raise ContentPolicyBlockedError(blocked_message)
                await page.wait_for_timeout(5000)
                continue

            suggested = download.suggested_filename
            suffix = Path(suggested).suffix.lower()
            if suffix_label == "video" and suffix not in {".mp4", ".webm", ".mov"}:
                with suppress(Exception):
                    await download.cancel()
                await page.wait_for_timeout(3000)
                continue
            target_path = output_dir / f"{job.id}-{suffix_label}-{attempt + 1}{suffix or '.bin'}"
            await download.save_as(str(target_path))
            try:
                if target_path.exists() and target_path.stat().st_size < 1024:
                    continue
            except Exception:
                pass
            return [str(target_path)]
        return []

    async def _download_video_asset(self, page: Page, profile: Profile, job: AutomationJob) -> list[str]:
        try:
            make_video_button = await self._wait_for_action_button(
                page,
                [
                    "button[aria-label='Make video']",
                    "button:has-text('Make video')",
                ],
                policy_target="video",
            )
        except RuntimeError as exc:
            hidden_message = await self._detect_hidden_media_block(page, "video")
            if hidden_message:
                raise ContentPolicyBlockedError(hidden_message) from exc
            raise
        await make_video_button.click()

        try:
            await page.wait_for_url("**/imagine/post/**", timeout=90000)
        except Exception:  # noqa: BLE001
            pass

        return await self._download_file(page, profile, job, "video")

    async def _promote_image_result_to_video(
        self,
        page: Page,
        profile: Profile,
        job: AutomationJob,
        prompt: str,
    ) -> list[str]:
        self._log_job_step(job, "image_result_to_video_start")
        if not await self._click_composer_video_mode(page):
            self._log_job_step(job, "image_result_to_video_no_video_button")
            return []

        await self._fill_grok_prompt(page, prompt, edit_mode=False)
        await self._ensure_video_generation_state(page, prompt)

        submit = await self._wait_for_enabled_submit_button(
            page,
            "image-to-video-second-pass",
            attempts=20,
            delay_ms=1000,
        )
        await submit.click(timeout=3000)
        await page.wait_for_timeout(1500)

        self._log_job_step(job, "image_result_to_video_submitted")
        media_urls = await self._wait_for_video_ready(page, job, timeout_ms=480000)
        if media_urls:
            return media_urls
        media_urls = await asyncio.wait_for(
            self._download_file(page, profile, job, "video"),
            timeout=180,
        )
        if media_urls:
            self._log_job_step(job, f"image_result_to_video_download_done media_count={len(media_urls)}")
            return media_urls

        self._log_job_step(job, "image_result_to_video_wait_media")
        return await asyncio.wait_for(self._wait_for_media(page, "video"), timeout=150)

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
            "requires_live_browser": settings.reuse_live_browser_for_jobs,
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
        if source_asset_path and isinstance(source_asset_path, str) and source_asset_path.startswith("http"):
            source_asset_path = _download_reference_image(source_asset_path, profile.id)
        ratio = provider_payload.get("ratio") or provider_payload.get("aspect_ratio")
        quality = provider_payload.get("quality")
        duration = provider_payload.get("duration")

        if job.target.value == "video":
            video_mode = str(provider_payload.get("video_mode") or "text_to_video")
            prompt_text = self._coerce_image_to_video_prompt(job.prompt) if video_mode == "image_to_video" else job.prompt
            if video_mode in {"text_to_video", "image_to_video"}:
                self._log_job_step(job, f"video_flow_open_start mode={video_mode}")
                option_state = await asyncio.wait_for(
                    self._open_imagine_video_flow(
                        page,
                        prompt_text,
                        source_asset_path if video_mode == "image_to_video" else None,
                        video_mode,
                        ratio=str(ratio) if ratio else None,
                        quality=str(quality) if quality else None,
                        duration=duration,
                    ),
                    timeout=180 if video_mode == "image_to_video" else 150,
                )
                self._log_job_step(job, f"video_flow_submitted mode={video_mode}")
                media_urls: list[str] = []
                media_urls = await self._wait_for_video_ready(
                    page,
                    job,
                    timeout_ms=480000 if video_mode == "image_to_video" else 300000,
                )
                if not media_urls:
                    media_urls = await self._extract_ready_video_urls(page)
                if not media_urls:
                    self._log_job_step(job, "direct_video_download_start")
                    try:
                        media_urls = await asyncio.wait_for(
                            self._download_file(page, profile, job, "video"),
                            timeout=180,
                        )
                    except asyncio.TimeoutError:
                        self._log_job_step(job, "direct_video_download_timeout")
                        media_urls = []
                if not media_urls:
                    self._log_job_step(job, "wait_video_media_start")
                    media_urls = await asyncio.wait_for(
                        self._wait_for_media(page, "video"),
                        timeout=150,
                    )
                if not media_urls and video_mode == "image_to_video":
                    self._log_job_step(job, "image_result_to_video_fallback_start")
                    try:
                        media_urls = await self._promote_image_result_to_video(page, profile, job, prompt_text)
                    except asyncio.TimeoutError:
                        self._log_job_step(job, "image_result_to_video_fallback_timeout")
                        media_urls = []
                    if media_urls:
                        output_dir = profile_storage.output_dir(profile.id)
                        localized: list[str] = []
                        for index, url in enumerate(media_urls, start=1):
                            if not str(url).startswith(("http://", "https://", "data:")):
                                localized.append(str(url))
                                continue
                            target_path = output_dir / f"{job.id}-video-{index}.mp4"
                            if url.startswith("data:"):
                                localized.append(await self._save_data_url(url, target_path))
                            else:
                                localized.append(await self._download_remote_media(page, url, target_path))
                        media_urls = localized
                media_urls = self._normalize_media_urls(media_urls, "video")
                if not media_urls:
                    if video_mode == "image_to_video":
                        raise InvalidVideoOutputError(
                            "Grok did not return a real video file for this image-to-video job. It appears to have stayed in an image flow or only produced image output."
                        )
                    raise InvalidVideoOutputError(
                        "Grok did not return a real video file for this video job."
                    )
                return {
                    "target": job.target.value,
                    "video_mode": video_mode,
                    "source_asset_path": source_asset_path,
                    "ratio": ratio,
                    "quality": quality,
                    "duration": duration,
                    "requested_options": option_state.get("requested", {}),
                    "applied_options": option_state.get("applied", {}),
                    "unapplied_options": option_state.get("unapplied", {}),
                    "media_urls": media_urls,
                }

        option_state = await self._open_imagine_image_flow(
            page,
            job.prompt,
            source_asset_path,
            ratio=str(ratio) if ratio else None,
            quality=str(quality) if quality else None,
        )

        media_urls = await self._wait_for_filtered_media(page, job.target.value)
        media_urls = await self._localize_image_media(page, profile, job, media_urls)
        return {
            "target": job.target.value,
            "source_asset_path": source_asset_path,
            "ratio": ratio,
            "quality": quality,
            "requested_options": option_state.get("requested", {}),
            "applied_options": option_state.get("applied", {}),
            "unapplied_options": option_state.get("unapplied", {}),
            "media_urls": media_urls,
        }


grok_provider = GrokAutomationProvider()
