import asyncio
import json
import re
import uuid
import logging
import hashlib
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings
from app.dependencies import get_current_user, get_listing_db
from app.models.schemas import (
    SearchRequest,
    SearchResponse,
    Listing,
    ListingScore,
    ListingWithScore,
    DealInfo,
)
from app.services.scraping.pipeline import run_scraping_pipeline
from app.services.scoring.pipeline import score_listings
from app.services.llm.intake_agent import parse_preferences
from app.services.llm.synthesizer import synthesize_recommendations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

_SEARCH_CACHE: dict[str, tuple[SearchResponse, float]] = {}


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
    import time as _time
    _t0 = _time.monotonic()
    
    cache_key = hashlib.md5(request.model_dump_json().encode()).hexdigest()
    if cache_key in _SEARCH_CACHE:
        cached_resp, timestamp = _SEARCH_CACHE[cache_key]
        if _t0 - timestamp < 120:
            logger.info("Search memory cache HIT for %s", cache_key)
            return cached_resp
            
    logger.info("Search memory cache MISS for %s", cache_key)

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

    # Require at least one meaningful filter, but be lenient --
    # semantic parsing may have set body_types/makes/fuel_types
    has_any_filter = any([
        filters.get("makes"),
        filters.get("models"),
        filters.get("budget_max"),
        filters.get("body_types"),
        filters.get("fuel_types"),
        filters.get("max_mileage"),
        filters.get("min_year"),
        filters.get("transmission"),
    ])
    if not has_any_filter:
        # Last resort: if we have natural language text, let the pipeline
        # do a broad popular-makes search rather than rejecting
        if request.natural_language and len(request.natural_language.strip()) > 3:
            logger.info("No structured filters extracted, running broad search for: %s", request.natural_language)
            # Set a reasonable default budget to avoid overwhelming results
            if not filters.get("budget_max"):
                filters["budget_max"] = 50000
        else:
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
    db_user_id: Optional[str] = _valid_user_id_for_db(user_id)
    if db:
        try:
            session_id = await db.create_search_session(
                db_user_id, request.natural_language or "", filters,
            )
        except Exception as exc:
            logger.warning("Failed to create search session: %s", exc)

    _t1 = _time.monotonic()
    raw_listings = await run_scraping_pipeline(filters)
    _t2 = _time.monotonic()
    logger.info("Scraping pipeline returned %d listings in %.1fs (intake: %.1fs)", len(raw_listings), _t2 - _t1, _t1 - _t0)

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
    persisted_ids: set[str] = set()
    if db:
        try:
            id_map, persisted_ids = await db.upsert_listings(raw_listings)
            for listing in raw_listings:
                old_id = listing["id"]
                if old_id in id_map:
                    listing["id"] = id_map[old_id]
            # Batch price history (fire-and-forget, don't block)
            asyncio.create_task(_record_prices_batch(db, raw_listings, persisted_ids))
        except Exception as exc:
            logger.warning("Failed to persist listings: %s", exc)

    # ── Step 6: Score + synthesize in parallel ──
    scored_listings = await score_listings(raw_listings)
    logger.info("Scoring pipeline scored %d listings", len(scored_listings))

    # Run DB persistence and LLM synthesis concurrently
    synthesis_coro = _run_synthesis(
        scored_listings,
        request.natural_language or _describe_filters(filters),
        nl_preferences or filters,
        settings,
    )
    db_persist_coro = _persist_scores_and_links(
        db, scored_listings, persisted_ids, session_id,
    )
    synthesis, _ = await asyncio.gather(synthesis_coro, db_persist_coro)
    _t3 = _time.monotonic()
    logger.info("Search complete in %.1fs total (scrape: %.1fs, score+synth: %.1fs)", _t3 - _t0, _t2 - _t1, _t3 - _t2)

    # ── Step 7: Build and return response ──
    response = _build_response(session_id, scored_listings, synthesis)
    _SEARCH_CACHE[cache_key] = (response, _time.monotonic())
    return response


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


async def _record_prices_batch(db: Any, listings: list[dict], persisted_ids: set[str]) -> None:
    """Record price history for persisted listings (fire-and-forget)."""
    try:
        tasks = []
        for listing in listings:
            lid = listing["id"]
            if lid in persisted_ids and listing.get("price") and listing["price"] > 0:
                tasks.append(db.record_price_changes(lid, listing["price"], listing.get("source_name", ""), valid_listing_ids=persisted_ids))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        logger.debug("Price history batch failed: %s", exc)


