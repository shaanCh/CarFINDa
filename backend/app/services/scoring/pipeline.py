"""
Scoring pipeline orchestrator.

Two modes:
  - **Fast mode** (default for search results): Parallel Tavily market-value
    lookups grouped by unique (make, model, year), with depreciation formula
    fallback. Typically ~1-2s total for any batch size.
  - **Full mode** (for individual listing detail): Calls NHTSA safety,
    NHTSA complaints, NHTSA recalls, EPA fuel economy, VinAudit market
    value, and VinAudit ownership cost.  ~2-3s per listing.
"""

import asyncio
import logging
import math
from dataclasses import asdict
from typing import Any

from app.services.scoring.calculator import calculate_composite_score, ListingScore

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = 20


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def score_listings(listings: list[dict], full: bool = False) -> list[dict]:
    """Score a batch of listings.

    Args:
        listings: Raw listing dicts from the scraping pipeline.
        full:     If True, call all external APIs (NHTSA, EPA, VinAudit).
                  If False (default), use fast scoring enhanced with parallel
                  Tavily market-value lookups per unique (make, model, year).
    """
    if not listings:
        return []

    if full:
        return await _score_listings_full(listings)
    return await _score_listings_fast(listings)


# ---------------------------------------------------------------------------
# Fast local-only scoring  (for search results grid)
# ---------------------------------------------------------------------------

# Current-era MSRP estimates (2024-2025 base trims, rounded)
_SEGMENT_MSRP: dict[str, int] = {
    # Sedans
    "civic": 28_000, "corolla": 24_000, "camry": 32_000, "accord": 33_000,
    "altima": 29_000, "sentra": 23_000, "malibu": 27_000, "sonata": 30_000,
    "elantra": 24_000, "mazda3": 27_000, "jetta": 25_000, "k5": 28_000,
    "forte": 21_000, "impreza": 24_000, "legacy": 26_000,
    # Compact SUV / crossover
    "rav4": 36_000, "cr-v": 36_000, "crv": 36_000, "rogue": 33_000,
    "tucson": 32_000, "cx-5": 31_000, "equinox": 31_000, "escape": 32_000,
    "sportage": 32_000, "seltos": 27_000, "bronco sport": 31_000,
    "cx-50": 32_000, "crosstrek": 28_000,
    # Mid-size / full-size SUV
    "highlander": 42_000, "pilot": 42_000, "4runner": 44_000,
    "tahoe": 60_000, "suburban": 64_000, "explorer": 40_000,
    "palisade": 40_000, "telluride": 40_000, "pathfinder": 38_000,
    "sequoia": 62_000, "expedition": 58_000, "cx-90": 40_000,
    # Jeep
    "wrangler": 42_000, "grand cherokee": 44_000, "cherokee": 35_000,
    # Trucks
    "f-150": 40_000, "f150": 40_000, "silverado": 40_000, "ram 1500": 42_000,
    "tacoma": 39_000, "tundra": 48_000, "colorado": 34_000, "ranger": 36_000,
    "frontier": 32_000, "ridgeline": 42_000, "maverick": 28_000,
    # EV
    "model 3": 42_000, "model y": 48_000, "model s": 85_000, "model x": 95_000,
    "ioniq 5": 45_000, "ioniq 6": 44_000, "ev6": 44_000, "id.4": 40_000,
    "mach-e": 44_000, "bolt": 28_000, "leaf": 30_000, "ariya": 44_000,
    # Luxury
    "3 series": 48_000, "5 series": 58_000, "x3": 50_000, "x5": 68_000,
    "c-class": 48_000, "e-class": 58_000, "glc": 50_000, "gle": 62_000,
    "a4": 42_000, "q5": 48_000, "is": 42_000, "rx": 52_000, "nx": 44_000,
    # Sports
    "corvette": 70_000, "mustang": 34_000, "camaro": 32_000, "supra": 52_000,
    "86": 30_000, "miata": 30_000, "brz": 30_000,
    # Other popular
    "prius": 32_000, "outback": 32_000, "forester": 34_000,
    "sienna": 40_000, "odyssey": 40_000, "carnival": 38_000,
    # Luxury brands missing
    "gv80": 58_000, "gv70": 48_000, "g70": 42_000, "g80": 58_000,
    "xt6": 55_000, "xt5": 48_000, "xt4": 40_000, "escalade": 85_000,
    "ix": 88_000, "x1": 42_000, "x7": 80_000,
    "gx": 65_000, "lx": 100_000, "es": 44_000,
    # Full-size truck variants
    "silverado 1500": 40_000, "ram 1500": 42_000,
    "suburban 1500": 64_000, "sierra 1500": 40_000,
    # FJ Cruiser (discontinued, cult following)
    "fj": 30_000, "fj cruiser": 30_000,
}
_DEFAULT_MSRP = 35_000
_AVG_ANNUAL_MILES = 12_000

