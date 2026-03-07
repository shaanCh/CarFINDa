"""
URL Security — validation and sanitization for browser navigation.

Prevents SSRF attacks, blocks internal network access, and sanitizes
snapshot content to remove potential prompt injection.

TODO: Expand blocklist and sanitization rules as needed.
"""

import re
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Optional
from urllib.parse import urlparse


@dataclass
class URLCheckResult:
    allowed: bool
    reason: str = ""


# Private/internal IP ranges that should never be navigated to
_BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "169.254.169.254",
}

_BLOCKED_SCHEMES = {"file", "ftp", "data", "javascript"}


def validate_navigation_url(url: str) -> URLCheckResult:
    """Validate that a URL is safe to navigate to.

    Blocks:
    - Non-HTTP(S) schemes
    - Localhost and private IPs (SSRF prevention)
    - Cloud metadata endpoints
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return URLCheckResult(allowed=False, reason="Invalid URL")

    if parsed.scheme not in ("http", "https"):
        return URLCheckResult(
            allowed=False, reason=f"Blocked scheme: {parsed.scheme}"
        )

    hostname = parsed.hostname or ""
    if hostname in _BLOCKED_HOSTS:
        return URLCheckResult(
            allowed=False, reason=f"Blocked host: {hostname}"
        )

    # Check for private IP addresses
    try:
        addr = ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            return URLCheckResult(
                allowed=False, reason=f"Private/internal IP: {hostname}"
            )
    except ValueError:
        pass  # Not an IP address — hostname is fine

    return URLCheckResult(allowed=True)


# Patterns that look like prompt injection attempts in page content
_INJECTION_PATTERNS = [
    re.compile(r"ignore (?:all )?(?:previous |above )?instructions", re.IGNORECASE),
    re.compile(r"you are now", re.IGNORECASE),
    re.compile(r"system:\s*", re.IGNORECASE),
    re.compile(r"<\|(?:im_start|system)\|>", re.IGNORECASE),
]


def sanitize_snapshot(snapshot: str) -> str:
    """Remove potential prompt injection patterns from page snapshot content."""
    result = snapshot
    for pattern in _INJECTION_PATTERNS:
        result = pattern.sub("[FILTERED]", result)
    return result