async def _persist_scores_and_links(
    db: Any, scored_listings: list[dict], persisted_ids: set[str], session_id: str,
) -> None:
    """Persist scores and link listings to search session concurrently."""
    if not db:
        return
    try:
        from app.services.db import score_dict_to_row
        score_rows = []
        for sl in scored_listings:
            score_data = sl.get("score", {})
            lid = sl.get("id", "")
            if lid and score_data and lid in persisted_ids:
                score_rows.append(score_dict_to_row(lid, score_data))

        listing_ids = [sl["id"] for sl in scored_listings if sl.get("id") and sl["id"] in persisted_ids]

        # Run score upsert and search linking in parallel
        coros = []
        if score_rows:
            coros.append(db.upsert_scores(score_rows))
        if listing_ids:
            coros.append(db.link_search_listings(session_id, listing_ids))
        coros.append(db.complete_search_session(session_id, len(scored_listings)))

        await asyncio.gather(*coros, return_exceptions=True)
        logger.info("Persisted %d scores, linked %d listings", len(score_rows), len(listing_ids))
    except Exception as exc:
        logger.warning("DB persistence failed: %s", exc)


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
                recall=score_dict.get("recall_score", 0.0),
                composite=score_dict.get("composite_score", 0.0),
                breakdown=score_dict.get("breakdown", {}),
            )
            deal_dict = raw.get("deal", {})
            deal = DealInfo(
                rating=deal_dict.get("rating", "Unknown"),
                savings=deal_dict.get("savings", 0.0),
                savings_pct=deal_dict.get("savings_pct", 0.0),
                source_badge=deal_dict.get("source_badge"),
                cross_source=deal_dict.get("cross_source"),
            ) if deal_dict else None
            results.append(ListingWithScore(listing=listing, score=score, deal=deal))
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


def _valid_user_id_for_db(user_id: str) -> Optional[str]:
    """Return user_id if it's a valid UUID (exists in auth.users), else None for anonymous."""
    if not user_id:
        return None
    # Dev/anonymous IDs like "dev-user-001" or "anon" are not valid UUIDs
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )
    return user_id if uuid_pattern.match(user_id) else None


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
    "rivian", "lucid", "polestar",
}

_MAKE_NORMALIZE = {
    "chevy": "Chevrolet", "vw": "Volkswagen", "merc": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz", "land rover": "Land Rover",
    "alfa romeo": "Alfa Romeo",
}

_BODY_TYPES = {
    "suv": "SUV", "sedan": "Sedan", "truck": "Truck", "coupe": "Coupe",
    "hatchback": "Hatchback", "wagon": "Wagon", "van": "Van",
    "minivan": "Minivan", "convertible": "Convertible", "crossover": "Crossover",
    "pickup": "Truck",
}

_KNOWN_MODELS = {
    "civic", "camry", "corolla", "accord", "rav4", "cr-v", "crv", "highlander",
    "tacoma", "4runner", "f-150", "f150", "silverado", "wrangler", "outback",
    "forester", "cx-5", "cx5", "cx-50", "cx50", "cx-30", "cx30", "cx-9", "cx-90",
    "rogue", "altima", "sentra", "tucson", "santa fe", "palisade",
    "elantra", "sonata", "telluride", "sorento", "sportage", "seltos",
    "pilot", "odyssey", "explorer", "escape", "bronco", "ranger",
    "colorado", "equinox", "tahoe", "suburban", "traverse", "trailblazer",
    "model 3", "model y", "model s", "model x",
    "3 series", "5 series", "x3", "x5", "x1",
    "grand cherokee", "ram 1500", "tundra", "prius", "camaro", "mustang",
    "malibu", "impala", "jetta", "tiguan", "atlas", "pathfinder",
    "crosstrek", "impreza", "wrx", "ascent", "solterra",
    "sienna", "venza", "gr86", "supra",
    "ioniq 5", "ioniq 6", "ev6", "niro", "carnival",
    "maverick", "expedition", "edge",
    "bolt", "blazer", "trax",
    "compass", "gladiator", "cherokee",
    "gv70", "gv80", "g70", "g80",
    "q5", "q7", "a4", "a6",
    "c-class", "e-class", "glc", "gle",
    "xc40", "xc60", "xc90",
    "rx", "nx", "es", "is",
    "rdx", "mdx", "integra", "tlx",
}

