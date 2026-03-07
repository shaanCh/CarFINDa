"""
Browser Tabs Tool

Manage browser tabs: list, open, close, focus.
"""

import logging
from typing import Any, Dict, Optional

from app.services.browser.tools.base import BaseTool, ToolParameter, ToolResult, ToolSchema
from app.services.browser.control_gateway import (
    BrowserControlError,
    get_browser_gateway_service,
)

logger = logging.getLogger(__name__)

_OP_TO_ACTION = {
    "list": "tabs",
    "open": "open",
    "close": "close",
    "focus": "focus",
}


class BrowserTabsTool(BaseTool):
    @classmethod
    def get_schema(cls) -> ToolSchema:
        return ToolSchema(
            name="browser.tabs",
            description=(
                "Manage browser tabs: list open tabs, open a new tab with a URL, "
                "close a tab, or focus an existing tab."
            ),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Tab operation: 'list', 'open', 'close', or 'focus'.",
                    required=True,
                ),
                ToolParameter(
                    name="url",
                    type="string",
                    description="URL to open (required for 'open' operation).",
                    required=False,
                ),
                ToolParameter(
                    name="target_id",
                    type="string",
                    description="Tab target ID (required for 'close' and 'focus').",
                    required=False,
                ),
            ],
            category="browser",
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_id: Optional[str] = kwargs.get("user_id")
        operation: Optional[str] = kwargs.get("operation")
        url: Optional[str] = kwargs.get("url")
        target_id: Optional[str] = kwargs.get("target_id")

        if not user_id:
            return ToolResult(
                success=False, error="Missing required parameter: user_id"
            )
        if not operation or operation not in _OP_TO_ACTION:
            return ToolResult(
                success=False,
                error=f"Invalid operation: {operation}. Use: list, open, close, focus.",
            )

        action = _OP_TO_ACTION[operation]
        args: Dict[str, Any] = {}

        if operation == "open":
            if not url:
                return ToolResult(
                    success=False, error="'url' is required for 'open' operation"
                )
            args["url"] = url
        elif operation in ("close", "focus"):
            if not target_id:
                return ToolResult(
                    success=False,
                    error=f"'target_id' is required for '{operation}' operation",
                )
            args["targetId"] = target_id

        gateway = get_browser_gateway_service()
        try:
            result = await gateway.execute_action(
                user_id=user_id,
                action=action,
                args=args,
                target="host",
                origin="browser.tabs",
            )
            return ToolResult(
                success=True,
                data=result,
                message=f"Tab {operation} complete",
            )
        except BrowserControlError as e:
            logger.warning("[BrowserTabs] Failed: %s", e)
            return ToolResult(
                success=False,
                error=str(e),
                error_code=e.code,
                retryable=e.status_code >= 500,
            )
        except Exception as e:
            logger.error("[BrowserTabs] Unexpected error: %s", e, exc_info=True)
            return ToolResult(success=False, error=f"Tab operation failed: {e}")