# Models that hold value better than average (multiply retained value by this factor)
_HIGH_RETENTION: dict[str, float] = {
    "tacoma": 1.15, "4runner": 1.18, "tundra": 1.12,
    "wrangler": 1.20, "rav4": 1.10, "highlander": 1.10,
    "cr-v": 1.05, "civic": 1.05, "corolla": 1.05,
    "forester": 1.05, "outback": 1.05, "crosstrek": 1.06,
    "model 3": 1.05, "model y": 1.05,
    "telluride": 1.08, "palisade": 1.06,
    # Sports / specialty (hold value well above average depreciation)
    "corvette": 1.20, "challenger": 1.12, "camaro": 1.08,
    "mustang": 1.08, "supra": 1.15, "911": 1.25,
    "brz": 1.08, "86": 1.08, "miata": 1.10,
    # Full-size trucks & SUVs
    "silverado": 1.06, "ram 1500": 1.06, "f-150": 1.08,
    "f150": 1.08, "suburban": 1.08, "tahoe": 1.08,
    "sequoia": 1.10, "expedition": 1.06,
    # Luxury with strong resale
    "rx": 1.08, "gx": 1.12, "lx": 1.15,
    "grand cherokee": 1.06,
}


def _lookup_msrp(model: str) -> int:
    """Look up MSRP with fuzzy model name matching.

    Scraped model names often include suffixes like "Hybrid", "1500", "4XE",
    "350h", etc. This tries exact match first, then checks if any known model
    key is contained within the scraped model name (or vice-versa).
    """
    key = model.lower().strip()

    # Exact match
    if key in _SEGMENT_MSRP:
        return _SEGMENT_MSRP[key]

    # Check if any known key is a substring of the scraped model name
    # e.g. "rav4" in "rav4 hybrid", "grand cherokee" in "grand cherokee 4xe"
    best_match = ""
    for known_key in _SEGMENT_MSRP:
        if known_key in key and len(known_key) > len(best_match):
            best_match = known_key

    if best_match:
        return _SEGMENT_MSRP[best_match]

    # Check if the scraped model is a substring of a known key
    # e.g. "1500" in "ram 1500"
    for known_key in _SEGMENT_MSRP:
        if key in known_key:
            return _SEGMENT_MSRP[known_key]

    return _DEFAULT_MSRP


def _lookup_retention(model: str) -> float:
    """Look up high-retention multiplier with fuzzy matching."""
    key = model.lower().strip()

    if key in _HIGH_RETENTION:
        return _HIGH_RETENTION[key]

    # Substring matching (same logic as MSRP lookup)
    best_match = ""
    for known_key in _HIGH_RETENTION:
        if known_key in key and len(known_key) > len(best_match):
            best_match = known_key

    if best_match:
        return _HIGH_RETENTION[best_match]

    for known_key in _HIGH_RETENTION:
        if key in known_key:
            return _HIGH_RETENTION[known_key]

    return 1.0