# Model → Make inference for when user says just the model name
_MODEL_TO_MAKE: dict[str, str] = {
    "camry": "Toyota", "corolla": "Toyota", "rav4": "Toyota", "highlander": "Toyota",
    "tacoma": "Toyota", "4runner": "Toyota", "tundra": "Toyota", "prius": "Toyota",
    "sienna": "Toyota", "venza": "Toyota", "gr86": "Toyota", "supra": "Toyota",
    "solterra": "Subaru",
    "civic": "Honda", "accord": "Honda", "cr-v": "Honda", "crv": "Honda",
    "pilot": "Honda", "odyssey": "Honda", "hr-v": "Honda", "hrv": "Honda",
    "integra": "Acura", "rdx": "Acura", "mdx": "Acura", "tlx": "Acura",
    "f-150": "Ford", "f150": "Ford", "explorer": "Ford", "escape": "Ford",
    "bronco": "Ford", "ranger": "Ford", "maverick": "Ford", "mustang": "Ford",
    "edge": "Ford", "expedition": "Ford",
    "silverado": "Chevrolet", "equinox": "Chevrolet", "tahoe": "Chevrolet",
    "suburban": "Chevrolet", "colorado": "Chevrolet", "traverse": "Chevrolet",
    "trailblazer": "Chevrolet", "camaro": "Chevrolet", "blazer": "Chevrolet",
    "bolt": "Chevrolet", "trax": "Chevrolet", "malibu": "Chevrolet",
    "wrangler": "Jeep", "grand cherokee": "Jeep", "compass": "Jeep",
    "gladiator": "Jeep", "cherokee": "Jeep",
    "outback": "Subaru", "forester": "Subaru", "crosstrek": "Subaru",
    "impreza": "Subaru", "wrx": "Subaru", "ascent": "Subaru",
    "cx-5": "Mazda", "cx5": "Mazda", "cx-50": "Mazda", "cx50": "Mazda",
    "cx-30": "Mazda", "cx30": "Mazda", "cx-9": "Mazda", "cx-90": "Mazda",
    "rogue": "Nissan", "altima": "Nissan", "sentra": "Nissan", "pathfinder": "Nissan",
    "tucson": "Hyundai", "santa fe": "Hyundai", "palisade": "Hyundai",
    "elantra": "Hyundai", "sonata": "Hyundai", "ioniq 5": "Hyundai", "ioniq 6": "Hyundai",
    "telluride": "Kia", "sorento": "Kia", "sportage": "Kia", "seltos": "Kia",
    "ev6": "Kia", "niro": "Kia", "carnival": "Kia",
    "model 3": "Tesla", "model y": "Tesla", "model s": "Tesla", "model x": "Tesla",
    "3 series": "BMW", "5 series": "BMW", "x3": "BMW", "x5": "BMW", "x1": "BMW",
    "ram 1500": "Ram",
    "jetta": "Volkswagen", "tiguan": "Volkswagen", "atlas": "Volkswagen",
    "gv70": "Genesis", "gv80": "Genesis", "g70": "Genesis", "g80": "Genesis",
    "q5": "Audi", "q7": "Audi", "a4": "Audi", "a6": "Audi",
    "c-class": "Mercedes-Benz", "e-class": "Mercedes-Benz",
    "glc": "Mercedes-Benz", "gle": "Mercedes-Benz",
    "xc40": "Volvo", "xc60": "Volvo", "xc90": "Volvo",
    "rx": "Lexus", "nx": "Lexus", "es": "Lexus", "is": "Lexus",
}

# Semantic keywords → structured filters
_SEMANTIC_RULES: list[tuple[list[str], dict[str, Any]]] = [
    # Lifestyle categories
    (["family", "family car", "family-friendly", "kid", "kids", "children"],
     {"body_types": ["SUV", "Sedan", "Minivan"]}),
    (["commuter", "commute", "daily driver", "daily"],
     {"body_types": ["Sedan", "Hatchback"]}),
    (["reliable", "dependable", "bulletproof", "last forever"],
     {"makes": ["Toyota", "Honda", "Lexus", "Mazda"]}),
    (["luxury", "luxurious", "premium", "upscale"],
     {"makes": ["BMW", "Mercedes-Benz", "Audi", "Lexus", "Genesis", "Volvo"]}),
    (["sporty", "fast", "performance", "fun to drive", "fun", "speed"],
     {"body_types": ["Coupe", "Sedan"]}),
    (["off-road", "offroad", "adventure", "trail", "overlanding"],
     {"body_types": ["SUV", "Truck"]}),
    (["towing", "tow", "hauling", "haul", "work truck"],
     {"body_types": ["Truck", "SUV"]}),
    (["fuel efficient", "gas mileage", "economical", "good mpg", "fuel economy", "efficient"],
     {"fuel_types": ["hybrid"]}),
    (["snow", "winter", "awd", "all wheel drive", "4wd", "four wheel drive", "all-wheel"],
     {}),  # handled separately for drivetrain
    (["cheap", "affordable", "budget", "inexpensive", "low cost"],
     {"budget_max": 15000}),
    (["first car", "new driver", "teen", "teenager", "student"],
     {"budget_max": 15000, "body_types": ["Sedan", "Hatchback"]}),
    (["road trip", "long distance", "highway", "touring"],
     {"body_types": ["SUV", "Sedan"]}),
    (["small", "compact", "little"],
     {"body_types": ["Hatchback", "Sedan"]}),
    (["large", "big", "spacious", "third row", "3rd row", "7 seater", "8 seater", "room"],
     {"body_types": ["SUV", "Minivan"]}),
    (["electric", "ev", "zero emission"],
     {"fuel_types": ["electric"]}),
    (["hybrid", "plug-in", "phev", "plug in"],
     {"fuel_types": ["hybrid"]}),
    (["diesel"],
     {"fuel_types": ["diesel"]}),
    (["manual", "stick shift", "stick", "manual transmission"],
     {"transmission": "manual"}),
    (["automatic", "auto trans"],
     {"transmission": "automatic"}),
]

