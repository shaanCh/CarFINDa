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

_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
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

async def get_fuel_economy(make: str, model: str, year: int) -> dict:
    """
    Fetch EPA fuel economy data for a vehicle.

    Strategy:
        1. GET /ws/rest/vehicle/menu/options?year={year}&make={make}&model={model}
           to discover available vehicle option IDs for that make/model/year.
        2. For each option ID, GET /ws/rest/vehicle/{id} to pull MPG numbers.
        3. Return the best (highest combined MPG) variant found, along with
           all variants for reference.

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

    # Step 1: Discover vehicle option IDs
    options_url = (
        f"https://fueleconomy.gov/ws/rest/vehicle/menu/options"
        f"?year={year}&make={make}&model={model}"
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