def _estimate_value(make: str, model: str, year: int, mileage: int) -> float:
    """Fast depreciation-based market value estimate.

    Uses a multi-phase depreciation curve calibrated against real used-car
    market data (2024-2025 prices). Depreciation is steepest in year 1,
    then slows progressively as the vehicle ages.
    """
    from datetime import datetime
    current_year = datetime.now().year
    age = max(0, current_year - year)
    msrp = _lookup_msrp(model)

    # Multi-phase depreciation curve (calibrated to real market):
    #   Year 0: 95% (dealer markup absorbed)
    #   Year 1: 85% (~15% first-year hit)
    #   Year 2-3: ~8% per year
    #   Year 4-7: ~6% per year
    #   Year 8+: ~4% per year (floor effect — old cars depreciate slowly)
    if age == 0:
        base = msrp * 0.95
    elif age == 1:
        base = msrp * 0.85
    elif age <= 3:
        base = msrp * 0.85 * (0.92 ** (age - 1))
    elif age <= 7:
        # Value at age 3, then 6%/year
        base = msrp * 0.85 * (0.92 ** 2) * (0.94 ** (age - 3))
    else:
        # Value at age 7, then 4%/year
        base = msrp * 0.85 * (0.92 ** 2) * (0.94 ** 4) * (0.96 ** (age - 7))

    # Vehicles known to hold value better (Toyota trucks, Wranglers, etc.)
    retention = _lookup_retention(model)
    base *= retention

    # Mileage adjustment: ±$0.04/mile relative to expected for the age
    expected_miles = age * _AVG_ANNUAL_MILES
    if expected_miles > 0:
        mileage_adj = (mileage - expected_miles) * -0.04
    else:
        mileage_adj = 0

    return max(2_000, base + mileage_adj)


async def _score_listings_fast(listings: list[dict]) -> list[dict]:
    """Score all listings locally, then enrich only the top picks with API data.

    Phase 1: Local-only scoring (instant, no API calls)
      - Depreciation-based market value estimate
      - Deal scoring (price vs estimated value)
      - Composite score with defaults for unknown fields

    Phase 2: Enrich top ~10 listings with NHTSA + EPA data (free APIs, ~1-2s)
      - Safety ratings, complaints, recalls, fuel economy
      - Only unique (make, model, year) configs are fetched
    """
    # --- Phase 1: Local-only scoring for ALL listings (instant) ------------
    scored: list[dict] = []
    for listing in listings:
        make = listing.get("make", "")
        model = listing.get("model", "")
        year = listing.get("year", 0)
        price = float(listing.get("price", 0) or 0)
        mileage = int(listing.get("mileage", 0) or 0)

        if not make or not model or not year:
            scored.append({**listing, "score": _default_score()})
            continue

        estimated_value = _estimate_value(make, model, year, mileage)

        score = calculate_composite_score(
            safety_rating=None,
            complaint_count=0,
            price=price,
            estimated_value=estimated_value,
            mpg_combined=None,
            open_recalls=0,


        )

        deal = _compute_deal_score(listing, price, estimated_value)

        scored.append({
            **listing,
            "score": asdict(score),
            "deal": deal,
            "data": {
                "market_value": {
                    "estimated_value": round(estimated_value, -2),
                    "confidence": "estimate",
                    "source": "depreciation_formula",
                },
            },
        })

    logger.info("Fast-scored %d listings (local only, no API calls)", len(scored))

    # --- Phase 2: Enrich ALL listings with NHTSA + EPA (free APIs) --------
    # Gov APIs are free and we batch by unique (make, model, year), so even
    # 100 listings typically produce only 15-20 unique configs (~4 calls each).
    all_configs: set[tuple[str, str, int]] = set()
    for item in scored:
        m, mo, y = item.get("make", ""), item.get("model", ""), item.get("year", 0)
        if m and mo and y:
            all_configs.add((m, mo, y))

    if not all_configs:
        return scored

    logger.info("Enriching %d listings (%d unique configs) with NHTSA/EPA", len(scored), len(all_configs))

    from app.services.scoring import nhtsa, epa
    enriched: dict[tuple[str, str, int], dict] = {}
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _enrich(config: tuple[str, str, int]) -> None:
        make, model, year = config
        data: dict[str, Any] = {}
        async with semaphore:
            results = await asyncio.gather(
                nhtsa.get_safety_ratings(make, model, year),
                nhtsa.get_complaints(make, model, year),
                nhtsa.get_recalls(make=make, model=model, year=year),
                epa.get_fuel_economy(make, model, year),
                return_exceptions=True,
            )
            data["safety"] = results[0] if not isinstance(results[0], Exception) else None
            data["complaints"] = results[1] if not isinstance(results[1], Exception) else None
            data["recalls"] = results[2] if not isinstance(results[2], Exception) else None
            data["fuel"] = results[3] if not isinstance(results[3], Exception) else None
        enriched[config] = data

    await asyncio.gather(*[_enrich(cfg) for cfg in all_configs], return_exceptions=True)

    # Re-score ALL listings with real API data
    for item in scored:
        config_key = (item.get("make", ""), item.get("model", ""), item.get("year", 0))
        api_data = enriched.get(config_key)
        if not api_data:
            continue

        price = float(item.get("price", 0) or 0)
        estimated_value = float(item.get("data", {}).get("market_value", {}).get("estimated_value", 0))

        safety_rating = _safe_extract(api_data.get("safety"), "overall_rating", None)
        complaint_count = _safe_extract(api_data.get("complaints"), "complaint_count", 0)
        recall_count = _safe_extract(api_data.get("recalls"), "recall_count", 0)
        mpg_combined = _safe_extract(api_data.get("fuel"), "combined_mpg", None)

        score = calculate_composite_score(
            safety_rating=safety_rating,
            complaint_count=complaint_count,
            price=price,
            estimated_value=estimated_value,
            mpg_combined=mpg_combined,
            open_recalls=recall_count,
        )

        item["score"] = asdict(score)
        item["data"]["safety"] = _safe_dict(api_data.get("safety"))
        item["data"]["complaints"] = _safe_dict(api_data.get("complaints"))
        item["data"]["recalls"] = _safe_dict(api_data.get("recalls"))
        item["data"]["fuel_economy"] = _safe_dict(api_data.get("fuel"))

    logger.info("Enriched %d listings with NHTSA/EPA data (%d configs)", len(scored), len(enriched))
    return scored


