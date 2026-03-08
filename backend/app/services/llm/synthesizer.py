"""
LLM Synthesizer -- picks the best listings for a user and explains WHY.

Takes scored listings + user context (budget, priorities, location, use case)
and produces personalized recommendations with plain-English reasoning.
"""

import json
import logging
from typing import Optional

from app.config import get_settings
from app.services.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """\
You are the CarFINDa Recommendation Engine. You receive a user's car search
context (what they asked for, why, and their situation) along with scored
vehicle listings from multiple marketplaces.

## Your Job

1. **Pick the top recommendations** (up to 5) from the scored listings.
   Rank them by how well they fit THIS user's specific needs, not just by
   raw composite score. A lower-scored car that perfectly matches a user's
   priorities can beat a higher-scored car that doesn't.

2. **For each recommendation, explain WHY** in 2-4 sentences tied to the
   user's stated needs. Reference specific data points: safety ratings,
   recall counts, market value vs listing price, fuel economy, complaint
   patterns. Never fabricate data.

3. **Provide a search summary** that captures the overall landscape:
   how many cars matched, price range found, any patterns or warnings.

4. **Flag red flags** across all listings: recalls, price anomalies,
   high complaint models.

## Output Rules

- Tie every recommendation back to the user's stated needs and context.
- Use concrete numbers: "$2,100 below market value", "4/5 NHTSA stars",
  "23 MPG combined", "3 open recalls".
- If you don't have data for a metric, say so honestly.
- Format prices with $ and commas. Format mileage with commas.
- Be concise but thorough. Each recommendation explanation should be
  specific and actionable, not generic.
- Return valid JSON matching the provided schema.
"""

# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "search_summary": {
            "type": "string",
            "description": "2-3 sentence overview of results: count, price range, patterns.",
        },
        "recommendations": {
            "type": "array",
            "description": "Top recommended listings, ranked by fit for this user.",
            "items": {
                "type": "object",
                "properties": {
                    "listing_id": {
                        "type": "string",
                        "description": "The ID of the recommended listing.",
                    },
                    "rank": {
                        "type": "number",
                        "description": "Rank position (1 = best fit).",
                    },
                    "headline": {
                        "type": "string",
                        "description": "One-line summary like 'Best Overall Value' or 'Safest Pick for Families'.",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "2-4 sentences explaining WHY this car fits the user's needs. Cite specific data.",
                    },
                    "strengths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key strengths as bullet points (e.g. '$1,500 below market', '5-star safety').",
                    },
                    "concerns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Any concerns to note (e.g. '2 open recalls', 'higher mileage').",
                    },
                },
                "required": ["listing_id", "rank", "headline", "explanation", "strengths", "concerns"],
            },
        },
        "red_flags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Global warnings across all listings (model-year issues, recall patterns, etc.).",
        },
    },
    "required": ["search_summary", "recommendations", "red_flags"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def synthesize_recommendations(
    scored_listings: list[dict],
    user_query: str,
    parsed_preferences: dict,
    max_recommendations: int = 5,
) -> dict:
    """Generate personalized recommendations from scored listings.

    Args:
        scored_listings: Listings enriched with ``score`` and ``data`` dicts
            from the scoring pipeline.
        user_query: The user's original natural language query.
        parsed_preferences: Structured preferences from the intake agent.
        max_recommendations: Maximum number of recommendations to return.

    Returns:
        Dict with ``search_summary``, ``recommendations`` (list), and ``red_flags``.
    """
    settings = get_settings()

    if not settings.GEMINI_API_KEY:
        return _fallback_synthesis(scored_listings, max_recommendations)

    gemini = GeminiClient(api_key=settings.GEMINI_API_KEY)

    # Build context for the LLM
    context = _build_synthesis_context(
        scored_listings, user_query, parsed_preferences, max_recommendations
    )

    logger.info(
        "Synthesizing recommendations for %d listings (query: %s)",
        len(scored_listings),
        user_query[:100],
    )

    try:
        result = await gemini.generate_structured(
            prompt=context,
            system_instruction=SYNTHESIS_SYSTEM_PROMPT,
            response_schema=SYNTHESIS_SCHEMA,
            temperature=0.4,
        )
        return result
    except Exception as exc:
        logger.error("LLM synthesis failed, using fallback: %s", exc)
        return _fallback_synthesis(scored_listings, max_recommendations)


def _build_synthesis_context(
    scored_listings: list[dict],
    user_query: str,
    parsed_preferences: dict,
    max_recommendations: int,
) -> str:
    """Build the prompt context block for the synthesizer."""
    parts = []

    parts.append(f'## User Query\n"{user_query}"')
    parts.append(f"\n## Parsed Preferences\n{json.dumps(parsed_preferences, indent=2, default=str)}")
    parts.append(f"\n## Instructions\nPick the top {max_recommendations} listings that best fit this user.")

    parts.append(f"\n## Scored Listings ({len(scored_listings)} total)\n")

    for i, listing in enumerate(scored_listings[:30], 1):  # Cap context at 30
        score = listing.get("score", {})
        data = listing.get("data", {})

        lid = listing.get("id", f"listing_{i}")
        year = listing.get("year", "?")
        make = listing.get("make", "?")
        model = listing.get("model", "?")
        trim = listing.get("trim", "")
        price = listing.get("price")
        mileage = listing.get("mileage")

        parts.append(f"### {i}. {year} {make} {model} {trim}".strip())
        parts.append(f"- ID: {lid}")
        if price:
            parts.append(f"- Price: ${price:,.0f}")
        if mileage:
            parts.append(f"- Mileage: {mileage:,}")
        parts.append(f"- Location: {listing.get('location', 'N/A')}")
        parts.append(f"- Source: {listing.get('source_name', 'N/A')}")

        # Composite score
        composite = score.get("composite_score", score.get("composite", "N/A"))
        parts.append(f"- Composite Score: {composite}/100")

        # Component scores
        for key in ["safety_score", "reliability_score", "value_score",
                     "efficiency_score", "ownership_cost_score", "recall_score"]:
            val = score.get(key)
            if val is not None:
                label = key.replace("_score", "").replace("_", " ").title()
                parts.append(f"  - {label}: {val}/100")

        # Data highlights
        safety = data.get("safety", {})
        if safety.get("overall_rating"):
            parts.append(f"- NHTSA Safety: {safety['overall_rating']}/5 stars")

        complaints = data.get("complaints", {})
        if complaints.get("complaint_count"):
            parts.append(f"- NHTSA Complaints: {complaints['complaint_count']}")
            top_cats = complaints.get("top_categories", [])[:3]
            for cat in top_cats:
                parts.append(f"  - {cat.get('component', '?')}: {cat.get('count', 0)}")

        recalls = data.get("recalls", {})
        if recalls.get("recall_count"):
            parts.append(f"- Open Recalls: {recalls['recall_count']}")

        fuel = data.get("fuel_economy", {})
        if fuel.get("combined_mpg"):
            parts.append(f"- MPG: {fuel['combined_mpg']} combined")

        market = data.get("market_value", {})
        if market.get("estimated_value"):
            ev = market["estimated_value"]
            parts.append(f"- Estimated Market Value: ${ev:,.0f}")
            if price and ev:
                diff = ev - price
                if diff > 0:
                    parts.append(f"  - ${diff:,.0f} BELOW market (good deal)")
                elif diff < 0:
                    parts.append(f"  - ${abs(diff):,.0f} ABOVE market")

        parts.append("")

    return "\n".join(parts)


def _fallback_synthesis(
    scored_listings: list[dict],
    max_recommendations: int,
) -> dict:
    """Generate a simple fallback when LLM is unavailable."""
    # Sort by composite score
    sorted_listings = sorted(
        scored_listings,
        key=lambda x: x.get("score", {}).get("composite_score",
                       x.get("score", {}).get("composite", 0)),
        reverse=True,
    )

    recommendations = []
    for i, listing in enumerate(sorted_listings[:max_recommendations], 1):
        score = listing.get("score", {})
        composite = score.get("composite_score", score.get("composite", 0))
        lid = listing.get("id", f"listing_{i}")
        year = listing.get("year", "?")
        make = listing.get("make", "?")
        model_name = listing.get("model", "?")
        price = listing.get("price", 0)

        recommendations.append({
            "listing_id": lid,
            "rank": i,
            "headline": f"#{i} Match" if i > 1 else "Top Match",
            "explanation": (
                f"The {year} {make} {model_name} scored {composite}/100 overall. "
                f"Listed at ${price:,.0f}."
            ),
            "strengths": [f"Composite score: {composite}/100"],
            "concerns": [],
        })

    return {
        "search_summary": (
            f"Found {len(scored_listings)} listings. "
            f"Showing top {len(recommendations)} by composite score."
        ),
        "recommendations": recommendations,
        "red_flags": [],
    }
