import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit

from app.errors import AppError

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443, 8080, 8443}
HOST_PATTERN = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*")


def _invalid(message: str = "The URL is not valid.") -> AppError:
    return AppError("invalid_url", message, 400)


def normalize_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value or any(ch.isspace() for ch in value):
        raise _invalid("The URL is empty or contains whitespace.")
    if "://" not in value:
        value = "https://" + value
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise _invalid()
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise AppError("invalid_scheme", "Only http and https URLs are supported.", 400)
    if parts.username or parts.password:
        raise _invalid("URLs with embedded credentials are not allowed.")
    host = parts.hostname
    if not host:
        raise _invalid("The URL has no host name.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise _invalid("The host name is not valid.")
        if len(host) > 253 or not HOST_PATTERN.fullmatch(host):
            raise _invalid("The host name is not valid.")
    if port not in ALLOWED_PORTS:
        raise AppError("blocked_port", "Only ports 80, 443, 8080 and 8443 are allowed.", 400)
    netloc = f"[{host}]" if ":" in host else host
    if port:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


async def resolve_host(host: str, port: int) -> list[str]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise AppError("unresolvable_host", f"The host '{host}' could not be resolved.", 400)
    return sorted({info[4][0].split("%")[0] for info in infos})


async def validate_url(raw: str) -> str:
    url = normalize_url(raw)
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    addresses = await resolve_host(parts.hostname, port)
    if not addresses or not all(is_public_ip(address) for address in addresses):
        raise AppError(
            "blocked_address",
            "The URL points to a private, internal or reserved network address and cannot be analysed.",
            400,
        )
    return url


async def domain_resolves(host: str) -> bool:
    try:
        return bool(await resolve_host(host, 443))
    except AppError:
        return False
