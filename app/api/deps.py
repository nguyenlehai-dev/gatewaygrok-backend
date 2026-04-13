from collections.abc import Generator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.services.admin_auth import admin_auth_service
from app.services.api_key_service import api_key_service


def db_session(db: Session = Depends(get_db)) -> Generator[Session, None, None]:
    yield db


def require_api_key(
    api_key: str | None = Header(default=None, alias=settings.api_key_header),
    db: Session = Depends(get_db),
) -> ApiKey:
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")

    record = api_key_service.verify(db, api_key)
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    if not api_key_service.allow_request(record):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")

    return record


def require_admin(
    authorization: str | None = Header(default=None),
):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing admin token")

    token = authorization.split(" ", 1)[1].strip()
    payload = admin_auth_service.verify_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")

    return payload
