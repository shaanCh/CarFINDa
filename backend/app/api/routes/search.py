import json
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings
from app.dependencies import get_current_user, get_listing_db
from app.models.schemas import (
    SearchRequest,
    SearchResponse,
    Listing,
    ListingScore,
    ListingWithScore,
)
from app.services.scraping.pipeline import run_scraping_pipeline
from app.services.scoring.pipeline import score_listings
from app.services.llm.intake_agent import parse_preferences
from app.services.llm.synthesizer import synthesize_recommendations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post(
    "/",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
)
async def create_search(
    request: SearchRequest,
    user: dict = Depends(get_current_user),
    db=Depends(get_listing_db),
):
    """Run the full CarFINDa pipeline:
    1. Parse natural language → structured filters (LLM intake)
    2. Query listings table with filters (DB-first; skip scrape if enough results)
    3. Check DB cache for recent identical search
    4. Scrape marketplaces (CarMax, Cars.com)
    5. Persist listings to DB
    6. Score every listing (NHTSA, EPA, market value)
    7. Persist scores to DB
    8. Synthesize personalized recommendations (LLM)
    9. Return ranked results with explanations
    """
    settings = get_settings()
    user_id = user.get("user_id", "anon")

    # ── Step 1: Parse natural language with intake agent ──
    filters = _build_filters(request)
    nl_preferences = {}

    if request.natural_language:
        if settings.GEMINI_API_KEY:
            try:
                nl_preferences = await parse_preferences(
                    request.natural_language, request.location
                )
                filters = _merge_filters(filters, nl_preferences)
                logger.info("Intake agent parsed: %s", nl_preferences)
            except Exception as exc:
                logger.warning("Intake agent failed, falling back to regex: %s", exc)
                regex_prefs = _regex_parse_nl(request.natural_language)
                filters = _merge_filters(filters, regex_prefs)
        else:
            logger.info("No Gemini API key, using regex NL parser")
            regex_prefs = _regex_parse_nl(request.natural_language)
            filters = _merge_filters(filters, regex_prefs)

    if (
        not filters.get("makes")
        and not filters.get("budget_max")
        and not filters.get("body_types")
        and not filters.get("models")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not extract any search criteria. Try something like: 'SUV under $20K near Denver'",
        )

    # ── Step 2: Query listings table first (DB-first) ──
    MIN_DB_RESULTS = 10
    if db:
        try:
            db_results = await db.search_listings(filters, limit=100)
            if len(db_results) >= MIN_DB_RESULTS:
                logger.info(
                    "Returning %d results from listings table (skipping scrape)",
                    len(db_results),
                )
                synthesis = await _run_synthesis(
                    db_results,
                    request.natural_language or _describe_filters(filters),
                    nl_preferences or filters,
                    settings,
                )
                return _build_response(str(uuid.uuid4()), db_results, synthesis)
        except Exception as exc:
            logger.warning("DB listing search failed, proceeding with scrape: %s", exc)

    # ── Step 3: Check DB cache (identical search in last 60 min) ──
    if db:
        try:
            cached_session_id = await db.find_cached_search(filters, max_age_minutes=60)
            if cached_session_id:
                cached_results = await db.get_cached_results(cached_session_id)
                if cached_results:
                    logger.info("Returning %d cached results from session %s", len(cached_results), cached_session_id)
                    synthesis = await _run_synthesis(
                        cached_results,
                        request.natural_language or _describe_filters(filters),
                        nl_preferences or filters,
                        settings,
                    )
                    return _build_response(cached_session_id, cached_results, synthesis)
        except Exception as exc:
            logger.warning("Cache lookup failed, proceeding with fresh scrape: %s", exc)

    # ── Step 4: Create search session & scrape ──
    session_id = str(uuid.uuid4())
    if db:
        try:
            session_id = await db.create_search_session(
                user_id, request.natural_language or "", filters,
            )
        except Exception as exc:
            logger.warning("Failed to create search session: %s", exc)

    raw_listings = await run_scraping_pipeline(filters)
    logger.info("Scraping pipeline returned %d listings", len(raw_listings))

    if not raw_listings:
        if db:
            try:
                await db.complete_search_session(session_id, 0)
            except Exception:
                pass
        return SearchResponse(
            search_session_id=session_id,
            status="complete",
            listings=[],
            total_results=0,
        )

    # ── Step 5: Persist listings to DB ──
    id_map: dict[str, str] = {}
    if db:
        try:
            id_map = await db.upsert_listings(raw_listings)
            # Remap scraper IDs to stable DB IDs
            for listing in raw_listings:
                old_id = listing["id"]
                if old_id in id_map:
                    listing["id"] = id_map[old_id]
            # Record price history for VIN-matched listings
            for listing in raw_listings:
                if listing.get("price") and listing.get("price") > 0:
                    try:
                        await db.record_price_changes(
                            listing["id"],
                            listing["price"],
                            listing.get("source_name", ""),
                        )
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("Failed to persist listings: %s", exc)

    # ── Step 6: Score every listing ──
    scored_listings = await score_listings(raw_listings)
    logger.info("Scoring pipeline scored %d listings", len(scored_listings))

    # ── Step 7: Persist scores to DB ──
    if db:
        try:
            from app.services.db import score_dict_to_row
            score_rows = []
            for sl in scored_listings:
                score_data = sl.get("score", {})
                lid = sl.get("id", "")
                if lid and score_data:
                    score_rows.append(score_dict_to_row(lid, score_data))
            if score_rows:
                await db.upsert_scores(score_rows)
                logger.info("Persisted %d scores to DB", len(score_rows))
        except Exception as exc:
            logger.warning("Failed to persist scores: %s", exc)

    # ── Step 8: Link listings to search session ──
    if db:
        try:
            listing_ids = [sl.get("id", "") for sl in scored_listings if sl.get("id")]
            await db.link_search_listings(session_id, listing_ids)
            await db.complete_search_session(session_id, len(scored_listings))
        except Exception as exc:
            logger.warning("Failed to link search results: %s", exc)

    # ── Step 9: Synthesize recommendations ──
    synthesis = await _run_synthesis(scored_listings, request.natural_language or _describe_filters(filters), nl_preferences or filters, settings)

    # ── Build and return response ──
    return _build_response(session_id, scored_listings, synthesis)


