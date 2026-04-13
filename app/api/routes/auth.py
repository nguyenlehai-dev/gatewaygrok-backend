from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.schemas.auth import AdminAuthResponse, AdminLoginRequest, AdminUserRead
from app.services.admin_auth import admin_auth_service

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=AdminAuthResponse)
def admin_login(payload: AdminLoginRequest):
    if not admin_auth_service.authenticate(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials")

    return AdminAuthResponse(
        access_token=admin_auth_service.issue_token(),
        expires_in=settings.admin_token_ttl_seconds,
        username=settings.admin_username,
    )


@router.get("/bootstrap", response_model=AdminUserRead)
def auth_bootstrap():
    return AdminUserRead(username=settings.admin_username)
