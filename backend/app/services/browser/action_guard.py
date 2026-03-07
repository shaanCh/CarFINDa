"""
Action Guard — safety checks for destructive browser actions.

Inspects the current page snapshot + action context to determine if an
action (click, type, submit) could be destructive (purchases, account
changes, form submissions) and requires user confirmation.

TODO: Expand guard rules with more patterns.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""
    risk_category: str = ""


# Patterns in snapshot text that suggest destructive actions
_DESTRUCTIVE_PATTERNS = [
    (re.compile(r"place.{0,10}order|buy.{0,10}now|purchase|checkout", re.IGNORECASE), "purchase"),
    (re.compile(r"delete.{0,10}account|deactivate.{0,10}account", re.IGNORECASE), "account_deletion"),
    (re.compile(r"confirm.{0,10}payment|pay\s+\$", re.IGNORECASE), "payment"),
]


def check_action_safety(
    kind: str,
    ref: Optional[str],
    text: Optional[str],
    snapshot: str,
    confirmed: bool = False,
) -> GuardResult:
    """Check if a browser action is safe to execute without user confirmation.

    Args:
        kind:      Action type (click, type, scroll, etc.)
        ref:       Target element ref
        text:      Text being typed (if applicable)
        snapshot:  Current page snapshot text
        confirmed: Whether the user has explicitly confirmed this action

    Returns:
        GuardResult with allowed=True if safe, or allowed=False with reason.
    """
    if confirmed:
        return GuardResult(allowed=True)

    # Only guard click and type actions on interactive elements
    if kind not in ("click", "type"):
        return GuardResult(allowed=True)

    # Check snapshot for destructive context
    for pattern, category in _DESTRUCTIVE_PATTERNS:
        if pattern.search(snapshot):
            return GuardResult(
                allowed=False,
                reason=(
                    f"This action may involve a {category.replace('_', ' ')}. "
                    f"Set confirmed=true after the user explicitly approves."
                ),
                risk_category=category,
            )

    return GuardResult(allowed=True)
