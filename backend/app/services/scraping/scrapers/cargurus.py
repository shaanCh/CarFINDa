"""
CarGurus Scraper

Scrapes cargurus.com vehicle listings using the Playwright sidecar browser
for rendering and BeautifulSoup for HTML parsing.  No LLM involved.

Flow:
  1. Start a sidecar browser session.
  2. Navigate to the CarGurus search URL (lets Playwright render all JS).
  3. Retrieve the fully rendered HTML via ``browser.content()``.
  4. Parse listing cards from the DOM with BeautifulSoup.
  5. Scroll down (infinite-scroll pagination) and repeat up to 3 times.
  6. Deduplicate results and normalise into the standard listing schema.

CarGurus URL pattern:
  https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action
  Query params: zip, distance, showNegotiable, sortDir, sourceContext,
                inventorySearchWidgetType, entitySelectingHelper.selectedEntity,
                entitySelectingHelper.selectedEntity2, minPrice, maxPrice,
                minMileage, maxMileage, startYear, endYear, bodyTypeGroup,
                transmission, driveType, offset, maxResults
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

MAX_PAGES = 3          # max scroll cycles for infinite scroll
RESULTS_PER_PAGE = 15  # approximate listings per scroll batch

# ── CarGurus entity IDs for makes ──────────────────────────────────────────
MAKE_ENTITY_IDS: dict[str, str] = {
    "acura": "d3",
    "audi": "d9",
    "bmw": "d17",
    "buick": "d21",
    "cadillac": "d23",
    "chevrolet": "d27",
    "chrysler": "d28",
    "dodge": "d35",
    "ford": "d39",
    "genesis": "d2426",
    "gmc": "d42",
    "honda": "d45",
    "hyundai": "d47",
    "infiniti": "d48",
    "jaguar": "d49",
    "jeep": "d51",
    "kia": "d52",
    "land rover": "d56",
    "lexus": "d57",
    "lincoln": "d58",
    "mazda": "d64",
    "mercedes-benz": "d66",
    "mini": "d2080",
    "mitsubishi": "d69",
    "nissan": "d71",
    "porsche": "d76",
    "ram": "d2459",
    "subaru": "d83",
    "tesla": "d2218",
    "toyota": "d87",
    "volkswagen": "d91",
    "volvo": "d93",
}

# ── Body type groups ───────────────────────────────────────────────────────
BODY_TYPE_GROUPS: dict[str, str] = {
    "sedan": "SEDAN",
    "suv": "SUV",
    "crossover": "CROSSOVER",
    "truck": "TRUCK",
    "pickup": "TRUCK",
    "coupe": "COUPE",
    "convertible": "CONVERTIBLE",
    "hatchback": "HATCHBACK",
    "wagon": "WAGON",
    "van": "VAN",
    "minivan": "MINIVAN",
}

# ── City-to-ZIP mapping ───────────────────────────────────────────────────
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

# ── Deal-rating label normalisation ───────────────────────────────────────
_DEAL_LABEL_MAP: dict[str, str] = {
    "great deal": "Great Deal",
    "good deal": "Good Deal",
    "fair price": "Fair Price",
    "high price": "High Price",
    "overpriced": "Overpriced",
    "no price analysis": "No Price Analysis",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _extract_zip(location: str) -> str:
    """Try to extract or map a zip code from a location string."""
    location = location.strip()

    if location.isdigit() and len(location) == 5:
        return location

    parts = location.split()
    if parts and parts[-1].isdigit() and len(parts[-1]) == 5:
        return parts[-1]

    normalized = location.lower().strip()
    if normalized in CITY_TO_ZIP:
        return CITY_TO_ZIP[normalized]

    for key, zipcode in CITY_TO_ZIP.items():
        if key in normalized:
            return zipcode

    logger.warning("Could not map location '%s' to zip for CarGurus", location)
    return ""


def _normalise_deal_rating(raw: str | None) -> str | None:
    """Normalise a deal-rating string to a canonical label."""
    if not raw:
        return None
    key = raw.strip().lower()
    return _DEAL_LABEL_MAP.get(key, raw.strip())


def _safe_int(value: Any) -> int | None:
    """Coerce *value* to ``int`` or return ``None``."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = (
            value.replace(",", "")
            .replace("mi", "")
            .replace("miles", "")
            .strip()
        )
        try:
            return int(float(cleaned))
        except (ValueError, TypeError):
            return None
    return None


