"""
Auto.dev API Scraper -- Fetches dealer listings via the Auto.dev REST API.

Auto.dev provides a free tier (1,000 calls/month) with comprehensive dealer
inventory data.  No browser rendering or scraping needed -- just clean JSON.

Response format (confirmed):
  {
    "totalCount": 7844,
    "records": [
      {
        "id": 326327301,
        "vin": "4T1DAACK5TU224195",
        "year": 2026,
        "make": "Toyota",
        "model": "Camry",
        "trim": "LE",
        "priceUnformatted": 29240,
        "mileageUnformatted": 5,
        "city": "Allentown",
        "state": "PA",
        "dealerName": "Bennett Toyota",
        "primaryPhotoUrl": "https://...",
        "photoUrls": [...],
        "bodyType": "sedan",
        "condition": "used",
        "vdpUrl": "/toyota-camry#vin=...",
        "displayColor": "Ocean",
        ...
      }
    ]
  }
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any, Optional

import httpx

from app.services.scraping.base_scraper import create_http_client

logger = logging.getLogger(__name__)

_API_BASE = "https://auto.dev/api/listings"
MAX_PAGES = 2  # Conserve API calls (1000/month free)
RESULTS_PER_PAGE = 24


class AutoDevScraper:
    """Scraper using the Auto.dev listings API."""

    source_name = "Auto.dev"

    def __init__(self, api_key: str, http_client: Optional[httpx.AsyncClient] = None):
        self.api_key = api_key
        self._http_client = http_client
        self._owns_client = http_client is None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = create_http_client()
            self._owns_client = True
        return self._http_client

    async def close(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def search(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Search Auto.dev for listings matching filters."""
        all_listings: list[dict[str, Any]] = []

        for page_num in range(1, MAX_PAGES + 1):
            params = self._build_params(filters, page=page_num)
            logger.info("Auto.dev: requesting page %d", page_num)

            try:
                resp = await self.http.get(
                    _API_BASE,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    timeout=20.0,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning("Auto.dev API HTTP %d: %s", exc.response.status_code, exc)
                break
            except httpx.RequestError as exc:
                logger.warning("Auto.dev API request failed: %s", exc)
                break

            try:
                data = resp.json()
            except Exception:
                logger.warning("Auto.dev: non-JSON response")
                break

            records = data.get("records", []) if isinstance(data, dict) else []
            total = data.get("totalCount", 0) if isinstance(data, dict) else 0

            if not records:
                logger.info("Auto.dev: no records on page %d -- stopping", page_num)
                break

            for item in records:
                normalized = self._parse_item(item)
                if normalized:
                    all_listings.append(normalized)

            logger.info(
                "Auto.dev: page %d yielded %d listings (total available: %d, fetched: %d)",
                page_num, len(records), total, len(all_listings),
            )

            if len(records) < RESULTS_PER_PAGE:
                break

            await asyncio.sleep(0.3)

        return all_listings

    def _build_params(self, filters: dict[str, Any], page: int = 1) -> dict[str, str]:
        """Build Auto.dev API query params from structured filters."""
        params: dict[str, str] = {
            "page": str(page),
            "per_page": str(RESULTS_PER_PAGE),
            "condition": "used",  # Only used cars
        }

        makes = filters.get("makes", [])
        if makes:
            params["make"] = makes[0]

        models = filters.get("models", [])
        if models:
            params["model"] = models[0]

        price_max = filters.get("budget_max")
        if price_max:
            params["price_max"] = str(int(price_max))

        price_min = filters.get("budget_min")
        if price_min and price_min > 0:
            params["price_min"] = str(int(price_min))

        min_year = filters.get("min_year")
        if min_year:
            params["year_min"] = str(min_year)

        max_mileage = filters.get("max_mileage")
        if max_mileage:
            params["mileage_max"] = str(max_mileage)

        location = filters.get("location", "")
        if location:
            zip_match = re.search(r"\d{5}", location)
            if zip_match:
                params["zip"] = zip_match.group()

        radius = filters.get("radius_miles")
        if radius:
            params["radius"] = str(radius)

        body_types = filters.get("body_types", [])
        if body_types:
            params["body_type"] = body_types[0].lower()

        return params

    def _parse_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Convert an Auto.dev listing record into the standard schema."""
        if not isinstance(item, dict):
            return None

        year = item.get("year")
        make = item.get("make", "")
        model = item.get("model", "")
        if not year or not make:
            return None

        # Price: use priceUnformatted (int) over price (formatted string "$29,240")
        price = item.get("priceUnformatted")
        if not price or price == 0:
            # Try parsing the formatted price string
            price_str = item.get("price", "")
            if isinstance(price_str, str):
                cleaned = re.sub(r"[^\d.]", "", price_str)
                try:
                    price = float(cleaned) if cleaned else None
                except ValueError:
                    price = None
        if price == 0:
            price = None

        # Mileage: use mileageUnformatted (int)
        mileage = item.get("mileageUnformatted")
        if isinstance(mileage, str):
            try:
                mileage = int(mileage)
            except ValueError:
                mileage = None
        if mileage is not None and mileage < 10:
            # Likely "new" with delivery miles, skip for used search
            mileage = None

        # Images
        image_urls = []
        primary = item.get("primaryPhotoUrl") or item.get("thumbnailUrlLarge") or item.get("thumbnailUrl")
        if primary:
            image_urls.append(primary)
        for url in (item.get("photoUrls") or [])[:5]:
            if isinstance(url, str) and url not in image_urls:
                image_urls.append(url)

        # Location
        city = item.get("city", "")
        state = item.get("state", "")
        location = f"{city}, {state}" if city and state else city or state or None

        # Source URL
        vdp = item.get("vdpUrl", "")
        if vdp and not vdp.startswith("http"):
            source_url = f"https://auto.dev{vdp}"
        elif vdp:
            source_url = vdp
        else:
            source_url = None

        dealer = item.get("dealerName", "")
        color = item.get("displayColor", "")

        return {
            "id": str(uuid.uuid4()),
            "vin": item.get("vin") or None,
            "year": int(year),
            "make": make,
            "model": model,
            "trim": item.get("trim") or None,
            "title": None,
            "price": float(price) if price else None,
            "monthly_payment": item.get("monthlyPayment") or None,
            "mileage": int(mileage) if mileage else None,
            "mpg": None,
            "location": location,
            "source_url": source_url,
            "source_name": self.source_name,
            "sources": [{"name": self.source_name, "url": source_url, "price": float(price) if price else None}],
            "image_urls": image_urls,
            "exterior_color": color or None,
            "interior_color": None,
            "fuel_type": None,
            "motor_type": None,
            "transmission": None,
            "drivetrain": None,
            "deal_rating": "Hot Deal" if item.get("isHot") else None,
            "dealer_name": dealer or None,
        }
