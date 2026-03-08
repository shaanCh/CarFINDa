import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.dependencies import get_current_user, get_listing_db
from app.models.schemas import (
    Listing,
    ListingScore,
    ListingWithScore,
    ListingResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/listings", tags=["listings"])


def _db_row_to_listing_with_score(row: dict) -> ListingWithScore:
    """Convert a DB listing+score dict to a ListingWithScore model."""
    listing_data = row.get("listing", row)
    score_data = row.get("score", {})

    listing = Listing(
        id=listing_data.get("id", str(uuid.uuid4())),
        vin=listing_data.get("vin"),
        year=listing_data.get("year") or 0,
        make=listing_data.get("make") or "Unknown",
        model=listing_data.get("model") or "Unknown",
        trim=listing_data.get("trim"),
        title=listing_data.get("title"),
        price=listing_data.get("price") or 0.0,
        mileage=listing_data.get("mileage"),
        location=listing_data.get("location"),
        source_url=listing_data.get("source_url"),
        source_name=listing_data.get("source_name"),
        image_urls=listing_data.get("image_urls") or [],
        exterior_color=listing_data.get("exterior_color"),
        interior_color=listing_data.get("interior_color"),
        fuel_type=listing_data.get("fuel_type"),
        transmission=listing_data.get("transmission"),
        drivetrain=listing_data.get("drivetrain"),
    )

    score = ListingScore(
        safety=float(score_data.get("safety_score", 0)),
        reliability=float(score_data.get("reliability_score", 0)),
        value=float(score_data.get("value_score", 0)),
        efficiency=float(score_data.get("efficiency_score", 0)),
        ownership_cost=float(score_data.get("ownership_cost_score", 50)),
        recall_penalty=float(score_data.get("recall_penalty", 0)),
        composite=float(score_data.get("composite_score", 0)),
        breakdown=score_data.get("breakdown") or {},
    )

    return ListingWithScore(listing=listing, score=score)


@router.get("/", response_model=ListingResponse)
async def list_listings(
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    min_year: Optional[int] = Query(None, ge=1900),
    max_year: Optional[int] = Query(None, le=2100),
    makes: Optional[str] = Query(None, description="Comma-separated makes"),
    model: Optional[str] = Query(None, description="Comma-separated models"),
    max_mileage: Optional[int] = Query(None, ge=0),
    sort_by: str = Query("composite_score", description="Field to sort by"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
    db=Depends(get_listing_db),
):
    """Return a paginated, filterable list of scored listings from the DB."""
    if not db:
        return ListingResponse(listings=[], total=0, limit=limit, offset=offset)

    # Build PostgREST query params
    params: dict = {"select": "*", "order": "last_seen_at.desc", "limit": str(limit), "offset": str(offset)}

    if min_price is not None:
        params["price"] = f"gte.{min_price}"
    if max_price is not None:
        # PostgREST doesn't support two filters on the same column via params,
        # so combine with 'and' syntax if min_price is also set
        if min_price is not None:
            params.pop("price", None)
            params["and"] = f"(price.gte.{min_price},price.lte.{max_price})"
        else:
            params["price"] = f"lte.{max_price}"
    if min_year is not None:
        params["year"] = f"gte.{min_year}"
    if max_year is not None:
        if min_year is not None:
            params.pop("year", None)
            year_filter = f"(year.gte.{min_year},year.lte.{max_year})"
            existing_and = params.get("and", "")
            if existing_and:
                params["and"] = f"{existing_and},{year_filter}"
            else:
                params["and"] = year_filter
        else:
            params["year"] = f"lte.{max_year}"
    if max_mileage is not None:
        params["mileage"] = f"lte.{max_mileage}"
    if makes:
        make_list = ",".join(m.strip() for m in makes.split(","))
        params["make"] = f"in.({make_list})"
    if model:
        model_list = ",".join(m.strip() for m in model.split(","))
        params["model"] = f"in.({model_list})"

    try:
        resp = await db._client.get(f"{db._rest_url}/listings", params=params)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        logger.error("Failed to query listings: %s", exc)
        return ListingResponse(listings=[], total=0, limit=limit, offset=offset)

    if not rows:
        return ListingResponse(listings=[], total=0, limit=limit, offset=offset)

    # Fetch scores for these listings
    listing_ids = [r["id"] for r in rows]
    scores_by_id: dict = {}
    try:
        ids_csv = ",".join(listing_ids)
        score_resp = await db._client.get(
            f"{db._rest_url}/listing_scores",
            params={"listing_id": f"in.({ids_csv})", "select": "*"},
        )
        score_resp.raise_for_status()
        for s in score_resp.json():
            scores_by_id[s["listing_id"]] = s
    except Exception as exc:
        logger.error("Failed to fetch scores for listings: %s", exc)

    results = []
    for row in rows:
        combined = {"listing": row, "score": scores_by_id.get(row["id"], {})}
        results.append(_db_row_to_listing_with_score(combined))

    # Sort by composite score descending if requested
    if sort_by == "composite_score":
        results.sort(key=lambda x: x.score.composite, reverse=True)

    return ListingResponse(
        listings=results,
        total=len(results),
        limit=limit,
        offset=offset,
    )


@router.get("/{listing_id}", response_model=ListingWithScore)
async def get_listing(
    listing_id: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_listing_db),
):
    """Return a single listing with its full score breakdown from the DB."""
    if not db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured.",
        )

    result = await db.get_listing(listing_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Listing {listing_id} not found.",
        )

    combined = {"listing": result["listing"], "score": result.get("score") or {}}
    return _db_row_to_listing_with_score(combined)
