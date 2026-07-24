import pytest

from app.domain.models import AirlineCode
from app.security.url_safety import UnsafeUrlError, sanitize_official_url


def test_sanitizes_allowed_official_url() -> None:
    url = sanitize_official_url(
        "https://www.united.com/foo?confirmation=ABC123&token=secret#frag",
        AirlineCode.UNITED,
    )
    assert url == "https://www.united.com/foo?confirmation=ABC123"


def test_rejects_wrong_host() -> None:
    with pytest.raises(UnsafeUrlError):
        sanitize_official_url("https://evil.example/foo?pnr=ABC123", AirlineCode.VIVA)


def test_rejects_non_https() -> None:
    with pytest.raises(UnsafeUrlError):
        sanitize_official_url("http://www.volaris.com/foo?pnr=ABC123", AirlineCode.VOLARIS)
