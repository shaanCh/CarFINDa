"""
NHTSA (National Highway Traffic Safety Administration) API client.

Provides async access to safety ratings, complaints, recalls, and VIN decoding
via the free public NHTSA APIs.
"""

import asyncio
import time
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# In-memory cache with TTL
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}

# TTLs in seconds
_TTL_SAFETY = 3600      # 1 hour — safety ratings rarely change
_TTL_COMPLAINTS = 3600  # 1 hour
_TTL_RECALLS = 1800     # 30 min — recalls can be issued at any time
_TTL_VIN = 86400        # 24 hours — VIN decode data never changes


def _cache_get(key: str) -> Any | None:
    """Return cached value if it exists and has not expired."""
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
# Rate-limiting helper — small delay between sequential government API calls
# ---------------------------------------------------------------------------

_INTER_REQUEST_DELAY = 0.15  # 150 ms between calls (polite)

_last_request_time: float = 0.0
_request_lock = asyncio.Lock()


async def _polite_delay() -> None:
    """Ensure at least _INTER_REQUEST_DELAY seconds between outgoing requests."""
    global _last_request_time
    async with _request_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < _INTER_REQUEST_DELAY:
            await asyncio.sleep(_INTER_REQUEST_DELAY - elapsed)
        _last_request_time = time.time()


# ---------------------------------------------------------------------------
# Shared HTTP client
# ---------------------------------------------------------------------------

_TIMEOUT = httpx.Timeout(8.0, connect=5.0)
_HEADERS = {"Accept": "application/json"}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS)


# ---------------------------------------------------------------------------
# Safety Ratings
# ---------------------------------------------------------------------------

