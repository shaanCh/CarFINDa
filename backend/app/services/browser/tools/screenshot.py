"""
Browser Screenshot Tool

Take a visual screenshot of the current page.
"""

import logging
from typing import Any, Dict, Optional

from app.services.browser.tools.base import BaseTool, ToolParameter, ToolResult, ToolSchema
from app.services.browser.control_gateway import (
    BrowserControlError,
    get_browser_gateway_service,
)

logger = logging.getLogger(__name__)


class BrowserScreenshotTool(BaseTool):
    @classmethod
    def get_schema(cls) -> ToolSchema:
        return ToolSchema(
            name="browser.screenshot",
            description="Take a visual screenshot of the current browser page.",
            parameters=[
                ToolParameter(
                    name="full_page",
                    type="boolean",
                    description="Capture full scrollable page (default: false, viewport only).",
                    required=False,
                ),
            ],
            category="browser",
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_id: Optional[str] = kwargs.get("user_id")
        full_page: bool = kwargs.get("full_page", False)

        if not user_id:
            return ToolResult(
                success=False, error="Missing required parameter: user_id"
            )

        args: Dict[str, Any] = {}
        if full_page:
            args["fullPage"] = True

        gateway = get_browser_gateway_service()
        try:
            result = await gateway.execute_action(
                user_id=user_id,
                action="screenshot",
                args=args,
                target="host",
                origin="browser.screenshot",
            )
            return ToolResult(
                success=True,
                data=result,
                message="Screenshot captured",
            )
        except BrowserControlError as e:
            logger.warning("[BrowserScreenshot] Failed: %s", e)
            return ToolResult(
                success=False,
                error=str(e),
                error_code=e.code,
                retryable=e.status_code >= 500,
            )
        except Exception as e:
            logger.error("[BrowserScreenshot] Unexpected error: %s", e, exc_info=True)
            return ToolResult(success=False, error=f"Screenshot failed: {e}")
