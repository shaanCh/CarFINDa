"""
Outreach Manager — Manages automated seller outreach across platforms.

Tracks which listings have been contacted, monitors response rates,
manages follow-up sequences, and persists campaign state to Supabase.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

from app.services.marketplace.facebook import FacebookMarketplaceScraper

logger = logging.getLogger(__name__)

# Default message templates by style
MESSAGE_TEMPLATES = {
    "friendly": (
        "Hi {seller_name}! I'm interested in your {year} {make} {model} "
        "listed at {price}. Is it still available? I'd love to learn more "
        "about its condition and history. Thanks!"
    ),
    "direct": (
        "Hi, is the {year} {make} {model} still available at {price}? "
        "I'm a serious buyer and can move quickly if the details check out."
    ),
    "negotiating": (
        "Hi {seller_name}, I'm interested in your {year} {make} {model}. "
        "Based on my research, I think {offer_price} would be a fair price. "
        "Would you be open to discussing? I can come look at it soon."
    ),
}

FOLLOWUP_TEMPLATES = {
    "friendly": (
        "Hi again! Just following up on the {year} {make} {model}. "
        "Is it still available? I'm still very interested. Let me know!"
    ),
    "direct": (
        "Hi, following up on the {year} {make} {model}. "
        "Still interested if it's available. Any updates?"
    ),
    "negotiating": (
        "Hi, just checking in about the {year} {make} {model}. "
        "I'm flexible on price and can schedule a viewing whenever works for you."
    ),
}


class OutreachManager:
    """Manages automated seller outreach across platforms.

    Tracks which listings have been contacted, response rates, and manages
    follow-up sequences. Campaign and message state is persisted to Supabase
    via PostgREST.
    """

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        facebook_scraper: FacebookMarketplaceScraper,
    ):
        """Initialize the outreach manager.

        Args:
            supabase_url:     Supabase project URL.
            supabase_key:     Supabase anon or service-role key.
            facebook_scraper: Initialized FacebookMarketplaceScraper instance.
        """
        self._base_url = supabase_url.rstrip("/")
        self._rest_url = f"{self._base_url}/rest/v1"
        self._headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        self.facebook = facebook_scraper

    # ------------------------------------------------------------------
    # Campaign CRUD
    # ------------------------------------------------------------------

    async def create_campaign(
        self,
        user_id: str,
        listings: list[dict],
        message_style: str = "friendly",
        max_messages: int = 10,
        auto_followup: bool = True,
    ) -> dict:
        """Create an outreach campaign for a set of listings.

        Creates the campaign record, generates personalized messages for each
        listing, persists message records, and then executes the outreach
        through the Facebook scraper.

        Args:
            user_id:        The user's UUID.
            listings:       List of listing dicts to contact.
            message_style:  One of 'friendly', 'direct', 'negotiating'.
            max_messages:   Maximum messages to send in this campaign.
            auto_followup:  Whether to enable automatic follow-ups.

        Returns:
            Campaign dict with id, status, message counts.
        """
        campaign_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Validate message style
        if message_style not in MESSAGE_TEMPLATES:
            message_style = "friendly"

        # Step 1: Create the campaign record
        campaign_payload = {
            "id": campaign_id,
            "user_id": user_id,
            "message_style": message_style,
            "max_messages": max_messages,
            "auto_followup": auto_followup,
            "status": "active",
            "created_at": now,
        }

        try:
            resp = await self._client.post(
                f"{self._rest_url}/outreach_campaigns",
                json=campaign_payload,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Failed to create campaign: %s %s",
                exc.response.status_code, exc.response.text,
            )
            raise

        # Step 2: Create outreach message records for each listing
        template = MESSAGE_TEMPLATES[message_style]
        messages_to_create: list[dict] = []
        listings_capped = listings[:max_messages]

        for listing in listings_capped:
            personalized = self.facebook._personalize_message(template, listing)
            message_record = {
                "id": str(uuid.uuid4()),
                "campaign_id": campaign_id,
                "listing_id": listing.get("id"),
                "seller_name": listing.get("seller_name"),
                "platform": "facebook",
                "message_text": personalized,
                "status": "pending",
                "created_at": now,
            }
            messages_to_create.append(message_record)

        if messages_to_create:
            try:
                resp = await self._client.post(
                    f"{self._rest_url}/outreach_messages",
                    json=messages_to_create,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Failed to create outreach messages: %s %s",
                    exc.response.status_code, exc.response.text,
                )
                # Campaign was created but messages failed — update status
                await self._update_campaign_status(campaign_id, "failed")
                raise

        # Step 3: Execute the outreach (send messages via Facebook)
        outreach_results = await self.facebook.bulk_outreach(
            listings=listings_capped,
            message_template=template,
            max_messages=max_messages,
            delay_seconds=30,
        )

        # Step 4: Update message records with results
        sent_count = 0
        failed_count = 0
        for i, result in enumerate(outreach_results):
            if i < len(messages_to_create):
                message_id = messages_to_create[i]["id"]
                if result.get("success"):
                    await self._update_message_status(
                        message_id,
                        status="sent",
                        sent_at=datetime.now(timezone.utc).isoformat(),
                        conversation_url=result.get("conversation_url"),
                    )
                    sent_count += 1
                else:
                    await self._update_message_status(
                        message_id,
                        status="failed",
                    )
                    failed_count += 1

        logger.info(
            "Campaign %s complete: %d sent, %d failed out of %d",
            campaign_id, sent_count, failed_count, len(listings_capped),
        )

        return {
            "campaign_id": campaign_id,
            "status": "active",
            "total": len(listings_capped),
            "sent": sent_count,
            "failed": failed_count,
            "pending": 0,
            "message_style": message_style,
            "auto_followup": auto_followup,
            "created_at": now,
        }

    async def get_campaign_status(self, campaign_id: str) -> dict:
        """Get the current status of an outreach campaign.

        Args:
            campaign_id: The campaign UUID.

        Returns:
            Dict with: campaign details, message counts by status, and
            a list of individual conversation statuses.
        """
        # Fetch campaign record
        try:
            resp = await self._client.get(
                f"{self._rest_url}/outreach_campaigns",
                params={
                    "id": f"eq.{campaign_id}",
                    "select": "*",
                    "limit": "1",
                },
            )
            resp.raise_for_status()
            campaigns = resp.json()
            if not campaigns:
                return {"error": "Campaign not found", "campaign_id": campaign_id}
            campaign = campaigns[0]
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch campaign %s: %s", campaign_id, exc)
            return {"error": str(exc), "campaign_id": campaign_id}

        # Fetch all messages for this campaign
        try:
            resp = await self._client.get(
                f"{self._rest_url}/outreach_messages",
                params={
                    "campaign_id": f"eq.{campaign_id}",
                    "select": "id,listing_id,seller_name,platform,status,sent_at,reply_text,replied_at,conversation_url",
                    "order": "created_at.asc",
                },
            )
            resp.raise_for_status()
            messages = resp.json()
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch messages for campaign %s: %s", campaign_id, exc)
            messages = []

        # Count by status
        status_counts = {"pending": 0, "sent": 0, "replied": 0, "failed": 0}
        for msg in messages:
            s = msg.get("status", "pending")
            if s in status_counts:
                status_counts[s] += 1

        return {
            "campaign_id": campaign_id,
            "status": campaign.get("status", "unknown"),
            "message_style": campaign.get("message_style"),
            "auto_followup": campaign.get("auto_followup"),
            "created_at": campaign.get("created_at"),
            "total": len(messages),
            "sent": status_counts["sent"],
            "replied": status_counts["replied"],
            "pending": status_counts["pending"],
            "failed": status_counts["failed"],
            "conversations": messages,
        }

    # ------------------------------------------------------------------
    # Reply Monitoring
    # ------------------------------------------------------------------

    async def check_replies(self, campaign_id: str) -> list[dict]:
        """Check for new replies to messages in a campaign.

        Scans the Facebook Messenger inbox and matches conversations back
        to campaign messages by seller name or conversation URL.

        Args:
            campaign_id: The campaign UUID.

        Returns:
            List of newly detected reply dicts.
        """
        # Fetch sent messages for this campaign that haven't been replied to yet
        try:
            resp = await self._client.get(
                f"{self._rest_url}/outreach_messages",
                params={
                    "campaign_id": f"eq.{campaign_id}",
                    "status": "eq.sent",
                    "select": "id,seller_name,conversation_url,listing_id",
                },
            )
            resp.raise_for_status()
            sent_messages = resp.json()
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch sent messages: %s", exc)
            return []

        if not sent_messages:
            logger.info("No pending sent messages to check for campaign %s", campaign_id)
            return []

        # Build lookup maps for matching
        by_seller = {}
        by_url = {}
        for msg in sent_messages:
            seller = msg.get("seller_name", "").lower().strip()
            if seller:
                by_seller[seller] = msg
            conv_url = msg.get("conversation_url")
            if conv_url:
                by_url[conv_url] = msg

        # Check Messenger inbox
        inbox_conversations = await self.facebook.check_inbox(limit=30)

        new_replies: list[dict] = []

        for conv in inbox_conversations:
            matched_message = None
            conv_seller = (conv.get("seller_name") or "").lower().strip()
            conv_url = conv.get("conversation_url", "")

            # Match by conversation URL first (most reliable)
            if conv_url and conv_url in by_url:
                matched_message = by_url[conv_url]
            # Fall back to matching by seller name
            elif conv_seller and conv_seller in by_seller:
                matched_message = by_seller[conv_seller]

            if matched_message and conv.get("last_message"):
                # Update the message record with the reply
                reply_data = {
                    "status": "replied",
                    "reply_text": conv["last_message"],
                    "replied_at": datetime.now(timezone.utc).isoformat(),
                    "conversation_url": conv_url or matched_message.get("conversation_url"),
                }

                await self._update_message_record(matched_message["id"], reply_data)

                new_replies.append({
                    "message_id": matched_message["id"],
                    "seller_name": conv.get("seller_name"),
                    "listing_id": matched_message.get("listing_id"),
                    "reply_text": conv["last_message"],
                    "timestamp": conv.get("timestamp"),
                    "conversation_url": conv_url,
                })

                logger.info(
                    "New reply detected from %s for campaign %s",
                    conv.get("seller_name"), campaign_id,
                )

        logger.info(
            "Reply check for campaign %s: %d new replies found",
            campaign_id, len(new_replies),
        )
        return new_replies

    # ------------------------------------------------------------------
    # Follow-ups
    # ------------------------------------------------------------------

    async def send_followups(
        self,
        campaign_id: str,
        days_since_sent: int = 2,
    ) -> list[dict]:
        """Auto-send follow-up messages for listings that haven't replied.

        Finds all "sent" (not replied) messages that were sent more than
        `days_since_sent` days ago, and sends a follow-up using the campaign's
        message style.

        Args:
            campaign_id:     The campaign UUID.
            days_since_sent: Minimum days since original message before following up.

        Returns:
            List of follow-up result dicts.
        """
        # Get campaign details for message style
        try:
            resp = await self._client.get(
                f"{self._rest_url}/outreach_campaigns",
                params={
                    "id": f"eq.{campaign_id}",
                    "select": "message_style,auto_followup",
                    "limit": "1",
                },
            )
            resp.raise_for_status()
            campaigns = resp.json()
            if not campaigns:
                return []
            campaign = campaigns[0]
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch campaign for follow-up: %s", exc)
            return []

        if not campaign.get("auto_followup"):
            logger.info("Auto follow-up disabled for campaign %s", campaign_id)
            return []

        message_style = campaign.get("message_style", "friendly")
        followup_template = FOLLOWUP_TEMPLATES.get(message_style, FOLLOWUP_TEMPLATES["friendly"])

        # Find messages that were sent but not replied to, older than threshold
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_since_sent)).isoformat()

        try:
            resp = await self._client.get(
                f"{self._rest_url}/outreach_messages",
                params={
                    "campaign_id": f"eq.{campaign_id}",
                    "status": "eq.sent",
                    "sent_at": f"lt.{cutoff}",
                    "select": "id,listing_id,seller_name,conversation_url,message_text",
                },
            )
            resp.raise_for_status()
            stale_messages = resp.json()
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch stale messages: %s", exc)
            return []

        if not stale_messages:
            logger.info(
                "No messages older than %d days without reply for campaign %s",
                days_since_sent, campaign_id,
            )
            return []

        logger.info(
            "Sending follow-ups for %d messages in campaign %s",
            len(stale_messages), campaign_id,
        )

        results: list[dict] = []

        for msg in stale_messages:
            conversation_url = msg.get("conversation_url")
            if not conversation_url:
                results.append({
                    "message_id": msg["id"],
                    "seller_name": msg.get("seller_name"),
                    "success": False,
                    "error": "No conversation URL to send follow-up to",
                })
                continue

            # Build a minimal listing dict for template personalization
            # We extract what we can from the original message text
            listing_stub = {
                "seller_name": msg.get("seller_name", "there"),
                "year": "",
                "make": "",
                "model": "",
            }

            # Try to fetch listing details if we have a listing_id
            if msg.get("listing_id"):
                listing_details = await self._get_listing_data(msg["listing_id"])
                if listing_details:
                    listing_stub.update(listing_details)

            followup_text = self.facebook._personalize_message(followup_template, listing_stub)

            # Send the follow-up
            send_result = await self.facebook.send_followup(conversation_url, followup_text)

            results.append({
                "message_id": msg["id"],
                "seller_name": msg.get("seller_name"),
                "success": send_result.get("success", False),
                "error": send_result.get("error"),
            })

            # Brief delay between follow-ups
            if msg != stale_messages[-1]:
                import asyncio
                await asyncio.sleep(15)

        logger.info(
            "Follow-up round for campaign %s: %d sent, %d failed",
            campaign_id,
            sum(1 for r in results if r["success"]),
            sum(1 for r in results if not r["success"]),
        )
        return results

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    async def _update_campaign_status(self, campaign_id: str, status: str) -> None:
        """Update the status field of a campaign record."""
        try:
            resp = await self._client.patch(
                f"{self._rest_url}/outreach_campaigns",
                params={"id": f"eq.{campaign_id}"},
                json={"status": status},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Failed to update campaign status: %s", exc)

    async def _update_message_status(
        self,
        message_id: str,
        status: str,
        sent_at: Optional[str] = None,
        conversation_url: Optional[str] = None,
    ) -> None:
        """Update the status and optional fields of an outreach message."""
        update: dict[str, Any] = {"status": status}
        if sent_at:
            update["sent_at"] = sent_at
        if conversation_url:
            update["conversation_url"] = conversation_url

        try:
            resp = await self._client.patch(
                f"{self._rest_url}/outreach_messages",
                params={"id": f"eq.{message_id}"},
                json=update,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Failed to update message %s: %s", message_id, exc)

    async def _update_message_record(self, message_id: str, data: dict) -> None:
        """Update arbitrary fields on an outreach message record."""
        try:
            resp = await self._client.patch(
                f"{self._rest_url}/outreach_messages",
                params={"id": f"eq.{message_id}"},
                json=data,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Failed to update message record %s: %s", message_id, exc)

    async def _get_listing_data(self, listing_id: str) -> Optional[dict]:
        """Fetch basic listing data from the listings table.

        Args:
            listing_id: The listing UUID.

        Returns:
            Dict with year, make, model, price, or None.
        """
        try:
            resp = await self._client.get(
                f"{self._rest_url}/listings",
                params={
                    "id": f"eq.{listing_id}",
                    "select": "year,make,model,price,mileage,location",
                    "limit": "1",
                },
            )
            resp.raise_for_status()
            results = resp.json()
            return results[0] if results else None
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch listing %s: %s", listing_id, exc)
            return None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "OutreachManager":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
