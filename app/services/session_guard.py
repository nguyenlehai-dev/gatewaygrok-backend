from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.profile import Profile
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
    result = await provider.analyze_session(profile, profile.proxy, automation_settings)
    if result["state"] != "authenticated":
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
    return result
