"""
Facebook Login Flow — Automated credential-based login for Facebook Marketplace.

The user provides their FB credentials (email + password) via environment
variables or direct parameters. This module handles the full login flow:

1. Navigate to facebook.com/login
2. Find and fill email/password fields
3. Click Log In
4. Handle 2FA if the user's account requires it
5. Verify login success

Uses the sidecar's persistent browser profile ('carfinda-fb') so cookies
persist across sessions — login only needs to happen once until cookies expire.
"""

import asyncio
import logging
import re
from typing import Optional

from app.config import get_settings
from app.services.scraping.browser_client import BrowserClient

logger = logging.getLogger(__name__)

FB_LOGIN_URL = "https://www.facebook.com/login"
FB_HOME_URL = "https://www.facebook.com/"

# Snapshot patterns for Facebook login form elements
_EMAIL_PATTERNS = [
    re.compile(r'textbox\s+"[^"]*[Ee]mail[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'textbox\s+"[^"]*[Pp]hone[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'textbox\s+"[^"]*[Ee]mail or phone[^"]*"\s+\[ref=(e\d+)\]', re.IGNORECASE),
    re.compile(r'textbox\s+\[ref=(e\d+)\]'),  # unnamed textbox fallback
]

_PASSWORD_PATTERNS = [
    re.compile(r'textbox\s+"[^"]*[Pp]ass(?:word)?[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'\[ref=(e\d+)\][^\n]*\[type="password"\]', re.IGNORECASE),
    re.compile(r'textbox\s+\[ref=(e\d+)\][^\n]*password', re.IGNORECASE),
]

_LOGIN_BUTTON_PATTERNS = [
    re.compile(r'button\s+"[^"]*[Ll]og\s*[Ii]n[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Ss]ign\s*[Ii]n[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Cc]ontinue[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Ss]ubmit[^"]*"\s+\[ref=(e\d+)\]'),
]

# 2FA detection
_2FA_INDICATORS = [
    "two-factor", "2fa", "authentication code", "code generator",
    "enter the code", "security code", "login code", "approvals code",
    "code from your", "check your email", "sent a code", "6-digit",
    "confirm your identity", "enter the 6",
]

_CODE_FIELD_PATTERNS = [
    re.compile(r'textbox\s+"[^"]*[Cc]ode[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'textbox\s+"[^"]*[Vv]erif[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'textbox\s+\[ref=(e\d+)\][^\n]*code', re.IGNORECASE),
    re.compile(r'textbox\s+\[ref=(e\d+)\][^\n]*digit', re.IGNORECASE),
    re.compile(r'textbox\s+\[ref=(e\d+)\]'),  # single textbox fallback for 2FA page
]

_SUBMIT_PATTERNS = [
    re.compile(r'button\s+"[^"]*[Cc]ontinue[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Ss]ubmit[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Ss]end[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Vv]erify[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Nn]ext[^"]*"\s+\[ref=(e\d+)\]'),
    re.compile(r'button\s+"[^"]*[Ll]og\s*[Ii]n[^"]*"\s+\[ref=(e\d+)\]'),
]

# CAPTCHA indicators
_CAPTCHA_INDICATORS = [
    "captcha", "solve this puzzle", "verify you are human",
    "security check", "i'm not a robot", "recaptcha", "hcaptcha",
    "suspicious activity", "automated", "unusual login",
]

# Logged-in indicators (seen on FB home when logged in)
_LOGGED_IN_INDICATORS = [
    "marketplace", "messenger", "notifications", "what's on your mind",
    "create post", "news feed", "friends", "groups",
]


def _find_ref(snapshot: str, patterns: list[re.Pattern]) -> Optional[str]:
    """Find the first matching element ref in a snapshot."""
    for pattern in patterns:
        match = pattern.search(snapshot)
        if match:
            return match.group(1)
    return None


def _has_captcha(snapshot: str) -> bool:
    lower = snapshot.lower()
    return any(ind in lower for ind in _CAPTCHA_INDICATORS)


def _has_2fa(snapshot: str) -> bool:
    lower = snapshot.lower()
    return any(ind in lower for ind in _2FA_INDICATORS)


def _is_logged_in(snapshot: str) -> bool:
    lower = snapshot.lower()
    login_form_indicators = ["log in", "log into", "create new account", "sign up"]
    login_score = sum(1 for ind in login_form_indicators if ind in lower)
    logged_in_score = sum(1 for ind in _LOGGED_IN_INDICATORS if ind in lower)
    return logged_in_score > login_score


async def facebook_login(
    browser: BrowserClient,
    profile: str = "carfinda-fb",
    email: Optional[str] = None,
    password: Optional[str] = None,
) -> dict:
    """
    Log into Facebook using provided or configured credentials.

    Args:
        browser:  BrowserClient instance connected to the sidecar.
        profile:  Browser profile name (persistent cookies).
        email:    Facebook email/phone. Falls back to FB_EMAIL env var.
        password: Facebook password. Falls back to FB_PASSWORD env var.

    Returns:
        dict with keys:
            success (bool)  — True if login succeeded.
            message (str)   — Human-readable status.
            needs_2fa (bool) — True if 2FA is required (user must provide code).
    """
    # Resolve credentials
    settings = get_settings()
    email = email or settings.FB_EMAIL
    password = password or settings.FB_PASSWORD

    if not email or not password:
        return {
            "success": False,
            "message": "Facebook credentials not provided. Set FB_EMAIL and FB_PASSWORD in .env.",
            "needs_2fa": False,
        }

    # Start browser session
    await browser.start_session(profile)

    # Check if already logged in
    try:
        result = await browser.navigate(profile, FB_HOME_URL)
        snapshot = result.get("snapshot", "")
        if _is_logged_in(snapshot):
            logger.info("Already logged into Facebook")
            return {
                "success": True,
                "message": "Already logged in to Facebook.",
                "needs_2fa": False,
            }
    except Exception as exc:
        logger.warning("Failed to check existing login: %s", exc)

    # Navigate to login page
    try:
        result = await browser.navigate(profile, FB_LOGIN_URL)
        snapshot = result.get("snapshot", "")
    except Exception as exc:
        return {
            "success": False,
            "message": f"Failed to navigate to Facebook login: {exc}",
            "needs_2fa": False,
        }

    if not snapshot.strip():
        return {
            "success": False,
            "message": "Empty page snapshot from Facebook login page.",
            "needs_2fa": False,
        }

    # Find email field
    email_ref = _find_ref(snapshot, _EMAIL_PATTERNS)
    if not email_ref:
        logger.error("Could not find email field on Facebook login page")
        return {
            "success": False,
            "message": "Could not find email field on the login page.",
            "needs_2fa": False,
        }

    # Find password field
    password_ref = _find_ref(snapshot, _PASSWORD_PATTERNS)

    # Find login button
    login_ref = _find_ref(snapshot, _LOGIN_BUTTON_PATTERNS)

    logger.info(
        "FB login refs: email=%s password=%s login=%s",
        email_ref, password_ref, login_ref,
    )

    # Fill email
    try:
        await browser.act(profile, "click", ref=email_ref)
        await asyncio.sleep(0.3)
        await browser.act(profile, "type", ref=email_ref, text=email)
        await asyncio.sleep(0.3)
    except Exception as exc:
        return {
            "success": False,
            "message": f"Failed to fill email field: {exc}",
            "needs_2fa": False,
        }

    # Fill password (Facebook shows both fields on same page)
    if password_ref:
        try:
            await browser.act(profile, "click", ref=password_ref)
            await asyncio.sleep(0.3)
            await browser.act(profile, "type", ref=password_ref, text=password)
            await asyncio.sleep(0.3)
        except Exception as exc:
            return {
                "success": False,
                "message": f"Failed to fill password field: {exc}",
                "needs_2fa": False,
            }
    else:
        # Multi-step: submit email first, then look for password
        if login_ref:
            await browser.act(profile, "click", ref=login_ref)
        else:
            await browser.act(profile, "press", key="Enter")
        await asyncio.sleep(3.0)

        snapshot = await browser.snapshot(profile)
        password_ref = _find_ref(snapshot, _PASSWORD_PATTERNS)
        if not password_ref:
            # Try unnamed textbox as fallback
            password_ref = _find_ref(snapshot, [re.compile(r'textbox\s+\[ref=(e\d+)\]')])

        if not password_ref:
            return {
                "success": False,
                "message": "Could not find password field after submitting email.",
                "needs_2fa": False,
            }

        login_ref = _find_ref(snapshot, _LOGIN_BUTTON_PATTERNS)

        await browser.act(profile, "click", ref=password_ref)
        await asyncio.sleep(0.3)
        await browser.act(profile, "type", ref=password_ref, text=password)
        await asyncio.sleep(0.3)

    # Click Login button (or press Enter)
    if login_ref:
        await browser.act(profile, "click", ref=login_ref)
    else:
        await browser.act(profile, "press", key="Enter")

    # Wait for login to process
    await asyncio.sleep(4.0)

    # Check result
    snapshot = await browser.snapshot(profile)

    # Check for CAPTCHA
    if _has_captcha(snapshot):
        logger.warning("CAPTCHA detected during Facebook login")
        solved = await browser.solve_captcha_if_present(profile)
        if solved:
            await asyncio.sleep(3.0)
            snapshot = await browser.snapshot(profile)
        else:
            return {
                "success": False,
                "message": "CAPTCHA detected during login. Could not solve automatically.",
                "needs_2fa": False,
            }

    # Check for 2FA
    if _has_2fa(snapshot):
        logger.info("Facebook 2FA detected")
        return {
            "success": False,
            "message": (
                "Two-factor authentication required. "
                "Call facebook_submit_2fa() with the code from your authenticator app or SMS."
            ),
            "needs_2fa": True,
        }

    # Check for wrong credentials
    error_indicators = [
        "incorrect password", "wrong password", "doesn't match",
        "not match", "try again", "find your account",
        "the password that you've entered is incorrect",
    ]
    lower = snapshot.lower()
    if any(ind in lower for ind in error_indicators):
        return {
            "success": False,
            "message": "Login failed: incorrect email or password.",
            "needs_2fa": False,
        }

    # Check if login succeeded
    if _is_logged_in(snapshot):
        logger.info("Facebook login successful")
        return {
            "success": True,
            "message": "Successfully logged into Facebook.",
            "needs_2fa": False,
        }

    # Ambiguous — may have succeeded (redirect in progress, etc.)
    # Try navigating to home to confirm
    await asyncio.sleep(2.0)
    try:
        result = await browser.navigate(profile, FB_HOME_URL)
        snapshot = result.get("snapshot", "")
        if _is_logged_in(snapshot):
            logger.info("Facebook login confirmed after redirect")
            return {
                "success": True,
                "message": "Successfully logged into Facebook.",
                "needs_2fa": False,
            }
    except Exception:
        pass

    return {
        "success": False,
        "message": "Login status unclear. Check the browser session manually.",
        "needs_2fa": False,
    }


async def facebook_submit_2fa(
    browser: BrowserClient,
    code: str,
    profile: str = "carfinda-fb",
) -> dict:
    """
    Submit a 2FA code to complete Facebook login.

    Call this after facebook_login() returns needs_2fa=True.

    Args:
        browser: BrowserClient instance.
        code:    The 6-digit 2FA code from authenticator app or SMS.
        profile: Browser profile name.

    Returns:
        dict with keys: success (bool), message (str).
    """
    snapshot = await browser.snapshot(profile)

    # Find the code input field
    code_ref = _find_ref(snapshot, _CODE_FIELD_PATTERNS)
    if not code_ref:
        return {
            "success": False,
            "message": "Could not find the 2FA code input field.",
        }

    # Fill the code
    await browser.act(profile, "click", ref=code_ref)
    await asyncio.sleep(0.3)
    await browser.act(profile, "type", ref=code_ref, text=code)
    await asyncio.sleep(0.3)

    # Find and click submit
    submit_ref = _find_ref(snapshot, _SUBMIT_PATTERNS)
    if submit_ref:
        await browser.act(profile, "click", ref=submit_ref)
    else:
        await browser.act(profile, "press", key="Enter")

    # Wait and verify
    await asyncio.sleep(4.0)
    snapshot = await browser.snapshot(profile)

    if _is_logged_in(snapshot):
        logger.info("Facebook 2FA verification successful")
        return {
            "success": True,
            "message": "2FA verified. Successfully logged into Facebook.",
        }

    # Try navigating home to confirm
    try:
        result = await browser.navigate(profile, FB_HOME_URL)
        snapshot = result.get("snapshot", "")
        if _is_logged_in(snapshot):
            return {
                "success": True,
                "message": "2FA verified. Successfully logged into Facebook.",
            }
    except Exception:
        pass

    # Check for error
    lower = snapshot.lower()
    if "incorrect" in lower or "invalid" in lower or "try again" in lower:
        return {
            "success": False,
            "message": "Invalid 2FA code. Please try again.",
        }

    return {
        "success": False,
        "message": "2FA verification status unclear. Check browser session.",
    }
