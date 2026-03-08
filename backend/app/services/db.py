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

    async def upsert_listings(self, listings: list[dict]) -> tuple[dict[str, str], set[str]]:
        """Upsert scraped listings into the DB.

        Listings with a VIN are upserted (dedup on VIN).
        Listings without a VIN are inserted as new rows.

        Returns (id_map, valid_ids) where:
          - id_map: scraper_id -> db_id for remapping
          - valid_ids: set of listing IDs that exist in DB (for FK-safe downstream writes)
        """
        id_map: dict[str, str] = {}
        valid_ids: set[str] = set()
        if not listings:
            return id_map, valid_ids

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
                    db_id = db_row["id"]
                    id_map[orig["id"]] = db_id
                    valid_ids.add(db_id)
            except Exception as exc:
                _log_httpx_error(exc, "upsert VIN listings")
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
                    db_id = db_row["id"]
                    id_map[orig["id"]] = db_id
                    valid_ids.add(db_id)
            except Exception as exc:
                _log_httpx_error(exc, "insert non-VIN listings")
                for l in batch:
                    id_map[l["id"]] = l["id"]

        logger.info(
            "Upserted %d listings (%d valid in DB, %d with VIN, %d without)",
            len(id_map), len(valid_ids), len(with_vin), len(without_vin),
        )
        return id_map, valid_ids

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

    async def upsert_scores(
        self, scores: list[dict],
        *,
        valid_listing_ids: Optional[set[str]] = None,
    ) -> None:
        """Bulk upsert listing scores.

        valid_listing_ids: if provided, only upsert scores for listings that exist (avoids FK 409).
        """
        if not scores:
            return

        to_upsert = scores
        if valid_listing_ids is not None:
            to_upsert = [s for s in scores if s.get("listing_id") in valid_listing_ids]

        for i in range(0, len(to_upsert), _BATCH_SIZE):
            batch = to_upsert[i : i + _BATCH_SIZE]
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
        self, user_id: Optional[str], query_text: str, parsed_filters: dict,
    ) -> str:
        """Create a new search session and return its ID.

        user_id: UUID from auth.users, or None for anonymous/dev.
        """
        session_id = str(uuid.uuid4())
        payload: dict = {
            "id": session_id,
            "query_text": query_text,
            "parsed_filters": parsed_filters,
            "status": "scraping",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if user_id:
            payload["user_id"] = user_id
        try:
            resp = await self._client.post(
                f"{self._rest_url}/search_sessions",
                json=payload,
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
        *,
        valid_listing_ids: Optional[set[str]] = None,
    ) -> None:
        """Link listings to a search session via junction table.

        valid_listing_ids: if provided, only link IDs that exist in listings (avoids FK 409).
        Deduplicates listing_ids and uses upsert to avoid duplicate-key 409.
        """
        if not listing_ids:
            return

        ids_to_link = list(dict.fromkeys(listing_ids))
        if valid_listing_ids is not None:
            ids_to_link = [lid for lid in ids_to_link if lid in valid_listing_ids]

        rows = [
            {"search_id": search_id, "listing_id": lid, "rank": rank}
            for rank, lid in enumerate(ids_to_link, 1)
        ]
        for i in range(0, len(rows), _BATCH_SIZE):
            batch = rows[i : i + _BATCH_SIZE]
            try:
                resp = await self._client.post(
                    f"{self._rest_url}/search_listings",
                    json=batch,
                    headers={
                        **self._headers,
                        "Prefer": "return=minimal,resolution=merge-duplicates",
                    },
                )
                resp.raise_for_status()
            except Exception as exc:
                logger.error("Failed to link search listings: %s", exc)

    # ------------------------------------------------------------------
    # Direct listing search (filter-based query)
    # ------------------------------------------------------------------

    async def search_listings(
        self,
        filters: dict[str, Any],
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query listings table with filters. Uses search_listings_filtered RPC.

        Returns list of dicts with listing fields + nested 'score' dict,
        compatible with _build_response in the search route.
        """
        try:
            body: dict[str, Any] = {"p_limit": limit}
            if filters.get("makes"):
                body["p_makes"] = [m.strip() for m in filters["makes"] if m]
            if filters.get("models"):
                body["p_models"] = [m.strip() for m in filters["models"] if m]
            if filters.get("budget_min") is not None:
                body["p_budget_min"] = float(filters["budget_min"])
            if filters.get("budget_max") is not None:
                body["p_budget_max"] = float(filters["budget_max"])
            if filters.get("min_year") is not None:
                body["p_min_year"] = int(filters["min_year"])
            if filters.get("max_mileage") is not None:
                body["p_max_mileage"] = int(filters["max_mileage"])
            if filters.get("location"):
                body["p_location"] = str(filters["location"]).strip()

            resp = await self._client.post(
                f"{self._rest_url}/rpc/search_listings_filtered",
                json=body,
            )
            if not resp.is_success:
                _log_httpx_response(resp, "search_listings_filtered")
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                return []

            # Convert flat RPC output to {listing fields} + {score} format
            results = []
            for r in rows:
                score = {
                    "safety_score": r.get("safety_score") or 0,
                    "reliability_score": r.get("reliability_score") or 0,
                    "value_score": r.get("value_score") or 0,
                    "efficiency_score": r.get("efficiency_score") or 0,
                    "recall_score": r.get("recall_penalty") or 0,
                    "composite_score": r.get("composite_score") or 0,
                    "breakdown": r.get("breakdown") or {},
                }
                listing = {
                    "id": r.get("id"),
                    "vin": r.get("vin"),
                    "year": r.get("year") or 0,
                    "make": r.get("make") or "Unknown",
                    "model": r.get("model") or "Unknown",
                    "trim": r.get("trim"),
                    "title": r.get("title"),
                    "price": r.get("price") or 0.0,
                    "mileage": r.get("mileage"),
                    "location": r.get("location"),
                    "source_url": r.get("source_url"),
                    "source_name": r.get("source_name") or "database",
                    "image_urls": r.get("image_urls") or [],
                    "exterior_color": r.get("exterior_color"),
                    "interior_color": r.get("interior_color"),
                    "fuel_type": r.get("fuel_type"),
                    "motor_type": r.get("motor_type"),
                    "transmission": r.get("transmission"),
                    "drivetrain": r.get("drivetrain"),
                }
                results.append({**listing, "score": score})
            return results
        except Exception as exc:
            logger.error("search_listings failed: %s", exc, exc_info=True)
            return []

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
        *,
        valid_listing_ids: Optional[set[str]] = None,
    ) -> None:
        """Record a price observation in the price_history table.

        valid_listing_ids: if provided, only record when listing_id exists (avoids FK 409).
        """
        if not price or price <= 0:
            return
        if valid_listing_ids is not None and listing_id not in valid_listing_ids:
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

def _log_httpx_error(exc: Exception, context: str) -> None:
    """Log httpx errors with response body when available."""
    if hasattr(exc, "response") and exc.response is not None:
        _log_httpx_response(exc.response, context)
    else:
        logger.error("Failed to %s: %s", context, exc)


def _log_httpx_response(resp: "httpx.Response", context: str) -> None:
    """Log HTTP response body for debugging 4xx/5xx."""
    try:
        body = resp.text
        if len(body) > 500:
            body = body[:500] + "..."
        logger.error(
            "Failed to %s: %d %s — %s",
            context, resp.status_code, resp.reason_phrase, body,
        )
    except Exception:
        logger.error("Failed to %s: %d %s", context, resp.status_code, resp.reason_phrase)


def _listing_to_row(listing: dict) -> dict:
    """Map a scraper output dict to a DB listings row.

    Matches actual Supabase schema: id, vin, year, make, model, title, price,
    mileage, location, detail_url, image_url, drivetrain, motor_type, transmission.
    """
    imgs = listing.get("image_urls") or []
    price_val = listing.get("price")
    mileage_val = listing.get("mileage")
    row = {
        "id": listing.get("id") or str(uuid.uuid4()),
        "vin": listing.get("vin") or None,
        "year": listing.get("year") or 0,
        "make": listing.get("make") or "Unknown",
        "model": listing.get("model") or "Unknown",
        "title": listing.get("title") or (f"{listing.get('year', '')} {listing.get('make', '')} {listing.get('model', '')}".strip() or "Vehicle"),
        "price": str(int(float(price_val))) if price_val is not None and price_val != "" else None,
        "mileage": str(int(mileage_val)) if mileage_val is not None and mileage_val != "" else None,
        "location": listing.get("location"),
        "detail_url": listing.get("source_url"),
        "image_url": imgs[0] if imgs else None,
        "drivetrain": listing.get("drivetrain"),
        "motor_type": listing.get("fuel_type") or listing.get("motor_type"),
        "transmission": listing.get("transmission"),
    }
    return {k: v for k, v in row.items() if v is not None or k in ("id", "vin", "year", "make", "model", "title")}


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
    breakdown = score.get("breakdown") or {}
    if isinstance(breakdown, str):
        try:
            breakdown = json.loads(breakdown) if breakdown else {}
        except json.JSONDecodeError:
            breakdown = {}
    return {
        "id": str(uuid.uuid4()),
        "listing_id": str(listing_id),
        "safety_score": score.get("safety_score", 0),
        "reliability_score": score.get("reliability_score", 0),
        "value_score": score.get("value_score", 0),
        "efficiency_score": score.get("efficiency_score", 0),
        "recall_penalty": score.get("recall_score", 0),
        "composite_score": score.get("composite_score", 0),
        "breakdown": breakdown,  # JSONB: pass dict, not json.dumps string
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
