"""
Base Scraper -- Abstract base class for all site-specific scrapers.

Each scraper must implement:
  - build_search_url(filters) -> str
  - search(filters) -> list[dict]

The base class provides:
  - A shared httpx.AsyncClient with realistic browser headers
  - fetch_page(url) -> str  for HTTP GET with retries
  - extract_listings_with_llm()  for Gemini-based extraction when HTML
    parsing alone is not enough
  - normalize_listing()  for converting raw dicts into the standard schema
"""

import asyncio
import logging
import random
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Realistic browser headers for anti-bot evasion
# ---------------------------------------------------------------------------

_USER_AGENTS = [
    # Chrome 124 on Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome 124 on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome 123 on Windows 11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Firefox 125 on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Safari 17 on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Retry / timing defaults
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5  # seconds
REQUEST_TIMEOUT = 30.0  # seconds


def create_http_client(
    *,
    headers: Optional[dict[str, str]] = None,
    timeout: float = REQUEST_TIMEOUT,
) -> httpx.AsyncClient:
    """Create a shared httpx.AsyncClient with realistic browser headers.

    The User-Agent is chosen randomly on creation so that all requests from
    a single client use a consistent UA (per-session, not per-request).
    """
    merged_headers = dict(DEFAULT_HEADERS)
    merged_headers["User-Agent"] = random.choice(_USER_AGENTS)
    if headers:
        merged_headers.update(headers)

    return httpx.AsyncClient(
        headers=merged_headers,
        timeout=httpx.Timeout(timeout, connect=10.0),
        follow_redirects=True,
        http2=True,
    )


class BaseScraper(ABC):
    """Abstract base class for marketplace scrapers."""

    # Subclasses should set this to identify the source marketplace.
    source_name: str = "unknown"

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        """
        Args:
            http_client: An optional shared httpx.AsyncClient.  If not
                         provided, the scraper will create its own (but
                         callers are encouraged to share one client across
                         scrapers for connection pooling).
        """
        self._http_client = http_client
        self._owns_client = http_client is None

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
    # Abstract methods -- each site scraper must implement these
    # ------------------------------------------------------------------

    @abstractmethod
    async def search(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Search for listings matching *filters*.

        Returns a list of normalized listing dicts.
        """

    @abstractmethod
    def build_search_url(self, filters: dict[str, Any]) -> str:
        """Build the marketplace search URL from structured filters."""

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def fetch_page(self, url: str) -> str:
        """GET *url* and return the response body as a string.

        Retries up to MAX_RETRIES times on transient failures (network
        errors, 429, 5xx). Adds a small random delay between retries.

        Raises:
            httpx.HTTPStatusError: If the final attempt returns a non-2xx
                status that is not retryable.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self.http.get(url)

                # Retry on rate-limit or server errors
                if resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        "%s: HTTP %d on attempt %d for %s",
                        self.source_name,
                        resp.status_code,
                        attempt,
                        url,
                    )
                    last_exc = httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    if attempt < MAX_RETRIES:
                        delay = RETRY_BACKOFF_BASE * attempt + random.uniform(0.5, 1.5)
                        await asyncio.sleep(delay)
                        continue
                    resp.raise_for_status()

                resp.raise_for_status()
                return resp.text

            except httpx.HTTPStatusError:
                raise
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                logger.warning(
                    "%s: request error on attempt %d for %s: %s",
                    self.source_name,
                    attempt,
                    url,
                    exc,
                )
                last_exc = exc
                if attempt < MAX_RETRIES:
                    delay = RETRY_BACKOFF_BASE * attempt + random.uniform(0.5, 1.5)
                    await asyncio.sleep(delay)

        # All retries exhausted
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # LLM-based extraction (delegates to Gemini snapshot parser)
    # ------------------------------------------------------------------

    async def extract_listings_with_llm(
        self,
        html: str,
        page_url: str = "",
    ) -> list[dict[str, Any]]:
        """Send raw HTML (or text) to Gemini for structured listing extraction.

        This is the fallback when BeautifulSoup parsing alone cannot
        reliably extract listings (e.g. heavily JS-templated pages).

        Args:
            html: The page HTML or extracted text to parse.
            page_url: The URL of the page (for context).

        Returns:
            List of raw listing dicts extracted by the LLM.
        """
        if not html or not html.strip():
            logger.warning("Empty HTML -- nothing to extract")
            return []

        from app.services.llm.snapshot_parser import parse_snapshot_to_listings

        try:
            listings = await parse_snapshot_to_listings(html, self.source_name)
            logger.info(
                "LLM extracted %d listings from %s (%d chars)",
                len(listings),
                self.source_name,
                len(html),
            )
            return listings

        except Exception as exc:
            logger.error("LLM extraction failed for %s: %s", self.source_name, exc)
            return []

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def normalize_listing(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw listing dict into the standard schema.

        Ensures all expected fields exist, generates a unique ID,
        and tags the listing with the source marketplace name.
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
            mileage = mileage.lower().replace("mi", "").replace(",", "").replace("miles", "").strip()
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
