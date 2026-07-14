"""URL safety for ScreenPilot navigation (SSRF + secret-in-URL).

Adapted from Hermes browser url_safety with enterprise OA exceptions:
- Hosts on ScreenSystem.allowed_domains may resolve to private/CGNAT IPs.
- Without an allowlist hit, private/loopback/link-local/metadata are blocked.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "metadata.goog",
})

_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_METADATA_IPS = frozenset({
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
})

# Common API key / token shapes that must never appear in navigate URLs.
_SECRET_IN_URL_RE = re.compile(
    r"(?:"
    r"sk-[a-zA-Z0-9_\-]{16,}"
    r"|sk-ant-[a-zA-Z0-9_\-]{16,}"
    r"|sk-proj-[a-zA-Z0-9_\-]{16,}"
    r"|ghp_[a-zA-Z0-9]{20,}"
    r"|gho_[a-zA-Z0-9]{20,}"
    r"|xox[baprs]-[a-zA-Z0-9\-]{10,}"
    r"|AIza[0-9A-Za-z_\-]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ya29\.[0-9A-Za-z_\-]{20,}"
    r"|eyJ[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{10,}"
    r"|Bearer%20[A-Za-z0-9\._\-]{20,}"
    r"|access_token=[^&\s]{16,}"
    r"|api[_-]?key=[^&\s]{16,}"
    r"|secret=[^&\s]{12,}"
    r"|password=[^&\s]{6,}"
    r")",
    re.IGNORECASE,
)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip in _METADATA_IPS:
        return True
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return True
    if ip.is_multicast or ip.is_unspecified:
        return True
    if ip in _CGNAT_NETWORK:
        return True
    return False


def url_contains_secret(url: str) -> bool:
    return bool(_SECRET_IN_URL_RE.search(url or ""))


def host_in_allowlist(hostname: str, allowed_domains: List[str]) -> bool:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    for domain in allowed_domains or []:
        d = (domain or "").strip().lower().rstrip(".")
        if not d:
            continue
        if host == d or host.endswith("." + d):
            return True
    return False


def check_url_safety(
    url: str,
    *,
    allowed_domains: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """Return (ok, reason). Fail-closed on parse/DNS errors."""
    raw = (url or "").strip()
    if not raw:
        return False, "URL 为空"

    if url_contains_secret(raw):
        return False, "URL 疑似包含密钥/令牌，已拦截导航"

    try:
        parsed = urlparse(raw)
    except Exception as exc:
        return False, f"URL 解析失败: {exc}"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"仅允许 http/https，收到 scheme={scheme or '(empty)'}"

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "URL 缺少主机名"

    if hostname in _BLOCKED_HOSTNAMES:
        return False, f"拦截云 metadata 主机: {hostname}"

    # Literal IP in URL
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    allowlisted = host_in_allowlist(hostname, allowed_domains or [])

    if literal_ip is not None:
        if literal_ip in _METADATA_IPS:
            return False, f"拦截 metadata 地址: {hostname}"
        if _is_blocked_ip(literal_ip) and not allowlisted:
            return False, f"拦截私网/内网地址（未在白名单）: {hostname}"
        return True, ""

    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        logger.warning("Blocked navigate — DNS failed for %s", hostname)
        return False, f"DNS 解析失败，已拦截: {hostname}"
    except Exception as exc:
        logger.warning("Blocked navigate — DNS error for %s: %s", hostname, exc)
        return False, f"DNS 检查异常，已拦截: {hostname}"

    for _family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip in _METADATA_IPS:
            return False, f"拦截解析到 metadata 的主机: {hostname} -> {ip_str}"
        if _is_blocked_ip(ip) and not allowlisted:
            logger.warning("Blocked private navigate: %s -> %s", hostname, ip_str)
            return False, f"拦截私网/内网地址（未在白名单）: {hostname} -> {ip_str}"

    return True, ""
