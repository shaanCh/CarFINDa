"""
Browser Agent — Gemini-driven agent loop for browser automation.

Unlike the scrapers (which follow hardcoded URL patterns), the browser agent
uses Gemini to reason about what it sees on screen and decide what to do next.
This makes it adaptive to UI changes and capable of complex multi-step flows:

- Logging into Facebook with stored credentials
- Navigating 2FA prompts
- Sending DMs to sellers with personalized negotiation messages
- Checking Messenger inbox for replies
- Filling out dealer contact forms

The agent loop: snapshot → Gemini decides action → execute → snapshot → repeat.
"""

import asyncio
import json
import logging
from typing import Any, Optional

from app.config import get_settings
from app.services.llm.gemini_client import GeminiClient
from app.services.scraping.browser_client import BrowserClient

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """\
You are CarFINDa's Browser Agent. You control a real Chromium browser via tools.
You can see pages as AI-readable text snapshots with element refs like [e5], [e12].

## Available Actions (respond with ONE JSON action per turn)

- {"action": "navigate", "url": "https://..."}
- {"action": "click", "ref": "e5"}
- {"action": "type", "ref": "e5", "text": "hello"}
- {"action": "press", "key": "Enter"}
- {"action": "scroll", "direction": "down"}
- {"action": "snapshot"} — re-read current page
- {"action": "wait", "seconds": 2}
- {"action": "done", "result": "..."} — task complete, describe what happened
- {"action": "error", "message": "..."} — task failed, explain why

## Rules

1. ALWAYS read the snapshot carefully before acting. Element refs like [e5] are your targets.
2. One action per response. You'll get the result and a new snapshot, then decide the next action.
3. For login flows: find the email input ref, type email, find password ref, type password, click login.
4. For messaging: find the message input/compose box ref, type the message, press Enter or click Send.
5. After important actions (login, send message), take a snapshot to verify the result.
6. If you see a 2FA/verification prompt, report it with {"action": "needs_input", "input_type": "2fa", "message": "..."}.
7. If you see a CAPTCHA, report it with {"action": "needs_input", "input_type": "captcha", "message": "..."}.
8. Never guess or hallucinate element refs. Only use refs you see in the current snapshot.
9. Be efficient — don't take unnecessary snapshots between simple sequential actions.
10. When typing credentials, NEVER include them in your reasoning text — only in the type action.

## Response Format

Respond with ONLY a JSON object. No markdown, no explanation outside the JSON.
"""


