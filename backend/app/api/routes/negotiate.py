"""
Negotiation Routes -- generates negotiation strategies and executes
AI-powered DM outreach + counter-negotiation via Facebook Marketplace.

Endpoints:
  POST /api/negotiate/              — Generate a full negotiation strategy (no DM sent)
  POST /api/negotiate/send-dm       — Generate AI message + send DM to seller
  POST /api/negotiate/reply         — Generate AI counter-offer + optionally send
  POST /api/negotiate/check         — Check inbox + auto-respond to active negotiations
  POST /api/negotiate/facebook/search — Search Facebook Marketplace only
  POST /api/negotiate/login         — Trigger Facebook login
  POST /api/negotiate/login/2fa     — Submit 2FA code
  GET  /api/negotiate/login/status  — Check FB login status
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies import get_current_user
from app.models.schemas import (
    NegotiationRequest,
    NegotiationResponse,
    SendDMRequest,
    SendDMResponse,
    NegotiateReplyRequest,
    NegotiateReplyResponse,
    CheckNegotiationsRequest,
    CheckNegotiationsResponse,
    FacebookSearchRequest,
    FacebookSearchResponse,
    FacebookLoginRequest,
    FacebookLoginResponse,
    Facebook2FARequest,
)
from app.services.llm.negotiation_agent import generate_negotiation_strategy
from app.services.marketplace.facebook import FacebookMarketplaceScraper
from app.services.marketplace.negotiation import get_negotiation_engine
from app.services.scraping.browser_client import BrowserClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/negotiate", tags=["negotiate"])


# ---------------------------------------------------------------------------
# Dependency: FacebookMarketplaceScraper
# ---------------------------------------------------------------------------

async def _get_fb_scraper() -> FacebookMarketplaceScraper:
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
# 1. Strategy generation (existing)
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=NegotiationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate negotiation strategy",
)
async def create_negotiation_strategy(
    request: NegotiationRequest,
    user: dict = Depends(get_current_user),
):
    """Generate a data-backed negotiation strategy for a specific listing.

    Returns:
    - Opening DM message to send the seller
    - Fair price range with explanation
    - Opening offer amount with reasoning
    - Leverage points (recalls, complaints, market comparisons)
    - Questions to ask the seller based on known issues
    - Competing listings for reference
    - Walk-away price
    - Tactical negotiation tips
    """
    if not request.listing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Listing data is required to generate a negotiation strategy.",
        )

    try:
        result = await generate_negotiation_strategy(
            listing=request.listing,
            score_data=request.score or {},
            enrichment_data=request.data or {},
            user_preferences=request.preferences or {},
            competing_listings=request.competing_listings or None,
        )

        return NegotiationResponse(**result)

    except Exception as exc:
        logger.error("Negotiation strategy generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate negotiation strategy: {exc}",
        )


# ---------------------------------------------------------------------------
# 2. Send AI-generated DM
# ---------------------------------------------------------------------------

@router.post(
    "/send-dm",
    response_model=SendDMResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate AI negotiation message and send via Facebook DM",
)
async def send_negotiation_dm(
    request: SendDMRequest,
    user: dict = Depends(get_current_user),
    fb_scraper: FacebookMarketplaceScraper = Depends(_get_fb_scraper),
):
    """Generate a personalized opening DM using AI negotiation engine
    and send it to the seller on Facebook Marketplace.

    The message is crafted using scoring data (market value, recalls,
    complaints) as leverage for price negotiation.

    Set `send=false` to preview the message without sending.
    """
    listing_url = request.listing.get("listing_url") or request.listing.get("source_url")
    if not listing_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="listing_url or source_url is required in the listing dict.",
        )

    try:
        # Auto-login if credentials are available
        settings = get_settings()
        if settings.FB_EMAIL and settings.FB_PASSWORD:
            await fb_scraper.ensure_logged_in(settings.FB_EMAIL, settings.FB_PASSWORD)

        if request.send:
            # Generate + send
            result = await fb_scraper.smart_outreach(
                listing=request.listing,
                scoring_data=request.scoring_data,
                target_price=request.target_price,
                strategy=request.strategy,
            )
            return SendDMResponse(**result)
        else:
            # Preview only — generate message without sending
            engine = get_negotiation_engine()
            gen_result = await engine.generate_opening_message(
                listing=request.listing,
                scoring_data=request.scoring_data,
                target_price=request.target_price,
                strategy=request.strategy,
            )
            return SendDMResponse(
                success=True,
                message_sent=gen_result["message"],
                target_price=gen_result["target_price"],
                strategy_notes=gen_result["strategy_notes"],
            )

    except Exception as exc:
        logger.error("Send DM failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send negotiation DM: {exc}",
        )


# ---------------------------------------------------------------------------
# 3. Reply / counter-offer
# ---------------------------------------------------------------------------

@router.post(
    "/reply",
    response_model=NegotiateReplyResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate AI counter-offer and optionally send",
)
async def negotiate_reply(
    request: NegotiateReplyRequest,
    user: dict = Depends(get_current_user),
    fb_scraper: FacebookMarketplaceScraper = Depends(_get_fb_scraper),
):
    """Analyze a seller's reply and generate an AI counter-offer.

    If `auto_send=true` and the analysis recommends sending (counter or
    accept), the reply is automatically sent via Facebook Messenger.
    Walk-away messages require manual approval.
    """
    try:
        if request.auto_send and request.conversation_url:
            result = await fb_scraper.smart_reply(
                listing=request.listing,
                seller_message=request.seller_message,
                conversation_history=request.conversation_history,
                conversation_url=request.conversation_url,
                scoring_data=request.scoring_data,
                target_price=request.target_price,
                max_price=request.max_price,
                strategy=request.strategy,
            )
        else:
            # Generate counter without sending
            engine = get_negotiation_engine()
            result = await engine.generate_counter(
                listing=request.listing,
                seller_message=request.seller_message,
                conversation_history=request.conversation_history,
                scoring_data=request.scoring_data,
                target_price=request.target_price,
                max_price=request.max_price,
                strategy=request.strategy,
            )
            result["auto_sent"] = False

        return NegotiateReplyResponse(**result)

    except Exception as exc:
        logger.error("Negotiate reply failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate counter-offer: {exc}",
        )


# ---------------------------------------------------------------------------
# 4. Check inbox + auto-respond
# ---------------------------------------------------------------------------

@router.post(
    "/check",
    response_model=CheckNegotiationsResponse,
    status_code=status.HTTP_200_OK,
    summary="Check inbox and auto-respond to active negotiations",
)
async def check_negotiations(
    request: CheckNegotiationsRequest,
    user: dict = Depends(get_current_user),
    fb_scraper: FacebookMarketplaceScraper = Depends(_get_fb_scraper),
):
    """Scan Facebook Messenger inbox for seller replies to active
    negotiations and auto-respond with AI counter-offers.

    For each unread reply matched to an active negotiation, the engine:
    1. Analyzes the seller's intent (accept/counter/reject/question)
    2. Generates an appropriate response
    3. Auto-sends if safe (counter or accept), holds for user approval otherwise
    """
    try:
        results = await fb_scraper.check_and_respond(
            active_negotiations=request.active_negotiations,
            strategy=request.strategy,
        )
        return CheckNegotiationsResponse(
            replies_found=len(results),
            responses=results,
        )
    except Exception as exc:
        logger.error("Check negotiations failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check negotiations: {exc}",
        )


# ---------------------------------------------------------------------------
# 5. Facebook Marketplace search
# ---------------------------------------------------------------------------

@router.post(
    "/facebook/search",
    response_model=FacebookSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search Facebook Marketplace",
)
async def facebook_search(
    request: FacebookSearchRequest,
    user: dict = Depends(get_current_user),
    fb_scraper: FacebookMarketplaceScraper = Depends(_get_fb_scraper),
):
    """Search Facebook Marketplace for vehicle listings.

    Starts the browser, logs in if credentials are configured,
    searches with the provided filters, and returns listings.
    """
    settings = get_settings()
    logged_in = False

    try:
        # Auto-login
        if settings.FB_EMAIL and settings.FB_PASSWORD:
            logged_in = await fb_scraper.ensure_logged_in(
                settings.FB_EMAIL, settings.FB_PASSWORD,
            )

        # Build filters for FB scraper
        # If we only have a natural-language query, parse it into structured
        # filters since FB Marketplace doesn't handle NL queries well.
        fb_filters: dict = {}

        if request.query and not request.makes and not request.models:
            from app.api.routes.search import _regex_parse_nl
            parsed = _regex_parse_nl(request.query)
            if parsed.get("makes"):
                fb_filters["make"] = parsed["makes"][0]
            if parsed.get("models"):
                fb_filters["model"] = parsed["models"][0]
            if parsed.get("budget_max") and request.budget_max is None:
                fb_filters["max_price"] = parsed["budget_max"]
            if parsed.get("min_year") and not request.min_year:
                fb_filters["min_year"] = parsed["min_year"]
            if parsed.get("max_mileage") and not request.max_mileage:
                fb_filters["max_mileage"] = parsed["max_mileage"]
            if parsed.get("body_types"):
                # Use body type as query (e.g. "SUV", "Truck")
                fb_filters["query"] = parsed["body_types"][0]
            # If we still have nothing useful, pass the raw query
            if not fb_filters.get("make") and not fb_filters.get("query"):
                fb_filters["query"] = request.query
        else:
            if request.query:
                fb_filters["query"] = request.query

        if request.makes:
            fb_filters["make"] = request.makes[0]  # FB search supports one make
        if request.models:
            fb_filters["model"] = request.models[0]
        if request.budget_min is not None:
            fb_filters["min_price"] = request.budget_min
        if request.budget_max is not None:
            fb_filters["max_price"] = request.budget_max
        if request.min_year:
            fb_filters["min_year"] = request.min_year
        if request.max_mileage:
            fb_filters["max_mileage"] = request.max_mileage
        fb_filters["max_pages"] = request.max_pages

        logger.info("Facebook search filters: %s", fb_filters)

        listings = await fb_scraper.search_marketplace(fb_filters)

        return FacebookSearchResponse(
            success=True,
            listings=listings,
            total=len(listings),
            logged_in=logged_in,
        )

    except Exception as exc:
        logger.error("Facebook search failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Facebook search failed: {exc}",
        )


# ---------------------------------------------------------------------------
# 6. Facebook login management
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_model=FacebookLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger Facebook login",
)
async def facebook_login(
    request: FacebookLoginRequest = FacebookLoginRequest(),
    user: dict = Depends(get_current_user),
    fb_scraper: FacebookMarketplaceScraper = Depends(_get_fb_scraper),
):
    """Log into Facebook using stored or provided credentials.

    Cookies persist in the browser profile, so login is typically
    needed only once. Returns status indicating success, 2FA required,
    or CAPTCHA challenge.
    """
    settings = get_settings()
    email = request.email or settings.FB_EMAIL
    password = request.password or settings.FB_PASSWORD

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Facebook email and password are required (provide in request or set FB_EMAIL/FB_PASSWORD env vars).",
        )

    try:
        result = await fb_scraper.login(email, password)
        return FacebookLoginResponse(
            success=result.get("success", False),
            status=result.get("status", "unknown"),
            needs_2fa=result.get("needs_2fa", False),
            error=result.get("error"),
        )
    except Exception as exc:
        logger.error("Facebook login failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Facebook login failed: {exc}",
        )


@router.post(
    "/login/2fa",
    response_model=FacebookLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit 2FA code",
)
async def facebook_2fa(
    request: Facebook2FARequest,
    user: dict = Depends(get_current_user),
    fb_scraper: FacebookMarketplaceScraper = Depends(_get_fb_scraper),
):
    """Submit a two-factor authentication code to complete Facebook login."""
    try:
        result = await fb_scraper.submit_2fa(request.code)
        return FacebookLoginResponse(
            success=result.get("success", False),
            status=result.get("status", "unknown"),
            error=result.get("error"),
        )
    except Exception as exc:
        logger.error("Facebook 2FA submission failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"2FA submission failed: {exc}",
        )


@router.get(
    "/login/status",
    response_model=FacebookLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Check Facebook login status",
)
async def facebook_login_status(
    user: dict = Depends(get_current_user),
    fb_scraper: FacebookMarketplaceScraper = Depends(_get_fb_scraper),
):
    """Check if the browser profile is currently logged into Facebook."""
    try:
        logged_in = await fb_scraper.check_login_status()
        return FacebookLoginResponse(
            success=logged_in,
            status="logged_in" if logged_in else "logged_out",
        )
    except Exception as exc:
        logger.error("Login status check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check login status: {exc}",
        )
