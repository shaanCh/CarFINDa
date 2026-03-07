import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user
from app.models.schemas import (
    SearchRequest,
    SearchResponse,
    Listing,
    ListingScore,
    ListingWithScore,
)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post(
    "/",
    response_model=SearchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_search(
    request: SearchRequest,
    user: dict = Depends(get_current_user),
):
    """Accept a natural-language car search and kick off the pipeline.

    Steps (stubbed):
    1. Call the intake agent to parse natural language into structured prefs.
    2. Trigger the scraping pipeline via the sidecar.
    3. Queue the scoring job.

    Returns a ``search_session_id`` the client can poll.
    """
    session_id = str(uuid.uuid4())

    # TODO: Parse natural_language with intake agent (LLM)
    # TODO: Dispatch scraping job to sidecar
    # TODO: Persist search session in DB

    return SearchResponse(
        search_session_id=session_id,
        status="pending",
        listings=[],
        total_results=0,
    )


@router.get(
    "/{session_id}",
    response_model=SearchResponse,
)
async def get_search_status(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Poll the status of an ongoing search session.

    TODO: Look up session in DB and return current status + any results
    gathered so far.
    """
    # Stub: return a synthetic response so the API shape is exercisable.
    stub_listing = Listing(
        id=str(uuid.uuid4()),
        year=2021,
        make="Toyota",
        model="Camry",
        trim="SE",
        price=24999.0,
        mileage=35000,
        location="Austin, TX",
        source_name="stub",
    )
    stub_score = ListingScore(
        safety=8.5,
        reliability=9.0,
        value=7.5,
        efficiency=8.0,
        recall_penalty=0.0,
        composite=8.25,
        breakdown={"note": "stub score"},
    )

    return SearchResponse(
        search_session_id=session_id,
        status="complete",
        listings=[ListingWithScore(listing=stub_listing, score=stub_score)],
        total_results=1,
    )
