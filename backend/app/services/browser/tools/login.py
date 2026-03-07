"""
Browser Login Tool

Securely inject stored credentials into a login form on the current page.
The agent NEVER sees the decrypted password — the system validates the
domain, retrieves the encrypted credential, and fills the form directly
via the browser sidecar.

Supports both single-page and multi-step login flows (e.g. Amazon, Google
show email first, then password on a separate page).
"""

import asyncio
import logging
from typing import Any, Optional

from app.services.browser.login_patterns import (
    PASSWORD_PATTERNS,
    SUBMIT_PATTERNS,
    detect_2fa_type,
    find_code_field,
    find_password_field_fallback,
    find_ref,
    has_captcha,
    sanitize_error,
    try_solve_captcha,
)
from app.services.browser.tools.base import BaseTool, ToolParameter, ToolResult, ToolSchema
from app.services.browser.control_gateway import (
    BrowserControlError,
    get_browser_gateway_service,
)

logger = logging.getLogger(__name__)


class BrowserLoginTool(BaseTool):
    @classmethod
    def get_schema(cls) -> ToolSchema:
        return ToolSchema(
            name="browser.login",
            description=(
                "Securely fill stored login credentials into the current page. "
                "Password is NEVER visible to you. Supports multi-step logins "
                "(email first, then password on next page). Navigate to the "
                "login page first."
            ),
            parameters=[
                ToolParameter(
                    name="site_domain",
                    type="string",
                    required=True,
                    description="Domain of the stored credential (e.g. 'amazon.com').",
                ),
                ToolParameter(
                    name="username_ref",
                    type="string",
                    required=True,
                    description="Element ref for the username/email field (e.g. 'e3').",
                ),
                ToolParameter(
                    name="password_ref",
                    type="string",
                    required=False,
                    description=(
                        "Element ref for the password field. Omit for multi-step "
                        "logins — the tool will auto-detect it after username."
                    ),
                ),
                ToolParameter(
                    name="submit_ref",
                    type="string",
                    required=False,
                    description="Element ref for submit/continue button (e.g. 'e7').",
                ),
            ],
            category="browser",
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_id: Optional[str] = kwargs.get("user_id")
        site_domain: Optional[str] = kwargs.get("site_domain")
        username_ref: Optional[str] = kwargs.get("username_ref")
        password_ref: Optional[str] = kwargs.get("password_ref")
        submit_ref: Optional[str] = kwargs.get("submit_ref")

        for param in ("user_id", "site_domain", "username_ref"):
            if not kwargs.get(param):
                return ToolResult(
                    success=False, error=f"Missing required parameter: {param}"
                )
        if password_ref and username_ref == password_ref:
            return ToolResult(
                success=False,
                error="username_ref and password_ref must be DIFFERENT elements.",
            )

        # 1. Get current page URL from cache (set by navigate/snapshot)
        from app.services.browser.tools.act import get_last_page_url

        current_url = get_last_page_url(user_id)
        if not current_url:
            return ToolResult(
                success=False,
                error="Cannot determine current page URL. Call browser.navigate first.",
            )

        # 2. Retrieve credential with mandatory domain validation
        from app.services.browser.credential_service import (
            get_browser_credential_service,
        )

        cred_service = get_browser_credential_service()
        credential = await cred_service.get_credential(
            user_id=user_id,
            site_domain=site_domain,
            current_page_url=current_url,
        )

        if not credential:
            return ToolResult(
                success=False,
                error=(
                    f"No credential found for '{site_domain}' or page URL "
                    f"mismatch. Save credentials in Settings > Applications."
                ),
            )

        # 3. Inject credentials — agent never sees password
        gateway = get_browser_gateway_service()
        username = credential["username"]
        password = credential["password"]
        multi_step = password_ref is None

        try:
            await self._act(gateway, user_id, "type", username_ref, username)

            if multi_step:
                result = await self._handle_multi_step(gateway, user_id, submit_ref)
                if result.get("captcha"):
                    return ToolResult(
                        success=False,
                        error="CAPTCHA detected after entering username. Could not solve automatically.",
                    )
                password_ref = result.get("password_ref")
                if not password_ref:
                    snapshot = result.get("snapshot", "")
                    logger.warning(
                        "[BrowserLogin] Password field not found — likely "
                        "not on a login page. url=%s",
                        get_last_page_url(user_id),
                    )
                    return ToolResult(
                        success=False,
                        error=(
                            "Login FAILED — could not find a password field "
                            "after submitting the username. This usually means "
                            "you are NOT on the login page. Navigate to the "
                            "site's sign-in page first, then retry browser_login "
                            "with refs from the login form."
                        ),
                        data={"snapshot": snapshot, "site_domain": site_domain},
                    )
                submit_ref = result.get("submit_ref")

            await self._act(gateway, user_id, "type", password_ref, password)
            if submit_ref:
                await self._act(gateway, user_id, "click", submit_ref)

            flow_type = "multi-step" if multi_step else "single-page"
            logger.info(
                "[BrowserLogin] Credentials injected for %s (%s, user=%s)",
                site_domain,
                flow_type,
                user_id,
            )

            # Check for 2FA after login submission
            tfa_result = await self._handle_2fa_if_present(
                gateway, user_id, site_domain, credential, cred_service
            )
            if tfa_result:
                return tfa_result

            submitted = " and submitted" if submit_ref else ""
            return ToolResult(
                success=True,
                data={"site_domain": site_domain, "username": username},
                message=(
                    f"Login credentials for {site_domain} filled{submitted} "
                    f"({flow_type} flow). Username: {username}. Password "
                    f"filled securely. Use browser.login to retry if needed."
                ),
            )

        except BrowserControlError as e:
            sanitized = sanitize_error(str(e), username, password)
            logger.warning("[BrowserLogin] Failed: %s", sanitized)
            return ToolResult(
                success=False,
                error=f"Login injection failed: {sanitized}",
                error_code=e.code,
                retryable=e.status_code >= 500,
            )
        except Exception as e:
            sanitized = sanitize_error(str(e), username, password)
            logger.error(
                "[BrowserLogin] Unexpected error: %s", sanitized, exc_info=True
            )
            return ToolResult(
                success=False,
                error=f"Login failed: {sanitized}",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _act(
        self, gateway: Any, user_id: str, kind: str, ref: str, text: str = ""
    ) -> None:
        """Execute a browser act (type or click)."""
        args = {"kind": kind, "ref": ref}
        if text:
            args["text"] = text
        await gateway.execute_action(
            user_id=user_id,
            action="act",
            args=args,
            target="host",
            origin="browser.login",
        )

    # ------------------------------------------------------------------
    # 2FA handling
    # ------------------------------------------------------------------

    async def _handle_2fa_if_present(
        self,
        gateway: Any,
        user_id: str,
        site_domain: str,
        credential: dict,
        cred_service: Any,
    ) -> Optional[ToolResult]:
        """Check for CAPTCHA/2FA after login and handle automatically."""
        await asyncio.sleep(2.0)
        snapshot = await self._get_snapshot(gateway, user_id)
        if not snapshot:
            return None

        if has_captcha(snapshot):
            logger.info("[BrowserLogin] CAPTCHA after login for %s", site_domain)
            from app.services.browser.tools.act import get_last_page_url

            page_url = get_last_page_url(user_id) or f"https://{site_domain}"
            if not await try_solve_captcha(gateway, user_id, page_url):
                return ToolResult(
                    success=False,
                    error="CAPTCHA detected after login — could not solve automatically.",
                )
            await asyncio.sleep(2.0)
            snapshot = await self._get_snapshot(gateway, user_id)
            if not snapshot:
                return ToolResult(
                    success=True,
                    data={"site_domain": site_domain, "captcha_solved": True},
                    message=f"Logged in to {site_domain} — solved the CAPTCHA.",
                )

        tfa_type = detect_2fa_type(snapshot)
        if not tfa_type:
            return None

        logger.info(
            "[BrowserLogin] 2FA detected: type=%s site=%s", tfa_type, site_domain
        )
        code_ref = find_code_field(snapshot)

        if tfa_type == "totp":
            return await self._handle_totp_2fa(
                gateway,
                user_id,
                site_domain,
                credential,
                cred_service,
                snapshot,
                code_ref,
            )

        if tfa_type == "email":
            return await self._handle_email_2fa(
                gateway, user_id, site_domain, snapshot, code_ref
            )

        return None

    async def _handle_totp_2fa(
        self,
        gateway: Any,
        user_id: str,
        site_domain: str,
        credential: dict,
        cred_service: Any,
        snapshot: str,
        code_ref: Optional[str],
    ) -> ToolResult:
        """Handle authenticator-app 2FA."""
        totp_secret = credential.get("totp_secret")
        if totp_secret and code_ref:
            code = cred_service.generate_totp_code(totp_secret)
            await self._act(gateway, user_id, "type", code_ref, code)
            verify_ref = find_ref(snapshot, SUBMIT_PATTERNS)
            if verify_ref:
                await self._act(gateway, user_id, "click", verify_ref)
            return ToolResult(
                success=True,
                data={"site_domain": site_domain, "tfa_type": "totp"},
                message=(
                    f"Logged in to {site_domain} — auto-generated and "
                    f"filled the authenticator code to get past 2FA."
                ),
            )
        return ToolResult(
            success=False,
            error=(
                f"2FA authenticator code required for {site_domain} but no "
                f"TOTP secret is stored. Save the TOTP secret in Settings > "
                f"Applications, or provide the code manually."
            ),
        )

    async def _handle_email_2fa(
        self,
        gateway: Any,
        user_id: str,
        site_domain: str,
        snapshot: str,
        code_ref: Optional[str],
    ) -> ToolResult:
        """Handle email-based 2FA by extracting the code from Gmail."""
        try:
            from app.services.browser.tfa_email_service import (
                extract_2fa_code_from_email,
            )

            code = await extract_2fa_code_from_email(user_id, site_domain)
        except Exception as e:
            logger.warning("[BrowserLogin] Email 2FA extraction failed: %s", e)
            code = None

        if not code:
            return ToolResult(
                success=False,
                error=(
                    f"2FA verification code was sent via email for {site_domain} "
                    f"but couldn't find it in the inbox. Check email manually "
                    f"or use email_search to find the code."
                ),
            )

        if not code_ref:
            code_ref = find_code_field(snapshot)
        if not code_ref:
            return ToolResult(
                success=False,
                error=(
                    f"Found 2FA code from email but couldn't locate the code "
                    f"input field. Use browser.snapshot to find it and type "
                    f"the code '{code}' manually with browser.act."
                ),
                data={"code": code},
            )

        await self._act(gateway, user_id, "type", code_ref, code)
        verify_ref = find_ref(snapshot, SUBMIT_PATTERNS)
        if verify_ref:
            await self._act(gateway, user_id, "click", verify_ref)

        return ToolResult(
            success=True,
            data={"site_domain": site_domain, "tfa_type": "email"},
            message=(
                f"Logged in to {site_domain} — grabbed the verification "
                f"code from your email to get past 2FA."
            ),
        )

    # ------------------------------------------------------------------
    # Multi-step login
    # ------------------------------------------------------------------

    async def _handle_multi_step(
        self,
        gateway: Any,
        user_id: str,
        submit_ref: Optional[str],
    ) -> dict:
        """Handle multi-step login: click continue after username,
        wait for password page, return password field ref."""
        # Find or use the continue/next button
        if not submit_ref:
            snapshot = await self._get_snapshot(gateway, user_id)
            if snapshot:
                submit_ref = find_ref(snapshot, SUBMIT_PATTERNS)

        if not submit_ref:
            logger.warning("[BrowserLogin] No continue button found for multi-step")
            return {"password_ref": None}

        await self._act(gateway, user_id, "click", submit_ref)

        # Wait for password page to load, then find the password field
        captcha_attempted = False
        for attempt, delay in enumerate((1.5, 2.0, 3.0), 1):
            await asyncio.sleep(delay)
            snapshot = await self._get_snapshot(gateway, user_id)
            if not snapshot:
                logger.info("[BrowserLogin] Step 2 attempt %d: empty snapshot", attempt)
                continue

            logger.info(
                "[BrowserLogin] Step 2 attempt %d: snapshot_len=%d preview=%.500s",
                attempt,
                len(snapshot),
                snapshot.replace("\n", " ")[:500],
            )

            if has_captcha(snapshot):
                if captcha_attempted:
                    logger.info("[BrowserLogin] CAPTCHA persists after solve attempt")
                    return {"captcha": True}
                logger.info("[BrowserLogin] CAPTCHA on step 2, attempting solve")
                from app.services.browser.tools.act import get_last_page_url

                page_url = get_last_page_url(user_id) or ""
                captcha_attempted = True
                solved = await try_solve_captcha(gateway, user_id, page_url)
                if not solved:
                    return {"captcha": True}
                continue

            pw_ref = find_ref(snapshot, PASSWORD_PATTERNS)
            if not pw_ref:
                pw_ref = find_password_field_fallback(snapshot)
            if pw_ref:
                logger.info("[BrowserLogin] Found password field %s on step 2", pw_ref)
                pw_submit = find_ref(snapshot, SUBMIT_PATTERNS)
                return {"password_ref": pw_ref, "submit_ref": pw_submit}

            logger.info(
                "[BrowserLogin] Step 2 attempt %d: no password field found", attempt
            )

        logger.warning("[BrowserLogin] All step 2 retries exhausted")
        return {"password_ref": None, "snapshot": snapshot or ""}

    # ------------------------------------------------------------------
    # Snapshot helper
    # ------------------------------------------------------------------

    async def _get_snapshot(self, gateway: Any, user_id: str) -> Optional[str]:
        """Get AI-readable snapshot of the current page."""
        try:
            result = await gateway.execute_action(
                user_id=user_id,
                action="snapshot",
                args={"format": "ai"},
                target="host",
                origin="browser.login",
            )
            if isinstance(result, dict):
                inner = result.get("result", {})
                if isinstance(inner, dict):
                    snapshot = inner.get("snapshot", "")
                else:
                    snapshot = result.get("snapshot", "")
                logger.debug(
                    "[BrowserLogin] Snapshot: len=%d keys=%s inner_type=%s url=%s",
                    len(snapshot) if snapshot else 0,
                    list(result.keys())[:6],
                    type(inner).__name__,
                    (inner.get("url", "") if isinstance(inner, dict) else "")[:80],
                )
                return snapshot
            return str(result) if result else None
        except Exception as e:
            logger.warning("[BrowserLogin] Snapshot failed: %s", e)
            return None
