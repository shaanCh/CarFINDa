"""
Browser Control Gateway — interface to the Playwright sidecar.

Wraps the low-level BrowserClient with per-user session management,
action routing, and error handling.

TODO: Implement full gateway logic. Currently provides the interface
that browser tools depend on, delegating to BrowserClient.
"""

import logging
from typing import Any, Optional

from app.config import get_settings
from app.services.scraping.browser_client import BrowserClient

logger = logging.getLogger(__name__)


class BrowserControlError(Exception):
    """Error from the browser control gateway."""

    def __init__(self, message: str, code: str = "browser_error", status_code: int = 500):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class BrowserGatewayService:
    """Gateway service managing browser sessions and action dispatch."""

    def __init__(self):
        settings = get_settings()
        self._client = BrowserClient(
            base_url=settings.SIDECAR_URL,
            token=settings.SIDECAR_TOKEN,
        )

    async def execute_action(
        self,
        user_id: str,
        action: str,
        args: dict[str, Any] | None = None,
        target: str = "host",
        origin: Optional[str] = None,
    ) -> dict[str, Any]:
        """Execute a browser action for a user.

        Routes the action to the appropriate BrowserClient method.

        Args:
            user_id: The user's ID (used as the sidecar profile name).
            action:  Action name (navigate, snapshot, screenshot, act, tabs, etc.).
            args:    Action-specific arguments.
            target:  Execution target (currently only 'host' is supported).
            origin:  Caller identifier for logging.

        Returns:
            Dict with the action result from the sidecar.

        Raises:
            BrowserControlError: If the action fails.
        """
        args = args or {}
        profile = f"carfinda-{user_id[:8]}"

        try:
            await self._client.start_session(profile)

            if action == "navigate":
                result = await self._client.navigate(profile, args.get("url", ""))
                return {"ok": True, "action": action, "result": result}

            elif action == "snapshot":
                snapshot = await self._client.snapshot(profile)
                return {
                    "ok": True,
                    "action": action,
                    "result": {"snapshot": snapshot},
                }

            elif action == "screenshot":
                result = await self._client.screenshot(
                    profile, full_page=args.get("fullPage", False)
                )
                return {"ok": True, "action": action, "result": result}

            elif action == "act":
                result = await self._client.act(
                    profile,
                    kind=args.get("kind", "click"),
                    ref=args.get("ref"),
                    text=args.get("text"),
                    key=args.get("key"),
                    direction=args.get("direction"),
                    values=args.get("values"),
                )
                return {"ok": True, "action": action, "result": result}

            elif action == "tabs":
                tabs = await self._client.list_tabs(profile)
                return {"ok": True, "action": action, "result": {"tabs": tabs}}

            else:
                raise BrowserControlError(
                    f"Unknown action: {action}",
                    code="unknown_action",
                    status_code=400,
                )

        except BrowserControlError:
            raise
        except Exception as e:
            logger.error(
                "[BrowserGateway] %s action=%s failed: %s",
                origin or "unknown",
                action,
                e,
            )
            raise BrowserControlError(str(e)) from e


_gateway_instance: Optional[BrowserGatewayService] = None


def get_browser_gateway_service() -> BrowserGatewayService:
    """Get or create the singleton gateway service."""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = BrowserGatewayService()
    return _gateway_instance
