import hashlib
import secrets
import time
from collections import defaultdict, deque

from sqlalchemy.orm import Session

from app.models.api_key import ApiKey


class ApiKeyService:
    def __init__(self) -> None:
        self._request_windows: dict[str, deque[float]] = defaultdict(deque)

    def _hash(self, plain_key: str) -> str:
        return hashlib.sha256(plain_key.encode("utf-8")).hexdigest()

    def create(self, db: Session, name: str, rate_limit_per_minute: int, allowed_categories: list[str], notes: str | None):
        plain_key = f"gg_{secrets.token_urlsafe(24)}"
        record = ApiKey(
            name=name,
            key_prefix=plain_key[:12],
            key_hash=self._hash(plain_key),
            rate_limit_per_minute=rate_limit_per_minute,
            allowed_categories=",".join(allowed_categories),
            notes=notes,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record, plain_key

    def verify(self, db: Session, plain_key: str) -> ApiKey | None:
        record = db.query(ApiKey).filter(ApiKey.key_hash == self._hash(plain_key), ApiKey.is_active.is_(True)).first()
        return record

    def allow_request(self, record: ApiKey) -> bool:
        now = time.time()
        queue = self._request_windows[record.id]
        while queue and now - queue[0] >= 60:
            queue.popleft()
        if len(queue) >= record.rate_limit_per_minute:
            return False
        queue.append(now)
        return True

    def parse_categories(self, record: ApiKey) -> list[str]:
        return [item for item in (record.allowed_categories or "").split(",") if item]


api_key_service = ApiKeyService()
