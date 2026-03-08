"""
VinAudit Ownership Cost API client.

Fetches 5-year projected ownership costs (depreciation, insurance, fuel,
maintenance, repairs, fees) for a vehicle by VIN.
"""

import time
from typing import Any

import httpx

from app.config import get_settings

# ---------------------------------------------------------------------------
# In-memory cache with TTL
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}
_TTL = 3600  # 1 hour


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
# Public API
# ---------------------------------------------------------------------------

_ENDPOINT = "https://ownershipcost.vinaudit.com/getownershipcost.php"


async def get_ownership_cost(
    vin: str,
    state: str = "CA",
    mileage_year: int = 12000,
) -> dict:
    """
    Fetch 5-year ownership cost projection from VinAudit.

    Args:
        vin:          17-character VIN.
        state:        US state code (affects insurance/fees). Defaults to CA.
        mileage_year: Estimated annual mileage.

    Returns dict with:
        yearly_total (list[float])     — total cost per year for 5 years,
        five_year_total (float)        — sum of all 5 years,
        annual_average (float)         — five_year_total / 5,
        categories (dict)              — breakdown by cost type,
        vehicle (str)                  — decoded vehicle description,
        source (str)                   — "vinaudit_ownership",
        error (str)                    — only on failure.
    """
    if not vin or len(vin) != 17:
        return _empty_result("Invalid or missing VIN")

    cache_key = f"ownership:{vin}:{state}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    settings = get_settings()
    api_key = settings.VINAUDIT_API_KEY
    if not api_key or api_key == "VA_DEMO_KEY":
        return _empty_result("VINAUDIT_API_KEY not configured or using demo key")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(
                _ENDPOINT,
                params={
                    "key": api_key,
                    "vin": vin,
                    "state": state,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if not data.get("vin") or not data.get("vehicle"):
            return _empty_result("No ownership cost data for this VIN")

        total_cost = data.get("total_cost", [])
        total_sum = data.get("total_cost_sum", 0)

        if not total_cost or total_sum <= 0:
            return _empty_result("Incomplete ownership cost data")

        annual_avg = total_sum / max(len(total_cost), 1)

        result = {
            "yearly_total": total_cost,
            "five_year_total": total_sum,
            "annual_average": round(annual_avg),
            "categories": {
                "depreciation": data.get("depreciation_cost", []),
                "insurance": data.get("insurance_cost", []),
                "fuel": data.get("fuel_cost", []),
                "maintenance": data.get("maintenance_cost", []),
                "repairs": data.get("repairs_cost", []),
                "fees": data.get("fees_cost", []),
            },
            "vehicle": data.get("vehicle", ""),
            "source": "vinaudit_ownership",
        }
        _cache_set(cache_key, result, _TTL)
        return result

    except (httpx.HTTPStatusError, httpx.RequestError, Exception) as exc:
        return _empty_result(str(exc))


def _empty_result(error: str) -> dict:
    return {
        "yearly_total": [],
        "five_year_total": 0,
        "annual_average": 0,
        "categories": {},
        "vehicle": "",
        "source": "vinaudit_ownership",
        "error": error,
    }