async def _run_synthesis(scored_listings, user_query, preferences, settings):
    """Run LLM synthesis on top listings. Returns None on failure."""
    if not settings.GEMINI_API_KEY or not scored_listings:
        return None
    try:
        top = sorted(
            scored_listings,
            key=lambda x: x.get("score", {}).get("composite_score", 0),
            reverse=True,
        )[:20]
        synthesis = await synthesize_recommendations(
            scored_listings=top,
            user_query=user_query,
            parsed_preferences=preferences,
        )
        logger.info("Synthesis complete: %s", synthesis.get("search_summary", "")[:100])
        return synthesis
    except Exception as exc:
        logger.warning("Synthesis failed: %s", exc)
        return None


def _build_response(
    session_id: str,
    scored_listings: list[dict],
    synthesis: dict | None = None,
) -> SearchResponse:
    """Build the SearchResponse from scored listings."""
    listing_order = {}
    if synthesis and synthesis.get("recommendations"):
        for rec in synthesis["recommendations"]:
            listing_order[rec["listing_id"]] = rec["rank"]

    results: list[ListingWithScore] = []
    for raw in scored_listings:
        try:
            score_dict = raw.get("score", {})
            listing = Listing(
                id=raw.get("id", str(uuid.uuid4())),
                vin=raw.get("vin"),
                year=raw.get("year") or 0,
                make=raw.get("make") or "Unknown",
                model=raw.get("model") or "Unknown",
                trim=raw.get("trim"),
                title=raw.get("title"),
                price=raw.get("price") or 0.0,
                monthly_payment=raw.get("monthly_payment"),
                mileage=raw.get("mileage"),
                mpg=raw.get("mpg"),
                location=raw.get("location"),
                source_url=raw.get("source_url"),
                source_name=raw.get("source_name"),
                image_urls=raw.get("image_urls", []),
                exterior_color=raw.get("exterior_color"),
                interior_color=raw.get("interior_color"),
                fuel_type=raw.get("fuel_type"),
                motor_type=raw.get("motor_type"),
                transmission=raw.get("transmission"),
                drivetrain=raw.get("drivetrain"),
            )
            score = ListingScore(
                safety=score_dict.get("safety_score", 0.0),
                reliability=score_dict.get("reliability_score", 0.0),
                value=score_dict.get("value_score", 0.0),
                efficiency=score_dict.get("efficiency_score", 0.0),
                ownership_cost=score_dict.get("ownership_cost_score", 0.0),
                recall_penalty=score_dict.get("recall_score", 0.0),
                composite=score_dict.get("composite_score", 0.0),
                breakdown=score_dict.get("breakdown", {}),
            )
            results.append(ListingWithScore(listing=listing, score=score))
        except Exception as exc:
            logger.warning(
                "Dropped listing %s %s %s: %s",
                raw.get("make"), raw.get("model"), raw.get("year"), exc,
            )
            continue

    def _sort_key(item: ListingWithScore):
        rank = listing_order.get(item.listing.id, 999)
        return (rank, -item.score.composite)

    results.sort(key=_sort_key)

    return SearchResponse(
        search_session_id=session_id,
        status="complete",
        listings=results,
        total_results=len(results),
        synthesis=synthesis,
    )


