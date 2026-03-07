"""
Browser Client — Async HTTP wrapper for the Playwright sidecar API.

Provides a clean Python interface over the sidecar's REST endpoints for
browser automation: starting sessions, navigating, taking snapshots and
screenshots, and performing page interactions (click, type, scroll, etc.).
"""

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Default timeout for sidecar HTTP requests (seconds).
# Navigation and act calls can be slow due to page loads.
DEFAULT_TIMEOUT = 60.0


class BrowserClient:
    """Async HTTP client wrapping the sidecar browser API."""

    def __init__(self, base_url: str, token: str = ""):
        """
        Args:
            base_url: The sidecar base URL, e.g. "http://localhost:3000".
            token:    Bearer token for sidecar auth (empty = no auth in dev).
        """
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(DEFAULT_TIMEOUT, connect=10.0),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_session(self, profile: str) -> None:
        """Start a browser session for the given profile.

        Idempotent — if a browser is already running for this profile,
        the sidecar simply returns ok.
        """
        resp = await self._client.post("/start", params={"profile": profile})
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Failed to start browser session: {data}")
        logger.debug("Browser session started for profile=%s", profile)

    async def stop_session(self, profile: str) -> None:
        """Stop the browser session for the given profile."""
        try:
            resp = await self._client.post("/stop", params={"profile": profile})
            resp.raise_for_status()
            logger.debug("Browser session stopped for profile=%s", profile)
        except httpx.HTTPError as exc:
            logger.warning("Failed to stop browser session for %s: %s", profile, exc)

    # ------------------------------------------------------------------
    # Navigation & Content
    # ------------------------------------------------------------------

    async def navigate(self, profile: str, url: str) -> dict[str, Any]:
        """Navigate to *url* and return page info with an AI-readable snapshot.

        Returns:
            dict with keys: ok, url, status, title, snapshot
        """
        resp = await self._client.post(
            "/navigate",
            params={"profile": profile},
            json={"url": url},
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "url": data.get("url", url),
            "title": data.get("title", ""),
            "snapshot": data.get("snapshot", ""),
        }

    async def snapshot(self, profile: str) -> str:
        """Get the AI-readable snapshot of the current page.

        Returns:
            The snapshot text (may be empty if the page has no content).
        """
        resp = await self._client.get("/snapshot", params={"profile": profile})
        resp.raise_for_status()
        data = resp.json()
        return data.get("snapshot", "")

    async def content(self, profile: str) -> str:
        """Get the rendered HTML of the current page (after JS execution).

        Returns:
            The full page HTML string.
        """
        resp = await self._client.get("/content", params={"profile": profile})
        resp.raise_for_status()
        data = resp.json()
        return data.get("html", "")

    async def evaluate(self, profile: str, script: str, *args: Any) -> Any:
        """Run JavaScript on the current page and return the result.

        Args:
            profile: Sidecar profile name.
            script:  JS function expression, e.g. "() => document.title"
            *args:   Optional arguments passed to the JS function.

        Returns:
            The JS evaluation result.
        """
        body: dict[str, Any] = {"script": script}
        if args:
            body["args"] = list(args)
        resp = await self._client.post(
            "/evaluate",
            params={"profile": profile},
            json=body,
        )
        resp.raise_for_status()
        return resp.json().get("result")

    async def screenshot(self, profile: str, full_page: bool = False) -> dict[str, Any]:
        """Take a screenshot of the current page.

        Returns:
            dict with keys: base64, path, mimeType, url
        """
        resp = await self._client.post(
            "/screenshot",
            params={"profile": profile},
            json={"fullPage": full_page},
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "base64": data.get("base64", ""),
            "path": data.get("path", ""),
        }

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    async def act(
        self,
        profile: str,
        kind: str,
        *,
        ref: Optional[str] = None,
        text: Optional[str] = None,
        key: Optional[str] = None,
        direction: Optional[str] = None,
        values: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Perform a page interaction (click, type, scroll, press, hover, select).

        Args:
            profile:   Sidecar profile name.
            kind:      One of: click, type, scroll, press, hover, select.
            ref:       Element ref from snapshot (e.g. "e3"). Required for
                       click, type, hover, select.
            text:      Text to type. Required for kind="type".
            key:       Key to press. Required for kind="press".
            direction: "up" or "down". Used for kind="scroll".
            values:    Option values. Used for kind="select".

        Returns:
            dict with keys: ok, kind, snapshot
        """
        body: dict[str, Any] = {"kind": kind}
        if ref is not None:
            body["ref"] = ref
        if text is not None:
            body["text"] = text
        if key is not None:
            body["key"] = key
        if direction is not None:
            body["direction"] = direction
        if values is not None:
            body["values"] = values

        resp = await self._client.post(
            "/act",
            params={"profile": profile},
            json=body,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Cookies
    # ------------------------------------------------------------------

    async def set_cookies(self, profile: str, cookies: list[dict[str, Any]]) -> None:
        """Set cookies on the browser context via the sidecar."""
        resp = await self._client.post(
            "/cookies/set",
            params={"profile": profile},
            json={"cookies": cookies},
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------

    async def list_tabs(self, profile: str) -> list[dict[str, str]]:
        """List open tabs for the given profile.

        Returns:
            List of dicts with keys: targetId, url, title
        """
        resp = await self._client.get("/tabs", params={"profile": profile})
        resp.raise_for_status()
        data = resp.json()
        return data.get("tabs", [])

    # ------------------------------------------------------------------
    # CAPTCHA solving
    # ------------------------------------------------------------------

    async def solve_captcha_if_present(self, profile: str) -> bool:
        """Detect and solve any CAPTCHA on the current page.

        Checks the rendered HTML for known captcha patterns (DataDome,
        reCAPTCHA, Akamai) and attempts to solve via CapSolver API.

        Returns True if a CAPTCHA was solved and the page reloaded,
        False if no CAPTCHA detected or solving failed/not configured.
        """
        import asyncio
        import re
        from urllib.parse import urlparse

        from app.services.browser.captcha_solver import get_captcha_solver

        solver = get_captcha_solver()
        if not solver:
            logger.debug("No captcha solver configured")
            return False

        try:
            html = await self.content(profile)
        except Exception:
            return False

        if not html or len(html) > 50_000:
            return False

        page_url = ""
        try:
            page_url = await self.evaluate(profile, "() => window.location.href")
        except Exception:
            pass

        # --- DataDome ---
        if "captcha-delivery.com" in html or "datadome" in html.lower():
            logger.info("DataDome captcha detected, attempting solve...")
            match = re.search(
                r'src=["\']?(https://geo\.captcha-delivery\.com/captcha/[^"\'>\s]+)',
                html,
            )
            captcha_url = match.group(1).replace("&amp;", "&") if match else ""

            info = {"type": "datadome", "sitekey": captcha_url}
            try:
                token = await solver._solve_datadome(page_url, info)
                if token:
                    logger.info("DataDome solved, setting cookie via sidecar and reloading")
                    parsed = urlparse(page_url)
                    domain = parsed.hostname or ""
                    await self.set_cookies(profile, [{
                        "name": "datadome",
                        "value": token,
                        "domain": domain,
                        "path": "/",
                        "secure": True,
                        "sameSite": "Lax",
                    }])
                    await asyncio.sleep(1)
                    await self.navigate(profile, page_url)
                    await asyncio.sleep(2)
                    return True
            except Exception as exc:
                logger.warning("DataDome solve failed: %s", exc)
                return False

        # --- reCAPTCHA ---
        elif "recaptcha" in html.lower() or "g-recaptcha" in html.lower():
            logger.info("reCAPTCHA detected, attempting solve...")

            async def eval_js(script: str, *args: Any) -> Any:
                return await self.evaluate(profile, script, *args)

            try:
                token = await solver.detect_and_solve(page_url, eval_js)
                if token:
                    await asyncio.sleep(3)
                    return True
            except Exception as exc:
                logger.warning("reCAPTCHA solve failed: %s", exc)

        return False

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "BrowserClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
