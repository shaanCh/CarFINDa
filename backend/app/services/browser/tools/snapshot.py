"""
Browser Snapshot Tool

Read the current page content as AI-optimized text.
Falls back to screenshot + vision model when the AI snapshot is too thin.
"""

import logging
from typing import Any, Optional

from app.services.browser.tools.base import BaseTool, ToolParameter, ToolResult, ToolSchema
from app.services.browser.control_gateway import (
    BrowserControlError,
    get_browser_gateway_service,
)

logger = logging.getLogger(__name__)


class BrowserSnapshotTool(BaseTool):
    @classmethod
    def get_schema(cls) -> ToolSchema:
        return ToolSchema(
            name="browser.snapshot",
            description=(
                "Read the current page content as structured text. "
                "Returns an AI-optimized readable version of the page."
            ),
            parameters=[
                ToolParameter(
                    name="format",
                    type="string",
                    description="Output format: 'ai' (default, readable text) or 'html'.",
                    required=False,
                ),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="Extraction mode: 'full' (default, complete page) or 'efficient' (interactive elements only, concise).",
                    required=False,
                ),
            ],
            category="browser",
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_id: Optional[str] = kwargs.get("user_id")
        fmt: str = kwargs.get("format", "ai")
        mode: str = kwargs.get("mode", "full")

        if not user_id:
            return ToolResult(
                success=False, error="Missing required parameter: user_id"
            )

        gateway = get_browser_gateway_service()
        try:
            result = await gateway.execute_action(
                user_id=user_id,
                action="snapshot",
                args={"format": fmt, "mode": mode},
                target="host",
                origin="browser.snapshot",
            )
            snapshot_text = ""
            sidecar_result = result.get("result", {})
            if isinstance(sidecar_result, dict):
                snapshot_text = sidecar_result.get("snapshot", "")
            elif isinstance(sidecar_result, str):
                snapshot_text = sidecar_result

            url = (
                sidecar_result.get("url", "")
                if isinstance(sidecar_result, dict)
                else ""
            )
            # Sanitize snapshot against prompt injection from page content
            if snapshot_text:
                from app.services.browser.url_security import sanitize_snapshot

                snapshot_text = sanitize_snapshot(snapshot_text)

            # Vision fallback: if snapshot is too thin, supplement with
            # screenshot + vision model description
            ref_count = snapshot_text.count("[ref=") if snapshot_text else 0
            is_thin = len(snapshot_text.strip()) < 100 or ref_count < 3
            if is_thin and snapshot_text.strip():
                vision_desc = await _describe_page_via_vision(gateway, user_id)
                if vision_desc:
                    snapshot_text = (
                        f"[AI Snapshot - limited elements detected]\n"
                        f"{snapshot_text}\n\n"
                        f"[Visual Description]\n{vision_desc}"
                    )

            # Cache full snapshot + URL for security context (guard, login)
            from app.services.browser.tools.act import (
                set_last_page_url,
                set_last_snapshot,
            )

            if url:
                set_last_page_url(user_id, url)
            if snapshot_text:
                set_last_snapshot(user_id, snapshot_text)

            from app.services.browser.snapshot_context import prepare_snapshot

            use_efficient = mode == "efficient"
            llm_text = (
                prepare_snapshot(user_id, snapshot_text, efficient=use_efficient)
                if snapshot_text
                else "Page content extracted (empty snapshot)"
            )
            message = f"[URL: {url}]\n\n{llm_text}" if url else llm_text

            return ToolResult(
                success=True,
                data=result,
                message=message,
            )
        except BrowserControlError as e:
            logger.warning("[BrowserSnapshot] Failed: %s", e)
            return ToolResult(
                success=False,
                error=str(e),
                error_code=e.code,
                retryable=e.status_code >= 500,
            )
        except Exception as e:
            logger.error("[BrowserSnapshot] Unexpected error: %s", e, exc_info=True)
            return ToolResult(success=False, error=f"Snapshot failed: {e}")


async def _describe_page_via_vision(
    gateway: Any,
    user_id: str,
) -> Optional[str]:
    """Take a screenshot and describe it with Gemini Flash."""
    try:
        screenshot_result = await gateway.execute_action(
            user_id=user_id,
            action="screenshot",
            args={},
            target="host",
            origin="browser.snapshot.vision_fallback",
        )
        sidecar_data = screenshot_result.get("result", {})
        base64_img = (
            sidecar_data.get("base64", "") if isinstance(sidecar_data, dict) else ""
        )
        if not base64_img:
            return None

        from app.services.llm.gemini_client import GeminiClient
        from app.config import get_settings

        settings = get_settings()
        client = GeminiClient(api_key=settings.GEMINI_API_KEY)
        # TODO: Use vision capabilities when available
        return None
    except Exception as e:
        logger.warning("[BrowserSnapshot] Vision fallback failed: %s", e)
        return None
