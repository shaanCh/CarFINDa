"""
Facebook Marketplace Scraper — Scrapes listings and automates seller outreach.

FLOW:
1. User logs into Facebook once via the sidecar's persistent browser profile
   (the profile persists cookies, so they stay logged in).
2. Agent searches Marketplace with filters (year, price, mileage, etc.).
3. Agent extracts listings from the search results snapshot.
4. For approved listings, agent DMs sellers with personalized messages.
5. Agent monitors inbox for seller replies.

This is the killer differentiator — no other car search tool does automated
seller outreach on Facebook Marketplace.

Uses the BrowserClient (sidecar wrapper) for all browser automation. Each
interaction follows: navigate -> snapshot -> parse -> act.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote_plus, urlencode

from app.config import get_settings
from app.services.llm.gemini_client import GeminiClient
from app.services.scraping.browser_client import BrowserClient

logger = logging.getLogger(__name__)

# Marketplace vehicles category base URL
FB_MARKETPLACE_VEHICLES_URL = "https://www.facebook.com/marketplace/category/vehicles"
FB_MARKETPLACE_BASE_URL = "https://www.facebook.com/marketplace"
FB_MESSENGER_URL = "https://www.facebook.com/messages/t/"
FB_LOGIN_URL = "https://www.facebook.com/login"

# Gemini prompt for extracting listings from a Marketplace snapshot
FB_LISTING_EXTRACTION_PROMPT = """You are a data extraction assistant for a car shopping platform.
You will be given an AI-readable snapshot of a Facebook Marketplace vehicle search results page.
Extract every vehicle listing you can find from the snapshot text.

For each listing, extract these fields (use null if not found):
- title: The full listing title (e.g. "2019 Toyota Camry SE")
- year: Model year (integer)
- make: Manufacturer (e.g. Toyota, Honda, Ford)
- model: Model name (e.g. Camry, Civic, F-150)
- price: Listed price in dollars (number, no $ sign)
- location: City/area shown for the listing
- mileage: Mileage if shown (integer, miles)
- listing_url: The URL/link to the listing detail page (look for /marketplace/item/ links)
- seller_name: Seller's name if visible
- image_urls: Array of image URLs if visible

Parse the title to extract year, make, and model if they are not separate fields.
Return a JSON array of listing objects. If no listings are found, return an empty array [].
Do NOT include any markdown formatting, code fences, or explanatory text — return ONLY the JSON array."""

# Prompt for extracting full listing details from a single listing page
FB_DETAIL_EXTRACTION_PROMPT = """You are a data extraction assistant. You are given an AI-readable
snapshot of a single Facebook Marketplace vehicle listing page. Extract all available information.

Return a JSON object with these fields (use null if not found):
- title: Full listing title
- year: Model year (integer)
- make: Manufacturer
- model: Model name
- trim: Trim level if mentioned
- price: Price in dollars (number)
- mileage: Mileage (integer)
- location: Location/city
- description: Full listing description text
- seller_name: Seller's display name
- seller_profile_url: Link to seller's profile
- listed_date: When it was listed (text as shown)
- num_saves: Number of saves/likes if shown
- condition: Vehicle condition if mentioned
- transmission: Transmission type if mentioned
- fuel_type: Fuel type if mentioned
- exterior_color: Color if mentioned
- body_type: Body style if mentioned
- image_urls: Array of image URLs
- has_message_button: true if there's a "Message Seller" or "Is this still available?" button
- message_button_ref: The element ref for the message button if visible

Return ONLY the JSON object, no markdown or extra text."""

# Prompt for parsing inbox/messenger conversations
FB_INBOX_EXTRACTION_PROMPT = """You are a data extraction assistant. You are given an AI-readable
snapshot of Facebook Messenger showing recent conversations.

Identify conversations that appear to be related to Facebook Marketplace listings (typically
contain messages about vehicles, prices, availability, or were started from a Marketplace listing).

For each relevant conversation, extract:
- seller_name: The other person's display name
- listing_title: The vehicle listing title if visible in the conversation
- last_message: The most recent message text
- timestamp: When the last message was sent (text as shown)
- conversation_url: The URL for this conversation if visible
- is_unread: Whether the conversation appears unread/has new messages

