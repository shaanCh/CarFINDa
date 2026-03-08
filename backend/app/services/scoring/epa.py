"""
EPA Fuel Economy API client.

Fetches fuel economy (MPG) data from the public fueleconomy.gov REST API.
"""

import time
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# In-memory cache with TTL
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}
_TTL_FUEL = 3600  # 1 hour


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
# HTTP helpers
# ---------------------------------------------------------------------------

_TIMEOUT = httpx.Timeout(8.0, connect=5.0)
# fueleconomy.gov returns XML by default; we request JSON-like XML and parse,
# but the REST API can also return JSON when we set the right header.
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "CarFINDa/1.0 (vehicle-scoring-service)",
}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=_TIMEOUT,
        headers=_HEADERS,
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_fuel_economy(make: str, model: str, year: int, trim: str = "") -> dict:
    """
    Fetch EPA fuel economy data for a vehicle.

    Strategy:
        1. List available model names for the make/year from EPA.
        2. Fuzzy-match the input model name to find the best EPA model name(s).
        3. Fetch vehicle option IDs for the matched model name.
        4. For each option ID, GET /ws/rest/vehicle/{id} to pull MPG numbers.
        5. Return the best (highest combined MPG) variant found.

    Returns a dict with:
        city_mpg (float | None),
        highway_mpg (float | None),
        combined_mpg (float | None),
        fuel_type (str),
        variants (list of dicts),
        error (str, only on failure)
    """
    cache_key = f"epa:{make}:{model}:{year}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Step 1: Find the correct EPA model name via fuzzy match
    epa_model = await _resolve_epa_model(make, model, year, trim)
    if not epa_model:
        result = _empty_result(
            f"No EPA model match found for {year} {make} {model}"
        )
        _cache_set(cache_key, result, _TTL_FUEL)
        return result

    # Step 2: Discover vehicle option IDs
    options_url = (
        f"https://fueleconomy.gov/ws/rest/vehicle/menu/options"
        f"?year={year}&make={make}&model={epa_model}"
    )

    try:
        async with _client() as client:
            resp = await client.get(options_url)
            resp.raise_for_status()

            # The API may return XML even with JSON Accept header.
            # Try JSON first, fall back to XML parsing.
            vehicle_ids: list[int] = []
            content_type = resp.headers.get("content-type", "")

            if "json" in content_type:
                data = resp.json()
                if data is None:
                    result = _empty_result("EPA returned null for options query")
                    _cache_set(cache_key, result, _TTL_FUEL)
                    return result
                menu_items = data.get("menuItem", [])
                # Single result comes as a dict, not a list
                if isinstance(menu_items, dict):
                    menu_items = [menu_items]
                for item in menu_items:
                    vid = item.get("value")
                    if vid:
                        try:
                            vehicle_ids.append(int(vid))
                        except (ValueError, TypeError):
                            pass
            else:
                # Parse minimal XML — look for <value>...</value> tags
                text = resp.text
                import re
                vehicle_ids = [
                    int(m) for m in re.findall(r"<value>(\d+)</value>", text)
                ]

        if not vehicle_ids:
            result = _empty_result("No vehicle options found for this make/model/year")
            _cache_set(cache_key, result, _TTL_FUEL)
            return result

        # Step 2: Fetch details for each vehicle option (limit to first 5
        # to be polite to the API)
        variants: list[dict] = []
        for vid in vehicle_ids[:5]:
            detail_url = f"https://fueleconomy.gov/ws/rest/vehicle/{vid}"
            try:
                async with _client() as client:
                    detail_resp = await client.get(detail_url)
                    detail_resp.raise_for_status()

                    detail_ct = detail_resp.headers.get("content-type", "")
                    if "json" in detail_ct:
                        vdata = detail_resp.json()
                        if vdata is None:
                            continue
                    else:
                        vdata = _parse_vehicle_xml(detail_resp.text)

                    variants.append({
                        "id": vid,
                        "city_mpg": _safe_float(vdata.get("city08")),
                        "highway_mpg": _safe_float(vdata.get("highway08")),
                        "combined_mpg": _safe_float(vdata.get("comb08")),
                        "fuel_type": vdata.get("fuelType", "") or vdata.get("fuelType1", ""),
                        "year": vdata.get("year", year),
                        "make": vdata.get("make", make),
                        "model": vdata.get("model", model),
                        "trany": vdata.get("trany", ""),
                        "cylinders": vdata.get("cylinders", ""),
                        "displ": vdata.get("displ", ""),
                    })
            except (httpx.HTTPStatusError, httpx.RequestError):
                continue

        if not variants:
            result = _empty_result("Could not fetch details for any vehicle option")
            _cache_set(cache_key, result, _TTL_FUEL)
            return result

        # Step 3: Pick the variant with the best combined MPG (most common trim)
        best = max(
            variants,
            key=lambda v: v.get("combined_mpg") or 0,
        )

        result = {
            "city_mpg": best.get("city_mpg"),
            "highway_mpg": best.get("highway_mpg"),
            "combined_mpg": best.get("combined_mpg"),
            "fuel_type": best.get("fuel_type", ""),
            "variants": variants,
        }
        _cache_set(cache_key, result, _TTL_FUEL)
        return result

    except (httpx.HTTPStatusError, httpx.RequestError, Exception) as exc:
        return _empty_result(str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_epa_model(
    make: str, model: str, year: int, trim: str = "",
) -> str | None:
    """
    Look up available EPA model names for a make/year and return the best
    match for the given model string.

    EPA uses very specific names (e.g. "Civic 4Dr", "F150 Pickup 2WD",
    "Model 3 Standard Range Plus RWD") so we need fuzzy matching.
    """
    url = (
        f"https://fueleconomy.gov/ws/rest/vehicle/menu/model"
        f"?year={year}&make={make}"
    )
    try:
        async with _client() as client:
            resp = await client.get(url)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            epa_models: list[str] = []

            if "json" in content_type:
                data = resp.json()
                if data is None:
                    return None
                menu_items = data.get("menuItem", [])
                if isinstance(menu_items, dict):
                    menu_items = [menu_items]
                epa_models = [item.get("value", "") for item in menu_items]
            else:
                import re
                epa_models = re.findall(r"<value>(.*?)</value>", resp.text)

        if not epa_models:
            return None

        # Try model name first
        result = _best_model_match(model, epa_models)
        if result:
            return result

        # If model is a series name (e.g. "3 Series"), try the trim instead
        if trim:
            result = _best_model_match(trim, epa_models)
            if result:
                return result

        return None

    except (httpx.HTTPStatusError, httpx.RequestError):
        return None


def _best_model_match(query: str, candidates: list[str]) -> str | None:
    """
    Find the best EPA model name matching a user-provided model string.

    Matching strategy (in priority order):
      1. Exact match (case-insensitive)
      2. Candidate starts with the query (e.g. "Civic" matches "Civic 4Dr")
      3. Query is contained in candidate after normalization
      4. Normalized query matches normalized candidate prefix
    """
    q = query.lower().strip()
    # Normalize: strip hyphens, common suffixes
    q_norm = q.replace("-", "").replace(" ", "")

    # Exact match
    for c in candidates:
        if c.lower().strip() == q:
            return c

    # Starts-with match — prefer shortest (most generic) candidate
    starts_with = [c for c in candidates if c.lower().startswith(q)]
    if starts_with:
        return min(starts_with, key=len)

    # Normalized prefix match (handles "F-150" → "F150 Pickup 2WD")
    norm_matches = [
        c for c in candidates
        if c.lower().replace("-", "").replace(" ", "").startswith(q_norm)
    ]
    if norm_matches:
        return min(norm_matches, key=len)

    # Query contained in candidate
    contains = [c for c in candidates if q in c.lower()]
    if contains:
        return min(contains, key=len)

    # Normalized containment
    norm_contains = [
        c for c in candidates
        if q_norm in c.lower().replace("-", "").replace(" ", "")
    ]
    if norm_contains:
        return min(norm_contains, key=len)

    return None


def _empty_result(error: str) -> dict:
    return {
        "city_mpg": None,
        "highway_mpg": None,
        "combined_mpg": None,
        "fuel_type": "",
        "variants": [],
        "error": error,
    }


def _safe_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _parse_vehicle_xml(xml_text: str) -> dict:
    """Minimal XML parser to extract key fields from fueleconomy.gov response."""
    import re

    fields = [
        "city08", "highway08", "comb08", "fuelType", "fuelType1",
        "year", "make", "model", "trany", "cylinders", "displ",
    ]
    result: dict[str, str] = {}
    for field in fields:
        match = re.search(rf"<{field}>(.*?)</{field}>", xml_text)
        if match:
            result[field] = match.group(1)
    return result
