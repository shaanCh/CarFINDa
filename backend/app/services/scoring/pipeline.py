"""
Scoring pipeline orchestrator.

Two modes:
  - **Fast mode** (default for search results): Uses only local data
    (depreciation formula, price/mileage/year heuristics). No external API
    calls. Scores 100+ listings in <100ms.
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
        full:     If True, call external APIs (NHTSA, EPA, VinAudit).
                  If False (default), use fast local-only scoring.
    """
    if not listings:
        return []

    if full:
        return await _score_listings_full(listings)
    return _score_listings_fast(listings)


# ---------------------------------------------------------------------------
# Fast local-only scoring  (for search results grid)
# ---------------------------------------------------------------------------

# Rough average depreciation-based MSRP estimates by model
_SEGMENT_MSRP: dict[str, int] = {
    "civic": 25_000, "corolla": 23_000, "camry": 28_000, "accord": 29_000,
    "altima": 27_000, "sentra": 21_000, "malibu": 25_000, "sonata": 27_000,
    "elantra": 22_000, "mazda3": 24_000, "jetta": 23_000,
    "rav4": 30_000, "cr-v": 31_000, "crv": 31_000, "rogue": 30_000,
    "tucson": 29_000, "cx-5": 29_000, "equinox": 28_000, "escape": 29_000,
    "highlander": 38_000, "pilot": 39_000, "4runner": 40_000,
    "tahoe": 55_000, "suburban": 58_000, "explorer": 37_000,
    "wrangler": 32_000, "grand cherokee": 42_000,
    "f-150": 35_000, "f150": 35_000, "silverado": 36_000, "ram 1500": 37_000,
    "tacoma": 30_000, "tundra": 40_000, "colorado": 28_000, "ranger": 28_000,
    "model 3": 40_000, "model y": 48_000, "model s": 80_000, "model x": 90_000,
    "3 series": 44_000, "5 series": 56_000, "x3": 48_000, "x5": 63_000,
    "corvette": 65_000, "mustang": 32_000, "camaro": 30_000,
    "prius": 28_000, "outback": 30_000, "forester": 29_000,
}
_DEFAULT_MSRP = 32_000
_AVG_ANNUAL_MILES = 12_000


def _estimate_value(make: str, model: str, year: int, mileage: int) -> float:
    """Fast depreciation-based market value estimate."""
    from datetime import datetime
    current_year = datetime.now().year
    age = max(0, current_year - year)
    msrp = _SEGMENT_MSRP.get(model.lower().strip(), _DEFAULT_MSRP)
    base = msrp * (0.85 ** age)
    expected_miles = age * _AVG_ANNUAL_MILES
    mileage_adj = (mileage - expected_miles) * -0.05
    return max(1_000, base + mileage_adj)


def _score_listings_fast(listings: list[dict]) -> list[dict]:
    """Score all listings using local-only heuristics. No API calls."""
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
            safety_rating=None,       # unknown — uses default 60
            complaint_count=0,        # unknown — uses default 100
            price=price,
            estimated_value=estimated_value,
            mpg_combined=None,        # unknown — uses default 50
            open_recalls=0,           # unknown — uses default 100
            annual_ownership_cost=None,
        )

        scored.append({
            **listing,
            "score": asdict(score),
            "data": {
                "market_value": {
                    "estimated_value": round(estimated_value, -2),
                    "confidence": "estimate",
                    "source": "depreciation_formula",
                },
            },
        })

    logger.info("Fast-scored %d listings (no external API calls)", len(scored))
    return scored


# ---------------------------------------------------------------------------
# Full scoring with external APIs  (for listing detail pages)
# ---------------------------------------------------------------------------

async def _score_listings_full(listings: list[dict]) -> list[dict]:
    """Score listings with full external API data (NHTSA, EPA, VinAudit)."""
    from app.services.scoring import nhtsa, epa, market_value, ownership_cost

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
    from app.services.scoring import nhtsa, market_value, ownership_cost

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

    recalls_data, value_data, cost_data = await asyncio.gather(
        nhtsa.get_recalls(vin=vin, make=make, model=model, year=year),
        market_value.estimate_market_value(make, model, year, mileage, trim, vin),
        ownership_cost.get_ownership_cost(vin=vin),
        return_exceptions=True,
    )

    safety_rating = _safe_extract(safety_data, "overall_rating", None)
    complaint_count = _safe_extract(complaints_data, "complaint_count", 0)
    recall_count = _safe_extract(recalls_data, "recall_count", 0)
    mpg_combined = _safe_extract(fuel_data, "combined_mpg", None)
    estimated_value = float(_safe_extract(value_data, "estimated_value", 0) or 0)
    annual_cost = _safe_extract(cost_data, "annual_average", None)
    if annual_cost is not None and annual_cost <= 0:
        annual_cost = None
    if price <= 0 and estimated_value > 0:
        price = estimated_value

    score = calculate_composite_score(
        safety_rating=safety_rating,
        complaint_count=complaint_count,
        price=price,
        estimated_value=estimated_value,
        mpg_combined=mpg_combined,
        open_recalls=recall_count,
        annual_ownership_cost=annual_cost,
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
            "ownership_cost": _safe_dict(cost_data),
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
