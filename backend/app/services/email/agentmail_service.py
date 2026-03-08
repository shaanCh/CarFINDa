"""AgentMail integration for CarFINDa agent email notifications."""

import logging
from typing import Optional

from agentmail import AgentMail

from app.config import get_settings

logger = logging.getLogger(__name__)

# The CarFINDa agent inbox (pre-created on the free tier)
AGENT_INBOX = "carfinda@agentmail.to"

_client: Optional[AgentMail] = None


def _get_client() -> AgentMail:
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.AGENTMAIL_API_KEY:
            raise RuntimeError("AGENTMAIL_API_KEY not configured")
        _client = AgentMail(api_key=settings.AGENTMAIL_API_KEY)
    return _client


async def get_inbox_address() -> str:
    """Return the agent's email address."""
    return AGENT_INBOX


async def send_email(
    to: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
) -> dict:
    """Send an email from the CarFINDa agent inbox."""
    client = _get_client()

    response = client.inboxes.messages.send(
        inbox_id=AGENT_INBOX,
        to=to,
        subject=subject,
        html=html,
        text=text or "",
    )
    msg_id = getattr(response, "message_id", None) or getattr(response, "id", "sent")
    logger.info("Sent email to %s: %s (message_id=%s)", to, subject, msg_id)
    return {
        "message_id": str(msg_id),
        "from": AGENT_INBOX,
        "to": to,
        "subject": subject,
    }


async def list_replies(limit: int = 20) -> list[dict]:
    """List recent incoming messages (replies from users)."""
    client = _get_client()

    response = client.inboxes.messages.list(inbox_id=AGENT_INBOX, limit=limit)
    messages = getattr(response, "messages", []) or []
    results = []
    for msg in messages:
        results.append({
            "id": getattr(msg, "message_id", None) or getattr(msg, "id", ""),
            "from": getattr(msg, "from_", None) or getattr(msg, "sender", ""),
            "subject": getattr(msg, "subject", ""),
            "text": getattr(msg, "extracted_text", "") or getattr(msg, "text", ""),
            "received_at": str(getattr(msg, "created_at", "")),
            "thread_id": getattr(msg, "thread_id", None),
        })
    return results
