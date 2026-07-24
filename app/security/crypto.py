import base64
import hashlib
import hmac

from app.config import settings


def encrypt_for_storage(value: str | None) -> str | None:
    if value is None:
        return None
    digest = hmac.new(
        settings.app_secret_pepper.encode(), value.strip().upper().encode(), hashlib.sha256
    ).digest()
    return "enc:" + base64.urlsafe_b64encode(digest).decode().rstrip("=")
