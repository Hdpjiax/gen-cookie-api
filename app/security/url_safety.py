import ipaddress
import socket
from urllib.parse import ParseResult, parse_qs, urlencode, urlparse, urlunparse

from app.domain.models import AirlineCode

ALLOWED_HOSTS: dict[AirlineCode, set[str]] = {
    AirlineCode.VIVA: {"www.vivaaerobus.com", "vivaaerobus.com"},
    AirlineCode.VOLARIS: {"www.volaris.com", "volaris.com"},
    AirlineCode.AEROMEXICO: {"www.aeromexico.com", "aeromexico.com"},
    AirlineCode.UNITED: {"www.united.com", "united.com"},
}

SAFE_QUERY_KEYS = {"pnr", "recordLocator", "confirmation", "ticketNumber"}


class UnsafeUrlError(ValueError):
    pass


def sanitize_official_url(url: str, airline: AirlineCode) -> str:
    parsed = urlparse(url)
    _validate_url(parsed, airline)
    safe_query = {
        key: values[-1]
        for key, values in parse_qs(parsed.query, keep_blank_values=False).items()
        if key in SAFE_QUERY_KEYS and values
    }
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path, "", urlencode(safe_query), ""))


def _validate_url(parsed: ParseResult, airline: AirlineCode) -> None:
    if parsed.scheme != "https":
        raise UnsafeUrlError("only_https_urls_allowed")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS[airline]:
        raise UnsafeUrlError("host_not_allowed")
    for ip in _resolve_host(host):
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeUrlError("host_resolves_to_blocked_ip")


def _resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError("host_not_resolvable") from exc
    return [ipaddress.ip_address(info[4][0]) for info in infos]
