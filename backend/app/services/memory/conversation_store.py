"""
Conversation Store — Persistent conversation memory backed by Supabase.

Stores and retrieves conversation history, search results, and generates
context summaries so the agent can "remember" users across sessions.

Uses direct Supabase REST (PostgREST) calls via httpx since the Supabase
Python client is not yet configured.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class ConversationStore:
    """Stores and retrieves conversation history per user.

    Enables the agent to remember past interactions, preferences evolution,
    and previous search results across sessions.
    """

    def __init__(self, supabase_url: str, supabase_key: str):
        """Initialize the conversation store with Supabase credentials.

        Args:
            supabase_url: The Supabase project URL (e.g. https://xyz.supabase.co).
            supabase_key: The Supabase anon or service-role key.
        """
        self._base_url = supabase_url.rstrip("/")
        self._rest_url = f"{self._base_url}/rest/v1"
        self._headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    # ------------------------------------------------------------------
    # Conversation Messages
    # ------------------------------------------------------------------

    async def save_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Save a conversation message to the conversations table.

        Args:
            user_id:    The user's UUID.
            session_id: The current conversation session UUID.
            role:       One of 'user', 'assistant', or 'system'.
            content:    The message text.
            metadata:   Optional dict of extra info (e.g. parsed filters, tool calls).
        """
        if role not in ("user", "assistant", "system"):
            raise ValueError(f"Invalid role: {role!r}. Must be 'user', 'assistant', or 'system'.")

        payload = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            resp = await self._client.post(
                f"{self._rest_url}/conversations",
                json=payload,
            )
            resp.raise_for_status()
            logger.debug(
                "Saved %s message for user=%s session=%s (%d chars)",
                role, user_id, session_id, len(content),
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Failed to save message: %s %s",
                exc.response.status_code, exc.response.text,
            )
            raise
        except httpx.HTTPError as exc:
            logger.error("HTTP error saving message: %s", exc)
            raise

    async def get_history(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get conversation history for a user.

        If session_id is provided, returns messages from that session only.
        Otherwise returns the most recent messages across all sessions.

        Args:
            user_id:    The user's UUID.
            session_id: Optional session UUID to filter by.
            limit:      Maximum number of messages to return.

        Returns:
            List of message dicts ordered by created_at ascending.
        """
        params: dict[str, Any] = {
            "user_id": f"eq.{user_id}",
            "order": "created_at.asc",
            "limit": str(limit),
            "select": "id,session_id,role,content,metadata,created_at",
        }
        if session_id:
            params["session_id"] = f"eq.{session_id}"

        try:
            resp = await self._client.get(
                f"{self._rest_url}/conversations",
                params=params,
            )
            resp.raise_for_status()
            messages = resp.json()
            logger.debug(
                "Retrieved %d messages for user=%s session=%s",
                len(messages), user_id, session_id or "all",
            )
            return messages
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Failed to get history: %s %s",
                exc.response.status_code, exc.response.text,
            )
            return []
        except httpx.HTTPError as exc:
            logger.error("HTTP error getting history: %s", exc)
            return []

    async def get_context_summary(self, user_id: str) -> str:
        """Generate a summary of the user's preferences evolution and past searches.

        Used to inject context into new conversations so the agent 'remembers'
        the user. Pulls recent conversations and search sessions to build a
        concise narrative.

        Args:
            user_id: The user's UUID.

        Returns:
            A human-readable summary string. Empty string if no history exists.
        """
        # Fetch recent conversations (last 100 messages across sessions)
        messages = await self.get_history(user_id, limit=100)
        if not messages:
            return ""

        # Fetch recent searches
        recent_searches = await self.get_recent_searches(user_id, limit=5)

        # Build the context summary
        parts: list[str] = []

        # Summarize session count and message volume
        session_ids = set(m.get("session_id") for m in messages if m.get("session_id"))
        parts.append(
            f"User has {len(session_ids)} previous conversation session(s) "
            f"with {len(messages)} total messages."
        )

        # Extract user messages to understand what they've been asking about
        user_messages = [m for m in messages if m.get("role") == "user"]
        if user_messages:
            # Take the last 10 user messages as representative queries
            recent_queries = [m["content"][:200] for m in user_messages[-10:]]
            parts.append("Recent user queries:")
            for i, query in enumerate(recent_queries, 1):
                parts.append(f"  {i}. {query}")

        # Summarize recent searches
        if recent_searches:
            parts.append(f"\nRecent searches ({len(recent_searches)}):")
            for search in recent_searches:
                filters = search.get("parsed_filters", {})
                status = search.get("status", "unknown")
                count = search.get("results_count", 0)
                query = search.get("query_text", "N/A")
                parts.append(
                    f"  - \"{query}\" -> {count} results ({status})"
                )
                if filters:
                    filter_summary = ", ".join(
                        f"{k}: {v}" for k, v in filters.items() if v is not None
                    )
                    if filter_summary:
                        parts.append(f"    Filters: {filter_summary}")

        # Extract any preference-related metadata from messages
        pref_messages = [
            m for m in messages
            if m.get("metadata") and m["metadata"].get("preferences")
        ]
        if pref_messages:
            latest_prefs = pref_messages[-1]["metadata"]["preferences"]
            parts.append(f"\nLatest known preferences: {latest_prefs}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Search Results
    # ------------------------------------------------------------------

    async def save_search_results(
        self,
        user_id: str,
        session_id: str,
        listings: list[dict],
    ) -> None:
        """Save search results as a system message for later reference in conversation.

        Stores a summary of the listings found so the agent can refer back to
        them in follow-up messages.

        Args:
            user_id:    The user's UUID.
            session_id: The search/conversation session UUID.
            listings:   List of listing dicts from the scraper pipeline.
        """
        if not listings:
            return

        # Build a compact summary of results for conversation context
        summaries = []
        for i, listing in enumerate(listings[:20], 1):  # Cap at 20 for context size
            year = listing.get("year", "?")
            make = listing.get("make", "?")
            model = listing.get("model", "?")
            price = listing.get("price")
            mileage = listing.get("mileage")
            location = listing.get("location", "")
            source = listing.get("source_name", "")

            price_str = f"${price:,.0f}" if price else "N/A"
            mileage_str = f"{mileage:,} mi" if mileage else "N/A"

            summaries.append(
                f"{i}. {year} {make} {model} - {price_str} - {mileage_str} - {location} ({source})"
            )

        content = f"Search results ({len(listings)} total):\n" + "\n".join(summaries)

        metadata = {
            "type": "search_results",
            "total_count": len(listings),
            "listing_ids": [l.get("id") for l in listings[:20] if l.get("id")],
        }

        await self.save_message(
            user_id=user_id,
            session_id=session_id,
            role="system",
            content=content,
            metadata=metadata,
        )

    async def get_recent_searches(self, user_id: str, limit: int = 5) -> list[dict]:
        """Get user's recent search sessions with summaries.

        Queries the search_sessions table for the user's most recent searches.

        Args:
            user_id: The user's UUID.
            limit:   Maximum number of search sessions to return.

        Returns:
            List of search session dicts with query_text, parsed_filters,
            status, results_count, and timestamps.
        """
        params = {
            "user_id": f"eq.{user_id}",
            "order": "created_at.desc",
            "limit": str(limit),
            "select": "id,query_text,parsed_filters,status,results_count,created_at,completed_at",
        }

        try:
            resp = await self._client.get(
                f"{self._rest_url}/search_sessions",
                params=params,
            )
            resp.raise_for_status()
            sessions = resp.json()
            logger.debug(
                "Retrieved %d recent searches for user=%s",
                len(sessions), user_id,
            )
            return sessions
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Failed to get recent searches: %s %s",
                exc.response.status_code, exc.response.text,
            )
            return []
        except httpx.HTTPError as exc:
            logger.error("HTTP error getting recent searches: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "ConversationStore":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
