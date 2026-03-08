"""
Scraping Pipeline -- Orchestrates multi-source scraping, deduplication, and sorting.

Active sources:
  - CarMax: httpx JSON API (fast, no bot protection)
  - Cars.com: sidecar browser + BS4 (renders JS, no CAPTCHA)

Disabled sources (require proxy to bypass bot protection):
  - Autotrader: blocked by Akamai (IP-level, not a solvable CAPTCHA)
  - CarGurus: blocked by DataDome (CapSolver requires proxy)

Each scraper receives a shared BrowserClient and its own profile name to
avoid tab conflicts in the sidecar.

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


def _get_browser() -> BrowserClient:
    """Return the module-level shared BrowserClient, creating it if needed."""
    global _shared_browser
    if _shared_browser is None:
        settings = get_settings()
        _shared_browser = BrowserClient(
            base_url=settings.SIDECAR_URL,
            token=settings.SIDECAR_TOKEN,
        )
    return _shared_browser


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def stop_scraping_pipeline() -> None:
    """Close the shared BrowserClient.

    Call this on application shutdown (e.g. in a FastAPI lifespan handler)
    to release resources cleanly.
    """
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
    1. Create a shared BrowserClient and per-source scrapers
    2. Run all scrapers in parallel (asyncio.gather with error isolation)
    3. Flatten results from all sources
    4. Deduplicate by VIN (with fuzzy fallback)
    5. Return normalized, deduplicated listings sorted by price

    Args:
        filters: Structured search filters dict with keys like
                 budget_min, budget_max, makes, body_types, max_mileage,
                 min_year, location, radius_miles.

    Returns:
        List of deduplicated, normalized listing dicts.
    """
    logger.info("Starting scraping pipeline with filters: %s", filters)

    browser = _get_browser()

    # Each scraper gets its own profile to avoid tab conflicts
    scrapers = [
        CarMaxScraper(browser=browser, profile="carfinda-carmax"),
        CarsComScraper(browser=browser, profile="carfinda-carscom"),
    ]

    # Run all scrapers in parallel -- each is error-isolated
    results = await asyncio.gather(
        *[_run_single_scraper(s, filters) for s in scrapers]
    )

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
