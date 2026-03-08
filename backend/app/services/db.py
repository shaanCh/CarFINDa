"""
Listing persistence service — Supabase PostgREST backend.

Handles upsert of scraped listings, score caching, search session tracking,
price history, and cached search retrieval. Follows the same httpx/PostgREST
pattern as ConversationStore.

All write methods fail gracefully (log + continue) so the search pipeline
keeps working even if the DB is unreachable.
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50


class ListingDB:
    """Async Supabase PostgREST client for listing persistence."""

    def __init__(self, supabase_url: str, service_role_key: str):
        self._rest_url = f"{supabase_url.rstrip('/')}/rest/v1"
        self._headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------

    async def upsert_listings(self, listings: list[dict]) -> dict[str, str]:
        """Upsert scraped listings into the DB.

        Listings with a VIN are upserted (dedup on VIN).
        Listings without a VIN are inserted as new rows.

        Returns a mapping of scraper_id -> db_id so callers can
        remap IDs to the stable DB primary keys.
        """
        id_map: dict[str, str] = {}
        if not listings:
            return id_map

        with_vin = [l for l in listings if l.get("vin")]
        without_vin = [l for l in listings if not l.get("vin")]

        # Batch upsert VIN-present listings
        for i in range(0, len(with_vin), _BATCH_SIZE):
            batch = with_vin[i : i + _BATCH_SIZE]
            rows = [_listing_to_row(l) for l in batch]
            try:
                resp = await self._client.post(
                    f"{self._rest_url}/listings",
                    json=rows,
                    headers={
                        **self._headers,
                        "Prefer": "return=representation,resolution=merge-duplicates",
                    },
                    params={"on_conflict": "vin"},
                )
                resp.raise_for_status()
                db_rows = resp.json()
                for orig, db_row in zip(batch, db_rows):
                    id_map[orig["id"]] = db_row["id"]
            except Exception as exc:
                logger.error("Failed to upsert VIN listings batch: %s", exc)
                for l in batch:
                    id_map[l["id"]] = l["id"]

        # Insert VIN-absent listings
        for i in range(0, len(without_vin), _BATCH_SIZE):
            batch = without_vin[i : i + _BATCH_SIZE]
            rows = [_listing_to_row(l) for l in batch]
            try:
                resp = await self._client.post(
                    f"{self._rest_url}/listings",
                    json=rows,
                )
                resp.raise_for_status()
                db_rows = resp.json()
                for orig, db_row in zip(batch, db_rows):
                    id_map[orig["id"]] = db_row["id"]
            except Exception as exc:
                logger.error("Failed to insert non-VIN listings batch: %s", exc)
                for l in batch:
                    id_map[l["id"]] = l["id"]

        logger.info(
            "Upserted %d listings (%d with VIN, %d without)",
            len(id_map), len(with_vin), len(without_vin),
        )
        return id_map

    async def get_listing(self, listing_id: str) -> Optional[dict]:
        """Fetch a single listing + score from the DB."""
        try:
            resp = await self._client.get(
                f"{self._rest_url}/listings",
                params={"id": f"eq.{listing_id}", "select": "*"},
            )
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                return None

            listing = rows[0]

            # Fetch score
            score_resp = await self._client.get(
                f"{self._rest_url}/listing_scores",
                params={"listing_id": f"eq.{listing_id}", "select": "*"},
            )
            score_resp.raise_for_status()
            scores = score_resp.json()
            score = scores[0] if scores else None

            return {"listing": listing, "score": score}
        except Exception as exc:
            logger.error("Failed to fetch listing %s: %s", listing_id, exc)
            return None

    # ------------------------------------------------------------------
    # Scores
    # ------------------------------------------------------------------

    async def upsert_scores(self, scores: list[dict]) -> None:
        """Bulk upsert listing scores."""
        if not scores:
            return

        for i in range(0, len(scores), _BATCH_SIZE):
            batch = scores[i : i + _BATCH_SIZE]
            try:
                resp = await self._client.post(
                    f"{self._rest_url}/listing_scores",
                    json=batch,
                    headers={
                        **self._headers,
                        "Prefer": "return=minimal,resolution=merge-duplicates",
                    },
                    params={"on_conflict": "listing_id"},
                )
                resp.raise_for_status()
            except Exception as exc:
                logger.error("Failed to upsert scores batch: %s", exc)

    async def get_fresh_scores(
        self, listing_ids: list[str], max_age_hours: int = 6,
    ) -> dict[str, dict]:
        """Return cached scores for listings scored within max_age_hours."""
        if not listing_ids:
            return {}

        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        ).isoformat()

        result: dict[str, dict] = {}
        # PostgREST in() filter has URL length limits, so batch
        for i in range(0, len(listing_ids), _BATCH_SIZE):
            batch = listing_ids[i : i + _BATCH_SIZE]
            ids_csv = ",".join(batch)
            try:
                resp = await self._client.get(
                    f"{self._rest_url}/listing_scores",
                    params={
                        "listing_id": f"in.({ids_csv})",
                        "scored_at": f"gt.{cutoff}",
                        "select": "*",
                    },
                )
                resp.raise_for_status()
                for row in resp.json():
                    result[row["listing_id"]] = row
            except Exception as exc:
                logger.error("Failed to fetch cached scores: %s", exc)

        return result

    # ------------------------------------------------------------------
    # Search sessions
    # ------------------------------------------------------------------

    async def create_search_session(
        self, user_id: str, query_text: str, parsed_filters: dict,
    ) -> str:
        """Create a new search session and return its ID."""
        session_id = str(uuid.uuid4())
        try:
            resp = await self._client.post(
                f"{self._rest_url}/search_sessions",
                json={
                    "id": session_id,
                    "user_id": user_id,
                    "query_text": query_text,
                    "parsed_filters": parsed_filters,
                    "status": "scraping",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Failed to create search session: %s", exc)
        return session_id

    async def complete_search_session(
        self, session_id: str, results_count: int,
    ) -> None:
        """Mark a search session as complete."""
        try:
            resp = await self._client.patch(
                f"{self._rest_url}/search_sessions",
                params={"id": f"eq.{session_id}"},
                json={
                    "status": "complete",
                    "results_count": results_count,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Failed to complete search session: %s", exc)

    async def link_search_listings(
        self, search_id: str, listing_ids: list[str],
    ) -> None:
        """Link listings to a search session via junction table."""
        if not listing_ids:
            return

        rows = [
            {"search_id": search_id, "listing_id": lid, "rank": rank}
            for rank, lid in enumerate(listing_ids, 1)
        ]
        for i in range(0, len(rows), _BATCH_SIZE):
            batch = rows[i : i + _BATCH_SIZE]
            try:
                resp = await self._client.post(
                    f"{self._rest_url}/search_listings",
                    json=batch,
                    headers={**self._headers, "Prefer": "return=minimal"},
                )
                resp.raise_for_status()
            except Exception as exc:
                logger.error("Failed to link search listings: %s", exc)

    # ------------------------------------------------------------------
    # Cache lookup
    # ------------------------------------------------------------------

    async def find_cached_search(
        self, parsed_filters: dict, max_age_minutes: int = 60,
    ) -> Optional[str]:
        """Find a recent search session with identical filters.

        Returns the session ID if found, else None.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        ).isoformat()

        # Canonical JSON for exact JSONB match
        canonical = json.dumps(parsed_filters, sort_keys=True)

        try:
            resp = await self._client.get(
                f"{self._rest_url}/search_sessions",
                params={
                    "status": "eq.complete",
                    "created_at": f"gt.{cutoff}",
                    "parsed_filters": f"eq.{canonical}",
                    "order": "created_at.desc",
                    "limit": "1",
                    "select": "id,results_count",
                },
            )
            resp.raise_for_status()
            rows = resp.json()
            if rows and rows[0].get("results_count", 0) > 0:
                logger.info("Cache hit: session %s", rows[0]["id"])
                return rows[0]["id"]
        except Exception as exc:
            logger.error("Cache lookup failed: %s", exc)

        return None

    async def get_cached_results(self, session_id: str) -> list[dict]:
        """Fetch full listing+score data for a cached search session."""
        try:
            # Get listing IDs + ranks from junction table
            resp = await self._client.get(
                f"{self._rest_url}/search_listings",
                params={
                    "search_id": f"eq.{session_id}",
                    "select": "listing_id,rank",
                    "order": "rank.asc",
                },
            )
            resp.raise_for_status()
            junctions = resp.json()
            if not junctions:
                return []

            listing_ids = [j["listing_id"] for j in junctions]
            ids_csv = ",".join(listing_ids)

            # Fetch listings
            list_resp = await self._client.get(
                f"{self._rest_url}/listings",
                params={"id": f"in.({ids_csv})", "select": "*"},
            )
            list_resp.raise_for_status()
            listings_by_id = {r["id"]: r for r in list_resp.json()}

            # Fetch scores
            score_resp = await self._client.get(
                f"{self._rest_url}/listing_scores",
                params={"listing_id": f"in.({ids_csv})", "select": "*"},
            )
            score_resp.raise_for_status()
            scores_by_id = {r["listing_id"]: r for r in score_resp.json()}

            # Combine in rank order
            results = []
            for j in junctions:
                lid = j["listing_id"]
                listing = listings_by_id.get(lid)
                if not listing:
                    continue
                score = scores_by_id.get(lid)
                results.append({
                    **listing,
                    "score": _db_score_to_dict(score) if score else {},
                })

            return results

        except Exception as exc:
            logger.error("Failed to fetch cached results: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    async def record_price_changes(
        self, listing_id: str, price: float, source_name: str,
    ) -> None:
        """Record a price observation in the price_history table."""
        if not price or price <= 0:
            return
        try:
            resp = await self._client.post(
                f"{self._rest_url}/price_history",
                json={
                    "id": str(uuid.uuid4()),
                    "listing_id": listing_id,
                    "price": float(price),
                    "source_name": source_name,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                },
                headers={**self._headers, "Prefer": "return=minimal"},
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Failed to record price history: %s", exc)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _listing_to_row(listing: dict) -> dict:
    """Map a scraper output dict to a DB listings row."""
    now = datetime.now(timezone.utc).isoformat()
    sources = listing.get("sources") or []
    if not sources and listing.get("source_name"):
        sources = [{
            "name": listing.get("source_name"),
            "url": listing.get("source_url"),
            "price": listing.get("price"),
        }]

    return {
        "id": listing.get("id") or str(uuid.uuid4()),
        "vin": listing.get("vin") or None,
        "year": listing.get("year"),
        "make": listing.get("make"),
        "model": listing.get("model"),
        "trim": listing.get("trim"),
        "price": float(listing["price"]) if listing.get("price") else None,
        "mileage": listing.get("mileage"),
        "location": listing.get("location"),
        "exterior_color": listing.get("exterior_color"),
        "interior_color": listing.get("interior_color"),
        "fuel_type": listing.get("fuel_type"),
        "transmission": listing.get("transmission"),
        "drivetrain": listing.get("drivetrain"),
        "image_urls": listing.get("image_urls") or [],
        "sources": json.dumps(sources),
        "last_seen_at": now,
    }


def _db_score_to_dict(score_row: dict) -> dict:
    """Map a listing_scores DB row to the calculator's dict format."""
    return {
        "safety_score": float(score_row.get("safety_score") or 0),
        "reliability_score": float(score_row.get("reliability_score") or 0),
        "value_score": float(score_row.get("value_score") or 0),
        "efficiency_score": float(score_row.get("efficiency_score") or 0),
        "ownership_cost_score": 50.0,  # not stored separately
        "recall_score": float(score_row.get("recall_penalty") or 0),
        "composite_score": float(score_row.get("composite_score") or 0),
        "breakdown": score_row.get("breakdown") or {},
    }


def score_dict_to_row(listing_id: str, score: dict) -> dict:
    """Map a scoring pipeline output dict to a listing_scores DB row."""
    return {
        "id": str(uuid.uuid4()),
        "listing_id": listing_id,
        "safety_score": score.get("safety_score", 0),
        "reliability_score": score.get("reliability_score", 0),
        "value_score": score.get("value_score", 0),
        "efficiency_score": score.get("efficiency_score", 0),
        "recall_penalty": score.get("recall_score", 0),
        "composite_score": score.get("composite_score", 0),
        "breakdown": json.dumps(score.get("breakdown", {})),
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
