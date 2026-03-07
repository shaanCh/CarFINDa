"""
Login Detection Patterns

Regex patterns and helper functions for detecting form fields, CAPTCHAs,
and 2FA prompts in Playwright AI snapshots during browser login flows.
"""

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password field patterns
#
# Sidecar snapshot format: role "name" [ref=eN] [suffix]:
#   - Ref comes immediately after the name
#   - Empty names are stripped (no quotes at all, not even "")
#   - Suffix attributes (e.g. [cursor=pointer]) come after ref
# ---------------------------------------------------------------------------
PASSWORD_PATTERNS = [
    # Named textbox/input with "password" in label
    re.compile(r'textbox\s+"[^"]*[Pp]ass(?:word|phrase|code)[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'input\s+"[^"]*[Pp]ass(?:word|phrase|code)[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(
        r'(?:textbox|input)\s+"[^"]*password[^"]*"\s+\[ref=(e\d+)\]',
        re.IGNORECASE,
    ),
    # Suffix contains [type="password"] (appears after ref)
    re.compile(r'\[ref=(e\d+)\][^\n]*\[type="password"\]', re.IGNORECASE),
    # Nameless textbox with "password" on same line (after ref in suffix)
    re.compile(r"textbox\s+\[ref=(e\d+)\][^\n]*password", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Submit / continue button patterns
# ---------------------------------------------------------------------------
SUBMIT_PATTERNS = [
    re.compile(r'button\s+"[^"]*[Ss]ign[- ]?[Ii]n[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Ll]og[- ]?[Ii]n[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Cc]ontinue[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Nn]ext[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Ss]ubmit[^"]*"\s+\[ref=(e\d+)\]'),
]

# ---------------------------------------------------------------------------
# CAPTCHA indicators (includes Amazon image-puzzle variants)
# ---------------------------------------------------------------------------
CAPTCHA_INDICATORS = [
    "captcha",
    "solve this puzzle",
    "verify you are human",
    "security check",
    "i'm not a robot",
    "recaptcha",
    "hcaptcha",
    "type the characters",
    "characters you see",
    "enter the characters",
    "characters in the image",
    "image below",
    "bot check",
    "automated access",
    "unusual activity",
]

# ---------------------------------------------------------------------------
# 2FA indicators
# ---------------------------------------------------------------------------
TOTP_2FA_INDICATORS = [
    "authenticator app",
    "authentication app",
    "authenticator code",
    "enter.*6.*digit",
    "enter.*code.*authenticator",
    "two-factor",
    "2-step verification",
    "totp",
    "one-time password",
    "security key or authenticator",
]

EMAIL_2FA_INDICATORS = [
    r"sent.*code.*email",
    r"check your email",
    r"emailed.*code",
    r"sent.*verification",
    r"code.*inbox",
    r"verification code.*sent",
    r"we sent.*code",
    r"enter.*code.*we.*sent",
]

# ---------------------------------------------------------------------------
# Code input field patterns
# ---------------------------------------------------------------------------
CODE_FIELD_PATTERNS = [
    re.compile(r'textbox\s+"[^"]*[Cc]ode[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'textbox\s+"[^"]*[Vv]erif[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'textbox\s+"[^"]*[Oo][Tt][Pp][^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'textbox\s+"[^"]*\d.*digit[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'input\s+"[^"]*[Cc]ode[^"]*"\s+\[ref=(e\d+)\]'),
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def find_ref(snapshot: str, patterns: list[re.Pattern]) -> Optional[str]:
    """Find the first matching element ref in a snapshot."""
    for pattern in patterns:
        match = pattern.search(snapshot)
        if match:
            return match.group(1)
    return None


def has_captcha(snapshot: str) -> bool:
    """Check if the snapshot contains CAPTCHA indicators."""
    lower = snapshot.lower()
    return any(indicator in lower for indicator in CAPTCHA_INDICATORS)


def detect_2fa_type(snapshot: str) -> Optional[str]:
    """Detect 2FA prompt type from snapshot. Returns 'totp', 'email', or None."""
    lower = snapshot.lower()
    for pattern in TOTP_2FA_INDICATORS:
        if re.search(pattern, lower):
            return "totp"
    for pattern in EMAIL_2FA_INDICATORS:
        if re.search(pattern, lower):
            return "email"
    return None


def find_code_field(snapshot: str) -> Optional[str]:
    """Find the verification code input field ref."""
    return find_ref(snapshot, CODE_FIELD_PATTERNS)


# Patterns to find refs in snapshot (for fallback detection)
# Textbox-specific (preferred)
_TEXTBOX_WITH_NAME_RE = re.compile(r'(?:textbox|input)\s+"([^"]*)"\s+\[ref=(e\d+)\]')
_TEXTBOX_NO_NAME_RE = re.compile(r"(?:textbox|input)\s+\[ref=(e\d+)\]")
# Any element with a ref (role-agnostic) — captures (role, name, ref)
_ANY_REF_RE = re.compile(r"(\w+)(?:\s+\"([^\"]*)\")?\s+\[ref=(e\d+)\]")
# Roles that are never fillable password fields
_NON_FILLABLE_ROLES = frozenset(
    {"link", "button", "heading", "img", "navigation", "banner", "list", "listitem"}
)


def find_password_field_fallback(snapshot: str) -> Optional[str]:
    """Last-resort password field detection.

    Some sites render password inputs as non-textbox roles (e.g. ``generic``)
    in the accessibility tree. This fallback handles three tiers:

    1. Look for textbox/input elements near "password" text
    2. Look for ANY ref near "password" text (excluding links/buttons/headings)
    3. Single textbox on page = probably the password field
    """
    # --- Tier 1: textbox/input elements ---
    textboxes: list[tuple[str, str]] = _TEXTBOX_WITH_NAME_RE.findall(snapshot)
    for m in _TEXTBOX_NO_NAME_RE.finditer(snapshot):
        ref = m.group(1)
        if not any(r == ref for _, r in textboxes):
            textboxes.append(("", ref))

    if textboxes:
        logger.info(
            "[BrowserLogin] Fallback: found %d textbox(es): %s",
            len(textboxes),
            [(label[:30], ref) for label, ref in textboxes],
        )

    lower = snapshot.lower()

    # Tier 1a: textbox near "password" text
    for label, ref in textboxes:
        if _ref_near_password(lower, ref):
            logger.info("[BrowserLogin] Fallback: textbox %s near 'password'", ref)
            return ref

    # --- Tier 2: any ref near "password" text (role-agnostic) ---
    for m in _ANY_REF_RE.finditer(snapshot):
        role, _name, ref = m.group(1), m.group(2) or "", m.group(3)
        if role.lower() in _NON_FILLABLE_ROLES:
            continue
        if _ref_near_password(lower, ref):
            logger.info("[BrowserLogin] Fallback: %s %s near 'password'", role, ref)
            return ref

    # --- Tier 3: single textbox = probably password ---
    if len(textboxes) == 1:
        ref = textboxes[0][1]
        logger.info("[BrowserLogin] Fallback: single textbox %s", ref)
        return ref

    logger.info(
        "[BrowserLogin] Fallback: no password field in snapshot (len=%d). "
        "First 500 chars: %.500s",
        len(snapshot),
        snapshot.replace("\n", " ")[:500],
    )
    return None


def _ref_near_password(lower_snapshot: str, ref: str, window: int = 200) -> bool:
    """Check if 'password' appears within ``window`` chars of [ref=eN]."""
    ref_pos = lower_snapshot.find(f"[ref={ref}]")
    if ref_pos < 0:
        return False
    start = max(0, ref_pos - window)
    end = min(len(lower_snapshot), ref_pos + window)
    return "password" in lower_snapshot[start:end]


async def try_solve_captcha(gateway: Any, user_id: str, page_url: str) -> bool:
    """Attempt to auto-solve a CAPTCHA on the current page via CapSolver/2Captcha.

    Returns True if solved and token injected, False otherwise.
    """
    from app.services.browser.captcha_solver import get_captcha_solver

    solver = get_captcha_solver()
    if not solver:
        logger.info(
            "[BrowserLogin] CAPTCHA solver not configured — skipping auto-solve at %s",
            page_url,
        )
        return False

    async def evaluate_js(script: str, *args: Any) -> Any:
        """Run JS on the active browser page via the gateway."""
        result = await gateway.execute_action(
            user_id=user_id,
            action="evaluate",
            args={"script": script, "args": list(args)},
            target="host",
            origin="browser.captcha",
        )
        # Gateway wraps sidecar response: {"ok": True, "result": {"ok": True, "result": <value>}}
        if isinstance(result, dict):
            inner = result.get("result", {})
            if isinstance(inner, dict):
                return inner.get("result")
        return None

    try:
        token = await solver.detect_and_solve(
            page_url=page_url, evaluate_js=evaluate_js
        )
        if token:
            logger.info("[BrowserLogin] CAPTCHA solved at %s", page_url)
            return True
        logger.info("[BrowserLogin] No solvable CAPTCHA found at %s", page_url)
        return False
    except Exception as e:
        logger.warning("[BrowserLogin] CAPTCHA solve error at %s: %s", page_url, e)
        return False


def sanitize_error(error_msg: str, username: str, password: str) -> str:
    """Strip credential values from Playwright error messages."""
    from urllib.parse import quote

    sanitized = error_msg.replace(password, "[REDACTED]")
    sanitized = sanitized.replace(username, "[EMAIL]")
    sanitized = sanitized.replace(quote(password), "[REDACTED]")
    sanitized = sanitized.replace(quote(username), "[EMAIL]")
    return sanitized
