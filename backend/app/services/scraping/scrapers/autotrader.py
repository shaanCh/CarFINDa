"""
Autotrader Scraper -- Sidecar browser + BeautifulSoup implementation.

Uses the Playwright sidecar to render pages (executing all JS), then
retrieves the fully rendered HTML via ``browser.content()`` and parses it
with BeautifulSoup.  No LLM / Gemini involved.

Flow:
  1. Start a sidecar browser session.
  2. Build search URL from filters.
  3. Navigate to the URL (Playwright renders the Next.js app).
  4. Retrieve the rendered HTML via ``browser.content()``.
  5. Parse listing cards from the DOM with BeautifulSoup.
  6. Paginate (up to MAX_PAGES) by updating ``firstRecord`` param.
  7. Normalize each raw listing into the standard schema.

Autotrader URL pattern:
  https://www.autotrader.com/cars-for-sale/all-cars/<make>/<city-state>
  Query params: searchRadius, makeCodeList, minPrice, maxPrice, maxMileage,
                startYear, endYear, listingTypes, firstRecord, numRecords

Example:
  https://www.autotrader.com/cars-for-sale/all-cars/toyota/boulder-co?
    searchRadius=50&maxPrice=25000&maxMileage=80000&startYear=2018&
    listingTypes=USED&numRecords=25&firstRecord=0
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import uuid
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag

from app.services.scraping.browser_client import BrowserClient

logger = logging.getLogger(__name__)

MAX_PAGES = 3
RESULTS_PER_PAGE = 25

# ---------------------------------------------------------------------------
# Autotrader make codes (lowercase key -> Autotrader makeCode)
# ---------------------------------------------------------------------------
MAKE_CODES: dict[str, str] = {
    "acura": "ACURA",
    "audi": "AUDI",
    "bmw": "BMW",
    "buick": "BUICK",
    "cadillac": "CAD",
    "chevrolet": "CHEV",
    "chrysler": "CHRY",
    "dodge": "DODGE",
    "ford": "FORD",
    "gmc": "GMC",
    "honda": "HONDA",
    "hyundai": "HYUND",
    "infiniti": "INFIN",
    "jaguar": "JAG",
    "jeep": "JEEP",
    "kia": "KIA",
    "land rover": "ROVER",
    "lexus": "LEXUS",
    "lincoln": "LINC",
    "mazda": "MAZDA",
    "mercedes-benz": "MB",
    "mini": "MINI",
    "mitsubishi": "MIT",
    "nissan": "NISSAN",
    "porsche": "POR",
    "ram": "RAM",
    "subaru": "SUB",
    "tesla": "TESLA",
    "toyota": "TOYOTA",
    "volkswagen": "VOLKS",
    "volvo": "VOLVO",
}

# ---------------------------------------------------------------------------
# Autotrader body style codes
# ---------------------------------------------------------------------------
BODY_TYPE_CODES: dict[str, str] = {
    "sedan": "SEDAN",
    "suv": "SUVCROSS",
    "crossover": "SUVCROSS",
    "truck": "TRUCKS",
    "pickup": "TRUCKS",
    "coupe": "COUPE",
    "convertible": "CONVERT",
    "hatchback": "HATCH",
    "wagon": "WAGON",
    "van": "VANMV",
    "minivan": "VANMV",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _location_to_slug(location: str) -> str:
    """Convert a location string like 'Boulder, CO' to 'boulder-co'.

    Handles formats:
      - "Boulder, CO" -> "boulder-co"
      - "Salt Lake City, UT" -> "salt-lake-city-ut"
      - "80302" -> "" (zip codes don't become slugs)
    """
    location = location.strip()

    # Skip if it's just a zip code
    if location.isdigit():
        return ""

    # Remove zip code if trailing
    location = re.sub(r"\s+\d{5}(-\d{4})?$", "", location)

    # Lowercase, replace commas and spaces with hyphens
    slug = location.lower()
    slug = slug.replace(",", "")
    slug = re.sub(r"\s+", "-", slug.strip())
    # Remove consecutive hyphens
    slug = re.sub(r"-+", "-", slug).strip("-")

    return slug


def _safe_int(value: Any) -> int | None:
    """Attempt to coerce *value* to an int, returning ``None`` on failure."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.]", "", value.replace(",", ""))
        try:
            return int(float(cleaned)) if cleaned else None
        except (ValueError, TypeError):
            return None
    return None


