import base64
import hashlib
import hmac
import json
import time

from app.core.config import settings


class AdminAuthService:
    def _b64encode(self, raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    def _b64decode(self, raw: str) -> bytes:
        padding = "=" * (-len(raw) % 4)
        return base64.urlsafe_b64decode(f"{raw}{padding}".encode("utf-8"))

    def authenticate(self, username: str, password: str) -> bool:
        return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(
            password,
            settings.admin_password,
        )

    def issue_token(self) -> str:
        payload = {
            "sub": settings.admin_username,
            "exp": int(time.time()) + settings.admin_token_ttl_seconds,
        }
        payload_raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(
            settings.admin_token_secret.encode("utf-8"),
            payload_raw,
            hashlib.sha256,
        ).digest()
        return f"{self._b64encode(payload_raw)}.{self._b64encode(signature)}"

    def verify_token(self, token: str) -> dict | None:
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            payload_raw = self._b64decode(encoded_payload)
            signature = self._b64decode(encoded_signature)
        except ValueError:
            return None

        expected_signature = hmac.new(
            settings.admin_token_secret.encode("utf-8"),
            payload_raw,
            hashlib.sha256,
        ).digest()

        if not hmac.compare_digest(signature, expected_signature):
            return None

        payload = json.loads(payload_raw.decode("utf-8"))
        if payload.get("sub") != settings.admin_username:
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload


admin_auth_service = AdminAuthService()
