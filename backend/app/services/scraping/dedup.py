"""
Listing Deduplication

Merges duplicate vehicle listings across multiple marketplace sources.
Primary dedup key: VIN (17-character Vehicle Identification Number).
Fallback fuzzy key: (year, make, model, mileage, price) tuple.

When duplicates are found the merged listing keeps:
  - The lowest price across all sources
  - All source URLs collected in a ``sources`` list
  - The first occurrence's metadata as the base (supplemented by later ones)
"""

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Valid VIN: 17 alphanumeric characters (excluding I, O, Q)
VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)


def _clean_vin(vin: Optional[str]) -> Optional[str]:
    """Normalize and validate a VIN string.

    Returns the uppercase VIN if valid, or None.
    """
    if not vin:
        return None
    vin = vin.strip().upper()
    if VIN_PATTERN.match(vin):
        return vin
    return None


def _fuzzy_key(listing: dict[str, Any]) -> Optional[tuple]:
    """Build a fuzzy dedup key from (year, make_lower, model_lower, mileage_bucket, price_bucket).

    Mileage is bucketed to nearest 1000 miles to handle slight discrepancies
    between sites. Price is bucketed to nearest $500.

    Returns None if essential fields are missing.
    """
    year = listing.get("year")
    make = listing.get("make")
    model = listing.get("model")

    if not year or not make or not model:
        return None

    # Bucket mileage to nearest 1000
    mileage = listing.get("mileage")
    if mileage is not None:
        mileage_bucket = round(mileage / 1000) * 1000
    else:
        mileage_bucket = None

    # Bucket price to nearest 500
    price = listing.get("price")
    if price is not None:
        price_bucket = round(price / 500) * 500
    else:
        price_bucket = None

    return (
        int(year),
        str(make).lower().strip(),
        str(model).lower().strip(),
        mileage_bucket,
        price_bucket,
    )


def _merge_listings(
    existing: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any]:
    """Merge *new* listing data into *existing*, keeping the better values.

    - Keeps the lower price.
    - Appends new source info to the ``sources`` list.
    - Fills in any None fields from the new listing.
    """
    merged = dict(existing)

    # Merge sources
    existing_sources = list(merged.get("sources") or [])
    new_sources = new.get("sources") or []

    # Avoid duplicate source entries (by URL)
    existing_urls = {s.get("url") for s in existing_sources if s.get("url")}
    for src in new_sources:
        if src.get("url") and src["url"] not in existing_urls:
            existing_sources.append(src)
            existing_urls.add(src["url"])
        elif not src.get("url"):
            existing_sources.append(src)

    merged["sources"] = existing_sources

    # Keep the lower price
    existing_price = merged.get("price")
    new_price = new.get("price")
    if new_price is not None:
        if existing_price is None or new_price < existing_price:
            merged["price"] = new_price
            # Also update the primary source_url to match the cheaper listing
            if new.get("source_url"):
                merged["source_url"] = new["source_url"]
                merged["source_name"] = new.get("source_name", merged.get("source_name"))

    # Fill in missing fields from the new listing
    fill_fields = [
        "vin", "trim", "mileage", "location", "exterior_color",
        "interior_color", "fuel_type", "transmission", "drivetrain",
        "deal_rating",
    ]
    for field in fill_fields:
        if merged.get(field) is None and new.get(field) is not None:
            merged[field] = new[field]

    # Merge image URLs (deduplicate)
    existing_images = set(merged.get("image_urls") or [])
    for img in new.get("image_urls") or []:
        if img not in existing_images:
            existing_images.add(img)
    merged["image_urls"] = list(existing_images)

    return merged


def deduplicate_listings(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate listings by VIN, with fuzzy fallback.

    When duplicate VINs are found, merges into one listing with the lowest
    price and all source URLs tracked in the ``sources`` list.

    For listings without a VIN, uses a fuzzy key based on
    (year, make, model, mileage, price) to detect likely duplicates.

    Args:
        listings: List of normalized listing dicts from multiple scrapers.

    Returns:
        Deduplicated list of listings.
    """
    # Index by VIN
    by_vin: dict[str, dict[str, Any]] = {}
    # Index by fuzzy key (for VIN-less listings)
    by_fuzzy: dict[tuple, dict[str, Any]] = {}
    # Listings that can't be deduped (no VIN, no fuzzy key)
    orphans: list[dict[str, Any]] = []

    vin_dupes = 0
    fuzzy_dupes = 0

    for listing in listings:
        vin = _clean_vin(listing.get("vin"))

        if vin:
            if vin in by_vin:
                by_vin[vin] = _merge_listings(by_vin[vin], listing)
                vin_dupes += 1
            else:
                # Also store the cleaned VIN back
                listing_copy = dict(listing)
                listing_copy["vin"] = vin
                by_vin[vin] = listing_copy
        else:
            # No VIN — try fuzzy key
            fkey = _fuzzy_key(listing)
            if fkey:
                if fkey in by_fuzzy:
                    by_fuzzy[fkey] = _merge_listings(by_fuzzy[fkey], listing)
                    fuzzy_dupes += 1
                else:
                    by_fuzzy[fkey] = dict(listing)
            else:
                orphans.append(listing)

    # Cross-check: a fuzzy-keyed listing might match a VIN-keyed one
    # if one source provided the VIN and another didn't.
    # We skip this for now since it's an uncommon edge case.

    result = list(by_vin.values()) + list(by_fuzzy.values()) + orphans

    logger.info(
        "Deduplication: %d input -> %d output (%d VIN dupes, %d fuzzy dupes, %d orphans)",
        len(listings),
        len(result),
        vin_dupes,
        fuzzy_dupes,
        len(orphans),
    )

    return result