Return a JSON array of conversation objects. If no Marketplace conversations are found, return [].
Do NOT include any markdown formatting — return ONLY the JSON array."""


class FacebookMarketplaceScraper:
    """Scrapes Facebook Marketplace and automates seller outreach.

    Uses a dedicated browser profile ('carfinda-fb') that persists Facebook
    cookies separately from the main scraping profile. This means the user
    logs in once and stays logged in across sessions.
    """

    def __init__(
        self,
        browser_client: BrowserClient,
        profile: str = "carfinda-fb",
    ):
        """Initialize the Facebook Marketplace scraper.

        Args:
            browser_client: The BrowserClient instance for sidecar communication.
            profile:        Browser profile name. Using a separate profile for
                            Facebook keeps cookies isolated from other scrapers.
        """
        self.browser = browser_client
        self.profile = profile
        self._gemini: Optional[GeminiClient] = None

    def _get_gemini(self) -> GeminiClient:
        """Lazy-initialize the Gemini client."""
        if self._gemini is None:
            settings = get_settings()
            self._gemini = GeminiClient(api_key=settings.GEMINI_API_KEY)
        return self._gemini

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> None:
        """Ensure the browser session is started for this profile."""
        await self.browser.start_session(self.profile)

    # ------------------------------------------------------------------
    # Login Status
    # ------------------------------------------------------------------

    async def check_login_status(self) -> bool:
        """Check if the user is logged into Facebook in this browser profile.

        Navigates to Facebook and checks whether the page shows a logged-in
        state (e.g., profile menu, notifications icon) vs a login form.

        Returns:
            True if logged in, False if not.
        """
        await self._ensure_session()

        try:
            result = await self.browser.navigate(
                self.profile,
                "https://www.facebook.com/",
            )
            snapshot = result.get("snapshot", "")

            # Heuristics: If the snapshot contains login form elements, the user
            # is not logged in. If it contains typical logged-in elements (like
            # a profile link, notifications, messenger icon), they are logged in.
            login_indicators = ["log in", "log into", "create new account", "sign up"]
            logged_in_indicators = [
                "marketplace", "messenger", "notifications",
                "what's on your mind", "create post",
            ]

            snapshot_lower = snapshot.lower()

            login_score = sum(1 for ind in login_indicators if ind in snapshot_lower)
            logged_in_score = sum(1 for ind in logged_in_indicators if ind in snapshot_lower)

            is_logged_in = logged_in_score > login_score
            logger.info(
                "Facebook login check: logged_in=%s (login_indicators=%d, logged_in_indicators=%d)",
                is_logged_in, login_score, logged_in_score,
            )
            return is_logged_in

        except Exception as exc:
            logger.error("Failed to check Facebook login status: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _build_search_url(self, filters: dict) -> str:
        """Build the Facebook Marketplace vehicles search URL from filters.

        Supported filter keys:
            - query (str): Text search query (e.g., "Toyota Camry")
            - min_price (int): Minimum price
            - max_price (int): Maximum price
            - min_year (int): Minimum model year
            - max_year (int): Maximum model year
            - max_mileage (int): Maximum mileage
            - make (str): Vehicle make
            - model (str): Vehicle model
            - location (str): Location for search (city/zip)
            - radius (int): Search radius in miles

        Args:
            filters: Dict of search filters.

        Returns:
            The fully constructed Marketplace search URL.
        """
        params: dict[str, str] = {}

        if filters.get("min_price") is not None:
            params["minPrice"] = str(int(filters["min_price"]))
        if filters.get("max_price") is not None:
            params["maxPrice"] = str(int(filters["max_price"]))
        if filters.get("max_mileage") is not None:
            params["maxMileage"] = str(int(filters["max_mileage"]))
        if filters.get("min_year") is not None:
            params["minYear"] = str(int(filters["min_year"]))
        if filters.get("max_year") is not None:
            params["maxYear"] = str(int(filters["max_year"]))

        # "exact=false" broadens results to include similar vehicles
        params["exact"] = "false"

        # Build query string from make/model if provided
        query_parts = []
        if filters.get("make"):
            query_parts.append(filters["make"])
        if filters.get("model"):
            query_parts.append(filters["model"])
        if filters.get("query"):
            query_parts.append(filters["query"])

        base_url = FB_MARKETPLACE_VEHICLES_URL
        if query_parts:
            params["query"] = " ".join(query_parts)

        if params:
            return f"{base_url}?{urlencode(params)}"
        return base_url

    async def search_marketplace(self, filters: dict) -> list[dict]:
        """Search Facebook Marketplace with filters.

        Navigates to the Marketplace vehicles URL with search parameters,
        parses results from the snapshot, and paginates by scrolling to load
        more results.

        Args:
            filters: Search filter dict. See _build_search_url for supported keys.

        Returns:
            List of listing dicts with keys: title, year, make, model, price,
            location, mileage, listing_url, seller_name, image_urls.
        """
        await self._ensure_session()

        url = self._build_search_url(filters)
        logger.info("Searching Facebook Marketplace: %s", url)

        # Navigate to search results
        result = await self.browser.navigate(self.profile, url)
        snapshot = result.get("snapshot", "")

        if not snapshot.strip():
            logger.warning("Empty snapshot from Marketplace search")
            return []

        all_listings: list[dict] = []
        seen_titles: set[str] = set()

        # Parse first page of results
        page_listings = await self._extract_listings_from_snapshot(snapshot, url)
        for listing in page_listings:
            title_key = f"{listing.get('title', '')}_{listing.get('price', '')}"
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                all_listings.append(listing)

        # Scroll to load more results (Facebook uses infinite scroll)
        max_scrolls = filters.get("max_pages", 3)
        for scroll_idx in range(max_scrolls):
            previous_count = len(all_listings)

            # Scroll down to trigger lazy loading
            await self.browser.act(self.profile, "scroll", direction="down")
            # Wait for new content to load
            await asyncio.sleep(2.0)

            # Get updated snapshot
            snapshot = await self.browser.snapshot(self.profile)
            if not snapshot.strip():
                break

            page_listings = await self._extract_listings_from_snapshot(snapshot, url)
            for listing in page_listings:
                title_key = f"{listing.get('title', '')}_{listing.get('price', '')}"
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    all_listings.append(listing)

            # If no new listings were found, stop scrolling
            if len(all_listings) == previous_count:
                logger.info(
                    "No new listings after scroll %d, stopping pagination",
                    scroll_idx + 1,
                )
                break

            logger.info(
                "Scroll %d: %d new listings (total: %d)",
                scroll_idx + 1, len(all_listings) - previous_count, len(all_listings),
            )

        # Normalize listings
        normalized = [self._normalize_listing(l) for l in all_listings]
        logger.info("Facebook Marketplace search returned %d listings", len(normalized))
        return normalized

    async def _extract_listings_from_snapshot(
        self,
        snapshot: str,
        page_url: str = "",
    ) -> list[dict]:
        """Extract listings from a Marketplace search results snapshot using Gemini.

        Args:
            snapshot: The AI-readable page snapshot text.
            page_url: The URL of the page (for context).

        Returns:
            List of raw listing dicts from the snapshot.
        """
        max_chars = 80_000
        if len(snapshot) > max_chars:
            snapshot = snapshot[:max_chars] + "\n... (truncated)"

        prompt = f"Page URL: {page_url}\n\n--- SNAPSHOT START ---\n{snapshot}\n--- SNAPSHOT END ---"

        schema = {
            "type": "object",
            "properties": {
                "listings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "year": {"type": "number"},
                            "make": {"type": "string"},
                            "model": {"type": "string"},
                            "price": {"type": "number"},
                            "location": {"type": "string"},
                            "mileage": {"type": "number"},
                            "listing_url": {"type": "string"},
                            "seller_name": {"type": "string"},
                            "image_urls": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["title", "price"],
                    },
                },
            },
            "required": ["listings"],
        }

        try:
            gemini = self._get_gemini()
            result = await gemini.generate_structured(
                prompt=prompt,
                system_instruction=FB_LISTING_EXTRACTION_PROMPT,
                response_schema=schema,
                temperature=0.1,
            )
            listings = result.get("listings", [])
            logger.info("Extracted %d listings from FB snapshot (%d chars)", len(listings), len(snapshot))
            return listings

        except Exception as exc:
            logger.error("FB listing extraction failed: %s", exc)
            return []

    def _normalize_listing(self, raw: dict) -> dict:
        """Normalize a raw Facebook listing into a standard format.

        Parses the title to extract year/make/model if not already present,
        cleans up price and mileage values.

        Args:
            raw: Raw listing dict from Gemini extraction.

        Returns:
            Normalized listing dict.
        """
        # Parse title for year/make/model if not explicitly set
        title = raw.get("title", "")
        year = raw.get("year")
        make = raw.get("make")
        model = raw.get("model")

        if title and (not year or not make or not model):
            # Try to parse "2019 Toyota Camry SE" pattern from title
            title_match = re.match(r"(\d{4})\s+(\w+)\s+(.+)", title.strip())
            if title_match:
                if not year:
                    try:
                        year = int(title_match.group(1))
                    except ValueError:
                        pass
                if not make:
                    make = title_match.group(2)
                if not model:
                    model = title_match.group(3).strip()

        # Clean price
        price = raw.get("price")
        if isinstance(price, str):
            price = price.replace("$", "").replace(",", "").replace("Free", "0").strip()
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
            mileage = mileage.lower().replace("mi", "").replace(",", "").replace("miles", "").replace("k", "000").strip()
            try:
                mileage = int(float(mileage))
            except ValueError:
                mileage = None
        elif isinstance(mileage, (int, float)):
            mileage = int(mileage)
        else:
            mileage = None

        # Clean year
        if isinstance(year, str):
            try:
                year = int(year)
            except ValueError:
                year = None
        elif isinstance(year, (int, float)):
            year = int(year)

        # Ensure listing_url is absolute
        listing_url = raw.get("listing_url", "")
        if listing_url and not listing_url.startswith("http"):
            listing_url = f"https://www.facebook.com{listing_url}"

        return {
            "id": str(uuid.uuid4()),
            "title": title,
            "year": year,
            "make": make or None,
            "model": model or None,
            "price": price,
            "mileage": mileage,
            "location": raw.get("location") or None,
            "listing_url": listing_url or None,
            "seller_name": raw.get("seller_name") or None,
            "image_urls": raw.get("image_urls") or [],
            "source_name": "facebook_marketplace",
            "source_url": listing_url or None,
        }

    # ------------------------------------------------------------------
    # Listing Details
    # ------------------------------------------------------------------

    async def get_listing_details(self, listing_url: str) -> dict:
        """Navigate to a specific listing and extract full details.

        Facebook Marketplace listings contain: description, seller profile,
        vehicle details, listed date, number of saves, etc.

        Args:
            listing_url: Full URL to the Facebook Marketplace listing.

        Returns:
            Dict with all extracted listing details.
        """
        await self._ensure_session()

        logger.info("Fetching listing details: %s", listing_url)

        try:
            result = await self.browser.navigate(self.profile, listing_url)
            snapshot = result.get("snapshot", "")

            if not snapshot.strip():
                logger.warning("Empty snapshot for listing: %s", listing_url)
                return {"error": "Empty page snapshot", "listing_url": listing_url}

            # Extract details using Gemini
            max_chars = 80_000
            if len(snapshot) > max_chars:
                snapshot = snapshot[:max_chars] + "\n... (truncated)"

            prompt = (
                f"Listing URL: {listing_url}\n\n"
                f"--- SNAPSHOT START ---\n{snapshot}\n--- SNAPSHOT END ---"
            )

            detail_schema = {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "year": {"type": "number"},
                    "make": {"type": "string"},
                    "model": {"type": "string"},
                    "trim": {"type": "string"},
                    "price": {"type": "number"},
                    "mileage": {"type": "number"},
                    "location": {"type": "string"},
                    "description": {"type": "string"},
                    "seller_name": {"type": "string"},
                    "seller_profile_url": {"type": "string"},
                    "listed_date": {"type": "string"},
                    "condition": {"type": "string"},
                    "transmission": {"type": "string"},
                    "fuel_type": {"type": "string"},
                    "exterior_color": {"type": "string"},
                    "body_type": {"type": "string"},
                    "image_urls": {"type": "array", "items": {"type": "string"}},
                    "has_message_button": {"type": "boolean"},
                    "message_button_ref": {"type": "string"},
                },
                "required": ["title", "price"],
            }

            gemini = self._get_gemini()
            details = await gemini.generate_structured(
                prompt=prompt,
                system_instruction=FB_DETAIL_EXTRACTION_PROMPT,
                response_schema=detail_schema,
                temperature=0.1,
            )
            details["listing_url"] = listing_url
            details["source_name"] = "facebook_marketplace"
            details["fetched_at"] = datetime.now(timezone.utc).isoformat()

            logger.info("Extracted details for listing: %s", listing_url)
            return details

        except json.JSONDecodeError as exc:
            logger.error("Failed to parse listing details: %s", exc)
            return {"error": f"Parse error: {exc}", "listing_url": listing_url}
        except Exception as exc:
            logger.error("Failed to fetch listing details: %s", exc)
            return {"error": str(exc), "listing_url": listing_url}

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_message(self, listing_url: str, message: str) -> dict:
        """Send a DM to the seller of a listing.

        Flow:
        1. Navigate to the listing page.
        2. Take a snapshot to find the "Message Seller" or "Is this still available?" button.
        3. Click the message button.
        4. Type the personalized message.
        5. Send it (press Enter or click Send).
        6. Take a verification snapshot to confirm it was sent.

        Args:
            listing_url: URL of the Facebook Marketplace listing.
            message:     The message text to send to the seller.

        Returns:
            Dict with keys: success (bool), conversation_url (str), error (str).
        """
        await self._ensure_session()

        logger.info("Sending message for listing: %s", listing_url)

        try:
            # Step 1: Navigate to the listing
            result = await self.browser.navigate(self.profile, listing_url)
            snapshot = result.get("snapshot", "")

            if not snapshot.strip():
                return {
                    "success": False,
                    "conversation_url": None,
                    "error": "Empty listing page snapshot",
                }

            # Step 2: Find the message/contact button in the snapshot
            # Look for common button refs: "Message Seller", "Is this still available?",
            # "Send Message", "Contact Seller", "Ask about availability"
            message_button_ref = self._find_message_button_ref(snapshot)

            if not message_button_ref:
                return {
                    "success": False,
                    "conversation_url": None,
                    "error": "Could not find message/contact button on listing page",
                }

            # Step 3: Click the message button
            click_result = await self.browser.act(
                self.profile, "click", ref=message_button_ref,
            )
            await asyncio.sleep(2.0)  # Wait for message dialog to open

            # Step 4: Take snapshot to find the message input field
            snapshot = await self.browser.snapshot(self.profile)
            input_ref = self._find_message_input_ref(snapshot)

            if not input_ref:
                # Sometimes clicking the button navigates to Messenger directly
                # Try to find a compose box in the current page
                await asyncio.sleep(2.0)
                snapshot = await self.browser.snapshot(self.profile)
                input_ref = self._find_message_input_ref(snapshot)

            if not input_ref:
                return {
                    "success": False,
                    "conversation_url": None,
                    "error": "Could not find message input field after clicking contact button",
                }

            # Step 5: Clear any pre-filled text (like "Is this still available?")
            # and type our custom message
            await self.browser.act(
                self.profile, "click", ref=input_ref,
            )
            # Select all existing text and replace it
            await self.browser.act(
                self.profile, "press", key="Meta+a",
            )
            await asyncio.sleep(0.3)

            # Type the message
            await self.browser.act(
                self.profile, "type", ref=input_ref, text=message,
            )
            await asyncio.sleep(0.5)

            # Step 6: Send the message (press Enter)
            await self.browser.act(
                self.profile, "press", key="Enter",
            )
            await asyncio.sleep(2.0)

            # Step 7: Verify the message was sent
            verification_snapshot = await self.browser.snapshot(self.profile)

            # Try to determine the conversation URL from the current page
            # After sending, Facebook usually shows the Messenger conversation
            tabs = await self.browser.list_tabs(self.profile)
            conversation_url = None
            for tab in tabs:
                tab_url = tab.get("url", "")
                if "messages" in tab_url or "messenger" in tab_url:
                    conversation_url = tab_url
                    break

            # Check if the message appears in the verification snapshot
            message_sent = message[:50].lower() in verification_snapshot.lower()

            if message_sent or "sent" in verification_snapshot.lower():
                logger.info("Message sent successfully for listing: %s", listing_url)
                return {
                    "success": True,
                    "conversation_url": conversation_url,
                    "error": None,
                }
            else:
                logger.warning(
                    "Message may not have been sent for listing: %s", listing_url,
                )
                return {
                    "success": True,  # Optimistic — hard to confirm 100%
                    "conversation_url": conversation_url,
                    "error": "Could not confirm message delivery from snapshot",
                }

        except Exception as exc:
            logger.error("Failed to send message for %s: %s", listing_url, exc)
            return {
                "success": False,
                "conversation_url": None,
                "error": str(exc),
            }

    def _find_message_button_ref(self, snapshot: str) -> Optional[str]:
        """Find the element ref for the message/contact button in a snapshot.

        Searches for common Facebook Marketplace contact button labels.

        Args:
            snapshot: AI-readable page snapshot text.

        Returns:
            Element ref string (e.g. "e12") or None if not found.
        """
        # Common button labels on FB Marketplace listing pages
        button_patterns = [
            r'(\be\d+\b)\s*.*?(?:message\s*seller)',
            r'(\be\d+\b)\s*.*?(?:is\s*this\s*still\s*available)',
            r'(\be\d+\b)\s*.*?(?:send\s*message)',
            r'(\be\d+\b)\s*.*?(?:contact\s*seller)',
            r'(\be\d+\b)\s*.*?(?:ask\s*about\s*availability)',
            r'(\be\d+\b)\s*.*?(?:send\s*seller\s*a\s*message)',
            # Reverse pattern: label then ref
            r'(?:message\s*seller).*?(\be\d+\b)',
            r'(?:is\s*this\s*still\s*available).*?(\be\d+\b)',
            r'(?:send\s*message).*?(\be\d+\b)',
            r'(?:contact\s*seller).*?(\be\d+\b)',
        ]

        snapshot_lower = snapshot.lower()
        for pattern in button_patterns:
            match = re.search(pattern, snapshot_lower)
            if match:
                ref = match.group(1)
                logger.debug("Found message button ref: %s", ref)
                return ref

        # Fallback: look for any button-like element near messaging keywords
        # Snapshot format typically has refs like [e5] or (e5) near element text
        ref_pattern = r'\[?(e\d+)\]?\s*[:\-]?\s*(?:button|link)\s*.*?(?:message|contact|available)'
        match = re.search(ref_pattern, snapshot_lower)
        if match:
            return match.group(1)

        logger.warning("Could not find message button ref in snapshot")
        return None

    def _find_message_input_ref(self, snapshot: str) -> Optional[str]:
        """Find the element ref for the message text input in a snapshot.

        Args:
            snapshot: AI-readable page snapshot text.

        Returns:
            Element ref string or None if not found.
        """
        # Look for text input / textarea / compose box refs
        input_patterns = [
            r'(\be\d+\b)\s*.*?(?:type\s*a\s*message)',
            r'(\be\d+\b)\s*.*?(?:write\s*a\s*message)',
            r'(\be\d+\b)\s*.*?(?:message\s*input)',
            r'(\be\d+\b)\s*.*?(?:compose)',
            r'(\be\d+\b)\s*.*?(?:textbox|textarea)',
            r'(?:type\s*a\s*message).*?(\be\d+\b)',
            r'(?:write\s*a\s*message).*?(\be\d+\b)',
            r'(?:aa\s*placeholder).*?(\be\d+\b)',  # FB Messenger "Aa" placeholder
            # Look for contenteditable or input refs
            r'(\be\d+\b)\s*[:\-]?\s*(?:input|textbox|contenteditable)',
        ]

        snapshot_lower = snapshot.lower()
        for pattern in input_patterns:
            match = re.search(pattern, snapshot_lower)
            if match:
                ref = match.group(1)
                logger.debug("Found message input ref: %s", ref)
                return ref

        logger.warning("Could not find message input ref in snapshot")
        return None

    # ------------------------------------------------------------------
    # Inbox / Reply Monitoring
    # ------------------------------------------------------------------

    async def check_inbox(self, limit: int = 20) -> list[dict]:
        """Check Facebook Messenger inbox for replies from sellers.

        Navigates to Messenger, scans recent conversations for replies
        related to Marketplace listings.

        Args:
            limit: Maximum number of conversations to check.

        Returns:
            List of dicts: [{seller_name, listing_title, last_message,
                             timestamp, conversation_url}]
        """
        await self._ensure_session()

        logger.info("Checking Facebook Messenger inbox (limit=%d)", limit)

        try:
            # Navigate to Messenger
            result = await self.browser.navigate(
                self.profile,
                "https://www.facebook.com/messages/",
            )
            snapshot = result.get("snapshot", "")

            if not snapshot.strip():
                logger.warning("Empty snapshot from Messenger inbox")
                return []

            # Wait for inbox to fully load
            await asyncio.sleep(2.0)
            snapshot = await self.browser.snapshot(self.profile)

            # Extract conversations using Gemini
            max_chars = 80_000
            if len(snapshot) > max_chars:
                snapshot = snapshot[:max_chars] + "\n... (truncated)"

            prompt = (
                f"Inbox URL: https://www.facebook.com/messages/\n\n"
                f"--- SNAPSHOT START ---\n{snapshot}\n--- SNAPSHOT END ---"
            )

            inbox_schema = {
                "type": "object",
                "properties": {
                    "conversations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "seller_name": {"type": "string"},
                                "listing_title": {"type": "string"},
                                "last_message": {"type": "string"},
                                "timestamp": {"type": "string"},
                                "conversation_url": {"type": "string"},
                                "is_unread": {"type": "boolean"},
                            },
                            "required": ["seller_name", "last_message"],
                        },
                    },
                },
                "required": ["conversations"],
            }

            gemini = self._get_gemini()
            result = await gemini.generate_structured(
                prompt=prompt,
                system_instruction=FB_INBOX_EXTRACTION_PROMPT,
                response_schema=inbox_schema,
                temperature=0.1,
            )

            conversations = result.get("conversations", [])

            # Limit results
            conversations = conversations[:limit]
            logger.info(
                "Found %d Marketplace-related conversations in inbox",
                len(conversations),
            )
            return conversations

        except json.JSONDecodeError as exc:
            logger.error("Failed to parse inbox extraction: %s", exc)
            return []
        except Exception as exc:
            logger.error("Failed to check Messenger inbox: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Follow-up Messages
    # ------------------------------------------------------------------

    async def send_followup(self, conversation_url: str, message: str) -> dict:
        """Send a follow-up message in an existing Messenger conversation.

        Args:
            conversation_url: URL of the Messenger conversation.
            message:          The follow-up message text.

        Returns:
            Dict with keys: success (bool), error (str or None).
        """
        await self._ensure_session()

        logger.info("Sending follow-up to: %s", conversation_url)

        try:
            # Navigate to the conversation
            result = await self.browser.navigate(self.profile, conversation_url)
            await asyncio.sleep(2.0)

            # Get snapshot and find the message input
            snapshot = await self.browser.snapshot(self.profile)
            input_ref = self._find_message_input_ref(snapshot)

            if not input_ref:
                return {
                    "success": False,
                    "error": "Could not find message input in conversation",
                }

            # Click the input, type message, and send
            await self.browser.act(self.profile, "click", ref=input_ref)
            await asyncio.sleep(0.3)
            await self.browser.act(
                self.profile, "type", ref=input_ref, text=message,
            )
            await asyncio.sleep(0.5)
            await self.browser.act(self.profile, "press", key="Enter")
            await asyncio.sleep(2.0)

            # Verify
            verification_snapshot = await self.browser.snapshot(self.profile)
            message_sent = message[:50].lower() in verification_snapshot.lower()

            logger.info("Follow-up sent (verified=%s): %s", message_sent, conversation_url)
            return {
                "success": True,
                "error": None if message_sent else "Could not confirm delivery from snapshot",
            }

        except Exception as exc:
            logger.error("Failed to send follow-up to %s: %s", conversation_url, exc)
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Bulk Outreach
    # ------------------------------------------------------------------

    async def bulk_outreach(
        self,
        listings: list[dict],
        message_template: str,
        max_messages: int = 10,
        delay_seconds: int = 30,
    ) -> list[dict]:
        """Send personalized messages to multiple sellers.

        For each listing, generates a personalized message from the template
        using listing data, navigates to the listing, sends the message, and
        waits between messages to avoid rate limiting.

        Template placeholders:
            {make}, {model}, {year}, {price}, {offer_price}, {title},
            {seller_name}, {location}, {mileage}

        Args:
            listings:        List of listing dicts to contact.
            message_template: Message template with {placeholder} variables.
            max_messages:    Safety limit on number of messages to send.
            delay_seconds:   Seconds to wait between messages (rate limit protection).

        Returns:
            List of result dicts: [{listing_url, seller_name, success, error}]
        """
        await self._ensure_session()

        results: list[dict] = []
        messages_sent = 0

        # Cap at the safety limit
        listings_to_contact = listings[:max_messages]
        logger.info(
            "Starting bulk outreach: %d listings (max=%d, delay=%ds)",
            len(listings_to_contact), max_messages, delay_seconds,
        )

        for i, listing in enumerate(listings_to_contact):
            listing_url = listing.get("listing_url") or listing.get("source_url")
            if not listing_url:
                results.append({
                    "listing_url": None,
                    "seller_name": listing.get("seller_name"),
                    "success": False,
                    "error": "No listing URL available",
                })
                continue

            # Generate personalized message from template
            personalized_message = self._personalize_message(message_template, listing)

            # Send the message
            send_result = await self.send_message(listing_url, personalized_message)

            results.append({
                "listing_url": listing_url,
                "seller_name": listing.get("seller_name"),
                "success": send_result["success"],
                "conversation_url": send_result.get("conversation_url"),
                "error": send_result.get("error"),
            })

            if send_result["success"]:
                messages_sent += 1

            logger.info(
                "Outreach %d/%d: %s -> %s",
                i + 1, len(listings_to_contact),
                listing_url,
                "sent" if send_result["success"] else f"failed: {send_result.get('error')}",
            )

            # Delay between messages to avoid rate limiting
            if i < len(listings_to_contact) - 1:
                logger.debug("Waiting %d seconds before next message...", delay_seconds)
                await asyncio.sleep(delay_seconds)

        logger.info(
            "Bulk outreach complete: %d/%d messages sent successfully",
            messages_sent, len(listings_to_contact),
        )
        return results

    def _personalize_message(self, template: str, listing: dict) -> str:
        """Fill in a message template with listing-specific data.

        Supported placeholders: {make}, {model}, {year}, {price}, {offer_price},
        {title}, {seller_name}, {location}, {mileage}.

        If a placeholder value is not available, it is replaced with a sensible
        default or removed.

        Args:
            template: Message template string with {placeholders}.
            listing:  Listing data dict.

        Returns:
            The personalized message string.
        """
        price = listing.get("price")
        # Calculate a default offer price (90% of listed price) if not provided
        offer_price = None
        if price and isinstance(price, (int, float)):
            offer_price = round(price * 0.9)

        replacements = {
            "make": str(listing.get("make") or "your vehicle"),
            "model": str(listing.get("model") or ""),
            "year": str(listing.get("year") or ""),
            "price": f"${price:,.0f}" if price else "the listed price",
            "offer_price": f"${offer_price:,.0f}" if offer_price else "a fair offer",
            "title": str(listing.get("title") or f"{listing.get('year', '')} {listing.get('make', '')} {listing.get('model', '')}").strip(),
            "seller_name": str(listing.get("seller_name") or "there"),
            "location": str(listing.get("location") or "your area"),
            "mileage": f"{listing.get('mileage'):,}" if listing.get("mileage") else "the listed mileage",
        }

        message = template
        for key, value in replacements.items():
            message = message.replace(f"{{{key}}}", value)

        return message
