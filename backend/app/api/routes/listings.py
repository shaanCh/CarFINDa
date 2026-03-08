import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user
from app.models.schemas import (
    Listing,
    ListingScore,
    ListingWithScore,
    ListingResponse,
)

router = APIRouter(prefix="/api/listings", tags=["listings"])


@router.get("/", response_model=ListingResponse)
async def list_listings(
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    min_year: Optional[int] = Query(None, ge=1900),
    max_year: Optional[int] = Query(None, le=2100),
    makes: Optional[str] = Query(None, description="Comma-separated makes"),
    model: Optional[str] = Query(None, description="Comma-separated models"),
    location: Optional[str] = Query(None, description="City, state, or zip"),
    body_types: Optional[str] = Query(None, description="Comma-separated body types"),
    max_mileage: Optional[int] = Query(None, ge=0),
    reliability_priority: Optional[str] = Query(None, description="Low, Medium, High"),
    ownership_cost_concern: Optional[str] = Query(None, description="Not important, Important, Critical"),
    seller_type: Optional[str] = Query(None, description="Any, Dealer only, Private only"),
    transmission: Optional[str] = Query(None, description="Any, Automatic, Manual"),
    primary_use: Optional[str] = Query(None, description="Daily commute, Road trips, Family, Hauling"),
    min_score: Optional[float] = Query(None, ge=0, le=10),
    sort_by: str = Query("composite_score", description="Field to sort by"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    """Return a paginated, filterable list of scored listings.

    TODO: Query the database with the provided filters and return real data.
    """
    # Stub listing for development
    stub_listing = Listing(
        id=str(uuid.uuid4()),
        year=2022,
        make="Honda",
        model="Civic",
        trim="EX",
        price=22500.0,
        mileage=28000,
        location="Dallas, TX",
        source_name="stub",
    )
    stub_score = ListingScore(
        safety=8.0,
        reliability=9.2,
        value=8.0,
        efficiency=8.5,
        recall_penalty=0.0,
        composite=8.43,
        breakdown={"note": "stub score"},
    )

    return ListingResponse(
        listings=[ListingWithScore(listing=stub_listing, score=stub_score)],
        total=1,
        limit=limit,
        offset=offset,
    )


@router.get("/{listing_id}", response_model=ListingWithScore)
async def get_listing(
    listing_id: str,
    user: dict = Depends(get_current_user),
):
    """Return a single listing with its full score breakdown.

    TODO: Fetch from database by listing_id. Return 404 if not found.
    """
    # Stub: return a synthetic listing
    stub_listing = Listing(
        id=listing_id,
        year=2020,
        make="Ford",
        model="Escape",
        trim="SEL",
        price=19800.0,
        mileage=45000,
        location="Houston, TX",
        source_name="stub",
    )
    stub_score = ListingScore(
        safety=7.5,
        reliability=7.0,
        value=8.5,
        efficiency=7.8,
        recall_penalty=-0.5,
        composite=7.66,
        breakdown={
            "safety_details": "NHTSA 5-star overall",
            "reliability_details": "JD Power above average",
            "value_details": "Below KBB fair market value",
            "efficiency_details": "28 combined MPG",
            "recall_info": "1 open recall",
        },
    )

    return ListingWithScore(listing=stub_listing, score=stub_score)
