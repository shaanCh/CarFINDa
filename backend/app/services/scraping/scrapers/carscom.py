"""
Cars.com Scraper -- Sidecar browser + BeautifulSoup implementation.

Uses the Playwright sidecar to render pages (executing all JS), then
retrieves the fully rendered HTML via ``browser.content()`` and parses it
with BeautifulSoup.  No LLM involved.

Flow:
  1. Start a sidecar browser session.
  2. Build search URL from filters.
  3. Navigate to the URL (Playwright renders the page).
  4. Retrieve the rendered HTML via ``browser.content()``.
  5. Parse ``<spark-card>`` listing elements with BeautifulSoup.
  6. Paginate by clicking "Load More" or updating page param.
  7. Normalize each raw listing into the standard schema.

Cars.com URL pattern:
  https://www.cars.com/shopping/results/
  Query params: stock_type, makes[], models[], maximum_distance, zip,
                list_price_max, list_price_min, year_min, year_max,
                mileage_max, page_size, page
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag

from app.services.scraping.browser_client import BrowserClient

logger = logging.getLogger(__name__)

MAX_PAGES = 2
RESULTS_PER_PAGE = 20

# Normalize common model names to their Cars.com slug format
_MODEL_SLUG_MAP: dict[str, str] = {
    "crv": "cr-v", "cr v": "cr-v",
    "rav4": "rav4",
    "cx5": "cx-5", "cx 5": "cx-5",
    "cx9": "cx-9", "cx 9": "cx-9",
    "cx30": "cx-30", "cx 30": "cx-30",
    "cx50": "cx-50", "cx 50": "cx-50",
    "hrv": "hr-v", "hr v": "hr-v",
    "brz": "brz",
    "f150": "f-150", "f 150": "f-150",
    "ram 1500": "1500",
    "model 3": "model-3", "model y": "model-y",
    "model s": "model-s", "model x": "model-x",
    "3 series": "3-series", "5 series": "5-series",
    "x3": "x3", "x5": "x5",
    "grand cherokee": "grand-cherokee",
    "santa fe": "santa-fe",
    "4runner": "4runner",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.]", "", value.replace(",", ""))
        try:
            return int(float(cleaned)) if cleaned else None
        except (ValueError, TypeError):
            return None
    return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.]", "", value.replace(",", ""))
        try:
            return float(cleaned) if cleaned else None
        except (ValueError, TypeError):
            return None
    return None


def _tag_text(tag: Tag | None) -> str:
    return tag.get_text(strip=True) if tag else ""


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------

class CarsComScraper:
    """Scraper for cars.com using sidecar browser + BeautifulSoup.

    Cars.com uses ``<spark-card>`` web components for listing cards.
    The sidecar renders the full JS page, then we parse the DOM.
    """

    source_name = "Cars.com"

    def __init__(self, browser: BrowserClient, profile: str = "carfinda-carscom"):
        self.browser = browser
        self.profile = profile

    # ------------------------------------------------------------------
    # URL building
    # ------------------------------------------------------------------

    def build_search_url(self, filters: dict[str, Any], *, page: int = 1) -> str:
        """Build a Cars.com search results URL from structured filters."""
        params: dict[str, str] = {
            "stock_type": "used",
            "page_size": str(RESULTS_PER_PAGE),
        }

        if page > 1:
            params["page"] = str(page)

        # Makes
        makes = filters.get("makes", [])
        if makes:
            params["makes[]"] = makes[0].lower()

        # Models
        models = filters.get("models", [])
        if models:
            # Cars.com model format: "make-model" e.g. "chevrolet-corvette"
            raw_model = models[0].lower().strip()
            model_slug = _MODEL_SLUG_MAP.get(raw_model, raw_model.replace(" ", "-"))
            if makes:
                params["models[]"] = f"{makes[0].lower()}-{model_slug}"
            else:
                params["models[]"] = model_slug

        # Location
        location = filters.get("location", "")
        if location:
            # Extract zip code
            zip_match = re.search(r"\d{5}", location)
            if zip_match:
                params["zip"] = zip_match.group()
            else:
                # Use city-to-zip mapping
                params["zip"] = _location_to_zip(location)

        # Radius
        radius = filters.get("radius_miles", 250)
        params["maximum_distance"] = str(radius)

        # Price range
        price_min = filters.get("budget_min")
        price_max = filters.get("budget_max")
        if price_min and price_min > 0:
            params["list_price_min"] = str(int(price_min))
        if price_max:
            params["list_price_max"] = str(int(price_max))

        # Year
        min_year = filters.get("min_year")
        if min_year:
            params["year_min"] = str(min_year)

        # Mileage
        max_mileage = filters.get("max_mileage")
        if max_mileage:
            params["mileage_max"] = str(max_mileage)

        # Body type
        body_types = filters.get("body_types", [])
        if body_types:
            params["body_style_slugs[]"] = body_types[0].lower()

        return f"https://www.cars.com/shopping/results/?{urlencode(params)}"

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Search Cars.com for listings matching *filters*."""
        all_listings: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        try:
            await self.browser.start_session(self.profile)

            for page_num in range(1, MAX_PAGES + 1):
                url = self.build_search_url(filters, page=page_num)
                logger.info("Cars.com: navigating to page %d -- %s", page_num, url)

                try:
                    await self.browser.navigate(self.profile, url)
                except Exception as exc:
                    logger.error("Cars.com: navigation failed on page %d: %s", page_num, exc)
                    break

                await asyncio.sleep(2.5)

                try:
                    html = await self.browser.content(self.profile)
                except Exception as exc:
                    logger.error("Cars.com: content fetch failed on page %d: %s", page_num, exc)
                    break

                if not html or len(html) < 1000:
                    logger.warning("Cars.com: empty response on page %d", page_num)
                    break

                raw_listings = self._parse_listings(html)

                if not raw_listings:
                    logger.info("Cars.com: no listings on page %d -- stopping", page_num)
                    break

                new_count = 0
                for raw in raw_listings:
                    normalized = self.normalize_listing(raw)
                    source_url = normalized.get("source_url", "")
                    if source_url in seen_urls:
                        continue
                    if source_url:
                        seen_urls.add(source_url)
                    all_listings.append(normalized)
                    new_count += 1

                logger.info(
                    "Cars.com: page %d yielded %d new listings (total: %d)",
                    page_num, new_count, len(all_listings),
                )

                if new_count == 0:
                    break

                if page_num < MAX_PAGES:
                    await asyncio.sleep(1.5)

        except Exception as exc:
            logger.error("Cars.com scraping failed: %s", exc, exc_info=True)
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
        """Parse listing cards from rendered HTML."""
        soup = BeautifulSoup(html, "html.parser")
        listings: list[dict[str, Any]] = []

        # Cars.com uses <spark-card id="vehicle-card-..."> elements
        cards: list[Tag] = soup.find_all(
            "spark-card", id=re.compile(r"vehicle-card-")
        )

        if not cards:
            # Fallback: find by vehicle detail links
            links = soup.find_all("a", href=re.compile(r"/vehicledetail/"))
            for link in links:
                card = link.find_parent("spark-card") or link.find_parent("li")
                if card and card not in cards:
                    cards.append(card)

        for card in cards:
            parsed = self._parse_single_card(card)
            if parsed:
                listings.append(parsed)

        logger.info("Cars.com: parsed %d listings from %d cards", len(listings), len(cards))
        return listings

    def _parse_single_card(self, card: Tag) -> dict[str, Any] | None:
        """Extract listing data from a single spark-card element."""

        # -- Title (e.g. "Used 2024 Toyota Camry LE") --
        title_el = card.find("h2") or card.find("h3")
        title_text = _tag_text(title_el)
        if not title_text:
            return None

        # Parse "Used 2024 Toyota Camry LE" or "Certified 2023 Toyota RAV4"
        title_clean = re.sub(
            r"^(Used|Certified|New|CPO)\s+", "", title_text, flags=re.I
        ).strip()

        year, make, model, trim = None, None, None, None
        parts = title_clean.split()
        if parts and re.match(r"^\d{4}$", parts[0]):
            year = int(parts[0])
            if len(parts) > 1:
                make = parts[1]
            if len(parts) > 2:
                model = parts[2]
            if len(parts) > 3:
                trim = " ".join(parts[3:])

        if not year or not make:
            return None

        # -- Price --
        # The primary price is in a <p> > <span class="spark-body-larger">
        price: float | None = None
        price_span = card.find("span", class_="spark-body-larger")
        if price_span:
            price = _safe_float(_tag_text(price_span))
        if price is None:
            # Fallback: first <p> containing a dollar sign
            for p in card.find_all("p"):
                text = _tag_text(p)
                if "$" in text and len(text) < 20:
                    price = _safe_float(text)
                    if price:
                        break

        # -- Mileage --
        mileage: int | None = None
        mi_el = card.find(string=re.compile(r"[\d,]+\s*mi\.", re.I))
        if mi_el:
            mi_match = re.search(r"([\d,]+)\s*mi\.", str(mi_el), re.I)
            if mi_match:
                mileage = _safe_int(mi_match.group(1))

        # -- Deal rating (spark-badge) --
        deal_rating: str | None = None
        badges = card.find_all("spark-badge")
        for badge in badges:
            text = _tag_text(badge)
            if text and any(
                kw in text.lower()
                for kw in ("deal", "price", "hot", "fair", "overpriced")
            ):
                deal_rating = text
                break

        # -- Source URL --
        source_url: str | None = None
        link = card.find("a", href=re.compile(r"/vehicledetail/"))
        if link:
            href = link.get("href", "")
            if href.startswith("/"):
                source_url = f"https://www.cars.com{href}"
            elif href.startswith("http"):
                source_url = href

        # -- Dealer / Location --
        dealer: str | None = None
        location: str | None = None
        # Dealer is in a <p> > <span class="spark-body-small">
        dealer_span = card.find("span", class_="spark-body-small")
        if dealer_span:
            dealer = _tag_text(dealer_span)

        # Location is typically the last span with "mi)" pattern
        loc_el = card.find(string=re.compile(r"\d+\s*mi\)"))
        if loc_el:
            loc_match = re.search(r"(.+?)\s*\(\d+\s*mi\)", str(loc_el))
            if loc_match:
                location = loc_match.group(1).strip()

        # -- Images --
        image_urls: list[str] = []
        for img in card.find_all("img", src=True):
            src = img.get("src", "")
            if src and "placeholder" not in src.lower() and src.startswith("http"):
                image_urls.append(src)

        return {
            "year": year,
            "make": make,
            "model": model,
            "trim": trim,
            "price": price,
            "mileage": mileage,
            "source_url": source_url,
            "image_urls": image_urls,
            "deal_rating": deal_rating,
            "location": location,
            "dealer_name": dealer,
            "vin": None,
            "exterior_color": None,
            "interior_color": None,
            "fuel_type": None,
            "motor_type": None,
            "transmission": None,
            "drivetrain": None,
            "title": None,
            "monthly_payment": None,
            "mpg": None,
        }

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def normalize_listing(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw listing dict into the standard schema."""
        price = raw.get("price")
        if isinstance(price, str):
            price = _safe_float(price)
        elif isinstance(price, (int, float)):
            price = float(price)
        else:
            price = None

        mileage = raw.get("mileage")
        if isinstance(mileage, (int, float)):
            mileage = int(mileage)
        elif isinstance(mileage, str):
            mileage = _safe_int(mileage)
        else:
            mileage = None

        year = raw.get("year")
        if isinstance(year, (int, float)):
            year = int(year)
        elif isinstance(year, str):
            year = _safe_int(year)
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
            "motor_type": raw.get("motor_type") or None,
            "transmission": raw.get("transmission") or None,
            "drivetrain": raw.get("drivetrain") or None,
            "deal_rating": raw.get("deal_rating") or None,
            "dealer_name": raw.get("dealer_name") or None,
            "title": raw.get("title") or None,
            "monthly_payment": raw.get("monthly_payment") or None,
            "mpg": raw.get("mpg") or None,
        }


# ---------------------------------------------------------------------------
# Location helpers
# ---------------------------------------------------------------------------

_CITY_TO_ZIP: dict[str, str] = {
    "boulder, co": "80302",
    "denver, co": "80202",
    "colorado springs, co": "80903",
    "austin, tx": "78701",
    "dallas, tx": "75201",
    "houston, tx": "77001",
    "los angeles, ca": "90001",
    "san francisco, ca": "94102",
    "phoenix, az": "85001",
    "seattle, wa": "98101",
    "chicago, il": "60601",
    "new york, ny": "10001",
    "miami, fl": "33101",
    "atlanta, ga": "30301",
    "salt lake city, ut": "84101",
}


def _location_to_zip(location: str) -> str:
    normalized = location.lower().strip()
    if normalized in _CITY_TO_ZIP:
        return _CITY_TO_ZIP[normalized]
    for key, zipcode in _CITY_TO_ZIP.items():
        if key in normalized:
            return zipcode
    return "80302"  # default to Boulder
