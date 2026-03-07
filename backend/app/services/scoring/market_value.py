"""
Market value estimation service.

Primary: Uses the Tavily search API to look up KBB / market pricing data.
Fallback: Simple depreciation-based estimation formula.
"""

import time
from datetime import datetime
from typing import Any

import httpx

from app.config import get_settings

# ---------------------------------------------------------------------------
# In-memory cache with TTL
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}
_TTL_VALUE = 3600  # 1 hour


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.time() > expires_at:
        del _cache[key]
        return None
    return value


def _cache_set(key: str, value: Any, ttl: float) -> None:
    _cache[key] = (time.time() + ttl, value)


# ---------------------------------------------------------------------------
# Rough MSRP estimates by segment (used for depreciation fallback)
# ---------------------------------------------------------------------------

_SEGMENT_MSRP: dict[str, int] = {
    # Sedans
    "civic": 25_000, "corolla": 23_000, "camry": 28_000, "accord": 29_000,
    "altima": 27_000, "sentra": 21_000, "malibu": 25_000, "sonata": 27_000,
    "elantra": 22_000, "mazda3": 24_000, "jetta": 23_000,
    # SUVs
    "rav4": 30_000, "cr-v": 31_000, "crv": 31_000, "rogue": 30_000,
    "tucson": 29_000, "cx-5": 29_000, "equinox": 28_000, "escape": 29_000,
    "highlander": 38_000, "pilot": 39_000, "4runner": 40_000,
    "tahoe": 55_000, "suburban": 58_000, "explorer": 37_000,
    "wrangler": 32_000, "grand cherokee": 42_000,
    # Trucks
    "f-150": 35_000, "f150": 35_000, "silverado": 36_000, "ram 1500": 37_000,
    "tacoma": 30_000, "tundra": 40_000, "colorado": 28_000, "ranger": 28_000,
    # Luxury
    "model 3": 40_000, "model y": 48_000, "model s": 80_000, "model x": 90_000,
    "3 series": 44_000, "5 series": 56_000, "x3": 48_000, "x5": 63_000,
    "c-class": 44_000, "e-class": 56_000, "glc": 48_000, "gle": 58_000,
    "a4": 42_000, "q5": 46_000, "rx": 48_000, "is": 40_000,
}

_DEFAULT_MSRP = 32_000  # reasonable mid-market default
_AVG_ANNUAL_MILEAGE = 12_000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def estimate_market_value(
    make: str,
    model: str,
    year: int,
    mileage: int,
    trim: str = "",
) -> dict:
    """
    Estimate fair market value for a vehicle.

    Tries Tavily search API first, falls back to depreciation formula.

    Returns:
        estimated_value (float),
        value_low (float),
        value_high (float),
        confidence ("api" | "estimate"),
        source (str),
        error (str, only on failure)
    """
    cache_key = f"value:{make}:{model}:{year}:{mileage}:{trim}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Try Tavily first
    settings = get_settings()
    tavily_key = settings.TAVILY_API_KEY

    if tavily_key:
        tavily_result = await _tavily_lookup(make, model, year, mileage, trim, tavily_key)
        if tavily_result is not None:
            _cache_set(cache_key, tavily_result, _TTL_VALUE)
            return tavily_result

    # Fallback: depreciation formula
    fallback = _depreciation_estimate(make, model, year, mileage)
    _cache_set(cache_key, fallback, _TTL_VALUE)
    return fallback


# ---------------------------------------------------------------------------
# Tavily search
# ---------------------------------------------------------------------------

async def _tavily_lookup(
    make: str,
    model: str,
    year: int,
    mileage: int,
    trim: str,
    api_key: str,
) -> dict | None:
    """Search Tavily for market value info and try to extract a price range."""
    trim_str = f" {trim}" if trim else ""
    query = f"{year} {make} {model}{trim_str} KBB fair market value"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5,
                    "include_answer": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Try to extract price from the answer or results
        answer = data.get("answer", "") or ""
        results_text = " ".join(
            r.get("content", "") for r in data.get("results", [])
        )
        combined_text = f"{answer} {results_text}"

        prices = _extract_prices(combined_text)

        if not prices:
            return None

        # Use median of extracted prices as the estimated value
        prices.sort()
        median_price = prices[len(prices) // 2]

        # Build a reasonable range
        if len(prices) >= 2:
            value_low = prices[0]
            value_high = prices[-1]
        else:
            value_low = median_price * 0.90
            value_high = median_price * 1.10

        # Adjust for mileage difference from average
        current_year = datetime.now().year
        vehicle_age = max(1, current_year - year)
        expected_mileage = vehicle_age * _AVG_ANNUAL_MILEAGE
        mileage_diff = mileage - expected_mileage
        mileage_adjustment = (mileage_diff / 1000) * -50  # $50 per 1k miles over/under

        adjusted_value = max(1000, median_price + mileage_adjustment)
        adjusted_low = max(1000, value_low + mileage_adjustment)
        adjusted_high = max(1000, value_high + mileage_adjustment)

        return {
            "estimated_value": round(adjusted_value, -2),  # round to nearest $100
            "value_low": round(adjusted_low, -2),
            "value_high": round(adjusted_high, -2),
            "confidence": "api",
            "source": "tavily_search",
        }

    except (httpx.HTTPStatusError, httpx.RequestError, Exception):
        return None


def _extract_prices(text: str) -> list[float]:
    """
    Extract dollar amounts from text that look like car prices ($XX,XXX format).
    Filters to reasonable vehicle price range ($1,000 - $200,000).
    """
    import re

    # Match patterns like $25,000 or $25000 or $25,500.00
    pattern = r"\$\s*([\d]{1,3}(?:,\d{3})*(?:\.\d{2})?)"
    matches = re.findall(pattern, text)

    prices: list[float] = []
    for m in matches:
        try:
            val = float(m.replace(",", ""))
            if 1_000 <= val <= 200_000:
                prices.append(val)
        except ValueError:
            continue

    return prices


# ---------------------------------------------------------------------------
# Depreciation fallback
# ---------------------------------------------------------------------------

def _depreciation_estimate(
    make: str,
    model: str,
    year: int,
    mileage: int,
) -> dict:
    """
    Simple depreciation-based market value estimate.

    Formula:
        base_price = MSRP * (0.85 ^ years_old)
        mileage_adjustment = (actual_mileage - expected_mileage) * -$0.05 per mile
    """
    current_year = datetime.now().year
    vehicle_age = max(0, current_year - year)

    # Try to look up a rough MSRP
    model_lower = model.lower().strip()
    msrp = _SEGMENT_MSRP.get(model_lower, _DEFAULT_MSRP)

    # Age-based depreciation: ~15% per year
    depreciation_factor = 0.85 ** vehicle_age
    base_price = msrp * depreciation_factor

    # Mileage adjustment
    expected_mileage = vehicle_age * _AVG_ANNUAL_MILEAGE
    mileage_diff = mileage - expected_mileage
    # $0.05 per mile over/under average
    mileage_adjustment = mileage_diff * -0.05

    estimated_value = max(1_000, base_price + mileage_adjustment)

    # Build a range (+-15% for estimate uncertainty)
    value_low = max(1_000, estimated_value * 0.85)
    value_high = estimated_value * 1.15

    return {
        "estimated_value": round(estimated_value, -2),
        "value_low": round(value_low, -2),
        "value_high": round(value_high, -2),
        "confidence": "estimate",
        "source": "depreciation_formula",
    }
