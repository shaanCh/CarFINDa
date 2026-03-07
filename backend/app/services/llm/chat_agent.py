"""
Chat Agent -- LLM assistant for post-search interactions.

Answers questions about scored car listings, explains scores, highlights
red flags, compares vehicles, drafts seller messages, and generates
negotiation talking points.
"""

import json
import logging
from typing import Optional

from app.services.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """\
You are CarFINDa Assistant, an expert automotive advisor helping users evaluate
used car listings. You have deep knowledge of vehicle reliability, safety ratings,
common problems, fair market pricing, NHTSA recalls/complaints, and negotiation tactics.

## Your Capabilities

1. **Explain Scores** -- When a user asks why a car scored high or low, break down
   the composite score into its components (safety, reliability, value, efficiency,
   recall penalty) and explain what drove each sub-score.

2. **Highlight Red Flags** -- Proactively point out concerning patterns:
   - Open recalls (especially safety-critical ones like airbags, brakes, fuel systems)
   - High complaint counts for specific components (transmission, engine, electrical)
   - Price significantly above or below market value (could indicate hidden issues)
   - Unusually low mileage for the age (potential odometer rollback)
   - Salvage/rebuilt titles, accident history, flood damage

3. **Compare Listings** -- When asked to compare two or more cars, create a clear
   side-by-side comparison covering: price, mileage, year, scores, known issues,
   ownership costs, and your recommendation with reasoning.

4. **Draft Seller Messages** -- Help users craft messages to sellers. Offer three
   styles: friendly (casual inquiry), direct (straight to business), and negotiation
   (leverage data to propose a fair price).

5. **Negotiation Talking Points** -- Using recall data, complaint patterns, market
   pricing, and condition factors, generate specific points the buyer can use to
   negotiate a better price. Always be factual; never fabricate data.

6. **Suggest Related Searches** -- If the user seems unsatisfied with results or
   asks "what else?", suggest modified search criteria that might yield better matches.

## Data Context

You will receive context about the user's search results, including:
- `listings`: Array of vehicle listings with details (year, make, model, price, mileage, etc.)
- `scores`: Score breakdowns for each listing (safety, reliability, value, efficiency, recall_penalty, composite)
- `preferences`: The user's original search preferences (budget, body types, dealbreakers, etc.)
- `recalls`: Any known NHTSA recalls for the vehicles
- `complaints`: NHTSA complaint summaries for the vehicles

## Response Guidelines

- Be concise but thorough. Use bullet points and clear structure.
- Always cite specific data when making claims (e.g., "This model year has 47 NHTSA complaints,
  23 of which are for the transmission").
- When discussing price, reference the user's budget and market comparisons.
- Never make up recall numbers, complaint counts, or safety ratings. If data is missing,
  say so and suggest the user verify.
- Use a friendly, knowledgeable tone. You are the user's trusted car-buying advisor.
- If the user asks something outside your scope (financing, insurance, registration),
  acknowledge the question and suggest they consult the relevant professional.
- Format monetary values with commas and dollar signs (e.g., $18,500).
- Format mileage with commas (e.g., 45,000 miles).
"""


