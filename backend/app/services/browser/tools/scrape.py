"""
Browser Scrape Tool

Automation-friendly wrapper around BrowserAgent.
Delegates a natural-language browsing task to the full agentic loop
(navigate, login, interact, extract) and returns structured results.

Designed for use in automation workflow steps where pre-planned
click/type sequences won't work — the BrowserAgent reasons through
each page dynamically.
"""

import logging
from typing import Any, Dict, Optional

from app.services.browser.tools.base import BaseTool, ToolParameter, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class BrowserScrapeTool(BaseTool):
    @classmethod
    def get_schema(cls) -> ToolSchema:
        return ToolSchema(
            name="browser.scrape",
            description=(
                "Browse a website and extract information using a full browser agent. "
                "Handles login, navigation, dynamic content, overlays, and multi-page "
                "flows automatically. Returns extracted data as text. "
                "Use for: scraping job boards, checking portal dashboards, reading "
                "authenticated pages, extracting listings or search results."
            ),
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description=(
                        "Starting URL to navigate to (must start with http/https)."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="instruction",
                    type="string",
                    description=(
                        "What to find or extract from the page. Be specific about "
                        "what data you need. Examples: 'Extract the latest 10 "
                        "software engineering internship postings with company, "
                        "title, location, and deadline', 'Check if there are any "
                        "new announcements on the dashboard'."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="login_site",
                    type="string",
                    description=(
                        "Domain of stored credentials to use for login "
                        "(e.g. 'joinhandshake.com'). Omit if no login needed."
                    ),
                    required=False,
                ),
            ],
            category="browser",
            execution_timeout=330,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        user_id: Optional[str] = kwargs.get("user_id")
        url: Optional[str] = kwargs.get("url")
        instruction: Optional[str] = kwargs.get("instruction")
        login_site: Optional[str] = kwargs.get("login_site")

        if not user_id:
            return ToolResult(
                success=False, error="Missing required parameter: user_id"
            )
        if not url:
            return ToolResult(success=False, error="Missing required parameter: url")
        if not instruction:
            return ToolResult(
                success=False, error="Missing required parameter: instruction"
            )

        # Build the full instruction for BrowserAgent
        parts = [f"Navigate to {url}."]
        if login_site:
            parts.append(
                f"The site requires login — use stored credentials for "
                f"'{login_site}' to log in first."
            )
        parts.append(instruction)
        parts.append(
            "Return ALL extracted data in detail — titles, dates, links, "
            "descriptions, and any other relevant fields. The caller cannot "
            "see the browser, so include everything."
        )
        full_instruction = " ".join(parts)

        try:
            from app.services.browser.agent import BrowserAgent
            from app.services.scraping.browser_client import BrowserClient
            from app.config import get_settings

            settings = get_settings()
            browser = BrowserClient(
                base_url=settings.SIDECAR_URL,
                token=settings.SIDECAR_TOKEN,
            )
            agent = BrowserAgent(
                browser=browser,
                profile=f"carfinda-{user_id[:8]}",
            )

            result = await agent.run(
                task=full_instruction,
                context={"user_id": user_id},
            )

            success = result.get("success", False)
            if success:
                logger.info("[BrowserScrape] Completed for user %s: %s", user_id, url)
            else:
                logger.warning(
                    "[BrowserScrape] Failed for user %s at %s: %s",
                    user_id, url, result.get("result"),
                )

            return ToolResult(
                success=success,
                data=result,
                message=result.get("result", ""),
                error=None if success else result.get("result"),
            )

        except Exception as e:
            logger.error(
                "[BrowserScrape] Unexpected error for %s: %s", url, e, exc_info=True,
            )
            return ToolResult(
                success=False,
                error=f"Browser scrape failed: {e}",
            )
