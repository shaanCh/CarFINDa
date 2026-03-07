"""
Outreach Routes — FastAPI router for seller outreach automation.

Provides endpoints for creating outreach campaigns, checking campaign status,
monitoring for seller replies, and sending follow-up messages.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.dependencies import get_current_user
from app.services.marketplace.facebook import FacebookMarketplaceScraper
from app.services.marketplace.outreach_manager import OutreachManager
from app.services.scraping.browser_client import BrowserClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outreach", tags=["outreach"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class OutreachListing(BaseModel):
    """A listing to include in an outreach campaign."""
    id: Optional[str] = None
    listing_url: str
    title: Optional[str] = None
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    price: Optional[float] = None
    mileage: Optional[int] = None
    location: Optional[str] = None
    seller_name: Optional[str] = None


class CreateCampaignRequest(BaseModel):
    """Request body for creating a new outreach campaign."""
    listings: list[OutreachListing]
    message_style: str = Field(
        default="friendly",
        description="Message tone: 'friendly', 'direct', or 'negotiating'",
    )
    max_messages: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of messages to send",
    )
    auto_followup: bool = Field(
        default=True,
        description="Whether to automatically follow up with non-responders",
    )


class CampaignStatusResponse(BaseModel):
    """Campaign status with message breakdown."""
    campaign_id: str
    status: str
    message_style: Optional[str] = None
    auto_followup: Optional[bool] = None
    created_at: Optional[str] = None
    total: int = 0
    sent: int = 0
    replied: int = 0
    pending: int = 0
    failed: int = 0
    conversations: list[dict] = []


class FollowupRequest(BaseModel):
    """Request body for sending follow-up messages."""
    days_since_sent: int = Field(
        default=2,
        ge=1,
        le=14,
        description="Minimum days since original message before following up",
    )


class LoginStatusResponse(BaseModel):
    """Facebook login status check response."""
    logged_in: bool
    profile: str


# ---------------------------------------------------------------------------
# Dependency: OutreachManager
# ---------------------------------------------------------------------------

async def get_outreach_manager() -> OutreachManager:
    """Build and return an OutreachManager instance.

    Instantiates the BrowserClient, FacebookMarketplaceScraper, and
    OutreachManager with settings from the environment.
    """
    settings = get_settings()
    browser_client = BrowserClient(
        base_url=settings.SIDECAR_URL,
        token=settings.SIDECAR_TOKEN,
    )
    fb_scraper = FacebookMarketplaceScraper(
        browser_client=browser_client,
        profile="carfinda-fb",
    )
    manager = OutreachManager(
        supabase_url=settings.SUPABASE_URL,
        supabase_key=settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY,
        facebook_scraper=fb_scraper,
    )
    return manager


async def get_facebook_scraper() -> FacebookMarketplaceScraper:
    """Build and return a FacebookMarketplaceScraper instance."""
    settings = get_settings()
    browser_client = BrowserClient(
        base_url=settings.SIDECAR_URL,
        token=settings.SIDECAR_TOKEN,
    )
    return FacebookMarketplaceScraper(
        browser_client=browser_client,
        profile="carfinda-fb",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=CampaignStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create outreach campaign",
)
async def create_campaign(
    request: CreateCampaignRequest,
    user: dict = Depends(get_current_user),
    manager: OutreachManager = Depends(get_outreach_manager),
):
    """Create a new outreach campaign that sends personalized messages
    to sellers on Facebook Marketplace.

    The campaign will:
    1. Generate personalized messages for each listing based on the message_style.
    2. Send messages to sellers via Facebook Marketplace DM.
    3. Track all outreach in the database for reply monitoring.
    """
    user_id = user["user_id"]

    # Convert Pydantic models to dicts for the outreach manager
    listings_data = [listing.model_dump() for listing in request.listings]

    try:
        result = await manager.create_campaign(
            user_id=user_id,
            listings=listings_data,
            message_style=request.message_style,
            max_messages=request.max_messages,
            auto_followup=request.auto_followup,
        )
        return CampaignStatusResponse(**result)
    except Exception as exc:
        logger.error("Failed to create outreach campaign: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create campaign: {exc}",
        )


@router.get(
    "/{campaign_id}",
    response_model=CampaignStatusResponse,
    summary="Get campaign status",
)
async def get_campaign_status(
    campaign_id: str,
    user: dict = Depends(get_current_user),
    manager: OutreachManager = Depends(get_outreach_manager),
):
    """Get the current status of an outreach campaign, including
    message counts (sent, replied, pending, failed) and individual
    conversation details."""
    result = await manager.get_campaign_status(campaign_id)

    if result.get("error"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )

    return CampaignStatusResponse(**result)


@router.post(
    "/{campaign_id}/check-replies",
    summary="Check for new seller replies",
)
async def check_replies(
    campaign_id: str,
    user: dict = Depends(get_current_user),
    manager: OutreachManager = Depends(get_outreach_manager),
):
    """Check Facebook Messenger for new replies from sellers
    contacted as part of this campaign.

    Scans the inbox, matches conversations to campaign messages,
    and updates the database with reply content.
    """
    try:
        new_replies = await manager.check_replies(campaign_id)
        return {
            "campaign_id": campaign_id,
            "new_replies": len(new_replies),
            "replies": new_replies,
        }
    except Exception as exc:
        logger.error("Failed to check replies for campaign %s: %s", campaign_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check replies: {exc}",
        )


@router.post(
    "/{campaign_id}/followup",
    summary="Send follow-up messages",
)
async def send_followups(
    campaign_id: str,
    request: FollowupRequest = FollowupRequest(),
    user: dict = Depends(get_current_user),
    manager: OutreachManager = Depends(get_outreach_manager),
):
    """Send follow-up messages to sellers who haven't replied within
    the specified number of days.

    Only sends follow-ups if the campaign has auto_followup enabled.
    Uses the same message_style as the original campaign.
    """
    try:
        results = await manager.send_followups(
            campaign_id=campaign_id,
            days_since_sent=request.days_since_sent,
        )
        successful = sum(1 for r in results if r.get("success"))
        return {
            "campaign_id": campaign_id,
            "followups_sent": successful,
            "followups_failed": len(results) - successful,
            "details": results,
        }
    except Exception as exc:
        logger.error("Failed to send follow-ups for campaign %s: %s", campaign_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send follow-ups: {exc}",
        )


@router.get(
    "/facebook/login-status",
    response_model=LoginStatusResponse,
    summary="Check Facebook login status",
)
async def facebook_login_status(
    user: dict = Depends(get_current_user),
    fb_scraper: FacebookMarketplaceScraper = Depends(get_facebook_scraper),
):
    """Check if the user is logged into Facebook in the dedicated
    browser profile used for Marketplace automation.

    The user needs to log in once; cookies persist in the browser profile.
    """
    try:
        logged_in = await fb_scraper.check_login_status()
        return LoginStatusResponse(
            logged_in=logged_in,
            profile="carfinda-fb",
        )
    except Exception as exc:
        logger.error("Failed to check Facebook login status: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check login status: {exc}",
        )