# US cities/states for location extraction (expanded)
_LOCATIONS = {
    "boulder": "Boulder, CO", "denver": "Denver, CO", "colorado springs": "Colorado Springs, CO",
    "fort collins": "Fort Collins, CO", "longmont": "Longmont, CO", "pueblo": "Pueblo, CO",
    "los angeles": "Los Angeles, CA", "san francisco": "San Francisco, CA", "san diego": "San Diego, CA",
    "sacramento": "Sacramento, CA", "san jose": "San Jose, CA", "oakland": "Oakland, CA",
    "new york": "New York, NY", "brooklyn": "Brooklyn, NY", "manhattan": "New York, NY",
    "chicago": "Chicago, IL", "houston": "Houston, TX", "san antonio": "San Antonio, TX",
    "phoenix": "Phoenix, AZ", "scottsdale": "Scottsdale, AZ", "tucson": "Tucson, AZ",
    "dallas": "Dallas, TX", "austin": "Austin, TX", "fort worth": "Fort Worth, TX",
    "seattle": "Seattle, WA", "portland": "Portland, OR",
    "atlanta": "Atlanta, GA", "savannah": "Savannah, GA",
    "miami": "Miami, FL", "tampa": "Tampa, FL", "orlando": "Orlando, FL", "jacksonville": "Jacksonville, FL",
    "nashville": "Nashville, TN", "memphis": "Memphis, TN", "knoxville": "Knoxville, TN",
    "charlotte": "Charlotte, NC", "raleigh": "Raleigh, NC", "durham": "Durham, NC",
    "minneapolis": "Minneapolis, MN", "detroit": "Detroit, MI", "ann arbor": "Ann Arbor, MI",
    "boston": "Boston, MA", "cambridge": "Cambridge, MA",
    "philadelphia": "Philadelphia, PA", "pittsburgh": "Pittsburgh, PA",
    "salt lake city": "Salt Lake City, UT", "provo": "Provo, UT",
    "las vegas": "Las Vegas, NV", "reno": "Reno, NV",
    "washington dc": "Washington, DC", "dc": "Washington, DC",
    "baltimore": "Baltimore, MD",
    "indianapolis": "Indianapolis, IN", "columbus": "Columbus, OH", "cleveland": "Cleveland, OH",
    "cincinnati": "Cincinnati, OH", "kansas city": "Kansas City, MO", "st louis": "St. Louis, MO",
    "milwaukee": "Milwaukee, WI", "madison": "Madison, WI",
    "new orleans": "New Orleans, LA", "baton rouge": "Baton Rouge, LA",
    "richmond": "Richmond, VA", "virginia beach": "Virginia Beach, VA",
    "albuquerque": "Albuquerque, NM", "boise": "Boise, ID",
    "omaha": "Omaha, NE", "des moines": "Des Moines, IA",
    "honolulu": "Honolulu, HI", "anchorage": "Anchorage, AK",
}


