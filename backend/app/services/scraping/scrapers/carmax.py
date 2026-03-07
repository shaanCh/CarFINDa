"""
CarMax Scraper

Fetches vehicle listings from carmax.com using a two-tier strategy:

  1. **Primary (fast path)** -- GET ``https://www.carmax.com/cars/api/search/run``
     via httpx.  No browser needed; returns structured JSON.
  2. **Fallback (browser path)** -- If the API returns 403 / fails, use the
     Playwright sidecar to render the search page, retrieve the rendered HTML,
     and parse with BeautifulSoup.

The class is standalone -- it does *not* inherit from ``BaseScraper``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import uuid
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from app.services.scraping.base_scraper import create_http_client
from app.services.scraping.browser_client import BrowserClient

logger = logging.getLogger(__name__)

# Maximum pages to scrape per search
MAX_PAGES = 3
# CarMax returns up to 24 results per API page
RESULTS_PER_PAGE = 24

# ---------------------------------------------------------------------------
# Location helpers
# ---------------------------------------------------------------------------

CITY_TO_ZIP: dict[str, str] = {
    "boulder, co": "80302",
    "denver, co": "80202",
    "colorado springs, co": "80903",
    "austin, tx": "78701",
    "dallas, tx": "75201",
    "houston, tx": "77001",
    "san antonio, tx": "78201",
    "los angeles, ca": "90001",
    "san francisco, ca": "94102",
    "san diego, ca": "92101",
    "phoenix, az": "85001",
    "seattle, wa": "98101",
    "portland, or": "97201",
    "chicago, il": "60601",
    "new york, ny": "10001",
    "miami, fl": "33101",
    "atlanta, ga": "30301",
    "charlotte, nc": "28201",
    "nashville, tn": "37201",
    "salt lake city, ut": "84101",
}


def _extract_zip(location: str) -> str:
    """Try to extract or map a zip code from a location string.

    Handles formats like:
      - "80302" (raw zip)
      - "Boulder, CO" (city lookup)
      - "Boulder, CO 80302" (extract trailing zip)
    """
    location = location.strip()

    # Already a zip code?
    if location.isdigit() and len(location) == 5:
        return location

    # Trailing zip code?
    parts = location.split()
    if parts and parts[-1].isdigit() and len(parts[-1]) == 5:
        return parts[-1]

    # City lookup
    normalized = location.lower().strip()
    if normalized in CITY_TO_ZIP:
        return CITY_TO_ZIP[normalized]

    # Try without trailing state abbreviation variations
    for key, zipcode in CITY_TO_ZIP.items():
        if key in normalized:
            return zipcode

    # Default fallback -- empty means CarMax will use nationwide search
    logger.warning("Could not map location '%s' to a zip code for CarMax", location)
    return ""


# ---------------------------------------------------------------------------
# CarMax API endpoint
# ---------------------------------------------------------------------------

_API_URL = "https://www.carmax.com/cars/api/search/run"


class CarMaxScraper:
    """Scraper for carmax.com.

    Primary path: CarMax JSON API via httpx (fast, no browser).
    Fallback: sidecar browser rendering + BeautifulSoup parsing.
    """

    source_name = "CarMax"

    def __init__(
        self,
        browser: BrowserClient,
        profile: str = "carfinda-carmax",
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        """
        Args:
            browser:     BrowserClient instance for the Playwright sidecar.
            profile:     Sidecar browser profile name for session isolation.
            http_client: Optional shared httpx.AsyncClient for the API path.
                         If not provided, one is created lazily via
                         ``create_http_client()``.
        """
        self._browser = browser
        self._profile = profile
        self._http_client = http_client
        self._owns_client = http_client is None

    # ------------------------------------------------------------------
    # HTTP client (lazy)
    # ------------------------------------------------------------------

    @property
    def http(self) -> httpx.AsyncClient:
        """Lazily initialise the HTTP client on first access."""
        if self._http_client is None:
            self._http_client = create_http_client()
            self._owns_client = True
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client if this scraper owns it."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    # ------------------------------------------------------------------
    # URL / param builders
    # ------------------------------------------------------------------

    def build_search_url(self, filters: dict[str, Any]) -> str:
        """Build a CarMax *human-readable* search URL from structured filters.

        This URL is used as the browser fallback target and as the
        ``Referer`` header for the API request.

        CarMax URL structure:
          /cars/<make>?year=<min>-<max>&price=<min>-<max>&mileage=0-<max>&location=<zip>&radius=<mi>
        """
        # Base path -- include make if specified
        makes = filters.get("makes", [])
        if len(makes) == 1:
            base_path = f"/cars/{makes[0].lower()}"
        else:
            base_path = "/cars"

        params: dict[str, str] = {}

        # Multiple makes -- use query param
        if len(makes) > 1:
            params["make"] = "|".join(m.lower() for m in makes)

        # Price range
        price_min = filters.get("budget_min", 0)
        price_max = filters.get("budget_max")
        if price_max:
            params["price"] = f"{int(price_min)}-{int(price_max)}"

        # Year range
        min_year = filters.get("min_year")
        if min_year:
            params["year"] = f"{min_year}-2026"

        # Mileage
        max_mileage = filters.get("max_mileage")
        if max_mileage:
            params["mileage"] = f"0-{max_mileage}"

        # Location
        location = filters.get("location", "")
        if location:
            zipcode = _extract_zip(location)
            if zipcode:
                params["location"] = zipcode

        # Radius
        radius = filters.get("radius_miles")
        if radius:
            params["radius"] = str(radius)

        # Body type
        body_types = filters.get("body_types", [])
        if body_types:
            params["bodytype"] = "|".join(bt.lower() for bt in body_types)

        query = urlencode(params)
        url = f"https://www.carmax.com{base_path}"
        if query:
            url += f"?{query}"
        return url

    def _build_api_params(
        self, filters: dict[str, Any], page: int = 0
    ) -> dict[str, str]:
        """Translate search *filters* into query-string params for the JSON API."""
        params: dict[str, str] = {}

        # The API requires a `uri` param that mirrors the human URL path
        makes = filters.get("makes", [])
        if len(makes) == 1:
            params["uri"] = f"/cars/{makes[0].lower()}"
        else:
            params["uri"] = "/cars"
        if len(makes) > 1:
            params["makes"] = "|".join(m.lower() for m in makes)

        price_min = filters.get("budget_min", 0)
        price_max = filters.get("budget_max")
        if price_max:
            params["price"] = f"{int(price_min)}-{int(price_max)}"

        min_year = filters.get("min_year")
        if min_year:
            params["year"] = f"{min_year}-2026"

        max_mileage = filters.get("max_mileage")
        if max_mileage:
            params["mileage"] = f"0-{max_mileage}"

        location = filters.get("location", "")
        if location:
            zipcode = _extract_zip(location)
            if zipcode:
                params["location"] = zipcode

        radius = filters.get("radius_miles")
        if radius:
            params["radius"] = str(radius)

        body_types = filters.get("body_types", [])
        if body_types:
            params["bodytype"] = "|".join(bt.lower() for bt in body_types)

        # Pagination
        if page > 0:
            params["skip"] = str(page * RESULTS_PER_PAGE)
        params["take"] = str(RESULTS_PER_PAGE)

        return params

    # ------------------------------------------------------------------
    # Main search entry point
    # ------------------------------------------------------------------

    async def search(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Search CarMax for listings matching *filters*.

        Attempts the JSON API first; falls back to sidecar browser rendering
        + BeautifulSoup parsing if the API is unavailable or returns no results.
        """
        all_listings: list[dict[str, Any]] = []

        # --- Try the JSON API first (fast path) ---
        try:
            api_results = await self._search_via_api(filters)
            if api_results:
                logger.info("CarMax: API returned %d raw listings", len(api_results))
                for raw in api_results:
                    all_listings.append(self.normalize_listing(raw))
                return all_listings
        except Exception as exc:
            logger.warning(
                "CarMax API attempt raised %s -- falling back to browser", exc
            )

        # --- Fallback: sidecar browser + BS4 ---
        try:
            browser_results = await self._search_via_browser(filters)
            if browser_results:
                logger.info(
                    "CarMax: browser scraping returned %d raw listings",
                    len(browser_results),
                )
                for raw in browser_results:
                    if not raw.get("source_url") and raw.get("vin"):
                        raw["source_url"] = f"https://www.carmax.com/car/{raw['vin']}"
                    all_listings.append(self.normalize_listing(raw))
        except Exception as exc:
            logger.error("CarMax browser scraping failed: %s", exc, exc_info=True)

        return all_listings

    # ------------------------------------------------------------------
    # JSON API approach (primary -- fast path)
    # ------------------------------------------------------------------

    async def _search_via_api(
        self, filters: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        """Attempt to fetch listings from CarMax's internal JSON search API.

        Returns a list of raw listing dicts on success, or ``None`` if the
        API call fails (so the caller can fall back to browser scraping).
        """
        all_listings: list[dict[str, Any]] = []
        referer = self.build_search_url(filters)

        for page_num in range(MAX_PAGES):
            api_params = self._build_api_params(filters, page=page_num)
            logger.info(
                "CarMax API: requesting page %d -- %s?%s",
                page_num + 1,
                _API_URL,
                urlencode(api_params),
            )

            try:
                resp = await self.http.get(
                    _API_URL,
                    params=api_params,
                    headers={
                        "Accept": "application/json",
                        "Referer": referer,
                    },
                    timeout=15.0,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "CarMax API returned HTTP %d -- falling back to browser",
                    exc.response.status_code,
                )
                return None
            except httpx.RequestError as exc:
                logger.warning(
                    "CarMax API request failed (%s) -- falling back to browser", exc
                )
                return None

            # Parse JSON payload
            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError):
                logger.warning("CarMax API returned non-JSON -- falling back to browser")
                return None

            # CarMax API nests results under various keys; try common ones
            items: list[dict] = []
            if isinstance(data, dict):
                items = (
                    data.get("items")
                    or data.get("results")
                    or data.get("vehicles")
                    or []
                )
            elif isinstance(data, list):
                items = data

            if not items:
                logger.info(
                    "CarMax API: no items on page %d -- stopping pagination",
                    page_num + 1,
                )
                break

            for item in items:
                listing = self._parse_api_item(item)
                if listing:
                    all_listings.append(listing)

            logger.info(
                "CarMax API: page %d yielded %d items (total: %d)",
                page_num + 1,
                len(items),
                len(all_listings),
            )

            # If fewer results than a full page, no more pages
            if len(items) < RESULTS_PER_PAGE:
                break

            # Brief pause between pages
            if page_num < MAX_PAGES - 1:
                await asyncio.sleep(1.0 + random.uniform(0.3, 1.0))

        return all_listings if all_listings else None

    @staticmethod
    def _parse_api_item(item: dict[str, Any]) -> dict[str, Any] | None:
        """Convert a single CarMax API vehicle object into a raw listing dict.

        The API response schema is not publicly documented, so we try
        both camelCase and PascalCase key variants.
        """
        if not isinstance(item, dict):
            return None

        stock_no = item.get("stockNumber") or item.get("StockNumber") or ""
        vin = item.get("vin") or item.get("Vin") or ""

        year = item.get("year") or item.get("Year")
        make = item.get("make") or item.get("Make") or ""
        model = item.get("model") or item.get("Model") or ""
        trim = item.get("trim") or item.get("Trim") or ""

        price = item.get("price") or item.get("Price") or item.get("basePrice")
        mileage = item.get("mileage") or item.get("Mileage") or item.get("miles")

        location_str = item.get("storeName") or item.get("storeCity") or ""

        # Build a source URL from stock number or VIN
        if stock_no:
            source_url = f"https://www.carmax.com/car/{stock_no}"
        elif vin:
            source_url = f"https://www.carmax.com/car/{vin}"
        else:
            source_url = ""

        # Collect image URLs
        image_urls: list[str] = []
        image_url = item.get("imageUrl") or item.get("imagePath") or ""
        if image_url:
            image_url = _ensure_absolute_url(image_url)
            image_urls.append(image_url)
        if isinstance(item.get("images"), list):
            for img in item["images"]:
                url = img if isinstance(img, str) else (img.get("url") or img.get("uri") or "")
                if url:
                    image_urls.append(_ensure_absolute_url(url))

        return {
            "vin": vin or None,
            "year": year,
            "make": make,
            "model": model,
            "trim": trim or None,
            "price": price,
            "mileage": mileage,
            "location": location_str or None,
            "source_url": source_url or None,
            "image_urls": image_urls,
            "exterior_color": item.get("exteriorColor") or item.get("ExteriorColor") or None,
            "interior_color": item.get("interiorColor") or item.get("InteriorColor") or None,
            "fuel_type": item.get("fuelType") or item.get("mpgStyle") or None,
            "transmission": item.get("transmission") or item.get("Transmission") or None,
            "drivetrain": item.get("drivetrain") or item.get("driveTrain") or None,
            "deal_rating": None,
        }

    # ------------------------------------------------------------------
    # Browser fallback approach (sidecar + BS4)
    # ------------------------------------------------------------------

    async def _search_via_browser(
        self, filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Render CarMax search pages using the sidecar browser and parse with BS4.

        Uses ``BrowserClient`` to start a session, navigate to each page,
        retrieve the fully-rendered HTML, and parse listings with
        BeautifulSoup.
        """
        all_listings: list[dict[str, Any]] = []
        base_url = self.build_search_url(filters)

        try:
            await self._browser.start_session(self._profile)

            for page_num in range(1, MAX_PAGES + 1):
                url = base_url
                if page_num > 1:
                    sep = "&" if "?" in url else "?"
                    url = f"{url}{sep}page={page_num}"

                logger.info(
                    "CarMax browser: navigating to page %d -- %s", page_num, url
                )

                try:
                    await self._browser.navigate(self._profile, url)
                except Exception as exc:
                    logger.warning(
                        "CarMax browser: failed to navigate page %d (%s)",
                        page_num,
                        exc,
                    )
                    break

                # Allow JS to finish rendering search results
                await asyncio.sleep(2.0 + random.uniform(0.5, 1.5))

                # Retrieve the fully rendered HTML
                try:
                    html = await self._browser.content(self._profile)
                except Exception as exc:
                    logger.warning(
                        "CarMax browser: failed to get content on page %d (%s)",
                        page_num,
                        exc,
                    )
                    break

                if not html:
                    logger.warning(
                        "CarMax browser: empty HTML on page %d", page_num
                    )
                    break

                # Parse with BS4
                page_listings = self._parse_html(html)

                if not page_listings:
                    logger.info(
                        "CarMax browser: BS4 found 0 listings on page %d -- stopping",
                        page_num,
                    )
                    break

                all_listings.extend(page_listings)

                logger.info(
                    "CarMax browser: page %d yielded %d listings (total: %d)",
                    page_num,
                    len(page_listings),
                    len(all_listings),
                )

                # Brief pause between pages
                if page_num < MAX_PAGES:
                    await asyncio.sleep(1.0 + random.uniform(0.5, 1.5))

        finally:
            # Always clean up the browser session
            try:
                await self._browser.stop_session(self._profile)
            except Exception as exc:
                logger.debug("CarMax browser: session cleanup error: %s", exc)

        return all_listings

    # ------------------------------------------------------------------
    # BS4 HTML parsing
    # ------------------------------------------------------------------

    def _parse_html(self, html: str) -> list[dict[str, Any]]:
        """Parse CarMax search-results HTML into raw listing dicts.

        Tries three strategies in order:
          1. Embedded JS variable containing a JSON vehicle array
             (e.g. ``const cars = [...]``)
          2. JSON-LD ``<script type="application/ld+json">`` blocks
          3. DOM listing cards (class patterns like ``result-tile``,
             ``car-tile``, ``vehicle-card``, etc.)
        """
        soup = BeautifulSoup(html, "html.parser")

        # --- Strategy 1: Embedded JSON data in <script> tags ---
        listings = self._extract_embedded_json(soup)
        if listings:
            return listings

        # --- Strategy 2: JSON-LD ---
        listings = self._extract_json_ld(soup)
        if listings:
            return listings

        # --- Strategy 3: DOM cards ---
        listings = self._extract_dom_cards(soup)
        return listings

    # ---- HTML sub-strategies ------------------------------------------------

    def _extract_embedded_json(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Look for inline ``<script>`` blocks containing a JSON vehicle array.

        Common patterns:
          - ``const cars = [...]``
          - ``window.__NEXT_DATA__``
          - ``window.__INITIAL_STATE__``
          - Any script whose text contains ``"stockNumber"`` or ``"vehicles"``
        """
        listings: list[dict[str, Any]] = []

        for script_tag in soup.find_all("script"):
            text = script_tag.string or ""
            if not text:
                continue

            # Only inspect scripts that mention vehicle-like keys
            if (
                "stockNumber" not in text
                and "vehicles" not in text
                and "storeId" not in text
            ):
                continue

            # Try to extract a JSON array (e.g. `const cars = [...]`)
            array_start = re.search(
                r"(?:const|var|let)\s+\w+\s*=\s*\[", text
            )
            if array_start:
                start_idx = array_start.end() - 1  # point at '['
                # Find matching closing bracket
                depth, end_idx = 0, start_idx
                for i in range(start_idx, len(text)):
                    if text[i] == "[":
                        depth += 1
                    elif text[i] == "]":
                        depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break
                try:
                    arr = json.loads(text[start_idx:end_idx])
                    if (
                        isinstance(arr, list)
                        and arr
                        and isinstance(arr[0], dict)
                        and ("stockNumber" in arr[0] or "vin" in arr[0])
                    ):
                        for v in arr:
                            parsed = self._parse_api_item(v)
                            if parsed:
                                listings.append(parsed)
                        if listings:
                            return listings
                except (json.JSONDecodeError, ValueError):
                    pass

            # Try to extract a JSON object from the script text
            for pattern in [
                r"__NEXT_DATA__\s*=\s*({.*?})\s*;",
                r"__INITIAL_STATE__\s*=\s*({.*?})\s*;",
                r"window\.__[A-Z_]+__\s*=\s*({.*?})\s*;",
            ]:
                match = re.search(pattern, text, re.DOTALL)
                if not match:
                    continue
                try:
                    blob = json.loads(match.group(1))
                except (json.JSONDecodeError, ValueError):
                    continue

                vehicles = _deep_find_vehicles(blob)
                for v in vehicles:
                    parsed = self._parse_api_item(v)
                    if parsed:
                        listings.append(parsed)
                if listings:
                    return listings

        return listings

    @staticmethod
    def _extract_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Pull vehicle listings from JSON-LD ``<script>`` tags."""
        listings: list[dict[str, Any]] = []

        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script_tag.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            items: list[dict] = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if data.get("@type") in ("Car", "Vehicle", "Product"):
                    items = [data]
                elif isinstance(data.get("itemListElement"), list):
                    items = [
                        el.get("item", el)
                        for el in data["itemListElement"]
                        if isinstance(el, dict)
                    ]

            for item in items:
                listing = _json_ld_to_listing(item)
                if listing:
                    listings.append(listing)

        return listings

    @staticmethod
    def _extract_dom_cards(soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Parse listing cards from the DOM using common CarMax class names."""
        listings: list[dict[str, Any]] = []

        # CarMax has used various class patterns; try several
        card_selectors = [
            {"class_": re.compile(r"result-tile|car-tile|vehicle-card|tombstone", re.I)},
            {"attrs": {"data-qa": re.compile(r"result|vehicle|car", re.I)}},
            {"attrs": {"data-testid": re.compile(r"result|vehicle|car", re.I)}},
        ]

        cards: list = []
        for selector in card_selectors:
            for tag in ("div", "article", "a"):
                cards = soup.find_all(tag, **selector)
                if cards:
                    break
            if cards:
                break

        for card in cards:
            listing = _dom_card_to_listing(card)
            if listing:
                listings.append(listing)

        return listings

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def normalize_listing(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw listing dict into the standard schema.

        Ensures all expected fields exist, generates a unique ID,
        and tags the listing with source_name="CarMax".
        """
        # Clean up price: might be string like "$24,999" or number
        price = raw.get("price")
        if isinstance(price, str):
            price = price.replace("$", "").replace(",", "").strip()
            try:
                price = float(price)
            except ValueError:
                price = None
        elif isinstance(price, (int, float)):
            price = float(price)
        else:
            price = None

        # Clean up mileage: might be string like "45,123 mi" or number
        mileage = raw.get("mileage")
        if isinstance(mileage, str):
            mileage = (
                mileage.lower()
                .replace("mi", "")
                .replace(",", "")
                .replace("miles", "")
                .strip()
            )
            try:
                mileage = int(float(mileage))
            except ValueError:
                mileage = None
        elif isinstance(mileage, (int, float)):
            mileage = int(mileage)
        else:
            mileage = None

        # Clean up year
        year = raw.get("year")
        if isinstance(year, str):
            try:
                year = int(year)
            except ValueError:
                year = None
        elif isinstance(year, (int, float)):
            year = int(year)
        else:
            year = None

        return {
            "id": str(uuid.uuid4()),
            "vin": raw.get("vin") or None,
            "year": year,
            "make": raw.get("make") or None,
            "model": raw.get("model") or None,
            "trim": raw.get("trim") or None,
            "price": price,
            "mileage": mileage,
            "location": raw.get("location") or None,
            "source_url": raw.get("source_url") or None,
            "source_name": self.source_name,
            "sources": [
                {
                    "name": self.source_name,
                    "url": raw.get("source_url") or None,
                    "price": price,
                }
            ],
            "image_urls": raw.get("image_urls") or [],
            "exterior_color": raw.get("exterior_color") or None,
            "interior_color": raw.get("interior_color") or None,
            "fuel_type": raw.get("fuel_type") or None,
            "transmission": raw.get("transmission") or None,
            "drivetrain": raw.get("drivetrain") or None,
            "deal_rating": raw.get("deal_rating") or None,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _ensure_absolute_url(url: str) -> str:
    """Ensure a URL is absolute, prepending the CarMax origin if needed."""
    if url.startswith("http"):
        return url
    if url.startswith("//"):
        return f"https:{url}"
    return f"https://www.carmax.com{url}"


def _json_ld_to_listing(item: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a JSON-LD Car / Vehicle / Product into a raw listing dict."""
    if not isinstance(item, dict):
        return None

    name = item.get("name", "")
    year, make, model, trim = None, None, None, None

    # Try to split "2022 Toyota Camry SE" into parts
    if name:
        parts = name.split()
        if parts and parts[0].isdigit() and len(parts[0]) == 4:
            year = int(parts[0])
            parts = parts[1:]
        if len(parts) >= 1:
            make = parts[0]
        if len(parts) >= 2:
            model = parts[1]
        if len(parts) >= 3:
            trim = " ".join(parts[2:])

    # Price -- can live in offers.price or directly
    price = None
    offers = item.get("offers")
    if isinstance(offers, dict):
        price = offers.get("price")
    if price is None:
        price = item.get("price")

    # Mileage -- may be an object with a "value" key
    mileage = item.get("mileageFromOdometer")
    if isinstance(mileage, dict):
        mileage = mileage.get("value")

    # Brand -- may be an object with a "name" key
    brand = item.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    # Image -- may be a string or a list
    raw_image = item.get("image")
    if isinstance(raw_image, str):
        image_urls = [raw_image]
    elif isinstance(raw_image, list):
        image_urls = raw_image
    else:
        image_urls = []

    # Source URL
    source_url = item.get("url")
    if not source_url and isinstance(offers, dict):
        source_url = offers.get("url")

    return {
        "vin": item.get("vehicleIdentificationNumber") or item.get("vin") or None,
        "year": item.get("modelDate") or item.get("productionDate") or year,
        "make": brand or make,
        "model": item.get("model") or model,
        "trim": trim,
        "price": price,
        "mileage": mileage,
        "location": None,
        "source_url": source_url,
        "image_urls": image_urls,
        "exterior_color": item.get("color") or None,
        "interior_color": item.get("vehicleInteriorColor") or None,
        "fuel_type": item.get("fuelType") or None,
        "transmission": item.get("vehicleTransmission") or None,
        "drivetrain": item.get("driveWheelConfiguration") or None,
        "deal_rating": None,
    }


def _dom_card_to_listing(card: Any) -> dict[str, Any] | None:
    """Best-effort extraction of listing data from a single DOM card element."""
    text = card.get_text(separator=" ", strip=True)
    if not text or len(text) < 10:
        return None

    # Try to find a title element
    title_el = card.find(class_=re.compile(r"title|heading|name", re.I)) or card.find(
        ["h2", "h3", "h4"]
    )
    title = title_el.get_text(strip=True) if title_el else ""

    year, make, model, trim = None, None, None, None
    if title:
        parts = title.split()
        if parts and parts[0].isdigit() and len(parts[0]) == 4:
            year = int(parts[0])
            parts = parts[1:]
        if len(parts) >= 1:
            make = parts[0]
        if len(parts) >= 2:
            model = parts[1]
        if len(parts) >= 3:
            trim = " ".join(parts[2:])

    # Price
    price = None
    price_el = card.find(class_=re.compile(r"price", re.I))
    if price_el:
        price_text = price_el.get_text(strip=True)
        price_match = re.search(r"\$?([\d,]+)", price_text)
        if price_match:
            price = price_match.group(1).replace(",", "")

    # Mileage
    mileage = None
    mileage_el = card.find(class_=re.compile(r"mileage|miles|odometer", re.I))
    if mileage_el:
        mi_text = mileage_el.get_text(strip=True)
        mi_match = re.search(r"([\d,]+)", mi_text)
        if mi_match:
            mileage = mi_match.group(1).replace(",", "")
    if mileage is None:
        mi_match = re.search(r"([\d,]+)\s*(?:mi|miles)", text, re.I)
        if mi_match:
            mileage = mi_match.group(1).replace(",", "")

    # Source URL
    source_url = None
    link = card.find("a", href=True)
    if link:
        source_url = _ensure_absolute_url(link["href"])

    # Image
    image_urls: list[str] = []
    img = card.find("img", src=True)
    if img:
        image_urls.append(_ensure_absolute_url(img["src"]))

    # Require at least some identifying data
    if not (year or make or model or price):
        return None

    return {
        "vin": card.get("data-vin") or None,
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "price": price,
        "mileage": mileage,
        "location": None,
        "source_url": source_url,
        "image_urls": image_urls,
        "exterior_color": None,
        "interior_color": None,
        "fuel_type": None,
        "transmission": None,
        "drivetrain": None,
        "deal_rating": None,
    }


def _deep_find_vehicles(obj: Any, _depth: int = 0) -> list[dict]:
    """Recursively search a nested dict/list for arrays of vehicle-like objects.

    Returns the first list of dicts that contain a ``stockNumber`` or ``vin`` key.
    Caps recursion at depth 8 to avoid runaway traversal.
    """
    if _depth > 8:
        return []

    if isinstance(obj, list):
        # Check if this list itself contains vehicle dicts
        if (
            obj
            and isinstance(obj[0], dict)
            and (
                "stockNumber" in obj[0]
                or "StockNumber" in obj[0]
                or "vin" in obj[0]
                or "Vin" in obj[0]
            )
        ):
            return obj
        for item in obj:
            result = _deep_find_vehicles(item, _depth + 1)
            if result:
                return result

    elif isinstance(obj, dict):
        # Check common container keys first for efficiency
        for key in ("items", "results", "vehicles", "data", "props", "pageProps"):
            if key in obj:
                result = _deep_find_vehicles(obj[key], _depth + 1)
                if result:
                    return result
        # Then walk all values
        for value in obj.values():
            result = _deep_find_vehicles(value, _depth + 1)
            if result:
                return result

    return []
