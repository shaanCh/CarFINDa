"""
Intake Agent — Re-exports the Gemini-based preference parser.

The actual implementation lives in app.services.llm.intake_agent.
This module exists for backwards-compatible imports from the scraping package.
"""

from app.services.llm.intake_agent import parse_preferences

__all__ = ["parse_preferences"]