def _regex_parse_nl(text: str) -> dict:
    """Extract basic filters from natural language without an LLM.

    Handles patterns like:
      - "reliable SUV under $18K for my family near Boulder"
      - "Toyota Camry under 80K miles, $15000 budget"
      - "truck for towing, diesel, 2018 or newer, around $30K"
      - "good commuter car for a college student"
      - "something reliable and fuel efficient"
    """
    lower = text.lower()
    result: dict = {}

    # ── Budget ──
    # Negative lookahead (?!\s*(?:miles?|mi\b)) prevents matching "80K miles" as budget
    budget_patterns = [
        (r'between\s+\$?\s*([\d,.]+)\s*k?\s*(?:and|-)\s*\$?\s*([\d,.]+)\s*k?(?!\s*(?:miles?|mi\b))\b', 'range'),
        (r'\$\s*([\d,.]+)\s*k(?!\s*(?:miles?|mi\b))\b', 'single'),
        (r'\$\s*([\d,]+(?:\.\d{2})?)(?!\s*(?:miles?|mi\b))\b', 'single'),
        (r'(?:under|less than|max|up to|no more than)\s+\$\s*([\d,.]+)\s*k?(?!\s*(?:miles?|mi\b))\b', 'max'),
        (r'(?:budget|spend|afford)\s+(?:of\s+|is\s+|about\s+)?\$?\s*([\d,.]+)\s*k?(?!\s*(?:miles?|mi\b))\b', 'single'),
        (r'(?:around|about|roughly|approximately)\s+\$\s*([\d,.]+)\s*k?(?!\s*(?:miles?|mi\b))\b', 'around'),
    ]
    for pattern, ptype in budget_patterns:
        m = re.search(pattern, lower)
        if m:
            if ptype == 'range':
                val1 = float(m.group(1).replace(",", ""))
                val2 = float(m.group(2).replace(",", ""))
                if val1 < 200: val1 *= 1000
                if val2 < 200: val2 *= 1000
                result["budget_min"] = val1
                result["budget_max"] = val2
            elif ptype == 'around':
                val = float(m.group(1).replace(",", ""))
                if val < 200: val *= 1000
                result["budget_min"] = val * 0.85
                result["budget_max"] = val * 1.15
            else:
                val = float(m.group(1).replace(",", ""))
                if val < 200: val *= 1000
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

    # ── Models (with auto-inferred makes) ──
    for model in sorted(_KNOWN_MODELS, key=len, reverse=True):  # longest first to match multi-word models
        if re.search(rf'\b{re.escape(model)}\b', lower):
            result.setdefault("models", []).append(model.title())
            # Auto-infer make if not already specified
            inferred_make = _MODEL_TO_MAKE.get(model)
            if inferred_make and inferred_make not in result.get("makes", []):
                result.setdefault("makes", []).append(inferred_make)

    # ── Year ──
    year_patterns = [
        r'(\d{4})\s*(?:or\s+)?(?:newer|\+|and up|and newer)',
        r'(?:newer than|after|min(?:imum)?\s+year|since)\s+(\d{4})',
        r'(?:newer|recent|late model)',  # no year specified
    ]
    for pattern in year_patterns:
        m = re.search(pattern, lower)
        if m:
            if m.lastindex:
                result["min_year"] = int(m.group(1))
            else:
                import datetime
                result["min_year"] = datetime.datetime.now().year - 5
            break

    # ── Mileage ──
    mileage_patterns = [
        r'(?:under|less than|max|below|no more than)\s+([\d,.]+)\s*k?\s*(?:miles?|mi)\b',
        r'([\d,.]+)\s*k?\s*(?:miles?|mi)\s*(?:or less|max|maximum)',
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
    # Sort by length (longest first) to match "salt lake city" before "salt"
    for city, full in sorted(_LOCATIONS.items(), key=lambda x: len(x[0]), reverse=True):
        if city in lower:
            result["location"] = full
            break
    if "location" not in result:
        # "near <City>" or "in <City>"
        m = re.search(r'(?:near|in|around|close to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', text)
        if m:
            result["location"] = m.group(1)

    # ── Semantic rules ──
    for keywords, filters in _SEMANTIC_RULES:
        for kw in keywords:
            if kw in lower:
                for key, val in filters.items():
                    if key == "body_types" and "body_types" not in result:
                        result["body_types"] = val
                    elif key == "makes" and "makes" not in result:
                        result["makes"] = val
                    elif key == "fuel_types":
                        result.setdefault("fuel_types", []).extend(
                            v for v in val if v not in result.get("fuel_types", [])
                        )
                    elif key == "transmission" and "transmission" not in result:
                        result["transmission"] = val
                    elif key == "budget_max" and "budget_max" not in result:
                        result["budget_max"] = val
                break  # Only apply once per rule group

    # ── Default radius ──
    if "location" in result and "radius_miles" not in result:
        result["radius_miles"] = 100

    logger.info("Regex NL parser extracted: %s", result)
    return result