class BrowserAgent:
    """Gemini-driven agent that controls a browser to complete tasks."""

    def __init__(
        self,
        browser: BrowserClient,
        profile: str = "carfinda-agent",
        max_steps: int = 25,
    ):
        self.browser = browser
        self.profile = profile
        self.max_steps = max_steps
        self._gemini: Optional[GeminiClient] = None

    def _get_gemini(self) -> GeminiClient:
        if self._gemini is None:
            settings = get_settings()
            self._gemini = GeminiClient(api_key=settings.GEMINI_API_KEY)
        return self._gemini

    async def run(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the agent loop to complete a task.

        Args:
            task:    Natural language description of what to do.
                     e.g. "Log into Facebook with the provided credentials"
                     e.g. "Send this message to the seller on this listing page"
            context: Additional context dict. Can include:
                     - email/password for login tasks
                     - message text for DM tasks
                     - listing_url for navigation
                     - Any other relevant data

        Returns:
            Dict with: success (bool), result (str), steps (int),
                       needs_input (dict|None for 2FA etc.)
        """
        await self.browser.start_session(self.profile)

        gemini = self._get_gemini()
        messages: list[dict] = []

        # Build initial prompt with task + context
        context_str = ""
        if context:
            # Redact passwords from the context description shown to the model
            safe_context = {
                k: ("***" if "password" in k.lower() else v)
                for k, v in context.items()
            }
            context_str = f"\n\nContext: {json.dumps(safe_context, indent=2)}"

        # Get initial page state
        snapshot = await self.browser.snapshot(self.profile)

        initial_prompt = (
            f"## Task\n{task}{context_str}\n\n"
            f"## Current Page Snapshot\n{self._truncate(snapshot)}\n\n"
            f"What's your first action?"
        )
        messages.append({"role": "user", "content": initial_prompt})

        steps = 0
        while steps < self.max_steps:
            steps += 1

            # Ask Gemini for next action
            response_text = await gemini.chat(
                messages=messages,
                system_instruction=AGENT_SYSTEM_PROMPT,
                temperature=0.2,
            )

            messages.append({"role": "model", "content": response_text})

            # Parse the action
            action = self._parse_action(response_text)
            if not action:
                logger.warning("Agent returned unparseable response: %s", response_text[:200])
                messages.append({
                    "role": "user",
                    "content": "Your response was not valid JSON. Respond with ONLY a JSON action object.",
                })
                continue

            action_type = action.get("action")
            logger.info("Agent step %d: %s", steps, action_type)

            # Handle terminal actions
            if action_type == "done":
                return {
                    "success": True,
                    "result": action.get("result", "Task completed"),
                    "steps": steps,
                    "needs_input": None,
                }

            if action_type == "error":
                return {
                    "success": False,
                    "result": action.get("message", "Task failed"),
                    "steps": steps,
                    "needs_input": None,
                }

            if action_type == "needs_input":
                return {
                    "success": False,
                    "result": action.get("message", "User input required"),
                    "steps": steps,
                    "needs_input": {
                        "input_type": action.get("input_type", "unknown"),
                        "message": action.get("message", ""),
                    },
                }

            # Execute the action
            result_text = await self._execute_action(action, context)

            # Feed result back to agent
            messages.append({"role": "user", "content": result_text})

        return {
            "success": False,
            "result": f"Agent exceeded max steps ({self.max_steps})",
            "steps": steps,
            "needs_input": None,
        }

    async def resume(
        self,
        task: str,
        user_input: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resume an agent task after user provided input (e.g. 2FA code).

        Args:
            task:       Original task description.
            user_input: The input the user provided (2FA code, CAPTCHA solution, etc.)
            context:    Same context as the original run.

        Returns:
            Same return format as run().
        """
        await self.browser.start_session(self.profile)

        # Type the user input into whatever field is currently focused/active
        snapshot = await self.browser.snapshot(self.profile)

        resume_task = (
            f"## Original Task\n{task}\n\n"
            f"## User Provided Input\nThe user provided this input: {user_input}\n"
            f"Find the appropriate input field on the current page and enter it, then continue the original task.\n\n"
            f"## Current Page Snapshot\n{self._truncate(snapshot)}"
        )

        return await self.run(resume_task, context)

    async def _execute_action(
        self,
        action: dict,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Execute a browser action and return a description of the result."""
        action_type = action.get("action")

        try:
            if action_type == "navigate":
                url = action.get("url", "")
                result = await self.browser.navigate(self.profile, url)
                snapshot = result.get("snapshot", "")
                return f"Navigated to {url}.\n\n## Page Snapshot\n{self._truncate(snapshot)}"

            elif action_type == "click":
                ref = action.get("ref", "")
                await self.browser.act(self.profile, "click", ref=ref)
                await asyncio.sleep(1.0)
                snapshot = await self.browser.snapshot(self.profile)
                return f"Clicked [{ref}].\n\n## Page Snapshot\n{self._truncate(snapshot)}"

            elif action_type == "type":
                ref = action.get("ref", "")
                text = action.get("text", "")
                # If the agent is typing a credential placeholder, swap in the real value
                if context and text in ("{{email}}", "{{password}}"):
                    key = "email" if text == "{{email}}" else "password"
                    text = context.get(key, text)
                await self.browser.act(self.profile, "type", ref=ref, text=text)
                return f"Typed text into [{ref}]. (Content not echoed for security)"

            elif action_type == "press":
                key = action.get("key", "Enter")
                await self.browser.act(self.profile, "press", key=key)
                await asyncio.sleep(1.0)
                snapshot = await self.browser.snapshot(self.profile)
                return f"Pressed {key}.\n\n## Page Snapshot\n{self._truncate(snapshot)}"

            elif action_type == "scroll":
                direction = action.get("direction", "down")
                await self.browser.act(self.profile, "scroll", direction=direction)
                await asyncio.sleep(0.5)
                snapshot = await self.browser.snapshot(self.profile)
                return f"Scrolled {direction}.\n\n## Page Snapshot\n{self._truncate(snapshot)}"

            elif action_type == "snapshot":
                snapshot = await self.browser.snapshot(self.profile)
                return f"## Page Snapshot\n{self._truncate(snapshot)}"

            elif action_type == "wait":
                seconds = min(action.get("seconds", 2), 10)
                await asyncio.sleep(seconds)
                snapshot = await self.browser.snapshot(self.profile)
                return f"Waited {seconds}s.\n\n## Page Snapshot\n{self._truncate(snapshot)}"

            else:
                return f"Unknown action type: {action_type}"

        except Exception as exc:
            logger.error("Action %s failed: %s", action_type, exc)
            return f"Action '{action_type}' failed with error: {exc}"

    def _parse_action(self, text: str) -> Optional[dict]:
        """Extract a JSON action object from the model's response."""
        text = text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON within the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        return None

    def _truncate(self, text: str, max_chars: int = 30_000) -> str:
        """Truncate snapshot text to stay within context limits."""
        if len(text) > max_chars:
            return text[:max_chars] + "\n... (truncated)"
        return text
