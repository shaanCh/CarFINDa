"""
Negotiation Agent -- generates data-backed negotiation strategies.

Two outputs:
  1. Auto-DM message to seller (via message_drafter)
  2. In-person negotiation script with fair price, leverage points,
     competing listings, questions to ask, and walk-away price.
"""

import json
import logging

from app.config import get_settings
from app.services.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

NEGOTIATION_SYSTEM_PROMPT = """\
You are the CarFINDa Negotiation Strategist. You help buyers negotiate the
best possible price on a used car using real data: market values, recall data,
NHTSA complaints, competing listings, and vehicle condition factors.

## Your Job

Generate a comprehensive negotiation package with TWO outputs:

### 1. Opening DM Message
A respectful, data-backed message the buyer can send to the seller.
- Express genuine interest first.
- Reference 1-2 specific data points that justify a lower price.
- Propose a specific offer price with brief reasoning.
- Keep it conversational (not robotic or aggressive).
- 4-6 sentences max.

### 2. In-Person Negotiation Script
A structured guide the buyer brings when viewing the car:

**a) Fair Price Range**: Based on market data, what the car is actually worth.
   Include low/mid/high values.

**b) Opening Offer**: The price to start negotiating from (typically 10-15%
   below fair value). Explain the logic.

**c) Leverage Points**: Specific, factual points the buyer can raise:
   - Market comparisons ("Similar 2019 RAV4s are averaging $X in this area")
   - Open recalls ("There are X unaddressed recalls, including [component]")
   - Complaint patterns ("This model year has Y NHTSA complaints, Z for [component]")
   - Mileage/condition adjustments
   - Time on market (if known)

**d) Questions to Ask**: Specific questions based on known issues for this
   model/year. E.g., "Has the transmission been serviced? The 2018 model
   has 47 complaints for transmission failure."

**e) Competing Listings**: Reference similar cars at lower prices the buyer
   can mention as leverage.

**f) Walk-Away Price**: The maximum the buyer should pay. Above this, walk away.

**g) Negotiation Tips**: 2-3 tactical tips specific to this situation.

## Rules
- NEVER fabricate data. Only use information provided in the context.
- Be respectful -- the goal is a fair deal, not to insult the seller.
- All prices should include $ and commas.
- If data is missing for a section, note what the buyer should research.
"""

NEGOTIATION_SCHEMA = {
    "type": "object",
    "properties": {
        "opening_dm": {
            "type": "string",
            "description": "The message to send to the seller via DM.",
        },
        "fair_price": {
            "type": "object",
            "properties": {
                "low": {"type": "number", "description": "Low end of fair value range."},
                "mid": {"type": "number", "description": "Mid-point fair value."},
                "high": {"type": "number", "description": "High end of fair value range."},
                "explanation": {"type": "string", "description": "How this range was determined."},
            },
            "required": ["low", "mid", "high", "explanation"],
        },
        "opening_offer": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Suggested opening offer."},
                "reasoning": {"type": "string", "description": "Why this is the right starting point."},
            },
            "required": ["amount", "reasoning"],
        },
        "leverage_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Type: market, recalls, complaints, mileage, condition."},
                    "point": {"type": "string", "description": "The specific leverage point to raise."},
                    "impact": {"type": "string", "description": "How much this could reduce price (e.g. '$500-1,000')."},
                },
                "required": ["category", "point", "impact"],
            },
        },
        "questions_to_ask": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "why": {"type": "string", "description": "Why this question matters based on data."},
                },
                "required": ["question", "why"],
            },
        },
        "competing_listings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Brief description of competing listing."},
                    "price": {"type": "number"},
                    "advantage": {"type": "string", "description": "Why this competing listing gives leverage."},
                },
                "required": ["description", "price", "advantage"],
            },
        },
        "walk_away_price": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Maximum price before walking away."},
                "reasoning": {"type": "string", "description": "Why this is the ceiling."},
            },
            "required": ["amount", "reasoning"],
        },
        "negotiation_tips": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-3 tactical tips specific to this negotiation.",
        },
    },
    "required": [
        "opening_dm", "fair_price", "opening_offer", "leverage_points",
        "questions_to_ask", "walk_away_price", "negotiation_tips",
    ],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_negotiation_strategy(
    listing: dict,
    score_data: dict,
    enrichment_data: dict,
    user_preferences: dict,
    competing_listings: list[dict] | None = None,
) -> dict:
    """Generate a full negotiation strategy for a specific listing.

    Args:
        listing: The target listing dict (year, make, model, price, mileage, etc.).
        score_data: The ListingScore breakdown dict.
        enrichment_data: The ``data`` dict from scoring pipeline with safety,
            complaints, recalls, fuel_economy, market_value sub-dicts.
        user_preferences: The user's parsed preferences.
        competing_listings: Optional list of similar listings at different prices
            to use as leverage.

    Returns:
        Dict matching NEGOTIATION_SCHEMA with opening_dm, fair_price,
        opening_offer, leverage_points, questions, walk_away_price, and tips.
    """
    settings = get_settings()

    if not settings.GEMINI_API_KEY:
        return _fallback_negotiation(listing, enrichment_data)

    gemini = GeminiClient(api_key=settings.GEMINI_API_KEY)

    context = _build_negotiation_context(
        listing, score_data, enrichment_data, user_preferences, competing_listings
    )

    logger.info(
        "Generating negotiation strategy for %s %s %s at $%s",
        listing.get("year"), listing.get("make"), listing.get("model"),
        f"{listing.get('price', 0):,.0f}",
    )

    try:
        result = await gemini.generate_structured(
            prompt=context,
            system_instruction=NEGOTIATION_SYSTEM_PROMPT,
            response_schema=NEGOTIATION_SCHEMA,
            temperature=0.4,
        )
        return result
    except Exception as exc:
        logger.error("Negotiation strategy generation failed: %s", exc)
        return _fallback_negotiation(listing, enrichment_data)


