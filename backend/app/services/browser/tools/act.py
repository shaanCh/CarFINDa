"""
Browser Act Tool

Perform an interaction on the current page (click, type, scroll, etc.).
Uses element refs from browser.snapshot to target elements.

Includes an ActionGuard that checks for destructive actions (purchases,
form submissions, account changes) and requires user confirmation.
"""

import logging
from typing import Any, Dict, Optional

from app.services.browser.tools.base import BaseTool, ToolParameter, ToolResult, ToolSchema
from app.services.browser.control_gateway import (
    BrowserControlError,
    get_browser_gateway_service,
)

logger = logging.getLogger(__name__)

# Per-user caches for security context awareness.
# Populated by browser_act, browser_navigate, and browser_snapshot.
_last_snapshot: Dict[str, str] = {}
_last_page_url: Dict[str, str] = {}


def set_last_snapshot(user_id: str, snapshot: str) -> None:
    """Store the most recent snapshot text for a user (used by guard)."""
    _last_snapshot[user_id] = snapshot


def get_last_snapshot(user_id: str) -> str:
    """Get the most recent snapshot text for a user."""
    return _last_snapshot.get(user_id, "")


def set_last_page_url(user_id: str, url: str) -> None:
    """Store the most recent page URL for a user (used by login tool)."""
    _last_page_url[user_id] = url


def get_last_page_url(user_id: str) -> str:
    """Get the most recent page URL for a user."""
    return _last_page_url.get(user_id, "")


class BrowserActTool(BaseTool):
    @classmethod
    def get_schema(cls) -> ToolSchema:
        return ToolSchema(
            name="browser.act",
            description=(
                "Perform an interaction on the current page. First call "
                "browser.snapshot to get element refs, then use those refs here. "
                "Actions: click, type, scroll, select, hover, press. "
                "Destructive actions (purchases, form submissions, account "
                "changes) require confirmed=true after user approval."
            ),
            parameters=[
                ToolParameter(
                    name="kind",
                    type="string",
                    description=(
                        "Action type: 'click', 'type', 'scroll', 'select', "
                        "'hover', or 'press'."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="ref",
                    type="string",
                    description=(
                        "Element ref from browser.snapshot output (e.g. 'e3', 'e6'). "
                        "Required for click, type, select, hover."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to type (required for 'type' action).",
                    required=False,
                ),
                ToolParameter(
                    name="key",
                    type="string",
                    description="Key to press (for 'press' action, e.g. 'Enter', 'Tab').",
                    required=False,
                ),
                ToolParameter(
                    name="direction",
                    type="string",
                    description="Scroll direction: 'up' or 'down' (for 'scroll' action).",
                    required=False,
                ),
                ToolParameter(
                    name="confirmed",
                    type="boolean",
                    description=(
                        "Set to true ONLY after the user has explicitly confirmed "
                        "this action. Required for destructive actions like form "
                        "submissions, purchases, and account changes."
                    ),
                    required=False,
                ),
            ],
            category="browser",
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_id: Optional[str] = kwargs.get("user_id")
        kind: Optional[str] = kwargs.get("kind")

        if not user_id:
            return ToolResult(
                success=False, error="Missing required parameter: user_id"
            )
        if not kind:
            return ToolResult(success=False, error="Missing required parameter: kind")

        ref = kwargs.get("ref")
        text = kwargs.get("text")
        confirmed = kwargs.get("confirmed", False)

        # --- Action Guard: check for destructive actions ---
        from app.services.browser.action_guard import check_action_safety

        snapshot_context = get_last_snapshot(user_id)
        guard = check_action_safety(
            kind=kind,
            ref=ref,
            text=text,
            snapshot=snapshot_context,
            confirmed=confirmed,
        )
        if not guard.allowed:
            return ToolResult(
                success=False,
                error=guard.reason,
                data={
                    "confirmation_required": True,
                    "risk_category": guard.risk_category,
                    "element_ref": ref,
                    "action_kind": kind,
                },
            )

        # --- Execute the action ---
        args: Dict[str, Any] = {"kind": kind}
        for key in ("ref", "text", "key", "direction"):
            val = kwargs.get(key)
            if val is not None:
                args[key] = val

        gateway = get_browser_gateway_service()
        try:
            result = await gateway.execute_action(
                user_id=user_id,
                action="act",
                args=args,
                target="host",
                origin="browser.act",
            )
            # Extract auto-included snapshot (sidecar snapshots after every action)
            act_result = (
                result.get("result", {})
                if isinstance(result.get("result"), dict)
                else {}
            )
            snapshot_text = act_result.get("snapshot", "")

            # Sanitize + cache snapshot for future guard checks
            if snapshot_text:
                from app.services.browser.url_security import sanitize_snapshot

                snapshot_text = sanitize_snapshot(snapshot_text)
                set_last_snapshot(user_id, snapshot_text)

                from app.services.browser.snapshot_context import (
                    _UNCHANGED_MSG,
                    prepare_snapshot,
                )

                llm_text = prepare_snapshot(user_id, snapshot_text, efficient=True)

                # Detect clicks that didn't change the page
                if llm_text == _UNCHANGED_MSG and kind == "click":
                    message = (
                        f"WARNING: Click on ref '{ref}' had NO EFFECT — the page "
                        f"content is identical to before the click. The element may "
                        f"be non-interactive, off-screen, or obscured by an overlay. "
                        f"Do NOT assume this action succeeded. Try a different "
                        f"element, scroll to find the correct target, or take a "
                        f"screenshot to visually inspect the page."
                    )
                else:
                    message = f"Action '{kind}' completed. Page content:\n\n{llm_text}"
            else:
                message = f"Action complete: {kind}"

            return ToolResult(
                success=True,
                data=result,
                message=message,
            )
        except BrowserControlError as e:
            logger.warning("[BrowserAct] Failed: %s", e)
            return ToolResult(
                success=False,
                error=str(e),
                error_code=e.code,
                retryable=e.status_code >= 500,
            )
        except Exception as e:
            logger.error("[BrowserAct] Unexpected error: %s", e, exc_info=True)
            return ToolResult(success=False, error=f"Browser action failed: {e}")
