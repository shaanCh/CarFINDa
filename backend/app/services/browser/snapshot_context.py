"""
Snapshot Context Management

Processes raw Playwright _snapshotForAI() output to keep sub-agent LLM
context lean.  Inspired by OpenClaw's efficient mode:

  1. strip_boilerplate  — remove skip-nav blocks (Amazon "Shortcuts menu", etc.)
  2. filter_interactive  — keep only interactive elements + headings for context
  3. compact             — remove empty structural lines, collapse whitespace
  4. limit_depth         — cap indentation depth to avoid deeply nested noise
  5. truncate            — hard character cap
  6. dedup               — MD5 dedup across consecutive snapshots

The full raw snapshot is still cached separately for the action guard /
login tool — only the LLM-facing text goes through this pipeline.
"""

import hashlib
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
MAX_SNAPSHOT_CHARS = 12_000
"""Hard cap for efficient mode (~3K tokens).  With interactive + compact
filtering, 12K comfortably fits Amazon product pages including Add to Cart."""

MAX_SNAPSHOT_CHARS_FULL = 30_000
"""Hard cap for full mode (explicit browser.snapshot calls)."""

_TRUNCATION_NOTICE = "\n\n[... snapshot truncated — use browser.snapshot for full page]"

# ---------------------------------------------------------------------------
# Per-user deduplication state
# ---------------------------------------------------------------------------
_last_snapshot_hash: Dict[str, str] = {}

_UNCHANGED_MSG = "[Page content unchanged from previous snapshot]"

# ---------------------------------------------------------------------------
# Efficient mode defaults (mirrors OpenClaw)
# ---------------------------------------------------------------------------
EFFICIENT_MAX_DEPTH = 8
"""Max indentation depth in efficient mode.  Deeper nesting is structural
noise (wrapper divs, nested lists-in-lists).  OpenClaw uses 6; we use 8 to
keep slightly more context."""

_INDENT_UNIT = 2
"""Playwright snapshots use 2-space indentation per nesting level."""

# ---------------------------------------------------------------------------
# Boilerplate stripping
# ---------------------------------------------------------------------------
_SKIP_BLOCK_MARKERS = [
    '"Shortcuts menu"',
    '"Skip to"',
    '"skip-nav"',
    '"skiplink"',
]