def _build_negotiation_context(
    listing: dict,
    score_data: dict,
    enrichment_data: dict,
    user_preferences: dict,
    competing_listings: list[dict] | None,
) -> str:
    """Build the prompt context for negotiation strategy generation."""
    parts = []

    year = listing.get("year", "?")
    make = listing.get("make", "?")
    model = listing.get("model", "?")
    trim = listing.get("trim", "")
    price = listing.get("price", 0)
    mileage = listing.get("mileage", 0)

    parts.append(f"## Target Vehicle: {year} {make} {model} {trim}".strip())
    parts.append(f"- Listed Price: ${price:,.0f}" if price else "- Listed Price: Unknown")
    parts.append(f"- Mileage: {mileage:,}" if mileage else "- Mileage: Unknown")
    parts.append(f"- Location: {listing.get('location', 'N/A')}")
    parts.append(f"- Source: {listing.get('source_name', 'N/A')}")
    parts.append(f"- Source URL: {listing.get('source_url', 'N/A')}")

    # Score breakdown
    if score_data:
        parts.append(f"\n## Score Breakdown")
        composite = score_data.get("composite_score", score_data.get("composite", "N/A"))
        parts.append(f"- Composite: {composite}/100")
        for key in ["safety_score", "reliability_score", "value_score",
                     "efficiency_score", "recall_score"]:
            val = score_data.get(key)
            if val is not None:
                label = key.replace("_score", "").replace("_", " ").title()
                parts.append(f"- {label}: {val}/100")

        breakdown = score_data.get("breakdown", {})
        if breakdown:
            parts.append(f"- Score Details: {json.dumps(breakdown, default=str)}")

    # Enrichment data
    if enrichment_data:
        # Market value
        market = enrichment_data.get("market_value", {})
        if market.get("estimated_value"):
            parts.append(f"\n## Market Value Data")
            parts.append(f"- Estimated Value: ${market['estimated_value']:,.0f}")
            if market.get("value_low"):
                parts.append(f"- Value Range: ${market['value_low']:,.0f} - ${market.get('value_high', 0):,.0f}")
            parts.append(f"- Confidence: {market.get('confidence', 'unknown')}")
            parts.append(f"- Source: {market.get('source', 'unknown')}")

        # Recalls
        recalls = enrichment_data.get("recalls", {})
        if recalls.get("recall_count"):
            parts.append(f"\n## NHTSA Recalls ({recalls['recall_count']})")
            for r in recalls.get("recalls", [])[:5]:
                parts.append(f"- [{r.get('nhtsa_campaign_number', '?')}] {r.get('component', '?')}: {r.get('summary', '')[:200]}")

        # Complaints
        complaints = enrichment_data.get("complaints", {})
        if complaints.get("complaint_count"):
            parts.append(f"\n## NHTSA Complaints ({complaints['complaint_count']} total)")
            for cat in complaints.get("top_categories", [])[:5]:
                parts.append(f"- {cat.get('component', '?')}: {cat.get('count', 0)} complaints")

        # Fuel economy
        fuel = enrichment_data.get("fuel_economy", {})
        if fuel.get("combined_mpg"):
            parts.append(f"\n## Fuel Economy")
            parts.append(f"- Combined: {fuel['combined_mpg']} MPG")

        # Ownership cost
        ownership = enrichment_data.get("ownership_cost", {})
        if ownership.get("annual_average") and ownership["annual_average"] > 0:
            parts.append(f"\n## Ownership Cost")
            parts.append(f"- Annual Average: ${ownership['annual_average']:,.0f}")

    # User preferences
    if user_preferences:
        parts.append(f"\n## Buyer Context")
        if user_preferences.get("budget_max"):
            parts.append(f"- Budget: up to ${user_preferences['budget_max']:,.0f}")
        if user_preferences.get("location"):
            parts.append(f"- Location: {user_preferences['location']}")
        if user_preferences.get("dealbreakers"):
            parts.append(f"- Dealbreakers: {', '.join(user_preferences['dealbreakers'])}")

    # Competing listings
    if competing_listings:
        parts.append(f"\n## Competing Listings ({len(competing_listings)})")
        for i, comp in enumerate(competing_listings[:5], 1):
            cy = comp.get("year", "?")
            cm = comp.get("make", "?")
            cmod = comp.get("model", "?")
            cp = comp.get("price", 0)
            cmil = comp.get("mileage", 0)
            parts.append(
                f"{i}. {cy} {cm} {cmod} - ${cp:,.0f} - {cmil:,} mi - {comp.get('location', 'N/A')}"
            )

    parts.append(
        "\n---\n"
        "Generate a complete negotiation strategy for this vehicle."
    )

    return "\n".join(parts)


