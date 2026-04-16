import asyncio
from fastapi import HTTPException, status

from app.core.config import settings
from sqlalchemy.orm import Session

from app.models.profile import Profile
from app.services.browser_runtime import launch_profile_browser, stop_profile_browser, wait_for_debug_port
from app.services.automation.registry import get_provider
from app.services.settings_service import settings_service


async def ensure_profile_session_ready(db: Session, profile: Profile) -> dict:
    provider = get_provider(profile.category)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider not available for category {profile.category.value}",
        )

    automation_settings = settings_service.get_settings(db).automation
    launched_live_browser = False

    async def _analyze():
        return await provider.analyze_session(profile, profile.proxy, automation_settings)

    try:
        result = await _analyze()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Profile session check failed",
                "error": str(exc),
            },
        )

    async def _retry_unknown_session(current_result: dict) -> dict:
        # Grok can render an empty shell for a few seconds right after a warm
        # browser connects. Do not cool down a valid profile on that first pass.
        if current_result.get("state") != "unknown":
            return current_result
        if current_result.get("indicators"):
            return current_result
        for delay_seconds in [2, 4, 8]:
            await asyncio.sleep(delay_seconds)
            try:
                retry_result = await _analyze()
            except Exception:
                continue
            if retry_result.get("state") != "unknown" or retry_result.get("indicators"):
                return retry_result
            current_result = retry_result
        return current_result

    result = await _retry_unknown_session(result)

    if result["state"] != "authenticated" and not result.get("live_browser_connected", False):
        launched_live_browser = launch_profile_browser(profile.id)
        if launched_live_browser and wait_for_debug_port(profile.id, timeout_seconds=settings.live_browser_start_timeout_seconds):
            retry_delays = [0, 3, 6, 10]
            for delay_seconds in retry_delays:
                if delay_seconds:
                    await asyncio.sleep(delay_seconds)
                try:
                    result = await _analyze()
                except Exception as exc:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "message": "Profile session check failed after launching browser",
                            "error": str(exc),
                        },
                    )
                if result.get("state") == "authenticated":
                    break

    result = await _retry_unknown_session(result)

    if result["state"] != "authenticated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Profile session is not ready for automation",
                "session_state": result["state"],
                "summary": result["summary"],
                "indicators": result.get("indicators", []),
                "live_browser_launched": launched_live_browser,
                "live_browser_connected": result.get("live_browser_connected", False),
            },
        )
    if result.get("requires_live_browser", False) and not result.get("live_browser_connected", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"{profile.category.value.title()} profile browser must stay open for automation",
                "session_state": result["state"],
                "summary": f"Launch login and keep that {profile.category.value} profile browser open before submitting jobs.",
                "indicators": result.get("indicators", []),
                "requires_live_browser": True,
                "live_browser_connected": False,
                "live_browser_launched": launched_live_browser,
            },
        )

    if launched_live_browser and not automation_settings.headless and settings.reuse_live_browser_for_jobs:
        return result
    if launched_live_browser and not settings.reuse_live_browser_for_jobs:
        stop_profile_browser(profile.id)
    return result