_SKIP_LINE_RE = re.compile(
    r'link "Skip to |"Skip navigation"|"Skip to main content"',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Interactive element detection
# ---------------------------------------------------------------------------
_INTERACTIVE_ROLES = re.compile(
    r"^\s*-\s*("
    r"button|link|textbox|checkbox|radio|combobox|listbox|option|"
    r"searchbox|slider|spinbutton|switch|tab|menuitem|menuitemcheckbox|"
    r"menuitemradio|treeitem|search"
    r")\b",
    re.IGNORECASE,
)
"""Roles for interactive elements that the agent can act on."""

_CONTEXT_ROLES = re.compile(
    r"^\s*-\s*("
    r"heading|img|dialog|alert|alertdialog|"
    r"status|progressbar|table|row|cell|columnheader|rowheader"
    r")\b",
    re.IGNORECASE,
)
"""Roles kept for structural context (headings, images, tables)."""

_STRUCTURAL_WRAPPER_ROLES = re.compile(
    r"^\s*-\s*("
    r"generic|group|banner|main|navigation|contentinfo|"
    r"complementary|region|section|article|form|list|listitem"
    r")\b",
    re.IGNORECASE,
)
"""Roles that are structural wrappers — only kept if they have a quoted
name that carries semantic meaning.  Without a name, these are just
container divs that waste snapshot budget (Amazon has 100+ of these)."""

_REF_RE = re.compile(r"\[ref=e\d+\]")
"""Element ref marker."""

_HAS_QUOTED_NAME = re.compile(r'"[^"]{2,}"')
"""Lines with a quoted name (e.g. heading "Products") carry semantic value."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def strip_boilerplate(text: str) -> str:
    """Remove skip-navigation blocks from snapshot."""
    lines = text.split("\n")
    result: List[str] = []
    skip_indent = -1

    for line in lines:
        indent = len(line) - len(line.lstrip())

        if skip_indent >= 0:
            if indent > skip_indent:
                continue
            skip_indent = -1

        if any(marker in line for marker in _SKIP_BLOCK_MARKERS):
            skip_indent = indent
            continue

        if _SKIP_LINE_RE.search(line):
            continue

        result.append(line)

    return "\n".join(result)


def filter_interactive(text: str) -> str:
    """Keep only interactive elements and meaningful content.

    Amazon puts [ref=] on *everything* including wrapper <div>s.  A blanket
    "keep anything with a ref" rule keeps 100+ structural wrappers like
    ``generic [ref=e2]:`` that waste the snapshot budget.

    Strategy (mirrors OpenClaw compact + interactive mode):
    1. Interactive roles (button, link, textbox…) → always keep
    2. Context roles (heading, img, table…) → keep if named
    3. Structural wrappers (generic, group, banner…) → keep ONLY if named
    4. Other lines with a quoted name under 120 chars → keep (prices, labels)
    5. Everything else → strip
    """
    lines = text.split("\n")
    result: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 1. Interactive roles — always keep (with or without ref)
        if _INTERACTIVE_ROLES.match(line):
            result.append(line)
            continue

        # 2. Context roles (headings, images, tables) — keep if named
        if _CONTEXT_ROLES.match(line):
            if _HAS_QUOTED_NAME.search(line):
                result.append(line)
            continue

        # 3. Structural wrappers — only keep if they have a semantic name
        #    e.g. keep: navigation "Primary"  |  skip: generic [ref=e2]:
        if _STRUCTURAL_WRAPPER_ROLES.match(line):
            if _HAS_QUOTED_NAME.search(line):
                result.append(line)
            continue

        # 4. Other lines with short quoted names (prices, labels, status text)
        if stripped.startswith("- ") and _HAS_QUOTED_NAME.search(line):
            if len(stripped) < 120:
                result.append(line)
                continue

    return "\n".join(result)


def compact(text: str) -> str:
    """Remove empty containers and collapse whitespace (OpenClaw-style).

    Goes beyond simple blank-line removal:
    1. Lines ending with ``:`` that have NO interactive children → strip
    2. Consecutive blank lines → collapse to one
    3. Trailing whitespace → strip

    This removes wrapper containers like ``- navigation "Primary":``
    when all their children were already stripped by filter_interactive.
    """
    lines = text.split("\n")

    # Pass 1: mark lines that are structural containers (end with `:`)
    # with no interactive children (lines containing [ref=e) below them.
    keep = [True] * len(lines)
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if not stripped:
            continue
        # Structural container lines end with `:`
        if not stripped.endswith(":"):
            continue
        # Check if any deeper-indented child has a ref
        current_indent = len(line) - len(line.lstrip())
        has_relevant_child = False
        for j in range(i + 1, len(lines)):
            child = lines[j]
            if not child.strip():
                continue
            child_indent = len(child) - len(child.lstrip())
            if child_indent <= current_indent:
                break  # Back at same/lower indent — block ended
            if "[ref=e" in child or _HAS_QUOTED_NAME.search(child):
                has_relevant_child = True
                break
        if not has_relevant_child:
            keep[i] = False

    # Pass 2: build result, collapsing blank lines
    result: List[str] = []
    prev_empty = False
    for i, line in enumerate(lines):
        if not keep[i]:
            continue
        if not line.strip():
            if not prev_empty:
                result.append("")
            prev_empty = True
            continue
        prev_empty = False
        result.append(line)

    return "\n".join(result).strip()


def limit_depth(text: str, max_depth: int = EFFICIENT_MAX_DEPTH) -> str:
    """Remove lines nested deeper than max_depth levels."""
    max_indent = max_depth * _INDENT_UNIT
    lines = text.split("\n")
    result: List[str] = []

    for line in lines:
        indent = len(line) - len(line.lstrip())
        if indent <= max_indent:
            result.append(line)

    return "\n".join(result)


def truncate_snapshot(text: str, max_chars: Optional[int] = None) -> str:
    """Cap snapshot text to the given limit."""
    limit = max_chars if max_chars is not None else MAX_SNAPSHOT_CHARS
    if len(text) <= limit:
        return text
    return text[:limit] + _TRUNCATION_NOTICE


def dedup_snapshot(user_id: str, text: str) -> str:
    """Return short placeholder if the snapshot is identical to the last one."""
    h = hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()
    prev = _last_snapshot_hash.get(user_id)
    _last_snapshot_hash[user_id] = h
    if prev == h:
        return _UNCHANGED_MSG
    return text


def prepare_snapshot(
    user_id: str,
    raw_text: str,
    *,
    efficient: bool = True,
    deduplicate: bool = True,
) -> str:
    """Full snapshot processing pipeline for LLM context.

    Args:
        user_id: For deduplication state.
        raw_text: Raw snapshot from sidecar (after sanitize_snapshot).
        efficient: If True (default), apply interactive filter + compact +
            depth limit + 12K cap.  If False, just boilerplate strip + 30K cap.
        deduplicate: If True (default), dedup identical consecutive snapshots.

    Call this *after* sanitize_snapshot() and *before* building the message.
    The full (unsanitized) text should still be cached separately for the
    action guard / login tool.
    """
    text = strip_boilerplate(raw_text)

    if efficient:
        text = filter_interactive(text)
        text = limit_depth(text)
        text = compact(text)
        text = truncate_snapshot(text, MAX_SNAPSHOT_CHARS)
    else:
        text = truncate_snapshot(text, MAX_SNAPSHOT_CHARS_FULL)

    if deduplicate:
        text = dedup_snapshot(user_id, text)

    return text


def clear_user(user_id: str) -> None:
    """Clean up dedup state for a user (call at session end)."""
    _last_snapshot_hash.pop(user_id, None)