def _fallback_negotiation(listing: dict, enrichment_data: dict) -> dict:
    """Simple fallback when LLM is unavailable."""
    price = listing.get("price", 0) or 0
    market = enrichment_data.get("market_value", {})
    estimated = market.get("estimated_value", price)
    low = market.get("value_low", estimated * 0.85)
    high = market.get("value_high", estimated * 1.15)

    year = listing.get("year", "?")
    make = listing.get("make", "?")
    model = listing.get("model", "?")

    opening = round(estimated * 0.88, -2) if estimated else round(price * 0.88, -2)
    walk_away = round(estimated * 1.05, -2) if estimated else round(price * 1.02, -2)

    return {
        "opening_dm": (
            f"Hi! I'm interested in your {year} {make} {model} listed at "
            f"${price:,.0f}. Based on current market data, similar vehicles "
            f"are priced around ${estimated:,.0f}. Would you consider "
            f"${opening:,.0f}? I'm a serious buyer and can come see it soon."
        ),
        "fair_price": {
            "low": low,
            "mid": estimated,
            "high": high,
            "explanation": "Based on market value estimation. Verify with KBB/Edmunds.",
        },
        "opening_offer": {
            "amount": opening,
            "reasoning": "~12% below estimated market value as a starting point.",
        },
        "leverage_points": [],
        "questions_to_ask": [
            {
                "question": "Can I see the maintenance records?",
                "why": "Verifies the car has been properly maintained.",
            },
            {
                "question": "Has it been in any accidents?",
                "why": "Accident history significantly affects value.",
            },
        ],
        "competing_listings": [],
        "walk_away_price": {
            "amount": walk_away,
            "reasoning": "Do not pay more than ~5% above estimated market value.",
        },
        "negotiation_tips": [
            "Always inspect the car in daylight and take it for a test drive.",
            "Get a pre-purchase inspection from an independent mechanic ($100-200).",
            "If the seller won't negotiate, be prepared to walk away.",
        ],
    }
