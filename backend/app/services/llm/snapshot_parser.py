"""
Snapshot Parser -- extracts structured listing data from browser snapshot text.

Uses Gemini structured output to parse the messy, AI-readable text dump from
a browser snapshot into clean listing objects.
"""

import logging
from typing import Optional

from app.config import get_settings
from app.services.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SNAPSHOT_PARSER_SYSTEM_PROMPT = """\
You are a data extraction specialist for CarFINDa. Your job is to parse the raw
text content of a car marketplace webpage into structured vehicle listing data.

## Input

You will receive the text content of a browser snapshot from a car marketplace
(e.g. Autotrader, Cars.com, CarGurus, Facebook Marketplace, Craigslist, dealer
websites). This text is often messy, with navigation elements, ads, and other
non-listing content mixed in.

## Your Task

Extract EVERY vehicle listing you can find in the text. For each listing, extract
as many fields as possible from the available data.

## Field Extraction Rules

1. **VIN**: 17-character alphanumeric string. May appear as "VIN: XXXXX" or in URLs.
   Leave empty string if not found.
2. **Year**: 4-digit number (1990-2026). Required -- skip listings without a year.
3. **Make**: Vehicle manufacturer (Toyota, Honda, Ford, etc.). Normalise to proper case.
4. **Model**: Vehicle model name (Camry, Civic, F-150, etc.). Normalise to proper case.
5. **Trim**: Sub-model designation (SE, EX, XLT, Limited, etc.). Empty string if not found.
6. **Price**: Numeric value in USD. Strip "$", commas, and "K" suffixes (e.g. "$18.5K" = 18500).
   Use 0 if price says "Call for price" or is not listed.
7. **Mileage**: Numeric value. Strip commas and "mi"/"miles" suffixes.
   Use 0 if not found.
8. **Source URL**: The listing's detail page URL if visible in the snapshot. Empty string if not found.
9. **Image URLs**: Any image URLs found for this listing. Empty array if none.
10. **Exterior Color**: Normalise to standard names (Black, White, Silver, Red, Blue, etc.).
    Empty string if not found.
11. **Interior Color**: Same normalisation. Empty string if not found.
12. **Location**: City, State format if available. Empty string if not found.
13. **Fuel Type**: gasoline, diesel, hybrid, plug-in hybrid, electric. Empty string if not found.
14. **Transmission**: automatic, manual, CVT. Empty string if not found.
15. **Drivetrain**: FWD, RWD, AWD, 4WD. Empty string if not found.
16. **Dealer Name**: Name of the selling dealer or "Private Seller". Empty string if not found.

## Important

- Do NOT fabricate data. If a field is not present in the text, use the default (empty string, 0, or empty array).
- If you see a price range, use the lower price.
- Skip entries that are clearly not vehicle listings (ads, navigation, headers).
- If the same listing appears twice (e.g. featured + regular), include it only once.
- Process ALL listings on the page, not just the first few.
"""

# ---------------------------------------------------------------------------
# Response schema for structured output
# ---------------------------------------------------------------------------

LISTING_SCHEMA = {
    "type": "object",
    "properties": {
        "listings": {
            "type": "array",
            "description": "Array of extracted vehicle listings.",
            "items": {
                "type": "object",
                "properties": {
                    "vin": {
                        "type": "string",
                        "description": "17-character VIN if found, empty string otherwise.",
                    },
                    "year": {
                        "type": "number",
                        "description": "Model year (e.g. 2021).",
                    },
                    "make": {
                        "type": "string",
                        "description": "Vehicle manufacturer (e.g. Toyota).",
                    },
                    "model": {
                        "type": "string",
                        "description": "Vehicle model (e.g. Camry).",
                    },
                    "trim": {
                        "type": "string",
                        "description": "Trim level (e.g. SE, XLE). Empty string if unknown.",
                    },
                    "price": {
                        "type": "number",
                        "description": "Listed price in USD. 0 if not available.",
                    },
                    "mileage": {
                        "type": "number",
                        "description": "Odometer reading. 0 if not available.",
                    },
                    "source_url": {
                        "type": "string",
                        "description": "URL to the listing detail page.",
                    },
                    "image_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Image URLs for this listing.",
                    },
                    "exterior_color": {
                        "type": "string",
                        "description": "Exterior colour. Empty string if unknown.",
                    },
                    "interior_color": {
                        "type": "string",
                        "description": "Interior colour. Empty string if unknown.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Dealer/seller location as 'City, ST'.",
                    },
                    "fuel_type": {
                        "type": "string",
                        "description": "Fuel type: gasoline, diesel, hybrid, plug-in hybrid, electric.",
                    },
                    "transmission": {
                        "type": "string",
                        "description": "Transmission type: automatic, manual, CVT.",
                    },
                    "drivetrain": {
                        "type": "string",
                        "description": "Drivetrain: FWD, RWD, AWD, 4WD.",
                    },
                    "dealer_name": {
                        "type": "string",
                        "description": "Selling dealer name or 'Private Seller'.",
                    },
                },
                "required": ["year", "make", "model", "price"],
            },
        },
    },
    "required": ["listings"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_snapshot_to_listings(
    snapshot_text: str,
    source_name: str,
) -> list[dict]:
    """Parse an AI-readable browser snapshot into structured listing data.

    Takes the raw text output from a browser snapshot tool (e.g. Stagehand's
    ``browser.snapshot``) and uses Gemini to extract every vehicle listing
    into a clean, structured format.

    Args:
        snapshot_text: The full text content of the browser page snapshot.
        source_name: Name of the source marketplace (e.g. "autotrader",
            "cargurus", "cars.com") for tagging extracted listings.

    Returns:
        A list of dicts, each representing one vehicle listing with fields:
        vin, year, make, model, trim, price, mileage, source_url, image_urls,
        exterior_color, interior_color, location, fuel_type, transmission,
        drivetrain, dealer_name, source_name.
    """
    settings = get_settings()
    gemini = GeminiClient(api_key=settings.GEMINI_API_KEY)

    # Truncate very long snapshots to stay within token limits.
    # Gemini 2.5 Flash has a large context window, but we still want to be
    # reasonable. Most marketplace pages with 20-25 listings fit well within 50K chars.
    max_chars = 100_000
    if len(snapshot_text) > max_chars:
        logger.warning(
            "Snapshot text truncated from %d to %d characters",
            len(snapshot_text),
            max_chars,
        )
        snapshot_text = snapshot_text[:max_chars]

    prompt = (
        f"Source marketplace: {source_name}\n\n"
        f"--- BEGIN PAGE SNAPSHOT ---\n"
        f"{snapshot_text}\n"
        f"--- END PAGE SNAPSHOT ---\n\n"
        f"Extract all vehicle listings from this page snapshot."
    )

    logger.info(
        "Parsing snapshot from %s (%d chars)",
        source_name,
        len(snapshot_text),
    )

    result = await gemini.generate_structured(
        prompt=prompt,
        system_instruction=SNAPSHOT_PARSER_SYSTEM_PROMPT,
        response_schema=LISTING_SCHEMA,
        temperature=0.1,  # Low temperature for factual extraction
    )

    listings = result.get("listings", [])

    # Tag each listing with the source name
    for listing in listings:
        listing["source_name"] = source_name

        # Clean up zero-value sentinels
        if listing.get("price") == 0:
            listing["price"] = None
        if listing.get("mileage") == 0:
            listing["mileage"] = None

    logger.info(
        "Extracted %d listings from %s snapshot",
        len(listings),
        source_name,
    )

    return listings
