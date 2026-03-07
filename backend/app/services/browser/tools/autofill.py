"""
Browser Auto-Fill Tool

Auto-fill form fields on the current page using the user's profile data.
Detects fields, classifies what each asks for via AI, and fills matching data.
"""

import logging
from typing import Any, Optional

from app.services.browser.tools.base import BaseTool, ToolParameter, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class BrowserAutofillTool(BaseTool):
    @classmethod
    def get_schema(cls) -> ToolSchema:
        return ToolSchema(
            name="browser.autofill",
            description=(
                "Auto-fill form fields on the current page using the user's "
                "profile data (name, email, school, demographics, etc.). "
                "Detects all fillable fields, classifies what each asks for, "
                "and fills matching data. Returns a summary of filled fields "
                "and fields that need manual input. Use dry_run=true to "
                "preview without filling."
            ),
            parameters=[
                ToolParameter(
                    name="dry_run",
                    type="boolean",
                    description=(
                        "If true, only analyze and classify fields without "
                        "actually filling them. Use this to preview first."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="fields_to_skip",
                    type="array",
                    description=(
                        "Field labels to skip (case-insensitive). "
                        'E.g. ["essay", "cover letter", "personal statement"].'
                    ),
                    required=False,
                    items={"type": "string"},
                ),
            ],
            category="browser",
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_id: Optional[str] = kwargs.get("user_id")
        if not user_id:
            return ToolResult(
                success=False, error="Missing required parameter: user_id"
            )

        dry_run: bool = kwargs.get("dry_run", False)
        fields_to_skip = kwargs.get("fields_to_skip") or []

        from app.services.browser.control_gateway import BrowserControlError
        from app.services.browser.form_autofill_service import (
            get_form_autofill_service,
        )

        service = get_form_autofill_service()
        try:
            result = await service.autofill_form(
                user_id=user_id,
                dry_run=dry_run,
                fields_to_skip=fields_to_skip,
            )
            return ToolResult(
                success=True,
                data=result.to_dict(),
                message=result.summary,
            )
        except BrowserControlError as e:
            logger.warning("[BrowserAutofill] Browser error: %s", e)
            return ToolResult(
                success=False,
                error=str(e),
                error_code=e.code,
                retryable=e.status_code >= 500,
            )
        except Exception as e:
            logger.error("[BrowserAutofill] Unexpected error: %s", e, exc_info=True)
            return ToolResult(success=False, error=f"Auto-fill failed: {e}")