@router.get(
    "/{session_id}",
    response_model=SearchResponse,
)
async def get_search_status(
    session_id: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_listing_db),
):
    """Poll the status of an ongoing search session."""
    if not db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database not configured.",
        )

    cached_results = await db.get_cached_results(session_id)
    if not cached_results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Search session {session_id} not found.",
        )

    return _build_response(session_id, cached_results)


def _build_filters(request: SearchRequest) -> dict:
    """Build a scraping pipeline filter dict from a SearchRequest."""
    filters: dict = {}
    if request.location:
        filters["location"] = request.location
    if request.radius_miles:
        filters["radius_miles"] = request.radius_miles
    if request.makes:
        filters["makes"] = request.makes
    if request.budget_min:
        filters["budget_min"] = request.budget_min
    if request.budget_max:
        filters["budget_max"] = request.budget_max
    if request.min_year:
        filters["min_year"] = request.min_year
    if request.max_mileage:
        filters["max_mileage"] = request.max_mileage
    if request.body_types:
        filters["body_types"] = request.body_types
    return filters


def _merge_filters(explicit: dict, nl_parsed: dict) -> dict:
    """Merge NL-parsed preferences into explicit filters.
    Explicit (structured) fields take priority.
    """
    merged = dict(explicit)

    # Only backfill from NL if explicit field is empty/None
    field_map = {
        "budget_min": "budget_min",
        "budget_max": "budget_max",
        "body_types": "body_types",
        "makes": "makes",
        "max_mileage": "max_mileage",
        "min_year": "min_year",
        "location": "location",
        "radius_miles": "radius_miles",
    }

    for explicit_key, nl_key in field_map.items():
        nl_val = nl_parsed.get(nl_key)
        existing = merged.get(explicit_key)

        if nl_val and not existing:
            merged[explicit_key] = nl_val
        elif isinstance(nl_val, list) and isinstance(existing, list) and not existing:
            merged[explicit_key] = nl_val

    # Also carry over NL-only fields
    for key in ["models", "dealbreakers", "fuel_types", "transmission"]:
        if nl_parsed.get(key):
            merged[key] = nl_parsed[key]

    return merged


def _describe_filters(filters: dict) -> str:
    """Generate a human-readable description from structured filters."""
    parts = []
    if filters.get("makes"):
        parts.append(", ".join(filters["makes"]))
    if filters.get("body_types"):
        parts.append(", ".join(filters["body_types"]))
    if filters.get("budget_max"):
        parts.append(f"under ${filters['budget_max']:,.0f}")
    if filters.get("location"):
        parts.append(f"near {filters['location']}")
    return " ".join(parts) if parts else "general car search"


# ---------------------------------------------------------------------------
# Simple regex-based NL parser (fallback when no Gemini key)
# ---------------------------------------------------------------------------

import re

_KNOWN_MAKES = {
    "toyota", "honda", "ford", "chevrolet", "chevy", "nissan", "hyundai",
    "kia", "subaru", "mazda", "bmw", "mercedes", "audi", "lexus", "acura",
    "volkswagen", "vw", "jeep", "dodge", "ram", "gmc", "buick", "cadillac",
    "chrysler", "lincoln", "volvo", "tesla", "porsche", "infiniti", "genesis",
    "mitsubishi", "mini", "fiat", "alfa romeo", "jaguar", "land rover",
}

_MAKE_NORMALIZE = {
    "chevy": "Chevrolet", "vw": "Volkswagen", "merc": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz",
}

_BODY_TYPES = {
    "suv": "SUV", "sedan": "Sedan", "truck": "Truck", "coupe": "Coupe",
    "hatchback": "Hatchback", "wagon": "Wagon", "van": "Van",
    "minivan": "Minivan", "convertible": "Convertible", "crossover": "Crossover",
}

_KNOWN_MODELS = {
    "civic", "camry", "corolla", "accord", "rav4", "cr-v", "crv", "highlander",
    "tacoma", "4runner", "f-150", "f150", "silverado", "wrangler", "outback",
    "forester", "cx-5", "cx5", "rogue", "altima", "sentra", "tucson", "santa fe",
    "elantra", "sonata", "telluride", "sorento", "pilot", "odyssey", "explorer",
    "escape", "bronco", "ranger", "colorado", "equinox", "tahoe", "suburban",
    "model 3", "model y", "model s", "model x", "3 series", "5 series", "x3", "x5",
    "grand cherokee", "ram 1500", "tundra", "prius", "camaro", "mustang",
    "malibu", "impala", "jetta", "tiguan", "atlas", "pathfinder",
}

