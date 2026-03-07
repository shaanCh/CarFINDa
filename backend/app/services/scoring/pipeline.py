"""
Scoring pipeline orchestrator.

Runs the full scoring pipeline for a batch of vehicle listings, calling all
data sources in parallel and computing composite scores.
"""

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from app.services.scoring import nhtsa, epa, market_value
from app.services.scoring.calculator import calculate_composite_score, ListingScore

logger = logging.getLogger(__name__)

# Maximum number of listings to score concurrently
_MAX_CONCURRENCY = 5


async def score_listings(listings: list[dict]) -> list[dict]:
    """
    Score a batch of vehicle listings.

    Each listing dict should contain at minimum:
        make (str), model (str), year (int)

    Optional fields that improve scoring:
        price (float)       — listing/asking price
        mileage (int)       — odometer reading
        vin (str)           — Vehicle Identification Number
        trim (str)          — vehicle trim level

    Returns the input listings enriched with a ``score`` key containing
    the ListingScore breakdown.
    """
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _score_one(listing: dict) -> dict:
        async with semaphore:
            return await _score_single_listing(listing)

    tasks = [_score_one(lst) for lst in listings]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    scored: list[dict] = []
    for listing, result in zip(listings, results):
        if isinstance(result, Exception):
            logger.error(
                "Failed to score listing %s %s %s: %s",
                listing.get("make"), listing.get("model"), listing.get("year"),
                result,
            )
            enriched = {**listing, "score": _default_score()}
        else:
            enriched = result
        scored.append(enriched)

    return scored


async def _score_single_listing(listing: dict) -> dict:
    """
    Fetch all data sources in parallel and calculate composite score for one listing.
    """
    make: str = listing.get("make", "")
    model: str = listing.get("model", "")
    year: int = listing.get("year", 0)
    price: float = float(listing.get("price", 0) or 0)
    mileage: int = int(listing.get("mileage", 0) or 0)
    vin: str = listing.get("vin", "")
    trim: str = listing.get("trim", "")

    if not make or not model or not year:
        logger.warning("Listing missing make/model/year, returning default score")
        return {**listing, "score": _default_score()}

    # Run all data fetches in parallel
    safety_task = nhtsa.get_safety_ratings(make, model, year)
    complaints_task = nhtsa.get_complaints(make, model, year)
    recalls_task = nhtsa.get_recalls(vin=vin, make=make, model=model, year=year)
    fuel_task = epa.get_fuel_economy(make, model, year)
    value_task = market_value.estimate_market_value(
        make, model, year, mileage, trim
    )

    (
        safety_data,
        complaints_data,
        recalls_data,
        fuel_data,
        value_data,
    ) = await asyncio.gather(
        safety_task,
        complaints_task,
        recalls_task,
        fuel_task,
        value_task,
        return_exceptions=True,
    )

    # Extract values with safe defaults if any call failed
    safety_rating = _safe_extract(safety_data, "overall_rating", None)
    complaint_count = _safe_extract(complaints_data, "complaint_count", 0)
    recall_count = _safe_extract(recalls_data, "recall_count", 0)
    mpg_combined = _safe_extract(fuel_data, "combined_mpg", None)
    estimated_value = float(_safe_extract(value_data, "estimated_value", 0) or 0)

    # Use estimated value for price if no listing price given
    if price <= 0 and estimated_value > 0:
        price = estimated_value

    # Calculate composite score
    score: ListingScore = calculate_composite_score(
        safety_rating=safety_rating,
        complaint_count=complaint_count,
        price=price,
        estimated_value=estimated_value,
        mpg_combined=mpg_combined,
        open_recalls=recall_count,
    )

    # Build enriched listing
    enriched = {
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

    return enriched


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_extract(result: Any, key: str, default: Any) -> Any:
    """Safely extract a key from a result that may be an Exception."""
    if isinstance(result, Exception):
        return default
    if isinstance(result, dict):
        return result.get(key, default)
    return default


def _safe_dict(result: Any) -> dict:
    """Return the result dict, or an error dict if the result is an Exception."""
    if isinstance(result, Exception):
        return {"error": str(result)}
    if isinstance(result, dict):
        return result
    return {"error": "Unexpected result type"}


def _default_score() -> dict:
    """Return a default score dict when scoring completely fails."""
    score = calculate_composite_score(
        safety_rating=None,
        complaint_count=0,
        price=0,
        estimated_value=0,
        mpg_combined=None,
        open_recalls=0,
    )
    return asdict(score)
