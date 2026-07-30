import base64
import hashlib
import hmac

from app.config import settings


def encrypt_for_storage(value: str | None) -> str | None:
    if value is None:
        return None
    key = settings.app_secret_pepper or "default_key"
    val_bytes = value.strip().upper().encode()
    key_bytes = key.encode()
    xored = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(val_bytes))
    return "enc:" + base64.urlsafe_b64encode(xored).decode().rstrip("=")


def decrypt_from_storage(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.startswith("enc:"):
        return value
    try:
        key = settings.app_secret_pepper or "default_key"
        val_str = value[4:]
        val_str += "=" * ((4 - len(val_str) % 4) % 4)
        xored = base64.urlsafe_b64decode(val_str.encode())
        key_bytes = key.encode()
        decrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(xored))
        return decrypted.decode()
    except Exception:
        return value