# ---------------------------------------------------------------------------
# Deal scoring
# ---------------------------------------------------------------------------

_DEAL_THRESHOLDS = [
    (-0.10, "Great Deal"),   # 10%+ below market
    (-0.05, "Good Deal"),    # 5-10% below market
    (0.02, "Fair Price"),    # within 2% of market
    (0.08, "Above Market"),  # 2-8% above market
    (1.0, "Overpriced"),     # 8%+ above market
]


def _compute_deal_score(listing: dict, price: float, estimated_value: float) -> dict:
    """Compute a deal rating based on price vs market value and cross-source data.

    Returns a dict with:
      - rating: "Great Deal", "Good Deal", "Fair Price", "Above Market", "Overpriced"
      - savings: dollar amount below/above market
      - savings_pct: percentage below/above market
      - cross_source: savings info if found on multiple sources
      - source_badge: deal badge from the original source (Cars.com, etc.)
    """
    deal: dict = {
        "rating": "Unknown",
        "savings": 0.0,
        "savings_pct": 0.0,
        "source_badge": listing.get("deal_rating"),
    }

    # Cross-source data
    cross = listing.get("cross_source")
    if cross:
        deal["cross_source"] = {
            "cheapest_source": cross["cheapest_source"],
            "cheapest_price": cross["cheapest_price"],
            "highest_source": cross["highest_source"],
            "highest_price": cross["highest_price"],
            "savings": cross["price_spread"],
            "savings_pct": cross["savings_pct"],
        }

    if price <= 0 or estimated_value <= 0:
        return deal

    diff = price - estimated_value
    diff_pct = diff / estimated_value

    deal["savings"] = round(-diff, 2)
    deal["savings_pct"] = round(-diff_pct * 100, 1)

    # Assign rating
    for threshold, label in _DEAL_THRESHOLDS:
        if diff_pct <= threshold:
            deal["rating"] = label
            break

    # Override with source badge if more specific (e.g., Cars.com "Hot Deal")
    source_badge = listing.get("deal_rating", "")
    if source_badge:
        badge_lower = source_badge.lower()
        if any(w in badge_lower for w in ("great", "hot", "excellent")):
            if deal["rating"] not in ("Great Deal",):
                deal["rating"] = "Great Deal"
        elif "good" in badge_lower:
            if deal["rating"] not in ("Great Deal", "Good Deal"):
                deal["rating"] = "Good Deal"

    return deal


# ---------------------------------------------------------------------------
# Full scoring with external APIs  (for listing detail pages)
# ---------------------------------------------------------------------------

