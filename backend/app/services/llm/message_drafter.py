"""
Message Drafter -- generates personalised messages to car sellers.

Supports three message styles: friendly, direct, and negotiation.
Uses Gemini to craft natural, data-informed messages.
"""

import json
import logging

from app.config import get_settings
from app.services.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompts for each style
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT = """\
You are a message drafting assistant for CarFINDa, a car-finding platform.
Your job is to write a message from a buyer to a car seller about a specific listing.

## Rules
- Write in first person as the buyer.
- Keep the message concise (3-6 sentences for friendly/direct, up to 8 for negotiation).
- Be polite and professional regardless of style.
- Reference specific details about the car to show genuine interest.
- NEVER fabricate data. Only reference information provided in the context.
- Do NOT include subject lines, greetings like "Dear Sir/Madam", or sign-offs like "Sincerely".
  Just write the message body. Start with "Hi!" or "Hello!" for friendly, or get straight to the
  point for direct/negotiation.
- Output the message as plain text. No markdown formatting.
"""

_STYLE_INSTRUCTIONS = {
    "friendly": """\
## Style: Friendly
Write a warm, casual message expressing genuine interest in the vehicle.
- Open with a friendly greeting.
- Mention what caught your eye about this specific car (year, model, colour, features).
- Ask about availability and whether you can schedule a viewing/test drive.
- Optionally ask one question about condition or history.
- Keep the tone conversational, like texting a friend-of-a-friend.

Example tone: "Hi! I came across your 2020 RAV4 and it looks like exactly what I've been
searching for. Love the blue colour! Is it still available? I'd love to come take a look
this weekend if you're free."
""",
    "direct": """\
## Style: Direct
Write a straightforward, no-nonsense message that gets to the point quickly.
- State that you are interested in the vehicle.
- Ask your key questions upfront: availability, firm price, known issues, service records.
- Keep pleasantries minimal.
- Show you are a serious buyer ready to move quickly.

Example tone: "Hi, I'm interested in your 2020 RAV4 listed at $22K. Is the price firm?
Any mechanical issues or accident history I should know about? I can come see it this week."
""",
    "negotiation": """\
## Style: Negotiation
Write a respectful but data-backed message that justifies a lower offer.
- Express genuine interest first.
- Then tactfully present data points that support a lower price:
  * Market value comparisons (if KBB/market data is in the score breakdown)
  * Open recalls that need to be addressed
  * High complaint counts for this model year
  * Mileage or age adjustments
  * Any condition concerns from the listing
- Propose a specific counter-offer and explain your reasoning.
- Keep the tone respectful -- you want to negotiate, not insult.
- End with openness to discuss.

Example tone: "Hi! I'm interested in your 2020 RAV4. I noticed it's listed at $22K,
but based on current market data for this year and mileage, fair value is closer to $19.5K.
I also see there are 2 open recalls on this model year that would need to be addressed.
Would you consider $19K? Happy to discuss and can come see it soon."
""",
}