# US cities/states for location extraction
_LOCATIONS = {
    "boulder": "Boulder, CO", "denver": "Denver, CO", "colorado springs": "Colorado Springs, CO",
    "los angeles": "Los Angeles, CA", "san francisco": "San Francisco, CA", "san diego": "San Diego, CA",
    "new york": "New York, NY", "chicago": "Chicago, IL", "houston": "Houston, TX",
    "phoenix": "Phoenix, AZ", "dallas": "Dallas, TX", "austin": "Austin, TX",
    "seattle": "Seattle, WA", "portland": "Portland, OR", "atlanta": "Atlanta, GA",
    "miami": "Miami, FL", "tampa": "Tampa, FL", "orlando": "Orlando, FL",
    "nashville": "Nashville, TN", "charlotte": "Charlotte, NC", "raleigh": "Raleigh, NC",
    "minneapolis": "Minneapolis, MN", "detroit": "Detroit, MI", "boston": "Boston, MA",
    "philadelphia": "Philadelphia, PA", "pittsburgh": "Pittsburgh, PA",
    "salt lake city": "Salt Lake City, UT", "las vegas": "Las Vegas, NV",
    "fort collins": "Fort Collins, CO", "longmont": "Longmont, CO",
}


def _regex_parse_nl(text: str) -> dict:
    """Extract basic filters from natural language without an LLM.

    Handles patterns like:
      - "reliable SUV under $18K for my family near Boulder"
      - "Toyota Camry under 80K miles, $15000 budget"
      - "truck for towing, diesel, 2018 or newer, around $30K"
    """
    lower = text.lower()
    result: dict = {}

    # ── Budget ──
    # "$18K", "$18k", "$18,000", "under 18000", "budget 20k"
    budget_patterns = [
        r'\$\s*([\d,.]+)\s*k\b',                  # $18K, $18.5k
        r'\$\s*([\d,]+(?:\.\d{2})?)\b',           # $18,000 or $18000
        r'under\s+\$?\s*([\d,.]+)\s*k?\b',        # under 18K, under $18K
        r'budget\s+(?:of\s+)?\$?\s*([\d,.]+)\s*k?\b',  # budget 18K
        r'(?:less than|max|up to)\s+\$?\s*([\d,.]+)\s*k?\b',
    ]
    for pattern in budget_patterns:
        m = re.search(pattern, lower)
        if m:
            val_str = m.group(1).replace(",", "")
            val = float(val_str)
            # If value looks like thousands shorthand (< 200), multiply by 1000
            if val < 200:
                val *= 1000
            result["budget_max"] = val
            break

    # ── Body types ──
    for keyword, normalized in _BODY_TYPES.items():
        if re.search(rf'\b{keyword}s?\b', lower):
            result.setdefault("body_types", []).append(normalized)

    # ── Makes ──
    for make in _KNOWN_MAKES:
        if re.search(rf'\b{re.escape(make)}\b', lower):
            normalized = _MAKE_NORMALIZE.get(make, make.title())
            result.setdefault("makes", []).append(normalized)

    # ── Models ──
    for model in _KNOWN_MODELS:
        if re.search(rf'\b{re.escape(model)}\b', lower):
            result.setdefault("models", []).append(model.title())

    # ── Year ──
    year_patterns = [
        r'(\d{4})\s*(?:or\s+)?(?:newer|\+|and up)',  # 2018 or newer, 2018+
        r'(?:newer than|after|min(?:imum)?\s+year)\s+(\d{4})',
    ]
    for pattern in year_patterns:
        m = re.search(pattern, lower)
        if m:
            result["min_year"] = int(m.group(1))
            break

    # ── Mileage ──
    mileage_patterns = [
        r'under\s+([\d,.]+)\s*k?\s*(?:miles?|mi)\b',
        r'(?:less than|max|below)\s+([\d,.]+)\s*k?\s*(?:miles?|mi)\b',
        r'([\d,.]+)\s*k?\s*(?:miles?|mi)\s*(?:or less|max)',
        r'low mileage',
    ]
    for pattern in mileage_patterns:
        m = re.search(pattern, lower)
        if m:
            if 'low mileage' in pattern:
                result["max_mileage"] = 50000
            else:
                val_str = m.group(1).replace(",", "")
                val = float(val_str)
                if val < 500:
                    val *= 1000
                result["max_mileage"] = int(val)
            break

    # ── Location ──
    for city, full in _LOCATIONS.items():
        if city in lower:
            result["location"] = full
            break
    # Also try "near <City>" pattern
    if "location" not in result:
        m = re.search(r'(?:near|in|around)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', text)
        if m:
            result["location"] = m.group(1)

    logger.info("Regex NL parser extracted: %s", result)
    return result
