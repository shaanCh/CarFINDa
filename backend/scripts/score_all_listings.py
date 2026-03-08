#!/usr/bin/env python3
"""
Full-mode scoring for all listings in the database.

- Scores only listings that don't already have a score (resume-safe)
- Persists scores after each batch (checkpoint on every batch)
- Runs as fast as possible with configurable concurrency
- Safe to stop and restart — progress is never lost

Usage:
  cd /path/to/CarFINDa
  python backend/scripts/score_all_listings.py

  # With higher concurrency (default 30, max recommended ~50):
  python backend/scripts/score_all_listings.py --concurrency 40

  # Smaller batches = more frequent checkpoints (default 25):
  python backend/scripts/score_all_listings.py --batch-size 10

  # Do NOT pipe to head/tail — that closes stdout and can kill the process.
"""
import argparse
import asyncio
import logging
import os
import sys
import time

# Project root for imports and .env
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)
os.chdir(ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def fetch_all_listing_ids(client: httpx.AsyncClient, rest_url: str, headers: dict) -> list[str]:
    """Paginate through listings to get all IDs."""
    ids: list[str] = []
    page_size = 1000
    offset = 0
    while True:
        resp = await client.get(
            f"{rest_url}/listings",
            params={
                "select": "id",
                "order": "id.asc",
                "limit": page_size,
                "offset": offset,
            },
            headers=headers,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        for r in rows:
            lid = r.get("id")
            if lid:
                ids.append(str(lid))
        offset += len(rows)
        if len(rows) < page_size:
            break
    return ids


async def fetch_scored_listing_ids(client: httpx.AsyncClient, rest_url: str, headers: dict) -> set[str]:
    """Paginate through listing_scores to get all listing_ids that have scores."""
    scored: set[str] = set()
    page_size = 1000
    offset = 0
    while True:
        resp = await client.get(
            f"{rest_url}/listing_scores",
            params={
                "select": "listing_id",
                "order": "listing_id.asc",
                "limit": page_size,
                "offset": offset,
            },
            headers=headers,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        for r in rows:
            lid = r.get("listing_id")
            if lid:
                scored.add(str(lid))
        offset += len(rows)
        if len(rows) < page_size:
            break
    return scored


def _db_row_to_listing(row: dict) -> dict:
    """Map a DB listing row to the format expected by the scoring pipeline."""
    price = row.get("price")
    if price is not None and price != "":
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = 0.0
    else:
        price = 0.0

    mileage = row.get("mileage")
    if mileage is not None and mileage != "":
        try:
            mileage = int(mileage)
        except (TypeError, ValueError):
            mileage = 0
    else:
        mileage = 0

    year = row.get("year")
    if year is not None and year != "":
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = 0
    else:
        year = 0

    return {
        "id": str(row.get("id", "")),
        "vin": row.get("vin") or None,
        "year": year,
        "make": (row.get("make") or "").strip() or "Unknown",
        "model": (row.get("model") or "").strip() or "Unknown",
        "trim": (row.get("trim") or "").strip() or None,
        "price": price,
        "mileage": mileage,
        "location": row.get("location"),
        "source_url": row.get("detail_url") or row.get("source_url"),
        "source_name": row.get("source_name") or "database",
        "image_urls": row.get("image_urls") or [],
        "exterior_color": row.get("exterior_color"),
        "interior_color": row.get("interior_color"),
        "fuel_type": row.get("fuel_type") or row.get("motor_type"),
        "motor_type": row.get("motor_type"),
        "transmission": row.get("transmission"),
        "drivetrain": row.get("drivetrain"),
    }


async def fetch_listings_by_ids(
    client: httpx.AsyncClient,
    rest_url: str,
    headers: dict,
    ids: list[str],
) -> list[dict]:
    """Fetch full listing rows for given IDs. PostgREST in() has URL limits, so we batch."""
    if not ids:
        return []
    batch_size = 200
    all_listings: list[dict] = []
    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i : i + batch_size]
        ids_csv = ",".join(batch_ids)
        resp = await client.get(
            f"{rest_url}/listings",
            params={"id": f"in.({ids_csv})", "select": "*"},
            headers=headers,
        )
        resp.raise_for_status()
        rows = resp.json()
        for r in rows:
            all_listings.append(_db_row_to_listing(r))
    return all_listings


async def upsert_scores(
    client: httpx.AsyncClient,
    rest_url: str,
    headers: dict,
    score_rows: list[dict],
) -> None:
    """Bulk upsert scores to listing_scores."""
    if not score_rows:
        return
    batch_size = 50
    for i in range(0, len(score_rows), batch_size):
        batch = score_rows[i : i + batch_size]
        resp = await client.post(
            f"{rest_url}/listing_scores",
            json=batch,
            headers={
                **headers,
                "Prefer": "return=minimal,resolution=merge-duplicates",
            },
            params={"on_conflict": "listing_id"},
        )
        if resp.status_code >= 400:
            err_body = resp.text[:500] if resp.text else "(no body)"
            logger.error("Supabase upsert failed %s: %s", resp.status_code, err_body)
        resp.raise_for_status()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Full-mode score all unscored listings")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=30,
        help="Max concurrent API calls (default 30, try 40-50 for faster runs)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Listings per batch; each batch is checkpointed (default 25)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count unscored listings, do not score",
    )
    args = parser.parse_args()

    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key or "supabase" not in url:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
        sys.exit(1)

    rest_url = f"{url}/rest/v1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    # Monkey-patch concurrency before importing pipeline
    import app.services.scoring.pipeline as pipeline_module
    pipeline_module._MAX_CONCURRENCY = args.concurrency

    from app.services.scoring.pipeline import score_listings
    from app.services.db import score_dict_to_row

    async with httpx.AsyncClient(timeout=60.0) as client:
        logger.info("Fetching all listing IDs...")
        all_ids = await fetch_all_listing_ids(client, rest_url, headers)
        logger.info("Total listings: %d", len(all_ids))

        logger.info("Fetching scored listing IDs...")
        scored_ids = await fetch_scored_listing_ids(client, rest_url, headers)
        unscored_ids = [i for i in all_ids if i not in scored_ids]
        logger.info("Already scored: %d | Unscored: %d", len(scored_ids), len(unscored_ids))

        if not unscored_ids:
            logger.info("Nothing to score. Exiting.")
            return

        if args.dry_run:
            logger.info("Dry run: would score %d listings. Exiting.", len(unscored_ids))
            return

        batch_size = max(1, min(args.batch_size, 100))
        total = len(unscored_ids)
        scored_this_run = 0
        failed = 0
        start = time.perf_counter()

        for i in range(0, total, batch_size):
            batch_ids = unscored_ids[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size

            logger.info(
                "Batch %d/%d: fetching %d listings...",
                batch_num, total_batches, len(batch_ids),
            )
            listings = await fetch_listings_by_ids(client, rest_url, headers, batch_ids)
            if not listings:
                logger.warning("Batch %d: no listings returned, skipping", batch_num)
                continue

            logger.info("Batch %d/%d: scoring %d listings (full mode)...", batch_num, total_batches, len(listings))
            batch_start = time.perf_counter()
            try:
                scored_listings = await score_listings(listings, full=True)
            except Exception as e:
                logger.error("Batch %d scoring failed: %s", batch_num, e)
                failed += len(listings)
                continue

            batch_elapsed = time.perf_counter() - batch_start
            score_rows = []
            for sl in scored_listings:
                lid = sl.get("id")
                score_data = sl.get("score", {})
                if lid and score_data:
                    score_rows.append(score_dict_to_row(lid, score_data))

            if score_rows:
                try:
                    await upsert_scores(client, rest_url, headers, score_rows)
                    scored_this_run += len(score_rows)
                    logger.info(
                        "Batch %d/%d: saved %d scores (%.1fs) [checkpoint] — %d/%d total this run",
                        batch_num, total_batches, len(score_rows), batch_elapsed,
                        scored_this_run, total,
                    )
                except Exception as e:
                    logger.error("Batch %d save failed: %s", batch_num, e)
                    failed += len(listings)
            else:
                failed += len(listings)

        elapsed = time.perf_counter() - start
        logger.info(
            "Done. Scored %d listings in %.1fs (%.1f/s). Failed: %d",
            scored_this_run, elapsed, scored_this_run / elapsed if elapsed > 0 else 0, failed,
        )


if __name__ == "__main__":
    asyncio.run(main())
