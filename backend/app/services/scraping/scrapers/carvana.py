"""
Carvana Scraper -- Browser-based scraper using the Playwright sidecar.

Carvana's API is behind Cloudflare Managed Challenge, so direct httpx
requests return 403.  We use the sidecar browser to:
  1. Navigate to the Carvana search URL
  2. Wait for the page to render (Cloudflare challenge auto-solves in browser)
  3. Extract listing data from the rendered DOM or intercepted JSON

Carvana URL pattern:
  https://www.carvana.com/cars/toyota-camry?price=10000-25000&year=2020-2026&mileage=0-80000
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag

from app.services.scraping.browser_client import BrowserClient

logger = logging.getLogger(__name__)

MAX_PAGES = 2


class CarvanaScraper:
    """Scraper for carvana.com using sidecar browser."""

    source_name = "Carvana"

    def __init__(self, browser: BrowserClient, profile: str = "carfinda-carvana"):
        self.browser = browser
        self.profile = profile

    def build_search_url(self, filters: dict[str, Any], *, page: int = 1) -> str:
        """Build a Carvana search URL from structured filters."""
        # Carvana URL: /cars/<make>-<model>?price=min-max&year=min-max&mileage=0-max
        makes = filters.get("makes", [])
        models = filters.get("models", [])

        if makes and models:
            path = f"/cars/{makes[0].lower()}-{models[0].lower().replace(' ', '-')}"
        elif makes:
            path = f"/cars/{makes[0].lower()}"
        else:
            path = "/cars"

        params: dict[str, str] = {}

        price_min = filters.get("budget_min", 0) or 0
        price_max = filters.get("budget_max")
        if price_max:
            params["price"] = f"{int(price_min)}-{int(price_max)}"

        min_year = filters.get("min_year")
        if min_year:
            params["year"] = f"{min_year}-2026"

        max_mileage = filters.get("max_mileage")
        if max_mileage:
            params["mileage"] = f"0-{max_mileage}"

        body_types = filters.get("body_types", [])
        if body_types:
            bt_map = {
                "sedan": "sedan", "suv": "suv", "truck": "truck",
                "coupe": "coupe", "hatchback": "hatchback",
                "minivan": "minivan", "van": "van",
                "convertible": "convertible", "wagon": "wagon",
                "crossover": "suv",
            }
            mapped = [bt_map.get(bt.lower(), bt.lower()) for bt in body_types]
            if mapped:
                params["bodyType"] = ",".join(set(mapped))

        if page > 1:
            params["page"] = str(page)

        query = urlencode(params)
        url = f"https://www.carvana.com{path}"
        if query:
            url += f"?{query}"
        return url

    async def search(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Search Carvana for listings using the sidecar browser."""
        all_listings: list[dict[str, Any]] = []
        seen_vins: set[str] = set()

        try:
            await self.browser.start_session(self.profile)

            for page_num in range(1, MAX_PAGES + 1):
                url = self.build_search_url(filters, page=page_num)
                logger.info("Carvana: navigating to page %d -- %s", page_num, url)

                try:
                    await self.browser.navigate(self.profile, url)
                except Exception as exc:
                    logger.error("Carvana: navigation failed on page %d: %s", page_num, exc)
                    break

                # Wait for Cloudflare challenge + page render
                await asyncio.sleep(5.0)

                # Try to extract data from the page
                try:
                    html = await self.browser.content(self.profile)
                except Exception as exc:
                    logger.error("Carvana: content fetch failed on page %d: %s", page_num, exc)
                    break

                if not html or len(html) < 500:
                    logger.warning("Carvana: empty response on page %d", page_num)
                    break

                # Check for Cloudflare challenge page
                if "Just a moment" in html[:500] or "challenge-platform" in html[:1000]:
                    logger.warning("Carvana: Cloudflare challenge not solved on page %d", page_num)
                    # Wait longer and retry once
                    await asyncio.sleep(5.0)
                    try:
                        html = await self.browser.content(self.profile)
                    except Exception:
                        break
                    if "Just a moment" in html[:500]:
                        logger.error("Carvana: Cloudflare challenge persists -- aborting")
                        break

                # Try embedded JSON first (Carvana often has __NEXT_DATA__)
                listings = self._extract_from_next_data(html)
                if not listings:
                    listings = self._parse_dom(html)

                if not listings:
                    logger.info("Carvana: no listings found on page %d -- stopping", page_num)
                    break

                new_count = 0
                for listing in listings:
                    vin = listing.get("vin", "")
                    if vin and vin in seen_vins:
                        continue
                    if vin:
                        seen_vins.add(vin)
                    all_listings.append(listing)
                    new_count += 1

                logger.info(
                    "Carvana: page %d yielded %d new listings (total: %d)",
                    page_num, new_count, len(all_listings),
                )

                if new_count == 0:
                    break

                if page_num < MAX_PAGES:
                    await asyncio.sleep(2.0)

        except Exception as exc:
            logger.error("Carvana scraping failed: %s", exc, exc_info=True)
        finally:
            try:
                await self.browser.stop_session(self.profile)
            except Exception:
                pass

        return all_listings

    def _extract_from_next_data(self, html: str) -> list[dict[str, Any]]:
        """Try to extract listings from __NEXT_DATA__ or embedded JSON."""
        listings: list[dict[str, Any]] = []
        soup = BeautifulSoup(html, "html.parser")

        for script in soup.find_all("script"):
            text = script.string or ""
            if not text:
                continue

            # Look for __NEXT_DATA__
            if "__NEXT_DATA__" in text:
                match = re.search(r"__NEXT_DATA__\s*=\s*({.*?})\s*;?\s*$", text, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        vehicles = self._find_vehicles_recursive(data)
                        for v in vehicles:
                            listing = self._parse_vehicle_json(v)
                            if listing:
                                listings.append(listing)
                        if listings:
                            return listings
                    except (json.JSONDecodeError, ValueError):
                        pass

            # Look for embedded inventory data
            if "inventory" in text and ("stockNumber" in text or "make" in text):
                # Try to find a JSON object
                for pattern in [r"({.*})", r"\[{.*}\]"]:
                    for match in re.finditer(pattern, text, re.DOTALL):
                        try:
                            data = json.loads(match.group())
                            if isinstance(data, list):
                                for v in data:
                                    listing = self._parse_vehicle_json(v)
                                    if listing:
                                        listings.append(listing)
                            elif isinstance(data, dict):
                                vehicles = self._find_vehicles_recursive(data)
                                for v in vehicles:
                                    listing = self._parse_vehicle_json(v)
                                    if listing:
                                        listings.append(listing)
                            if listings:
                                return listings
                        except (json.JSONDecodeError, ValueError):
                            continue

        return listings

    def _find_vehicles_recursive(self, obj: Any, depth: int = 0) -> list[dict]:
        """Recursively search for vehicle-like objects."""
        if depth > 8:
            return []

        if isinstance(obj, list):
            if (obj and isinstance(obj[0], dict) and
                any(k in obj[0] for k in ("stockNumber", "vin", "make", "model"))):
                return obj
            for item in obj:
                result = self._find_vehicles_recursive(item, depth + 1)
                if result:
                    return result

        elif isinstance(obj, dict):
            for key in ("vehicles", "inventory", "results", "items", "listings",
                        "data", "props", "pageProps"):
                if key in obj:
                    result = self._find_vehicles_recursive(obj[key], depth + 1)
                    if result:
                        return result
            for value in obj.values():
                result = self._find_vehicles_recursive(value, depth + 1)
                if result:
                    return result

        return []

    def _parse_vehicle_json(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a vehicle JSON object from Carvana's data."""
        if not isinstance(item, dict):
            return None

        year = item.get("year")
        make = item.get("make", "")
        model = item.get("model", "")
        if not year or not make:
            return None

        # Price
        price = None
        price_data = item.get("price")
        if isinstance(price_data, dict):
            price = price_data.get("total") or price_data.get("base")
        elif isinstance(price_data, (int, float)):
            price = price_data
        if not price:
            price = item.get("listPrice") or item.get("basePrice")

        mileage = item.get("mileage")
        vin = item.get("vin", "")
        stock = item.get("stockNumber", "")
        trim = item.get("trim", "")

        # Images
        image_urls = []
        for key in ("heroImageUrl", "imageUrl", "primaryPhotoUrl", "thumbnailUrl"):
            if item.get(key):
                image_urls.append(item[key])
                break
        if isinstance(item.get("images"), list):
            for img in item["images"][:5]:
                url = img if isinstance(img, str) else (img.get("url") or "")
                if url and url not in image_urls:
                    image_urls.append(url)

        # Source URL
        source_url = f"https://www.carvana.com/vehicle/{stock}" if stock else None
        if not source_url and vin:
            source_url = f"https://www.carvana.com/vehicle/{vin}"

        return {
            "id": str(uuid.uuid4()),
            "vin": vin or None,
            "year": int(year),
            "make": make,
            "model": model,
            "trim": trim or None,
            "title": None,
            "price": float(price) if price else None,
            "monthly_payment": None,
            "mileage": int(mileage) if mileage else None,
            "mpg": None,
            "location": "Carvana (Online)",
            "source_url": source_url,
            "source_name": self.source_name,
            "sources": [{"name": self.source_name, "url": source_url, "price": float(price) if price else None}],
            "image_urls": image_urls,
            "exterior_color": item.get("exteriorColor") or item.get("color") or None,
            "interior_color": item.get("interiorColor") or None,
            "fuel_type": item.get("fuelType") or None,
            "motor_type": item.get("engineType") or None,
            "transmission": item.get("transmission") or None,
            "drivetrain": item.get("driveTrain") or item.get("drivetrain") or None,
            "deal_rating": None,
            "dealer_name": "Carvana",
        }

    def _parse_dom(self, html: str) -> list[dict[str, Any]]:
        """Parse listings from the rendered DOM as a fallback."""
        soup = BeautifulSoup(html, "html.parser")
        listings: list[dict[str, Any]] = []

        # Carvana uses various card patterns
        cards = soup.find_all(
            ["div", "article", "a"],
            class_=re.compile(r"result-tile|vehicle-card|inventory-card|tk-card", re.I),
        )

        if not cards:
            # Try links to vehicle detail pages
            links = soup.find_all("a", href=re.compile(r"/vehicle/\d+"))
            for link in links:
                card = link.find_parent("div", class_=True)
                if card and card not in cards:
                    cards.append(card)

        for card in cards:
            listing = self._parse_dom_card(card)
            if listing:
                listings.append(listing)

        logger.info("Carvana DOM: parsed %d listings from %d cards", len(listings), len(cards))
        return listings

    def _parse_dom_card(self, card: Tag) -> dict[str, Any] | None:
        """Parse a single DOM card into a listing."""
        text = card.get_text(separator=" ", strip=True)
        if not text or len(text) < 10:
            return None

        # Title: "2022 Toyota Camry SE"
        title_el = card.find(["h2", "h3", "h4"]) or card.find(
            class_=re.compile(r"title|heading|name|year-make", re.I)
        )
        title = title_el.get_text(strip=True) if title_el else ""

        year, make, model, trim = None, None, None, None
        if title:
            parts = title.split()
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

        # Price
        price = None
        price_el = card.find(class_=re.compile(r"price", re.I))
        if price_el:
            price_text = price_el.get_text(strip=True)
            price_match = re.search(r"\$?([\d,]+)", price_text)
            if price_match:
                try:
                    price = float(price_match.group(1).replace(",", ""))
                except ValueError:
                    pass

        # Mileage
        mileage = None
        mi_match = re.search(r"([\d,]+)\s*(?:mi|miles)", text, re.I)
        if mi_match:
            try:
                mileage = int(mi_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Source URL
        source_url = None
        link = card.find("a", href=re.compile(r"/vehicle/"))
        if link:
            href = link.get("href", "")
            source_url = f"https://www.carvana.com{href}" if href.startswith("/") else href

        # Image
        image_urls = []
        img = card.find("img", src=True)
        if img:
            src = img.get("src", "")
            if src.startswith("http"):
                image_urls.append(src)

        if not price and not mileage:
            return None

        return {
            "id": str(uuid.uuid4()),
            "vin": None,
            "year": year,
            "make": make,
            "model": model,
            "trim": trim,
            "title": title,
            "price": price,
            "monthly_payment": None,
            "mileage": mileage,
            "mpg": None,
            "location": "Carvana (Online)",
            "source_url": source_url,
            "source_name": self.source_name,
            "sources": [{"name": self.source_name, "url": source_url, "price": price}],
            "image_urls": image_urls,
            "exterior_color": None,
            "interior_color": None,
            "fuel_type": None,
            "motor_type": None,
            "transmission": None,
            "drivetrain": None,
            "deal_rating": None,
            "dealer_name": "Carvana",
        }