def _safe_float(value: Any) -> float | None:
    """Attempt to coerce *value* to a float, returning ``None`` on failure."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.]", "", value.replace(",", ""))
        try:
            return float(cleaned) if cleaned else None
        except (ValueError, TypeError):
            return None
    return None


def _parse_year_make_model(title: str) -> dict[str, str | None]:
    """Extract year, make, model, and optional trim from a title string.

    Typical Autotrader titles:
      "2022 Toyota Camry SE"
      "2020 Mercedes-Benz GLC 300"
    """
    result: dict[str, str | None] = {
        "year": None,
        "make": None,
        "model": None,
        "trim": None,
    }
    if not title:
        return result

    m = re.match(r"(\d{4})\s+(.+)", title.strip())
    if not m:
        return result

    result["year"] = m.group(1)
    remainder = m.group(2).strip()

    # Match a known make (longest match first to handle "land rover", etc.)
    remainder_lower = remainder.lower()
    matched_make: str | None = None
    for make_key in sorted(MAKE_CODES, key=len, reverse=True):
        if remainder_lower.startswith(make_key):
            matched_make = remainder[: len(make_key)]
            remainder = remainder[len(make_key) :].strip()
            break

    if matched_make:
        # Preserve original casing for hyphenated makes like "Mercedes-Benz"
        result["make"] = matched_make.title() if "-" not in matched_make else matched_make
    else:
        # Fallback: first token is the make
        parts = remainder.split(None, 1)
        if parts:
            result["make"] = parts[0]
            remainder = parts[1] if len(parts) > 1 else ""

    # First remaining token is model, rest is trim
    if remainder:
        parts = remainder.split(None, 1)
        result["model"] = parts[0]
        if len(parts) > 1:
            result["trim"] = parts[1]

    return result


def _collect_images(images: Any) -> list[str]:
    """Normalize an images value (str, list[str], list[dict], dict) to a URL list."""
    urls: list[str] = []
    if isinstance(images, str):
        urls.append(images)
    elif isinstance(images, list):
        for img in images:
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                url = img.get("url") or img.get("src") or img.get("uri") or ""
                if url:
                    urls.append(url)
    elif isinstance(images, dict):
        url = images.get("url") or images.get("src") or ""
        if url:
            urls.append(url)
    return urls


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------

class AutotraderScraper:
    """Scraper for autotrader.com using sidecar browser + BeautifulSoup.

    The sidecar (Playwright) handles page rendering so that all JS-generated
    content is present in the HTML.  BeautifulSoup then parses the fully
    rendered DOM to extract listing data.  No LLM is involved.
    """

    source_name = "Autotrader"

    def __init__(self, browser: BrowserClient, profile: str = "carfinda-autotrader"):
        """
        Args:
            browser: A ``BrowserClient`` instance connected to the sidecar.
            profile: Sidecar profile name for session isolation.
        """
        self.browser = browser
        self.profile = profile

    # ------------------------------------------------------------------
    # URL building
    # ------------------------------------------------------------------

    def build_search_url(self, filters: dict[str, Any]) -> str:
        """Build an Autotrader search URL from structured filters.

        Autotrader URL structure:
          /cars-for-sale/all-cars[/<make>][/<location-slug>]?<params>
        """
        # Build path segments
        makes = filters.get("makes", [])
        location = filters.get("location", "")
        location_slug = _location_to_slug(location) if location else ""

        path_parts = ["/cars-for-sale/all-cars"]

        if len(makes) == 1:
            path_parts.append(makes[0].lower())

        if location_slug:
            path_parts.append(location_slug)

        base_path = "/".join(path_parts)

        # Query parameters
        params: dict[str, str] = {
            "listingTypes": "USED",
            "numRecords": str(RESULTS_PER_PAGE),
            "firstRecord": "0",
        }

        # Search radius
        radius = filters.get("radius_miles", 50)
        params["searchRadius"] = str(radius)

        # Multiple makes
        if len(makes) > 1:
            for make_name in makes:
                code = MAKE_CODES.get(make_name.lower(), make_name.upper())
                params["makeCodeList"] = code

        # Price range
        price_min = filters.get("budget_min")
        price_max = filters.get("budget_max")
        if price_min and price_min > 0:
            params["minPrice"] = str(int(price_min))
        if price_max:
            params["maxPrice"] = str(int(price_max))

        # Year range
        min_year = filters.get("min_year")
        if min_year:
            params["startYear"] = str(min_year)

        # Mileage
        max_mileage = filters.get("max_mileage")
        if max_mileage:
            params["maxMileage"] = str(max_mileage)

        # Body types
        body_types = filters.get("body_types", [])
        if body_types:
            codes = []
            for bt in body_types:
                code = BODY_TYPE_CODES.get(bt.lower())
                if code and code not in codes:
                    codes.append(code)
            if codes:
                params["vehicleStyleCodes"] = ",".join(codes)

        # Handle multiple makes via repeated makeCodeList params
        if len(makes) > 1:
            query_parts = []
            for k, v in params.items():
                if k == "makeCodeList":
                    continue  # handled below
                query_parts.append(f"{k}={v}")
            for make_name in makes:
                code = MAKE_CODES.get(make_name.lower(), make_name.upper())
                query_parts.append(f"makeCodeList={code}")
            query = "&".join(query_parts)
        else:
            query = urlencode(params)

        return f"https://www.autotrader.com{base_path}?{query}"

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Search Autotrader for listings matching *filters*.

        Uses the sidecar browser to render each page, then extracts
        listings from the fully rendered HTML with BeautifulSoup.
        Paginates up to ``MAX_PAGES`` pages using the ``firstRecord``
        offset.
        """
        all_listings: list[dict[str, Any]] = []
        base_url = self.build_search_url(filters)

        try:
            await self.browser.start_session(self.profile)

            for page_num in range(1, MAX_PAGES + 1):
                # Calculate firstRecord offset for pagination
                first_record = (page_num - 1) * RESULTS_PER_PAGE

                url = base_url
                if page_num > 1:
                    if "firstRecord=" in url:
                        url = re.sub(
                            r"firstRecord=\d+",
                            f"firstRecord={first_record}",
                            url,
                        )
                    else:
                        url = f"{url}&firstRecord={first_record}"

                logger.info("Autotrader: navigating to page %d -- %s", page_num, url)

                # --- Sidecar: navigate (renders JS) ---
                try:
                    await self.browser.navigate(self.profile, url)
                except Exception as exc:
                    logger.error(
                        "Autotrader: failed to navigate page %d: %s",
                        page_num,
                        exc,
                    )
                    break

                # Small delay to let any lazy-loaded content settle
                await asyncio.sleep(1.0 + random.uniform(0.3, 0.8))

                # --- Check for CAPTCHA and attempt to solve ---
                try:
                    solved = await self.browser.solve_captcha_if_present(self.profile)
                    if solved:
                        logger.info("Autotrader: CAPTCHA solved on page %d, continuing", page_num)
                        await asyncio.sleep(1.0)
                except Exception as exc:
                    logger.debug("Autotrader: captcha check failed: %s", exc)

                # --- Sidecar: get rendered HTML ---
                try:
                    html = await self.browser.content(self.profile)
                except Exception as exc:
                    logger.error(
                        "Autotrader: failed to get page content on page %d: %s",
                        page_num,
                        exc,
                    )
                    break

                if not html or len(html) < 500:
                    logger.warning(
                        "Autotrader: empty or too-short response on page %d "
                        "(%d bytes)",
                        page_num,
                        len(html) if html else 0,
                    )
                    break

                # --- Parse listings from rendered HTML ---
                raw_listings = self._parse_listings(html)

                if not raw_listings:
                    logger.info(
                        "Autotrader: no listings found on page %d -- stopping",
                        page_num,
                    )
                    break

                for raw in raw_listings:
                    normalized = self.normalize_listing(raw)
                    all_listings.append(normalized)

                logger.info(
                    "Autotrader: page %d yielded %d listings (total: %d)",
                    page_num,
                    len(raw_listings),
                    len(all_listings),
                )

                # Polite delay between page fetches
                if page_num < MAX_PAGES and raw_listings:
                    await asyncio.sleep(1.5 + random.uniform(0.5, 1.5))

        except Exception as exc:
            logger.error("Autotrader scraping failed: %s", exc, exc_info=True)
        finally:
            try:
                await self.browser.stop_session(self.profile)
            except Exception:
                pass

        return all_listings

    # ------------------------------------------------------------------
    # BS4 parsing
    # ------------------------------------------------------------------

    def _parse_listings(self, html: str) -> list[dict[str, Any]]:
        """Parse fully rendered HTML and extract listing data.

        Tries multiple extraction strategies in priority order:
          1. ``__NEXT_DATA__`` JSON blob (richest data when present)
          2. JSON-LD structured data
          3. HTML listing card elements from the rendered DOM

        Returns a list of raw listing dicts.
        """
        soup = BeautifulSoup(html, "html.parser")

        # 1. __NEXT_DATA__ (Next.js SSR payload — richest source)
        listings = self._extract_from_next_data(soup)
        if listings:
            logger.debug(
                "Autotrader: extracted %d listings from __NEXT_DATA__",
                len(listings),
            )
            return listings

        # 2. JSON-LD structured data
        listings = self._extract_from_json_ld(soup)
        if listings:
            logger.debug(
                "Autotrader: extracted %d listings from JSON-LD",
                len(listings),
            )
            return listings

        # 3. HTML listing cards (rendered DOM)
        listings = self._extract_from_cards(soup)
        if listings:
            logger.debug(
                "Autotrader: extracted %d listings from HTML cards",
                len(listings),
            )
            return listings

        logger.warning("Autotrader: no listings found in rendered HTML")
        return []

    # -- Strategy 1: __NEXT_DATA__ ---

    def _extract_from_next_data(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract listings from the ``__NEXT_DATA__`` JSON blob."""
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return []

        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Failed to parse __NEXT_DATA__ JSON")
            return []

        page_props = data.get("props", {}).get("pageProps", {})

        # Try several known keys where listings live
        raw_items: list[dict] = []
        for key in ("listings", "initialListings", "searchResults", "results"):
            candidate = page_props.get(key)
            if isinstance(candidate, list) and candidate:
                raw_items = candidate
                break
            if isinstance(candidate, dict):
                for sub_key in ("listings", "items", "results"):
                    sub = candidate.get(sub_key)
                    if isinstance(sub, list) and sub:
                        raw_items = sub
                        break
                if raw_items:
                    break

        listings: list[dict[str, Any]] = []
        for item in raw_items:
            listing = self._normalize_next_data_item(item)
            if listing:
                listings.append(listing)
        return listings

    @staticmethod
    def _normalize_next_data_item(item: dict) -> dict[str, Any] | None:
        """Normalize a single item from ``__NEXT_DATA__`` into a raw listing."""
        if not isinstance(item, dict):
            return None

        title = item.get("title") or item.get("heading") or item.get("name") or ""
        parsed = _parse_year_make_model(title)

        year = _safe_int(item.get("year") or parsed.get("year"))
        make = item.get("make") or item.get("makeName") or parsed.get("make")
        model = item.get("model") or item.get("modelName") or parsed.get("model")
        trim = item.get("trim") or item.get("trimName") or parsed.get("trim")

        price = _safe_float(
            item.get("price")
            or item.get("pricingDetail", {}).get("primary")
            or item.get("derivedPrice")
            or item.get("listPrice")
        )

        mileage = _safe_int(
            item.get("mileage")
            or item.get("mileageString")
            or item.get("specifications", {}).get("mileage", {}).get("value")
        )

        vin = item.get("vin") or item.get("vehicleIdentificationNumber")

        # Location
        owner = item.get("owner") or item.get("dealer") or {}
        location = item.get("location") or owner.get("location") or owner.get("city")
        if isinstance(location, dict):
            city = location.get("city", "")
            state = location.get("state", "")
            location = f"{city}, {state}" if city else state

        # Source URL
        listing_id = item.get("id") or item.get("listingId")
        source_url = item.get("url") or item.get("clickUrl")
        if source_url and not source_url.startswith("http"):
            source_url = f"https://www.autotrader.com{source_url}"
        elif not source_url and listing_id:
            source_url = (
                f"https://www.autotrader.com/cars-for-sale/vehicledetails.xhtml"
                f"?listingId={listing_id}"
            )

        image_urls = _collect_images(
            item.get("images") or item.get("imageUrls") or item.get("photos") or []
        )

        deal_rating = (
            item.get("dealRating")
            or item.get("pricingDetail", {}).get("dealType")
            or item.get("dealType")
        )

        return {
            "year": year,
            "make": make,
            "model": model,
            "trim": trim,
            "price": price,
            "mileage": mileage,
            "vin": vin,
            "location": location if isinstance(location, str) else None,
            "source_url": source_url,
            "image_urls": image_urls,
            "deal_rating": deal_rating,
            "exterior_color": item.get("exteriorColor") or item.get("exteriorColorSimple"),
            "interior_color": item.get("interiorColor") or item.get("interiorColorSimple"),
            "fuel_type": item.get("fuelType"),
            "transmission": item.get("transmission"),
            "drivetrain": item.get("driveType") or item.get("drivetrain"),
        }

    # -- Strategy 2: JSON-LD ---

    def _extract_from_json_ld(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract listings from ``<script type="application/ld+json">`` blocks."""
        scripts = soup.find_all("script", type="application/ld+json")
        listings: list[dict[str, Any]] = []

        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue

                item_type = item.get("@type", "")

                if item_type in ("Car", "Vehicle", "Product", "Offer"):
                    listing = self._normalize_json_ld_item(item)
                    if listing:
                        listings.append(listing)
                    continue

                list_elements = item.get("itemListElement", [])
                if isinstance(list_elements, list):
                    for elem in list_elements:
                        if isinstance(elem, dict):
                            inner = elem.get("item") or elem
                            listing = self._normalize_json_ld_item(inner)
                            if listing:
                                listings.append(listing)

        return listings

    @staticmethod
    def _normalize_json_ld_item(item: dict) -> dict[str, Any] | None:
        """Normalize a JSON-LD item into a raw listing dict."""
        if not isinstance(item, dict):
            return None

        name = item.get("name", "")
        parsed = _parse_year_make_model(name)

        year = _safe_int(
            item.get("vehicleModelDate") or item.get("modelDate") or parsed.get("year")
        )

        brand = item.get("brand")
        make = brand.get("name") if isinstance(brand, dict) else brand
        make = make or item.get("manufacturer") or parsed.get("make")

        model = item.get("model") or parsed.get("model")
        trim = parsed.get("trim")

        price: float | None = None
        offers = item.get("offers")
        if isinstance(offers, dict):
            price = _safe_float(offers.get("price") or offers.get("lowPrice"))
        elif isinstance(offers, list) and offers:
            price = _safe_float(offers[0].get("price"))
        if price is None:
            price = _safe_float(item.get("price"))

        mileage: int | None = None
        mileage_data = item.get("mileageFromOdometer")
        if isinstance(mileage_data, dict):
            mileage = _safe_int(mileage_data.get("value"))
        elif mileage_data is not None:
            mileage = _safe_int(mileage_data)

        vin = item.get("vehicleIdentificationNumber") or item.get("vin")

        source_url = item.get("url")
        if source_url and not source_url.startswith("http"):
            source_url = f"https://www.autotrader.com{source_url}"

        image_urls = _collect_images(item.get("image") or [])

        return {
            "year": year,
            "make": make,
            "model": model,
            "trim": trim,
            "price": price,
            "mileage": mileage,
            "vin": vin,
            "location": None,
            "source_url": source_url,
            "image_urls": image_urls,
            "deal_rating": None,
            "exterior_color": item.get("color") or item.get("vehicleInteriorColor"),
            "interior_color": item.get("vehicleInteriorColor"),
            "fuel_type": item.get("fuelType"),
            "transmission": item.get("vehicleTransmission"),
            "drivetrain": item.get("driveWheelConfiguration"),
        }

    # -- Strategy 3: HTML listing cards ---

    def _extract_from_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract listings from rendered HTML listing-card elements.

        Autotrader uses various ``data-cmp`` attributes and CSS classes on
        listing cards.  Since the sidecar renders all JS, these elements
        will be present in the DOM even if they are client-side rendered.
        """
        listings: list[dict[str, Any]] = []

        # Try selectors from most specific to broadest
        cards: list[Tag] = soup.find_all(
            attrs={"data-cmp": re.compile(r"inventoryListing|listing", re.I)}
        )
        if not cards:
            cards = soup.find_all(
                attrs={"data-testid": re.compile(r"listing", re.I)}
            )
        if not cards:
            cards = soup.find_all(
                class_=re.compile(
                    r"inventory-listing|listing-card|result-item", re.I
                )
            )
        if not cards:
            cards = soup.select("[data-listing-id]")

        for card in cards:
            listing = self._parse_card(card)
            if listing and (listing.get("year") or listing.get("price")):
                listings.append(listing)

        return listings

    @staticmethod
    def _parse_card(card: Tag) -> dict[str, Any]:
        """Parse a single listing card ``Tag`` into a raw listing dict."""
        # -- Title (year / make / model / trim) --
        title_el = (
            card.find(class_=re.compile(r"title|heading", re.I))
            or card.find("h2")
            or card.find("h3")
        )
        title = title_el.get_text(strip=True) if title_el else ""
        parsed = _parse_year_make_model(title)

        # -- Price --
        price_el = card.find(class_=re.compile(r"price|first-price", re.I))
        price = _safe_float(price_el.get_text(strip=True) if price_el else None)

        # -- Mileage --
        mileage_el = card.find(
            class_=re.compile(r"mileage", re.I)
        ) or card.find(string=re.compile(r"[\d,]+\s*mi", re.I))
        mileage_text: str | None = None
        if mileage_el:
            if isinstance(mileage_el, Tag):
                mileage_text = mileage_el.get_text(strip=True)
            else:
                mileage_text = str(mileage_el).strip()
        mileage = _safe_int(mileage_text)

        # -- VIN --
        vin = card.get("data-vin")
        if not vin:
            vin_el = card.find(attrs={"data-vin": True})
            vin = vin_el["data-vin"] if vin_el else None

        # -- Source URL (link to detail page) --
        link_el = card.find("a", href=re.compile(r"/cars-for-sale/|vehicledetails"))
        source_url: str | None = None
        if link_el and link_el.get("href"):
            href = link_el["href"]
            source_url = (
                href
                if href.startswith("http")
                else f"https://www.autotrader.com{href}"
            )

        # -- Images (eager + lazy-loaded) --
        image_urls: list[str] = []
        for img_el in card.find_all("img", limit=5):
            src = img_el.get("src") or img_el.get("data-src") or ""
            if src and not src.startswith("data:"):
                image_urls.append(src)

        # -- Location / dealer --
        location_el = card.find(
            class_=re.compile(r"dealer-name|location|city", re.I)
        )
        location = location_el.get_text(strip=True) if location_el else None

        # -- Deal rating badge --
        deal_el = card.find(class_=re.compile(r"deal|badge|price-badge", re.I))
        deal_rating = deal_el.get_text(strip=True) if deal_el else None

        # -- Listing ID fallback for source URL --
        listing_id = card.get("data-listing-id") or card.get("id")
        if not source_url and listing_id:
            source_url = (
                f"https://www.autotrader.com/cars-for-sale/vehicledetails.xhtml"
                f"?listingId={listing_id}"
            )

        return {
            "year": _safe_int(parsed.get("year")),
            "make": parsed.get("make"),
            "model": parsed.get("model"),
            "trim": parsed.get("trim"),
            "price": price,
            "mileage": mileage,
            "vin": vin,
            "location": location,
            "source_url": source_url,
            "image_urls": image_urls,
            "deal_rating": deal_rating,
        }

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def normalize_listing(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw listing dict into the standard schema.

        Cleans price/mileage/year strings, generates a UUID, and tags the
        listing with ``source_name``.
        """
        # Clean price: might be string like "$24,999" or number
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

        # Clean mileage: might be string like "45,123 mi" or number
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

        # Clean year
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
