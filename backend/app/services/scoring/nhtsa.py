"""
NHTSA (National Highway Traffic Safety Administration) API client.

Provides async access to safety ratings, complaints, recalls, and VIN decoding
via the free public NHTSA APIs.
"""

import asyncio
import time
from typing import Any, Optional
from urllib.parse import quote

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


def _cache_get(key: str) -> Optional[Any]:
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

_INTER_REQUEST_DELAY = 0.05  # 50 ms between calls (polite but not a bottleneck)

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
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "CarFINDa/1.0 (vehicle-scoring-service)",
}


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
        # to get actual star ratings.  Limit to 3 variants to avoid excessive calls.
        variants: list[dict] = []
        for item in results[:3]:
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
        def _safe_int(val: Any) -> Optional[int]:
            if val is None or val == "" or val == "Not Rated":
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        overall: Optional[int] = None
        front: Optional[int] = None
        side: Optional[int] = None
        rollover: Optional[int] = None

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

def _sanitize_for_path(s: str) -> str:
    """Clean and encode a string for use in URL path segments."""
    if not s or not isinstance(s, str):
        return ""
    return quote(s.strip().replace("/", " "), safe="")


async def get_complaints(make: str, model: str, year: int) -> dict:
    """
    Fetch NHTSA consumer complaints for a vehicle.

    Uses path-based ODI Complaints API:
    /Complaints/vehicle/modelyear/{YEAR}/make/{MAKE}/model/{MODEL}

    Returns a dict with:
        complaint_count (int),
        top_categories (list of {component, count}),
        error (str, only on failure)
    """
    cache_key = f"complaints:{make}:{model}:{year}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    make_enc = _sanitize_for_path(make)
    model_enc = _sanitize_for_path(model)
    # Both endpoints return 403 for programmatic access; single attempt
    url = (
        f"https://api.nhtsa.gov/complaints/vehicle/modelyear/{year}/make/{make_enc}/model/{model_enc}"
    )
    try:
        await _polite_delay()
        async with _client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", data.get("Results", []))
        complaint_count = len(results)

        # Tally complaints by component
        component_counts: dict[str, int] = {}
        for item in results:
            components = item.get("components") or item.get("Component", "Unknown")
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

    except (httpx.HTTPStatusError, httpx.RequestError, Exception):
        return {
            "complaint_count": 0,
            "top_categories": [],
            "error": "Complaints API returned 403 (blocked) or unreachable",
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

    Uses VPIC path-based RecallsByVehicle endpoint:
    https://vpic.nhtsa.dot.gov/api/RecallsByVehicle/{make}/{model}/{year}

    When only VIN is provided, decodes VIN first to get make/model/year.
    The query-param recallsByVehicle?vin= endpoint returns 400, so we use
    make/model/year path exclusively.

    Returns a dict with:
        recall_count (int),
        recalls (list of {nhtsa_campaign_number, component, summary}),
        error (str, only on failure)
    """
    cache_key = f"recalls:{vin or f'{make}:{model}:{year}'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Resolve make/model/year: use direct params or decode from VIN
    resolved_make, resolved_model, resolved_year = make, model, year
    if (not make or not model or not year) and vin and len(vin) == 17:
        decoded = await decode_vin(vin)
        if not decoded.get("error"):
            resolved_make = decoded.get("make", "")
            resolved_model = decoded.get("model", "")
            resolved_year = decoded.get("year", 0) or year

    if not resolved_make or not resolved_model or not resolved_year:
        return {
            "recall_count": 0,
            "recalls": [],
            "error": "No make/model/year (or valid VIN to decode) provided",
        }

    make_enc = _sanitize_for_path(resolved_make).lower() or "unknown"
    model_clean = resolved_model.strip()
    # VPIC often returns 404 for trim-specific models (e.g. "Camry SE").
    # Try base model first: "Camry SE" -> "Camry", "Sierra 1500 Denali" -> "Sierra 1500"
    def _base_model(m: str) -> str:
        parts = m.split()
        if not parts:
            return m
        if len(parts) >= 2 and parts[1].replace("-", "").isdigit():
            return " ".join(parts[:2])  # "Sierra 1500", "Model 3", "4Runner"
        return parts[0]

    # Try base model first (VPIC often 404s on trim-specific like "Camry SE")
    model_variants = [_base_model(model_clean), model_clean]
    model_variants = list(dict.fromkeys(model_variants))  # dedupe

    for model_try in model_variants:
        model_enc = _sanitize_for_path(model_try).lower() or "unknown"
        url = (
            "https://vpic.nhtsa.dot.gov/api/RecallsByVehicle"
            f"/{make_enc}/{model_enc}/{resolved_year}?format=json"
        )
        try:
            await _polite_delay()
            async with _client() as client:
                resp = await client.get(url)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
        except (httpx.HTTPStatusError, httpx.RequestError):
            continue
    else:
        return {
            "recall_count": 0,
            "recalls": [],
            "error": f"RecallsByVehicle 404 for {make}/{model}/{year}",
        }

    try:
        results = data.get("Results", data.get("results", []))

        recalls_list = []
        for r in results:
            recalls_list.append({
                "nhtsa_campaign_number": (
                    r.get("NHTSACampaignNumber") or r.get("nhtsa_campaign_number", "")
                ),
                "component": r.get("Component") or r.get("component", ""),
                "summary": r.get("Summary") or r.get("summary", ""),
                "consequence": r.get("Consequence") or r.get("consequence", ""),
                "remedy": r.get("Remedy") or r.get("remedy", ""),
                "report_date": (
                    r.get("ReportReceivedDate") or r.get("report_received_date", "")
                ),
            })

        result = {
            "recall_count": len(recalls_list),
            "recalls": recalls_list,
        }
        _cache_set(cache_key, result, _TTL_RECALLS)
        return result

    except (httpx.HTTPStatusError, httpx.RequestError, Exception) as exc:
        return {
            "recall_count": 0,
            "recalls": [],
            "error": str(exc),
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