def _safe_float(value: Any) -> float | None:
    """Coerce *value* to ``float`` or return ``None``."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return None
    return None


def _tag_text(tag: Tag | None) -> str:
    """Safely extract stripped text from a BS4 tag."""
    return tag.get_text(strip=True) if tag else ""


def _first_str(val: Any) -> str:
    """Return *val* as a plain string (handles BS4 multi-valued attrs)."""
    if isinstance(val, list):
        return val[0] if val else ""
    return str(val) if val else ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main scraper class
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CarGurusScraper:
    """Scraper for cargurus.com using the sidecar browser + BeautifulSoup.

    The sidecar (Playwright) handles JS rendering and anti-bot stealth.
    BeautifulSoup parses the fully rendered HTML to extract listing data.
    No LLM is involved.

    CarGurus provides deal ratings (Great Deal, Good Deal, Fair Price,
    High Price, Overpriced) which are extracted alongside standard fields.
    """

    source_name = "CarGurus"

    def __init__(self, browser: BrowserClient, profile: str = "carfinda-cargurus"):
        """
        Args:
            browser: A BrowserClient connected to the Playwright sidecar.
            profile: Sidecar profile name (for persistent browser context).
        """
        self.browser = browser
        self.profile = profile

    # ------------------------------------------------------------------
    # URL building
    # ------------------------------------------------------------------

    def build_search_url(self, filters: dict[str, Any], *, offset: int = 0) -> str:
        """Build a CarGurus search URL from structured filters.

        Args:
            filters: Structured search filter dict.
            offset:  Result offset for pagination (0-based).
        """
        base_url = (
            "https://www.cargurus.com/Cars/inventorylisting/"
            "viewDetailsFilterViewInventoryListing.action"
        )

        params: dict[str, str] = {
            "sourceContext": "carGurusHomePageModel",
            "inventorySearchWidgetType": "AUTO",
            "sortDir": "ASC",
            "sortType": "DEAL_SCORE",
            "showNegotiable": "true",
        }

        if offset > 0:
            params["offset"] = str(offset)
            params["maxResults"] = str(RESULTS_PER_PAGE)

        # Location (zip code)
        location = filters.get("location", "")
        if location:
            zipcode = _extract_zip(location)
            if zipcode:
                params["zip"] = zipcode

        # Search radius
        radius = filters.get("radius_miles", 50)
        params["distance"] = str(radius)

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

        # Make filters -- CarGurus uses entity IDs
        makes = filters.get("makes", [])
        if makes:
            entity_id = MAKE_ENTITY_IDS.get(makes[0].lower())
            if entity_id:
                params["entitySelectingHelper.selectedEntity"] = entity_id
            if len(makes) > 1:
                entity_id2 = MAKE_ENTITY_IDS.get(makes[1].lower())
                if entity_id2:
                    params["entitySelectingHelper.selectedEntity2"] = entity_id2

        # Body type
        body_types = filters.get("body_types", [])
        if body_types:
            groups: list[str] = []
            for bt in body_types:
                group = BODY_TYPE_GROUPS.get(bt.lower())
                if group and group not in groups:
                    groups.append(group)
            if groups:
                params["bodyTypeGroup"] = groups[0]

        return f"{base_url}?{urlencode(params)}"

    # ------------------------------------------------------------------
    # Search (main entry point)
    # ------------------------------------------------------------------

    async def search(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Search CarGurus for listings matching *filters*.

        Uses the sidecar browser to render the page, then parses the
        fully rendered HTML with BeautifulSoup.  Handles CarGurus's
        infinite scroll by scrolling down and re-reading the DOM up to
        ``MAX_PAGES`` times.

        Returns:
            List of normalised listing dicts.
        """
        all_listings: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        url = self.build_search_url(filters)
        logger.info("CarGurus: starting search -- %s", url)

        try:
            await self.browser.start_session(self.profile)

            # Initial navigation -- Playwright renders all JS
            await self.browser.navigate(self.profile, url)

            # Allow the page to fully hydrate after navigation
            await asyncio.sleep(2.0)

            # ── Check for CAPTCHA and attempt to solve ────────────────
            try:
                solved = await self.browser.solve_captcha_if_present(self.profile)
                if solved:
                    logger.info("CarGurus: CAPTCHA solved, continuing with scrape")
                    await asyncio.sleep(1.0)
            except Exception as exc:
                logger.debug("CarGurus: captcha check failed: %s", exc)

            # ── Scroll loop (infinite scroll pagination) ──────────────
            for scroll_cycle in range(MAX_PAGES):
                logger.info(
                    "CarGurus: reading DOM (scroll cycle %d/%d)",
                    scroll_cycle + 1,
                    MAX_PAGES,
                )

                # Get the fully rendered HTML
                html = await self.browser.content(self.profile)

                if not html or len(html) < 500:
                    logger.warning(
                        "CarGurus: empty or very short HTML on scroll cycle %d",
                        scroll_cycle + 1,
                    )
                    break

                # Parse listing cards from the rendered HTML
                raw_listings = self._parse_listings(html)

                new_count = 0
                for raw in raw_listings:
                    normalized = self.normalize_listing(raw)

                    # Deduplicate by title + price composite key
                    title = (
                        f"{normalized.get('year', '')}"
                        f" {normalized.get('make', '')}"
                        f" {normalized.get('model', '')}"
                    ).strip()
                    dedup_key = f"{title}_{normalized.get('price', '')}"

                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)

                    all_listings.append(normalized)
                    new_count += 1

                logger.info(
                    "CarGurus: scroll cycle %d yielded %d new listings (total: %d)",
                    scroll_cycle + 1,
                    new_count,
                    len(all_listings),
                )

                # If this scroll cycle yielded nothing new, stop scrolling
                if new_count == 0:
                    logger.info("CarGurus: no new listings from scroll -- stopping")
                    break

                # Scroll down to trigger infinite scroll (unless last cycle)
                if scroll_cycle < MAX_PAGES - 1:
                    await self.browser.act(
                        self.profile, "scroll", direction="down"
                    )
                    # Wait for new content to load after scroll
                    await asyncio.sleep(2.0)

        except Exception as exc:
            logger.error("CarGurus: scraping failed: %s", exc, exc_info=True)
        finally:
            try:
                await self.browser.stop_session(self.profile)
            except Exception:
                pass

        logger.info(
            "CarGurus: search complete -- %d total listings", len(all_listings)
        )
        return all_listings

    # ------------------------------------------------------------------
    # BS4 HTML parsing
    # ------------------------------------------------------------------

    def _parse_listings(self, html: str) -> list[dict[str, Any]]:
        """Parse listing cards from fully rendered HTML using BeautifulSoup.

        Tries multiple CSS selectors to find listing card elements, then
        extracts vehicle data from each card.

        Args:
            html: The fully rendered page HTML (after JS execution).

        Returns:
            List of raw listing dicts (not yet normalised).
        """
        soup = BeautifulSoup(html, "html.parser")
        listings: list[dict[str, Any]] = []

        # Try multiple selectors that CarGurus uses for listing cards
        card_selectors = [
            {"attrs": {"data-cg-listing-id": True}},
            {"class_": re.compile(r"listing[-_]?row", re.I)},
            {"attrs": {"data-listing-id": True}},
            {"class_": re.compile(r"srp[-_]?listing[-_]?blade", re.I)},
            {"class_": re.compile(r"result[-_]?card", re.I)},
            {"attrs": {"data-testid": re.compile(r"listing", re.I)}},
            {"class_": re.compile(r"listing[-_]?card", re.I)},
            {"class_": re.compile(r"cg-listing", re.I)},
            {"attrs": {"data-cg-ft": "srp-listing-blade"}},
            {"attrs": {"id": re.compile(r"listing_\d+")}},
        ]

        cards: list[Tag] = []
        for sel in card_selectors:
            # Try div, a, article, section, li elements
            for tag_name in ("div", "a", "article", "section", "li"):
                found = soup.find_all(tag_name, **sel)
                if found:
                    cards = found
                    logger.debug(
                        "CarGurus: found %d cards via <%s %s>",
                        len(cards),
                        tag_name,
                        sel,
                    )
                    break
            if cards:
                break

        if not cards:
            logger.warning("CarGurus: no listing cards found in HTML")
            return listings

        for card in cards:
            parsed = self._parse_single_card(card)
            if parsed:
                listings.append(parsed)

        logger.info(
            "CarGurus: parsed %d listings from %d cards", len(listings), len(cards)
        )
        return listings

    def _parse_single_card(self, card: Tag) -> dict[str, Any] | None:
        """Extract listing fields from a single HTML listing card.

        Args:
            card: A BeautifulSoup Tag representing one listing card.

        Returns:
            A raw listing dict, or None if the card cannot be parsed.
        """

        # ── Title (year / make / model / trim) ────────────────────────
        title_tag = (
            card.find(class_=re.compile(r"listing[-_]?title", re.I))
            or card.find("h2")
            or card.find("h3")
            or card.find("h4")
            or card.find(class_=re.compile(r"vehicle[-_]?name", re.I))
            or card.find(class_=re.compile(r"car[-_]?name", re.I))
        )
        title_text = _tag_text(title_tag)
        if not title_text:
            title_text = _first_str(
                card.get("data-title") or card.get("aria-label") or ""
            )

        if not title_text:
            return None

        # Parse "2021 Toyota Camry SE" style titles
        title_parts = title_text.split()
        year: int | None = None
        make: str | None = None
        model: str | None = None
        trim: str | None = None

        if title_parts and re.match(r"^\d{4}$", title_parts[0]):
            year = int(title_parts[0])
            if len(title_parts) > 1:
                make = title_parts[1]
            if len(title_parts) > 2:
                model = title_parts[2]
            if len(title_parts) > 3:
                trim = " ".join(title_parts[3:])

        if not year or not make:
            return None

        # ── Price ─────────────────────────────────────────────────────
        price_tag = card.find(class_=re.compile(r"price", re.I))
        price = _safe_float(_tag_text(price_tag))
        if price is None:
            price = _safe_float(
                _first_str(
                    card.get("data-price") or card.get("data-listed-price")
                )
            )

        # ── Mileage ──────────────────────────────────────────────────
        mileage_tag = card.find(
            class_=re.compile(r"mileage|miles|odometer", re.I)
        )
        mileage = _safe_int(_tag_text(mileage_tag))
        if mileage is None:
            mileage = _safe_int(_first_str(card.get("data-mileage")))
        # Also check for text containing "mi" pattern in spans/divs
        if mileage is None:
            for el in card.find_all(string=re.compile(r"[\d,]+\s*mi", re.I)):
                match = re.search(r"([\d,]+)\s*mi", el, re.I)
                if match:
                    mileage = _safe_int(match.group(1))
                    break

        # ── Deal rating ──────────────────────────────────────────────
        deal_tag = card.find(
            class_=re.compile(r"deal[-_]?(rating|badge|label|type)", re.I)
        )
        deal_rating: str | None = _tag_text(deal_tag) or None

        if not deal_rating:
            # Check data attributes
            raw_deal = _first_str(
                card.get("data-deal-rating") or card.get("data-deal-type")
            )
            deal_rating = raw_deal or None

        if not deal_rating:
            # Look for price badge elements
            badge_tag = card.find(
                class_=re.compile(r"price[-_]?badge", re.I)
            )
            deal_rating = _tag_text(badge_tag) or None

        if not deal_rating:
            # Search for known deal-rating text anywhere in the card
            for label in _DEAL_LABEL_MAP.values():
                found_el = card.find(
                    string=re.compile(re.escape(label), re.I)
                )
                if found_el:
                    deal_rating = label
                    break

        # ── Source URL ────────────────────────────────────────────────
        link_tag = card.find("a", href=True) if card.name != "a" else card
        source_url: str | None = None
        if link_tag and link_tag.get("href"):
            href = _first_str(link_tag["href"])
            if href.startswith("/"):
                source_url = f"https://www.cargurus.com{href}"
            elif href.startswith("http"):
                source_url = href

        # ── VIN ──────────────────────────────────────────────────────
        vin: str | None = _first_str(card.get("data-vin")) or None
        if not vin:
            # Try data-cg-listing-id or other data attrs
            vin_attr = card.get("data-vin") or card.get("data-vehicle-vin")
            if vin_attr:
                vin = _first_str(vin_attr)
        if not vin and source_url:
            vin_match = re.search(r"[A-HJ-NPR-Z0-9]{17}", source_url)
            if vin_match:
                vin = vin_match.group(0)

        # ── Images ───────────────────────────────────────────────────
        image_urls: list[str] = []
        for img in card.find_all("img", src=True):
            src = _first_str(img.get("src", ""))
            if (
                src
                and "placeholder" not in src.lower()
                and "pixel" not in src.lower()
                and "blank" not in src.lower()
            ):
                if src.startswith("/"):
                    src = f"https://www.cargurus.com{src}"
                image_urls.append(src)
        # Also check lazy-loaded images
        for img in card.find_all("img", attrs={"data-src": True}):
            dsrc = _first_str(img["data-src"])
            if dsrc:
                if dsrc.startswith("/"):
                    dsrc = f"https://www.cargurus.com{dsrc}"
                image_urls.append(dsrc)
        # Check srcset as well
        for img in card.find_all("img", attrs={"srcset": True}):
            srcset = _first_str(img["srcset"])
            if srcset:
                # Take the first URL from srcset
                first_src = srcset.split(",")[0].strip().split(" ")[0]
                if first_src and first_src.startswith("http"):
                    image_urls.append(first_src)

        # ── Location ─────────────────────────────────────────────────
        loc_tag = card.find(
            class_=re.compile(
                r"(dealer|seller)[-_]?(location|city|name|address)", re.I
            )
        )
        location = _tag_text(loc_tag) or None

        return {
            "year": year,
            "make": make,
            "model": model,
            "trim": trim,
            "price": price,
            "mileage": mileage,
            "vin": vin,
            "source_url": source_url,
            "image_urls": image_urls,
            "deal_rating": _normalise_deal_rating(deal_rating),
            "location": location,
            "exterior_color": None,
            "interior_color": None,
            "fuel_type": None,
            "transmission": None,
            "drivetrain": None,
            "dealer_name": None,
        }

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def normalize_listing(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalise a raw listing dict into the standard listing schema.

        Cleans price/mileage/year strings, generates a UUID, and tags
        the listing with ``source_name="CarGurus"``.

        Args:
            raw: Raw listing dict from ``_parse_listings()``.

        Returns:
            A normalised listing dict with all expected fields.
        """
        # Clean price
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

        # Clean mileage
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
            "dealer_name": raw.get("dealer_name") or None,
        }