def _build_listing_context(
    listing: dict,
    score_breakdown: dict,
    user_preferences: dict,
) -> str:
    """Build a text context block from listing data for the LLM."""
    parts = []

    # Listing details
    year = listing.get("year", "?")
    make = listing.get("make", "?")
    model = listing.get("model", "?")
    trim = listing.get("trim", "")
    price = listing.get("price")
    mileage = listing.get("mileage")

    parts.append(f"## Vehicle: {year} {make} {model} {trim}".strip())
    if price:
        parts.append(f"- Listed Price: ${price:,.0f}" if isinstance(price, (int, float)) else f"- Listed Price: {price}")
    if mileage:
        parts.append(f"- Mileage: {mileage:,}" if isinstance(mileage, (int, float)) else f"- Mileage: {mileage}")

    for field in [
        "exterior_color", "interior_color", "location", "fuel_type",
        "transmission", "drivetrain", "dealer_name", "source_name",
    ]:
        val = listing.get(field)
        if val:
            label = field.replace("_", " ").title()
            parts.append(f"- {label}: {val}")

    # Score breakdown
    if score_breakdown:
        parts.append("\n## Score Breakdown")
        parts.append(f"- Composite Score: {score_breakdown.get('composite', 'N/A')}/10")
        parts.append(f"- Safety: {score_breakdown.get('safety', 'N/A')}")
        parts.append(f"- Reliability: {score_breakdown.get('reliability', 'N/A')}")
        parts.append(f"- Value: {score_breakdown.get('value', 'N/A')}")
        parts.append(f"- Efficiency: {score_breakdown.get('efficiency', 'N/A')}")
        parts.append(f"- Recall Penalty: {score_breakdown.get('recall_penalty', 'N/A')}")
        breakdown = score_breakdown.get("breakdown", {})
        if breakdown:
            # Include recall details if present
            recalls = breakdown.get("recalls", {})
            if recalls:
                parts.append(f"- Open Recalls: {recalls.get('recall_count', 0)}")
                for r in recalls.get("recalls", [])[:3]:
                    parts.append(f"  - {r.get('component', '?')}: {r.get('summary', '')[:150]}")
            # Include complaint details if present
            complaints = breakdown.get("complaints", {})
            if complaints:
                parts.append(f"- NHTSA Complaints: {complaints.get('complaint_count', 0)}")
                for cat in complaints.get("top_categories", [])[:3]:
                    parts.append(f"  - {cat.get('component', '?')}: {cat.get('count', 0)} complaints")
            # Include market value if present
            market_value = breakdown.get("market_value") or breakdown.get("kbb_value")
            if market_value:
                parts.append(f"- Estimated Market Value: ${market_value:,.0f}" if isinstance(market_value, (int, float)) else f"- Estimated Market Value: {market_value}")

    # User preferences for context
    if user_preferences:
        parts.append("\n## Buyer Preferences")
        if user_preferences.get("budget_max"):
            parts.append(f"- Budget: up to ${user_preferences['budget_max']:,.0f}")
        if user_preferences.get("location"):
            parts.append(f"- Location: {user_preferences['location']}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def draft_seller_message(
    listing: dict,
    score_breakdown: dict,
    user_preferences: dict,
    style: str = "friendly",
) -> str:
    """Draft a personalised message to a car seller.

    Args:
        listing: Vehicle listing dict with fields like year, make, model,
            price, mileage, exterior_color, location, etc.
        score_breakdown: Score breakdown dict with fields like composite,
            safety, reliability, value, efficiency, recall_penalty, and a
            nested ``breakdown`` dict with recalls/complaints/market data.
        user_preferences: User's search preferences dict (budget, location, etc.).
        style: Message style -- one of:
            - ``"friendly"``: Casual intro, genuine interest, ask about availability.
            - ``"direct"``: Straight to the point, ask about price/condition.
            - ``"negotiation"``: Reference market value, recalls, complaints
              to justify a lower offer.

    Returns:
        The drafted message as a plain text string.

    Example (negotiation style):
        "Hi! I'm interested in your 2020 RAV4. I noticed it's listed at $22K,
        but KBB fair market value for this year/mileage is around $19.5K. There
        are also 2 open recalls on this model year. Would you consider $19K?"
    """
    if style not in _STYLE_INSTRUCTIONS:
        logger.warning("Unknown message style '%s', falling back to 'friendly'", style)
        style = "friendly"

    settings = get_settings()
    gemini = GeminiClient(api_key=settings.GEMINI_API_KEY)

    system_instruction = (
        f"{_BASE_SYSTEM_PROMPT}\n\n"
        f"{_STYLE_INSTRUCTIONS[style]}"
    )

    context_block = _build_listing_context(listing, score_breakdown, user_preferences)

    year = listing.get("year", "?")
    make = listing.get("make", "?")
    model = listing.get("model", "?")

    prompt = (
        f"{context_block}\n\n"
        f"---\n\n"
        f'Draft a "{style}" style message to the seller of this '
        f"{year} {make} {model}."
    )

    logger.info("Drafting %s message for %s %s %s", style, year, make, model)

    response = await gemini.generate(
        prompt=prompt,
        system_instruction=system_instruction,
        temperature=0.8,  # Slightly creative for natural-sounding messages
    )

    return response.strip()
