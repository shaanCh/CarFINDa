"""
Scraping Pipeline -- Orchestrates multi-source scraping, deduplication, and sorting.

Active sources:
  - CarMax: httpx JSON API (fast, no bot protection)
  - Cars.com: httpx direct (primary) + sidecar browser fallback
  - Auto.dev: REST API (free tier, 1000 calls/month) -- if API key set

Disabled sources (require proxy to bypass bot protection):
  - Autotrader: blocked by Akamai (IP-level, not a solvable CAPTCHA)
  - CarGurus: blocked by DataDome (CapSolver requires proxy)

Usage:
    from app.services.scraping.pipeline import run_scraping_pipeline

    listings = await run_scraping_pipeline(filters)

    # On app shutdown:
    await stop_scraping_pipeline()
"""

import asyncio
import logging
from typing import Any, Optional

from app.config import get_settings
from app.services.scraping.browser_client import BrowserClient
from app.services.scraping.dedup import deduplicate_listings
from app.services.scraping.scrapers.carmax import CarMaxScraper
from app.services.scraping.scrapers.carscom import CarsComScraper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level shared BrowserClient (lazy-initialised)
# ---------------------------------------------------------------------------

_shared_browser: Optional[BrowserClient] = None


def _get_browser() -> Optional[BrowserClient]:
    """Return the module-level shared BrowserClient, creating it if needed.
    Returns None if sidecar is not configured."""
    global _shared_browser
    if _shared_browser is None:
        settings = get_settings()
        if settings.SIDECAR_URL:
            _shared_browser = BrowserClient(
                base_url=settings.SIDECAR_URL,
                token=settings.SIDECAR_TOKEN,
            )
    return _shared_browser


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def stop_scraping_pipeline() -> None:
    """Close the shared BrowserClient."""
    global _shared_browser
    if _shared_browser is not None:
        await _shared_browser.close()
        _shared_browser = None
        logger.info("Scraping pipeline browser client closed")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _run_single_scraper(
    scraper: Any,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run a single scraper with error isolation.

    If the scraper raises an exception, logs the error and returns an
    empty list so other scrapers can continue.
    """
    scraper_name = type(scraper).__name__
    try:
        logger.info("Starting %s", scraper_name)
        results = await scraper.search(filters)
        logger.info("%s returned %d listings", scraper_name, len(results))
        return results
    except Exception as exc:
        logger.error(
            "%s failed (continuing with other sources): %s",
            scraper_name,
            exc,
            exc_info=True,
        )
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_scraping_pipeline(
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run the full scraping pipeline across all marketplace sources.

    Steps:
    1. Create scrapers (CarMax, Cars.com, Auto.dev if configured)
    2. If no make specified and semantic categories present, expand into multiple makes
    3. Run all scrapers in parallel (asyncio.gather with error isolation)
    4. Flatten results from all sources
    5. Deduplicate by VIN (with fuzzy fallback)
    6. Return normalized, deduplicated listings sorted by price

    Args:
        filters: Structured search filters dict with keys like
                 budget_min, budget_max, makes, body_types, max_mileage,
                 min_year, location, radius_miles.

    Returns:
        List of deduplicated, normalized listing dicts.
    """
    logger.info("Starting scraping pipeline with filters: %s", filters)

    settings = get_settings()
    browser = _get_browser()

    # Shared HTTP client for all scrapers — avoids connection storms.
    from app.services.scraping.base_scraper import create_http_client
    shared_http = create_http_client()

    # ── Smart multi-make expansion ──
    filter_sets = _expand_filters(filters)

    # Limit concurrent web scraper tasks to avoid 403s from rate limiting.
    # Run at most 3 web scraper tasks at a time.
    scraper_semaphore = asyncio.Semaphore(3)

    async def _run_with_limit(scraper: Any, fset: dict) -> list[dict]:
        async with scraper_semaphore:
            return await _run_single_scraper(scraper, fset)

    # Build tasks — each expanded filter set gets its own scraper instance
    tasks = []
    for fset in filter_sets:
        tasks.append(_run_with_limit(
            CarMaxScraper(browser=None, profile="carfinda-carmax",
                          http_client=shared_http),
            fset,
        ))
        tasks.append(_run_with_limit(
            CarsComScraper(browser=None, profile="carfinda-carscom",
                           http_client=shared_http),
            fset,
        ))

    # API-based scrapers search broadly — no need for expansion
    if settings.AUTO_DEV_API_KEY:
        from app.services.scraping.scrapers.autodev import AutoDevScraper
        tasks.append(_run_single_scraper(AutoDevScraper(api_key=settings.AUTO_DEV_API_KEY), filters))

    results = await asyncio.gather(*tasks)

    # Clean up shared HTTP client
    await shared_http.aclose()

    # Flatten all results into a single list
    all_listings: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for scraper_results in results:
        for listing in scraper_results:
            source = listing.get("source_name", "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
            all_listings.append(listing)

    logger.info(
        "Scraped %d total listings across sources: %s",
        len(all_listings),
        source_counts,
    )

    if not all_listings:
        logger.warning("No listings found from any source")
        return []

    # Deduplicate by VIN / fuzzy match
    deduped = deduplicate_listings(all_listings)

    # Sort by price (lowest first), with None-priced at the end
    deduped.sort(key=lambda x: (x.get("price") is None, x.get("price") or float("inf")))

    logger.info(
        "Pipeline complete: %d listings after deduplication (from %d raw)",
        len(deduped),
        len(all_listings),
    )

    return deduped


# ---------------------------------------------------------------------------
# Smart filter expansion
# ---------------------------------------------------------------------------

# Popular makes for broad searches, grouped by category
_POPULAR_MAKES_BY_CATEGORY: dict[str, list[str]] = {
    "SUV": ["Toyota", "Honda", "Hyundai", "Kia", "Ford", "Chevrolet", "Subaru", "Mazda"],
    "Crossover": ["Toyota", "Honda", "Hyundai", "Kia", "Mazda", "Subaru"],
    "Truck": ["Ford", "Chevrolet", "Toyota", "Ram", "GMC", "Nissan"],
    "Sedan": ["Toyota", "Honda", "Hyundai", "Kia", "Mazda", "Nissan", "Subaru"],
    "Coupe": ["Honda", "Toyota", "Ford", "Chevrolet", "BMW", "Nissan"],
    "Hatchback": ["Honda", "Toyota", "Mazda", "Hyundai", "Volkswagen", "Subaru"],
    "Minivan": ["Honda", "Toyota", "Chrysler", "Kia"],
}
_DEFAULT_POPULAR_MAKES = ["Toyota", "Honda", "Ford", "Chevrolet", "Hyundai", "Kia", "Subaru", "Mazda"]


def _expand_filters(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand a single filter set into multiple sets for broader coverage.

    When no make is specified, generates separate searches for popular makes
    based on the body type. This dramatically increases result volume.
    """
    # If makes or models are already specified, just run as-is
    if filters.get("makes") or filters.get("models"):
        return [filters]

    # Pick makes to expand based on body types
    body_types = filters.get("body_types", [])
    if body_types:
        # Get makes relevant to the requested body type
        makes_set: set[str] = set()
        for bt in body_types:
            bt_upper = bt.strip().title()
            if bt_upper in _POPULAR_MAKES_BY_CATEGORY:
                makes_set.update(_POPULAR_MAKES_BY_CATEGORY[bt_upper])
        expand_makes = list(makes_set) if makes_set else _DEFAULT_POPULAR_MAKES
    else:
        expand_makes = _DEFAULT_POPULAR_MAKES

    # Limit expansion to avoid excessive API calls
    expand_makes = expand_makes[:6]

    expanded = []
    for make in expand_makes:
        f = dict(filters)
        f["makes"] = [make]
        expanded.append(f)

    logger.info("Expanded filters into %d make-specific searches: %s", len(expanded), expand_makes)
    return expanded