async def _score_listings_full(listings: list[dict]) -> list[dict]:
    """Score listings with full external API data (NHTSA, EPA, VinAudit)."""
    from app.services.scoring import nhtsa, epa, market_value

    # Phase 1: Prefetch shared data for unique (make, model, year) combos
    unique_configs: set[tuple[str, str, int]] = set()
    for lst in listings:
        m, mo, y = lst.get("make", ""), lst.get("model", ""), lst.get("year", 0)
        if m and mo and y:
            unique_configs.add((m, mo, y))

    logger.info("Full-scoring %d listings (%d unique configs)", len(listings), len(unique_configs))

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    shared_data: dict[tuple[str, str, int], dict] = {}

    async def _prefetch(key: tuple[str, str, int]) -> None:
        make, model, year = key
        async with semaphore:
            safety, complaints, fuel = await asyncio.gather(
                nhtsa.get_safety_ratings(make, model, year),
                nhtsa.get_complaints(make, model, year),
                epa.get_fuel_economy(make, model, year, ""),
                return_exceptions=True,
            )
            shared_data[key] = {"safety": safety, "complaints": complaints, "fuel": fuel}

    await asyncio.gather(*[_prefetch(k) for k in unique_configs])

    # Phase 2: Per-listing scoring
    async def _score_one(listing: dict) -> dict:
        async with semaphore:
            return await _score_single_full(listing, shared_data)

    results = await asyncio.gather(*[_score_one(l) for l in listings], return_exceptions=True)

    scored: list[dict] = []
    for listing, result in zip(listings, results):
        if isinstance(result, Exception):
            logger.error("Scoring failed for %s %s: %s", listing.get("make"), listing.get("model"), result)
            scored.append({**listing, "score": _default_score()})
        else:
            scored.append(result)
    return scored


async def _score_single_full(listing: dict, shared_data: dict) -> dict:
    from app.services.scoring import nhtsa, market_value

    make = listing.get("make", "")
    model = listing.get("model", "")
    year = listing.get("year", 0)
    price = float(listing.get("price", 0) or 0)
    mileage = int(listing.get("mileage", 0) or 0)
    vin = listing.get("vin", "")
    trim = listing.get("trim", "")

    if not make or not model or not year:
        return {**listing, "score": _default_score()}

    prefetched = shared_data.get((make, model, year), {})
    safety_data = prefetched.get("safety")
    complaints_data = prefetched.get("complaints")
    fuel_data = prefetched.get("fuel")

    recalls_data, value_data = await asyncio.gather(
        nhtsa.get_recalls(vin=vin, make=make, model=model, year=year),
        market_value.estimate_market_value(make, model, year, mileage, trim, vin),
        return_exceptions=True,
    )

    safety_rating = _safe_extract(safety_data, "overall_rating", None)
    complaint_count = _safe_extract(complaints_data, "complaint_count", 0)
    recall_count = _safe_extract(recalls_data, "recall_count", 0)
    mpg_combined = _safe_extract(fuel_data, "combined_mpg", None)
    estimated_value = float(_safe_extract(value_data, "estimated_value", 0) or 0)
    if price <= 0 and estimated_value > 0:
        price = estimated_value

    score = calculate_composite_score(
        safety_rating=safety_rating,
        complaint_count=complaint_count,
        price=price,
        estimated_value=estimated_value,
        mpg_combined=mpg_combined,
        open_recalls=recall_count,
    )

    return {
        **listing,
        "score": asdict(score),
        "data": {
            "safety": _safe_dict(safety_data),
            "complaints": _safe_dict(complaints_data),
            "recalls": _safe_dict(recalls_data),
            "fuel_economy": _safe_dict(fuel_data),
            "market_value": _safe_dict(value_data),
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_extract(result: Any, key: str, default: Any) -> Any:
    if isinstance(result, Exception):
        return default
    if isinstance(result, dict):
        return result.get(key, default)
    return default


def _safe_dict(result: Any) -> dict:
    if isinstance(result, Exception):
        return {"error": str(result)}
    if isinstance(result, dict):
        return result
    return {"error": "Unexpected result type"}


def _default_score() -> dict:
    score = calculate_composite_score(
        safety_rating=None, complaint_count=0, price=0,
        estimated_value=0, mpg_combined=None, open_recalls=0,
    )
    return asdict(score)
