"""
Browser Navigate Tool

Navigate to a URL in the managed browser.
"""

import logging
from typing import Any, Dict, Optional

from app.services.browser.tools.base import BaseTool, ToolParameter, ToolResult, ToolSchema
from app.services.browser.control_gateway import (
    BrowserControlError,
    get_browser_gateway_service,
)

logger = logging.getLogger(__name__)


class BrowserNavigateTool(BaseTool):
    @classmethod
    def get_schema(cls) -> ToolSchema:
        return ToolSchema(
            name="browser.navigate",
            description=(
                "Navigate to a URL in the browser. Returns the page title "
                "and final URL after any redirects."
            ),
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="Full URL to navigate to (must start with http/https).",
                    required=True,
                ),
                ToolParameter(
                    name="wait_until",
                    type="string",
                    description=(
                        "When to consider navigation complete: "
                        "'load' (default), 'domcontentloaded', or 'networkidle'."
                    ),
                    required=False,
                ),
            ],
            category="browser",
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_id: Optional[str] = kwargs.get("user_id")
        url: Optional[str] = kwargs.get("url")
        wait_until: Optional[str] = kwargs.get("wait_until")

        if not user_id:
            return ToolResult(
                success=False, error="Missing required parameter: user_id"
            )
        if not url:
            return ToolResult(success=False, error="Missing required parameter: url")

        # --- URL security check (SSRF / internal network prevention) ---
        from app.services.browser.url_security import validate_navigation_url

        url_check = validate_navigation_url(url)
        if not url_check.allowed:
            logger.warning(
                "[BrowserNavigate] Blocked URL: %s — %s", url, url_check.reason
            )
            return ToolResult(
                success=False,
                error=f"Navigation blocked: {url_check.reason}",
                error_code="url_blocked",
            )

        args: Dict[str, Any] = {"url": url}
        if wait_until:
            args["waitUntil"] = wait_until

        gateway = get_browser_gateway_service()
        try:
            result = await gateway.execute_action(
                user_id=user_id,
                action="navigate",
                args=args,
                target="host",
                origin="browser.navigate",
            )
            # Extract navigation result + auto-included snapshot
            nav = (
                result.get("result", {})
                if isinstance(result.get("result"), dict)
                else {}
            )
            final_url = nav.get("url", url)
            title = nav.get("title", "")
            status = nav.get("status", "")
            snapshot_text = nav.get("snapshot", "")

            # Validate final URL after redirects (anti-SSRF redirect bypass)
            redirect_warning = ""
            if final_url and final_url != url:
                redirect_check = validate_navigation_url(final_url)
                if not redirect_check.allowed:
                    logger.warning(
                        "[BrowserNavigate] Redirect to blocked URL: %s → %s — %s",
                        url,
                        final_url,
                        redirect_check.reason,
                    )
                    redirect_warning = (
                        f"\n\nSECURITY WARNING: This page redirected to a "
                        f"suspicious destination ({redirect_check.reason}). "
                        f"Do NOT enter credentials or sensitive data on this page."
                    )

            header = f"Navigated to {final_url}"
            if title:
                header += f" — Title: {title}"
            if status:
                header += f" (HTTP {status})"

            # Track current page URL for credential domain verification
            from app.services.browser.tools.act import (
                set_last_page_url,
                set_last_snapshot,
            )

            if final_url:
                set_last_page_url(user_id, final_url)

            # Sanitize + cache snapshot
            if snapshot_text:
                from app.services.browser.url_security import sanitize_snapshot

                snapshot_text = sanitize_snapshot(snapshot_text)
                set_last_snapshot(user_id, snapshot_text)

                from app.services.browser.snapshot_context import prepare_snapshot

                llm_text = prepare_snapshot(user_id, snapshot_text, efficient=False)
                message = f"{header}\n\n{llm_text}"
            else:
                message = header

            if redirect_warning:
                message += redirect_warning

            return ToolResult(
                success=True,
                data=result,
                message=message,
            )
        except BrowserControlError as e:
            logger.warning("[BrowserNavigate] Failed: %s", e)
            return ToolResult(
                success=False,
                error=str(e),
                error_code=e.code,
                retryable=e.status_code >= 500,
            )
        except Exception as e:
            logger.error("[BrowserNavigate] Unexpected error: %s", e, exc_info=True)
            return ToolResult(success=False, error=f"Navigation failed: {e}")