def _build_context_block(context: dict) -> str:
    """Serialize the search context into a text block for the system prompt."""
    parts = []

    # User preferences
    preferences = context.get("preferences")
    if preferences:
        parts.append("## User Preferences")
        parts.append(json.dumps(preferences, indent=2, default=str))

    # Listings with scores
    listings = context.get("listings", [])
    scores = context.get("scores", {})
    if listings:
        parts.append(f"\n## Listings ({len(listings)} results)")
        for i, listing in enumerate(listings, 1):
            lid = listing.get("id", f"listing_{i}")
            parts.append(f"\n### Listing {i}: {listing.get('year', '?')} {listing.get('make', '?')} {listing.get('model', '?')}")
            parts.append(f"- ID: {lid}")
            parts.append(f"- Price: ${listing.get('price', 'N/A'):,.0f}" if isinstance(listing.get('price'), (int, float)) else f"- Price: {listing.get('price', 'N/A')}")
            parts.append(f"- Mileage: {listing.get('mileage', 'N/A'):,}" if isinstance(listing.get('mileage'), (int, float)) else f"- Mileage: {listing.get('mileage', 'N/A')}")
            parts.append(f"- Trim: {listing.get('trim', 'N/A')}")
            parts.append(f"- Location: {listing.get('location', 'N/A')}")
            parts.append(f"- Source: {listing.get('source_name', 'N/A')}")
            parts.append(f"- VIN: {listing.get('vin', 'N/A')}")
            parts.append(f"- Color: {listing.get('exterior_color', 'N/A')}")
            parts.append(f"- Fuel: {listing.get('fuel_type', 'N/A')}")
            parts.append(f"- Transmission: {listing.get('transmission', 'N/A')}")
            parts.append(f"- Drivetrain: {listing.get('drivetrain', 'N/A')}")

            # Score breakdown
            score = scores.get(lid)
            if score:
                parts.append(f"- **Composite Score**: {score.get('composite', 'N/A')}/10")
                parts.append(f"  - Safety: {score.get('safety', 'N/A')}")
                parts.append(f"  - Reliability: {score.get('reliability', 'N/A')}")
                parts.append(f"  - Value: {score.get('value', 'N/A')}")
                parts.append(f"  - Efficiency: {score.get('efficiency', 'N/A')}")
                parts.append(f"  - Recall Penalty: {score.get('recall_penalty', 'N/A')}")
                breakdown = score.get("breakdown", {})
                if breakdown:
                    parts.append(f"  - Details: {json.dumps(breakdown, default=str)}")

    # Recalls
    recalls = context.get("recalls", {})
    if recalls:
        parts.append("\n## NHTSA Recalls")
        for vehicle_key, recall_data in recalls.items():
            parts.append(f"\n### {vehicle_key}")
            parts.append(f"- Recall count: {recall_data.get('recall_count', 0)}")
            for r in recall_data.get("recalls", [])[:5]:
                parts.append(f"  - [{r.get('nhtsa_campaign_number', '?')}] {r.get('component', '?')}: {r.get('summary', '')[:200]}")

    # Complaints
    complaints = context.get("complaints", {})
    if complaints:
        parts.append("\n## NHTSA Complaints")
        for vehicle_key, complaint_data in complaints.items():
            parts.append(f"\n### {vehicle_key}")
            parts.append(f"- Total complaints: {complaint_data.get('complaint_count', 0)}")
            for cat in complaint_data.get("top_categories", []):
                parts.append(f"  - {cat.get('component', '?')}: {cat.get('count', 0)} complaints")

    return "\n".join(parts) if parts else "(No context data provided.)"


class CarAssistant:
    """LLM assistant that answers questions about scored car listings."""

    def __init__(self, gemini: GeminiClient):
        self.gemini = gemini

    async def chat(
        self,
        message: str,
        conversation_history: list[dict],
        context: dict,
    ) -> str:
        """Handle user questions about their car search results.

        Args:
            message: The user's latest message.
            conversation_history: Previous messages in the conversation.
                Each dict has ``role`` ("user" or "model") and ``content`` (str).
            context: Search context dict containing:
                - ``listings``: List of listing dicts
                - ``scores``: Dict mapping listing IDs to score breakdowns
                - ``preferences``: User's search preferences dict
                - ``recalls``: Dict mapping vehicle keys to recall data
                - ``complaints``: Dict mapping vehicle keys to complaint data

        Returns:
            The assistant's text response.

        Capabilities:
            - Explain why a car scored high/low
            - Highlight red flags (recalls, complaint patterns, price anomalies)
            - Compare two listings side-by-side
            - Draft messages to sellers
            - Generate negotiation talking points using complaint/recall data
            - Suggest related searches
        """
        # Build the full system instruction with data context
        context_block = _build_context_block(context)
        system_instruction = (
            f"{CHAT_SYSTEM_PROMPT}\n\n"
            f"---\n\n"
            f"# Current Search Data\n\n"
            f"{context_block}"
        )

        # Build conversation for multi-turn chat
        messages = list(conversation_history)
        messages.append({"role": "user", "content": message})

        response = await self.gemini.chat(
            messages=messages,
            system_instruction=system_instruction,
            temperature=0.7,
        )

        return response
