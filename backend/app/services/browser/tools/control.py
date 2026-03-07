"""
Browser Control Tool

Generic action dispatcher to the browser gateway.
"""

import logging

from app.services.browser.tools.base import BaseTool, ToolParameter, ToolResult, ToolSchema
from app.services.browser.control_gateway import (
    BrowserControlError,
    get_browser_gateway_service,
)

logger = logging.getLogger(__name__)

# Actions allowed through the generic control tool.
# navigate/act have dedicated tools with safety checks — block here.
_CONTROL_ALLOWED_ACTIONS = {
    "status",
    "start",
    "stop",
    "reset_profile",
    "profiles",
    "tabs",
    "open",
    "focus",
    "close",
    "snapshot",
    "screenshot",
    "cookies_get",
    "cookies_set",
    "cookies_clear",
    "storage_get",
    "storage_set",
    "storage_clear",
}


class BrowserControlTool(BaseTool):
    @classmethod
    def get_schema(cls) -> ToolSchema:
        return ToolSchema(
            name="browser.control",
            description=(
                "Execute a browser control action against the authenticated user's "
                "managed browser profile. Supports tab lifecycle, navigation, "
                "snapshots, screenshots, storage/cookie operations, and diagnostics."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Browser action name (e.g., navigate, snapshot, act, cookies_get).",
                    required=True,
                ),
                ToolParameter(
                    name="args",
                    type="object",
                    description="Action-specific arguments object.",
                    required=False,
                    default={},
                ),
                ToolParameter(
                    name="target",
                    type="string",
                    description="Execution target: host or sandbox. Default host.",
                    required=False,
                    default="host",
                ),
            ],
            category="browser",
        )

    async def execute(self, **kwargs) -> ToolResult:
        user_id = kwargs.get("user_id")
        action = kwargs.get("action")
        args = kwargs.get("args") or {}
        target = kwargs.get("target", "host")

        if not user_id:
            return ToolResult(
                success=False, error="Missing required parameter: user_id"
            )
        if not action:
            return ToolResult(success=False, error="Missing required parameter: action")
        if not isinstance(args, dict):
            return ToolResult(success=False, error="Parameter 'args' must be an object")

        # Block restricted actions — use dedicated tools instead
        if action not in _CONTROL_ALLOWED_ACTIONS:
            logger.warning(
                "[BrowserControl] Blocked action '%s' — use dedicated tool", action
            )
            return ToolResult(
                success=False,
                error=(
                    f"Action '{action}' is not available through browser.control. "
                    "Use the dedicated tool (browser.navigate, browser.act, etc.)."
                ),
                error_code="action_blocked",
            )

        gateway = get_browser_gateway_service()
        try:
            result = await gateway.execute_action(
                user_id=user_id,
                action=str(action),
                args=args,
                target=str(target),
                origin=kwargs.get("origin"),
            )
            return ToolResult(
                success=True,
                data=result,
                message=f"Executed browser action '{action}' successfully.",
            )
        except BrowserControlError as e:
            logger.warning("[BrowserControlTool] Action failed (%s): %s", action, e)
            return ToolResult(
                success=False,
                error=str(e),
                error_code=e.code,
                retryable=e.status_code >= 500,
            )
        except Exception as e:
            logger.error("[BrowserControlTool] Unexpected error: %s", e, exc_info=True)
            return ToolResult(
                success=False,
                error=f"Browser action failed: {e}",
            )
