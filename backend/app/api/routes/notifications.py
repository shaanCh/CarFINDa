"""Email notification routes powered by AgentMail."""

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings
from app.dependencies import get_current_user
from app.models.schemas import (
    EmailSubscribeRequest,
    EmailSubscribeResponse,
    SendOutreachSummaryRequest,
    EmailNotificationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# In-memory subscription store (would be Supabase in production)
_subscriptions: dict[str, dict] = {}


@router.post(
    "/subscribe",
    response_model=EmailSubscribeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def subscribe_alerts(
    request: EmailSubscribeRequest,
    user: dict = Depends(get_current_user),
):
    """Subscribe to email alerts for a listing or search.

    Supported alert_types:
      - 'negotiation': Get emailed when a seller replies to your DM
      - 'price_drop':  Get emailed when a watched listing drops in price
      - 'new_matches': Get emailed when new listings match your search
    """
    settings = get_settings()
    if not settings.AGENTMAIL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email notifications not configured (AGENTMAIL_API_KEY missing)",
        )

    from app.services.email.agentmail_service import get_inbox_address

    sub_id = str(uuid.uuid4())
    _subscriptions[sub_id] = {
        "user_id": user.get("user_id", "anon"),
        "email": request.email,
        "alert_type": request.alert_type,
        "listing": request.listing,
        "search_filters": request.search_filters,
        "car_title": request.car_title,
        "car_price": request.car_price,
        "image_url": request.image_url,
    }

    agent_email = await get_inbox_address()

    logger.info(
        "New %s subscription: %s -> %s (sub_id=%s)",
        request.alert_type, request.email, agent_email, sub_id,
    )

    return EmailSubscribeResponse(
        success=True,
        agent_email=agent_email,
        subscription_id=sub_id,
        message=f"You'll receive {request.alert_type} alerts at {request.email}",
    )


@router.post(
    "/send-outreach-summary",
    response_model=EmailNotificationResponse,
)
async def send_outreach_summary(
    request: SendOutreachSummaryRequest,
    user: dict = Depends(get_current_user),
):
    """Send an outreach summary email after the agent finishes sending DMs."""
    settings = get_settings()
    if not settings.AGENTMAIL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email notifications not configured",
        )

    from app.services.email.agentmail_service import send_email
    from app.services.email.templates import outreach_summary_email

    subject, html = outreach_summary_email(
        search_query=request.search_query,
        messages_sent=request.messages_sent,
        listings=request.listings,
    )

    try:
        result = await send_email(to=request.email, subject=subject, html=html)
        return EmailNotificationResponse(
            success=True,
            message_id=result["message_id"],
        )
    except Exception as exc:
        logger.error("Failed to send outreach summary: %s", exc)
        return EmailNotificationResponse(success=False, error=str(exc))


@router.post(
    "/send-price-drop",
    response_model=EmailNotificationResponse,
)
async def send_price_drop_alert(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Send a price drop alert email."""
    settings = get_settings()
    if not settings.AGENTMAIL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email notifications not configured",
        )

    body = await request.json()
    from app.services.email.agentmail_service import send_email
    from app.services.email.templates import price_drop_email

    old_price = body.get("old_price", 0)
    new_price = body.get("new_price", 0)
    drop = old_price - new_price
    pct = (drop / old_price * 100) if old_price > 0 else 0

    subject, html = price_drop_email(
        car_title=body.get("car_title", "Vehicle"),
        old_price=old_price,
        new_price=new_price,
        drop_amount=drop,
        drop_pct=pct,
        market_avg=body.get("market_avg"),
        image_url=body.get("image_url", ""),
        listing_url=body.get("listing_url", ""),
    )

    try:
        result = await send_email(to=body["email"], subject=subject, html=html)
        return EmailNotificationResponse(success=True, message_id=result["message_id"])
    except Exception as exc:
        logger.error("Failed to send price drop alert: %s", exc)
        return EmailNotificationResponse(success=False, error=str(exc))


@router.post(
    "/send-negotiation-update",
    response_model=EmailNotificationResponse,
)
async def send_negotiation_update(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Send a negotiation update when a seller replies."""
    settings = get_settings()
    if not settings.AGENTMAIL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email notifications not configured",
        )

    body = await request.json()
    from app.services.email.agentmail_service import send_email
    from app.services.email.templates import negotiation_update_email

    subject, html = negotiation_update_email(
        car_title=body.get("car_title", "Vehicle"),
        car_price=body.get("car_price", ""),
        seller_reply=body.get("seller_reply", ""),
        suggested_response=body.get("suggested_response", ""),
        fair_price_range=body.get("fair_price_range", ""),
        image_url=body.get("image_url", ""),
    )

    try:
        result = await send_email(to=body["email"], subject=subject, html=html)
        return EmailNotificationResponse(success=True, message_id=result["message_id"])
    except Exception as exc:
        logger.error("Failed to send negotiation update: %s", exc)
        return EmailNotificationResponse(success=False, error=str(exc))


@router.post("/webhook/incoming")
async def agentmail_webhook(request: Request):
    """Webhook endpoint for AgentMail — receives user replies to agent emails.

    When a user replies "send" to a negotiation update email, the agent
    will forward the suggested counter-offer to the seller.
    """
    body = await request.json()
    event_type = body.get("event_type", "")

    if event_type == "message.received":
        sender = body.get("from", "")
        text = body.get("text", "") or body.get("preview", "")
        subject = body.get("subject", "")

        logger.info(
            "Incoming email from %s: subject=%s, text=%s",
            sender, subject, text[:100],
        )

        # Check if user replied "send" to forward counter-offer
        if text.strip().lower() in ("send", "yes", "accept", "send it"):
            logger.info("User %s approved sending counter-offer", sender)
            # TODO: Look up the negotiation context and auto-send the reply

    return {"status": "ok"}


@router.get("/subscriptions")
async def list_subscriptions(user: dict = Depends(get_current_user)):
    """List active email subscriptions for the current user."""
    user_id = user.get("user_id", "anon")
    user_subs = [
        {"id": k, **v}
        for k, v in _subscriptions.items()
        if v.get("user_id") == user_id
    ]
    return {"subscriptions": user_subs}
