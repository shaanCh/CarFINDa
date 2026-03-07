"""
Browser service package — browser automation agent, tools, and supporting services.

Key components:
- agent.py           — Gemini-driven agentic loop (snapshot → reason → act → repeat)
- tools/             — Individual browser tool classes (navigate, act, snapshot, etc.)
- login_patterns.py  — Regex helpers for login form detection
- snapshot_context.py — Snapshot processing pipeline for LLM context management
- control_gateway.py — Gateway service to the Playwright sidecar
- url_security.py    — URL validation and snapshot sanitization
"""

from app.services.browser.agent import BrowserAgent

__all__ = ["BrowserAgent"]