async def get_safety_ratings(make: str, model: str, year: int) -> dict:
    """
    Fetch NHTSA 5-star safety ratings for a vehicle.

    Returns a dict with:
        overall_rating (int 1-5 or None),
        front_crash (int or None),
        side_crash (int or None),
        rollover (int or None),
        raw_results (list of variant dicts)
    """
    cache_key = f"safety:{make}:{model}:{year}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = (
        f"https://api.nhtsa.gov/SafetyRatings"
        f"/modelyear/{year}/make/{make}/model/{model}"
    )

    try:
        await _polite_delay()
        async with _client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("Results", [])

        # The first call returns vehicle IDs; we need to fetch each variant
        # to get actual star ratings.
        variants: list[dict] = []
        for item in results:
            vehicle_id = item.get("VehicleId")
            if vehicle_id is None:
                continue
            detail_url = f"https://api.nhtsa.gov/SafetyRatings/VehicleId/{vehicle_id}"
            await _polite_delay()
            async with _client() as client:
                detail_resp = await client.get(detail_url)
                detail_resp.raise_for_status()
                detail_data = detail_resp.json()
            for r in detail_data.get("Results", []):
                variants.append(r)

        # Pick the best available overall rating across variants
        def _safe_int(val: Any) -> int | None:
            if val is None or val == "" or val == "Not Rated":
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        overall: int | None = None
        front: int | None = None
        side: int | None = None
        rollover: int | None = None

        for v in variants:
            o = _safe_int(v.get("OverallRating"))
            if o is not None and (overall is None or o > overall):
                overall = o
                front = _safe_int(v.get("FrontCrashDriversideRating")) or _safe_int(
                    v.get("FrontCrashPassengersideRating")
                )
                side = _safe_int(v.get("SideCrashDriversideRating")) or _safe_int(
                    v.get("SideCrashPassengersideRating")
                )
                rollover = _safe_int(v.get("RolloverRating") or v.get("RolloverRating2"))

        result = {
            "overall_rating": overall,
            "front_crash": front,
            "side_crash": side,
            "rollover": rollover,
            "raw_results": variants,
        }
        _cache_set(cache_key, result, _TTL_SAFETY)
        return result

    except (httpx.HTTPStatusError, httpx.RequestError, Exception) as exc:
        return {
            "overall_rating": None,
            "front_crash": None,
            "side_crash": None,
            "rollover": None,
            "raw_results": [],
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

async def get_complaints(make: str, model: str, year: int) -> dict:
    """
    Fetch NHTSA consumer complaints for a vehicle.

    Returns a dict with:
        complaint_count (int),
        top_categories (list of {component, count}),
        error (str, only on failure)
    """
    cache_key = f"complaints:{make}:{model}:{year}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = (
        "https://api.nhtsa.gov/complaints/complaintsByVehicle"
        f"?make={make}&model={model}&modelYear={year}"
    )

    try:
        await _polite_delay()
        async with _client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        complaint_count = len(results)

        # Tally complaints by component
        component_counts: dict[str, int] = {}
        for item in results:
            components = item.get("components", "Unknown")
            if components:
                for comp in components.split(","):
                    comp = comp.strip()
                    if comp:
                        component_counts[comp] = component_counts.get(comp, 0) + 1

        # Sort by frequency, take top 5
        top_categories = sorted(
            [{"component": k, "count": v} for k, v in component_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        result = {
            "complaint_count": complaint_count,
            "top_categories": top_categories,
        }
        _cache_set(cache_key, result, _TTL_COMPLAINTS)
        return result

    except (httpx.HTTPStatusError, httpx.RequestError, Exception) as exc:
        return {
            "complaint_count": 0,
            "top_categories": [],
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Recalls
# ---------------------------------------------------------------------------

async def get_recalls(
    vin: str = "",
    make: str = "",
    model: str = "",
    year: int = 0,
) -> dict:
    """
    Fetch NHTSA recall information for a vehicle.

    Prefers VIN-based lookup if a VIN is provided, falling back to
    make/model/year lookup.

    Returns a dict with:
        recall_count (int),
        recalls (list of {nhtsa_campaign_number, component, summary}),
        error (str, only on failure)
    """
    cache_key = f"recalls:{vin or f'{make}:{model}:{year}'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    urls_to_try: list[str] = []
    if vin:
        urls_to_try.append(
            f"https://api.nhtsa.gov/recalls/recallsByVehicle?vin={vin}"
        )
    if make and model and year:
        urls_to_try.append(
            "https://api.nhtsa.gov/recalls/recallsByVehicle"
            f"?make={make}&model={model}&modelYear={year}"
        )

    if not urls_to_try:
        return {
            "recall_count": 0,
            "recalls": [],
            "error": "No VIN or make/model/year provided",
        }

    for url in urls_to_try:
        try:
            await _polite_delay()
            async with _client() as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

            results = data.get("results", [])

            recalls_list = []
            for r in results:
                recalls_list.append({
                    "nhtsa_campaign_number": r.get("NHTSACampaignNumber", ""),
                    "component": r.get("Component", ""),
                    "summary": r.get("Summary", ""),
                    "consequence": r.get("Consequence", ""),
                    "remedy": r.get("Remedy", ""),
                    "report_date": r.get("ReportReceivedDate", ""),
                })

            result = {
                "recall_count": len(recalls_list),
                "recalls": recalls_list,
            }
            _cache_set(cache_key, result, _TTL_RECALLS)
            return result

        except (httpx.HTTPStatusError, httpx.RequestError):
            continue  # try next URL

    return {
        "recall_count": 0,
        "recalls": [],
        "error": "All recall lookup attempts failed",
    }


# ---------------------------------------------------------------------------
# VIN Decode
# ---------------------------------------------------------------------------

async def decode_vin(vin: str) -> dict:
    """
    Decode a VIN using NHTSA vPIC API.

    Returns a dict with:
        make, model, year, body_class, fuel_type, engine, drive_type, trim,
        and the full decoded_values dict.
    """
    cache_key = f"vin:{vin}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"

    try:
        await _polite_delay()
        async with _client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("Results", [])
        if not results:
            return {
                "make": "",
                "model": "",
                "year": 0,
                "body_class": "",
                "fuel_type": "",
                "engine": "",
                "drive_type": "",
                "trim": "",
                "decoded_values": {},
                "error": "No results returned from VIN decode",
            }

        r = results[0]

        def _val(key: str) -> str:
            v = r.get(key, "")
            return v if v and v != "Not Applicable" else ""

        year_str = _val("ModelYear")
        try:
            year_int = int(year_str)
        except (ValueError, TypeError):
            year_int = 0

        result = {
            "make": _val("Make"),
            "model": _val("Model"),
            "year": year_int,
            "body_class": _val("BodyClass"),
            "fuel_type": _val("FuelTypePrimary"),
            "engine": f"{_val('EngineCylinders')}cyl {_val('DisplacementL')}L".strip(),
            "drive_type": _val("DriveType"),
            "trim": _val("Trim"),
            "decoded_values": r,
        }
        _cache_set(cache_key, result, _TTL_VIN)
        return result

    except (httpx.HTTPStatusError, httpx.RequestError, Exception) as exc:
        return {
            "make": "",
            "model": "",
            "year": 0,
            "body_class": "",
            "fuel_type": "",
            "engine": "",
            "drive_type": "",
            "trim": "",
            "decoded_values": {},
            "error": str(exc),
        }
