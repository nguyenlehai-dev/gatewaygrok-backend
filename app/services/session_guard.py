from time import monotonic

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.profile import Profile
from app.services.automation.registry import get_provider
from app.services.browser_runtime import is_debug_port_open
from app.services.settings_service import settings_service

SESSION_READY_CACHE_TTL_SECONDS = 180
_SESSION_READY_CACHE: dict[str, tuple[float, dict]] = {}


def _get_cached_ready_session(profile_id: str) -> dict | None:
    cached = _SESSION_READY_CACHE.get(profile_id)
    if not cached:
        return None
    expires_at, payload = cached
    if monotonic() >= expires_at:
        _SESSION_READY_CACHE.pop(profile_id, None)
        return None
    return payload


def _cache_ready_session(profile_id: str, payload: dict) -> None:
    _SESSION_READY_CACHE[profile_id] = (
        monotonic() + SESSION_READY_CACHE_TTL_SECONDS,
        payload,
    )


def _clear_ready_session(profile_id: str) -> None:
    _SESSION_READY_CACHE.pop(profile_id, None)


async def ensure_profile_session_ready(db: Session, profile: Profile) -> dict:
    provider = get_provider(profile.category)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider not available for category {profile.category.value}",
        )

    cached = _get_cached_ready_session(profile.id)
    if cached and is_debug_port_open(profile.id):
        return cached

    automation_settings = settings_service.get_settings(db).automation
    result = await provider.analyze_session(profile, profile.proxy, automation_settings)
    if result["state"] != "authenticated":
        _clear_ready_session(profile.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Profile session is not ready for automation",
                "session_state": result["state"],
                "summary": result["summary"],
                "indicators": result.get("indicators", []),
            },
        )
    if result.get("requires_live_browser", False) and not result.get("live_browser_connected", False):
        _clear_ready_session(profile.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"{profile.category.value.title()} profile browser must stay open for automation",
                "session_state": result["state"],
                "summary": f"Launch login and keep that {profile.category.value} profile browser open before submitting jobs.",
                "indicators": result.get("indicators", []),
                "requires_live_browser": True,
                "live_browser_connected": False,
            },
        )
    _cache_ready_session(profile.id, result)
    return result
