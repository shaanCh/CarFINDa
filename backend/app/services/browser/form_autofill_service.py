"""
Form Auto-Fill Service — automatically fill form fields using user profile data.

Detects form fields on a page, classifies what each asks for, and fills
matching data from the user's profile.

TODO: Implement form detection and auto-fill logic.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AutofillResult:
    """Result of an auto-fill operation."""

    filled_fields: list[dict[str, str]] = field(default_factory=list)
    skipped_fields: list[dict[str, str]] = field(default_factory=list)
    unfilled_fields: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "filled_fields": self.filled_fields,
            "skipped_fields": self.skipped_fields,
            "unfilled_fields": self.unfilled_fields,
            "summary": self.summary,
        }


class FormAutofillService:
    """Service for auto-filling forms in the browser."""

    async def autofill_form(
        self,
        user_id: str,
        dry_run: bool = False,
        fields_to_skip: list[str] | None = None,
    ) -> AutofillResult:
        """Auto-fill form fields on the current page.

        TODO: Implement form detection and auto-fill.
        """
        raise NotImplementedError("Form auto-fill not yet implemented")


_service_instance: Optional[FormAutofillService] = None


def get_form_autofill_service() -> FormAutofillService:
    """Get or create the singleton form autofill service."""
    global _service_instance
    if _service_instance is None:
        _service_instance = FormAutofillService()
    return _service_instance
