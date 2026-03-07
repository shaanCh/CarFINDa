"""
Preference Tracker — Tracks how user preferences evolve over time.

Records preference snapshots from explicit user input and inferred behavior,
then generates human-readable insights about how preferences have changed.
This enables the agent to make smarter suggestions like:
"You initially wanted SUVs under $18K but your last 3 searches expanded to
include sedans. Want me to include sedans this time?"

Uses direct Supabase REST (PostgREST) calls via httpx.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class PreferenceTracker:
    """Tracks user preference changes over time to provide better recommendations."""

    def __init__(self, supabase_url: str, supabase_key: str):
        """Initialize the preference tracker with Supabase credentials.

        Args:
            supabase_url: The Supabase project URL.
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

    async def record_preferences(
        self,
        user_id: str,
        preferences: dict,
        source: str = "explicit",
    ) -> None:
        """Record a preference snapshot.

        Args:
            user_id:     The user's UUID.
            preferences: Dict of current preferences (budget, makes, types, etc.).
            source:      'explicit' if the user directly set preferences,
                         'inferred' if derived from search behavior.
        """
        if source not in ("explicit", "inferred"):
            raise ValueError(f"Invalid source: {source!r}. Must be 'explicit' or 'inferred'.")

        payload = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "preferences": preferences,
            "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            resp = await self._client.post(
                f"{self._rest_url}/preference_history",
                json=payload,
            )
            resp.raise_for_status()
            logger.debug(
                "Recorded %s preferences for user=%s: %s",
                source, user_id, list(preferences.keys()),
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Failed to record preferences: %s %s",
                exc.response.status_code, exc.response.text,
            )
            raise
        except httpx.HTTPError as exc:
            logger.error("HTTP error recording preferences: %s", exc)
            raise

    async def get_preference_history(self, user_id: str) -> list[dict]:
        """Get the full preference evolution timeline for a user.

        Args:
            user_id: The user's UUID.

        Returns:
            List of preference snapshot dicts ordered by created_at ascending,
            each containing: id, preferences, source, created_at.
        """
        params = {
            "user_id": f"eq.{user_id}",
            "order": "created_at.asc",
            "select": "id,preferences,source,created_at",
        }

        try:
            resp = await self._client.get(
                f"{self._rest_url}/preference_history",
                params=params,
            )
            resp.raise_for_status()
            history = resp.json()
            logger.debug(
                "Retrieved %d preference snapshots for user=%s",
                len(history), user_id,
            )
            return history
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Failed to get preference history: %s %s",
                exc.response.status_code, exc.response.text,
            )
            return []
        except httpx.HTTPError as exc:
            logger.error("HTTP error getting preference history: %s", exc)
            return []

    async def get_preference_insights(self, user_id: str) -> list[str]:
        """Generate insights about preference changes over time.

        Analyzes the preference history to detect trends and changes,
        returning human-readable insight strings the agent can relay to the user.

        Args:
            user_id: The user's UUID.

        Returns:
            List of human-readable insight strings. Empty list if insufficient
            history to generate insights.
        """
        history = await self.get_preference_history(user_id)

        if len(history) < 2:
            return []

        insights: list[str] = []
        earliest = history[0]
        latest = history[-1]
        earliest_prefs = earliest.get("preferences", {})
        latest_prefs = latest.get("preferences", {})

        # --- Budget changes ---
        early_budget_max = earliest_prefs.get("budget_max")
        latest_budget_max = latest_prefs.get("budget_max")
        if early_budget_max is not None and latest_budget_max is not None:
            if latest_budget_max > early_budget_max:
                insights.append(
                    f"Your budget has increased from "
                    f"${early_budget_max:,.0f} to ${latest_budget_max:,.0f} "
                    f"over your search history."
                )
            elif latest_budget_max < early_budget_max:
                insights.append(
                    f"Your budget has decreased from "
                    f"${early_budget_max:,.0f} to ${latest_budget_max:,.0f} "
                    f"over your search history."
                )

        early_budget_min = earliest_prefs.get("budget_min")
        latest_budget_min = latest_prefs.get("budget_min")
        if early_budget_min is not None and latest_budget_min is not None:
            if latest_budget_min != early_budget_min:
                insights.append(
                    f"Your minimum budget shifted from "
                    f"${early_budget_min:,.0f} to ${latest_budget_min:,.0f}."
                )

        # --- Vehicle type changes ---
        early_types = set(earliest_prefs.get("vehicle_types", []))
        latest_types = set(latest_prefs.get("vehicle_types", []))
        if early_types and latest_types:
            added_types = latest_types - early_types
            removed_types = early_types - latest_types
            if added_types:
                insights.append(
                    f"You've expanded your vehicle type preferences to include: "
                    f"{', '.join(sorted(added_types))}."
                )
            if removed_types:
                insights.append(
                    f"You've narrowed your vehicle type preferences, "
                    f"dropping: {', '.join(sorted(removed_types))}."
                )

        # --- Make preferences ---
        early_makes = set(earliest_prefs.get("preferred_makes", []))
        latest_makes = set(latest_prefs.get("preferred_makes", []))
        if early_makes and latest_makes:
            added_makes = latest_makes - early_makes
            removed_makes = early_makes - latest_makes
            if added_makes:
                insights.append(
                    f"You've added new preferred makes: "
                    f"{', '.join(sorted(added_makes))}."
                )
            if removed_makes:
                insights.append(
                    f"You've removed these makes from your preferences: "
                    f"{', '.join(sorted(removed_makes))}."
                )

        # --- Mileage threshold ---
        early_mileage = earliest_prefs.get("max_mileage")
        latest_mileage = latest_prefs.get("max_mileage")
        if early_mileage is not None and latest_mileage is not None:
            if latest_mileage > early_mileage:
                insights.append(
                    f"You've relaxed your mileage limit from "
                    f"{early_mileage:,} to {latest_mileage:,} miles."
                )
            elif latest_mileage < early_mileage:
                insights.append(
                    f"You've tightened your mileage limit from "
                    f"{early_mileage:,} to {latest_mileage:,} miles."
                )

        # --- Year preferences ---
        early_year = earliest_prefs.get("min_year")
        latest_year = latest_prefs.get("min_year")
        if early_year is not None and latest_year is not None:
            if latest_year < early_year:
                insights.append(
                    f"You've started considering older vehicles "
                    f"(min year moved from {early_year} to {latest_year})."
                )
            elif latest_year > early_year:
                insights.append(
                    f"You've shifted toward newer vehicles "
                    f"(min year moved from {early_year} to {latest_year})."
                )

        # --- Location / radius ---
        early_radius = earliest_prefs.get("radius_miles")
        latest_radius = latest_prefs.get("radius_miles")
        if early_radius is not None and latest_radius is not None:
            if latest_radius > early_radius:
                insights.append(
                    f"Your search radius has expanded from "
                    f"{early_radius} to {latest_radius} miles."
                )
            elif latest_radius < early_radius:
                insights.append(
                    f"Your search radius has narrowed from "
                    f"{early_radius} to {latest_radius} miles."
                )

        # --- Inferred vs explicit ratio ---
        inferred_count = sum(1 for h in history if h.get("source") == "inferred")
        explicit_count = sum(1 for h in history if h.get("source") == "explicit")
        if inferred_count > explicit_count and inferred_count >= 3:
            insights.append(
                f"Most of your preference changes ({inferred_count} of "
                f"{len(history)}) were inferred from search behavior rather "
                f"than explicitly set."
            )

        # --- Recent trend detection (last 3 snapshots) ---
        if len(history) >= 3:
            recent = history[-3:]
            recent_budget_maxes = [
                h["preferences"].get("budget_max")
                for h in recent
                if h.get("preferences", {}).get("budget_max") is not None
            ]
            if len(recent_budget_maxes) == 3:
                if recent_budget_maxes[0] < recent_budget_maxes[1] < recent_budget_maxes[2]:
                    insights.append(
                        "Your budget has been steadily increasing over your last 3 searches."
                    )
                elif recent_budget_maxes[0] > recent_budget_maxes[1] > recent_budget_maxes[2]:
                    insights.append(
                        "Your budget has been steadily decreasing over your last 3 searches."
                    )

        return insights

    # ------------------------------------------------------------------
    # Current Preferences (from user_preferences table)
    # ------------------------------------------------------------------

    async def get_current_preferences(self, user_id: str) -> Optional[dict]:
        """Get the user's current saved preferences from the user_preferences table.

        Args:
            user_id: The user's UUID.

        Returns:
            Preference dict or None if no preferences are saved.
        """
        params = {
            "user_id": f"eq.{user_id}",
            "select": "*",
            "limit": "1",
        }

        try:
            resp = await self._client.get(
                f"{self._rest_url}/user_preferences",
                params=params,
            )
            resp.raise_for_status()
            results = resp.json()
            return results[0] if results else None
        except httpx.HTTPError as exc:
            logger.error("Failed to get current preferences: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "PreferenceTracker":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
