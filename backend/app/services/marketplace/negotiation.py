"""
AI-powered negotiation engine for Facebook Marketplace.

Uses Gemini to craft intelligent opening messages and negotiate pricing
based on vehicle scoring data (market value, recalls, complaints, etc.).

Flow:
  1. User approves a listing for outreach
  2. Engine generates a personalized opening message using scoring data
  3. When seller replies, engine analyzes the response and crafts a counter
  4. Continues negotiating until a deal is reached or user intervenes
"""

import logging
from typing import Any, Optional

from app.config import get_settings
from app.services.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_NEGOTIATOR_SYSTEM = """You are a car buyer's negotiation assistant on Facebook Marketplace.
You write short, friendly, casual messages to sellers — like a real person texting.

Rules:
- Keep messages under 3-4 sentences. Marketplace DMs are casual.
- Be polite but firm on price. Never sound desperate.
- Reference specific data points naturally (don't dump stats).
- Never reveal you are an AI or automated system.
- Use the buyer's first name if provided, otherwise write in first person.
- Adjust tone based on conversation stage:
  * Opening: friendly, interested, mention what you like about the car
  * Counter-offer: reference a specific reason the price should be lower
  * Follow-up: brief, keep momentum going
  * Walk-away: polite but create urgency ("I have a few other options I'm looking at")
"""

_OPENING_PROMPT = """Generate an opening message to a Facebook Marketplace vehicle seller.

LISTING:
- Title: {title}
- Asking Price: ${price:,.0f}
- Year: {year}
- Make: {make}
- Model: {model}
- Mileage: {mileage}
- Location: {location}

SCORING DATA:
{scoring_summary}

TARGET OFFER: ${target_price:,.0f} (this is what we want to pay)

STRATEGY: {strategy}

Write ONLY the message text, nothing else. No quotes, no "Message:" prefix."""

_COUNTER_PROMPT = """Generate a counter-offer response to a Facebook Marketplace seller.

LISTING:
- Title: {title}
- Asking Price: ${asking_price:,.0f}
- Year/Make/Model: {year} {make} {model}
- Mileage: {mileage}

SCORING DATA:
{scoring_summary}

OUR TARGET: ${target_price:,.0f}
OUR MAX: ${max_price:,.0f}

CONVERSATION SO FAR:
{conversation_history}

SELLER'S LATEST MESSAGE:
{seller_message}

STRATEGY: {strategy}

Write ONLY the reply message text. Keep it casual and short (2-3 sentences max)."""

_REPLY_ANALYSIS_PROMPT = """Analyze this seller reply from a Facebook Marketplace negotiation.

LISTING: {year} {make} {model} — asking ${asking_price:,.0f}
OUR LAST OFFER: ${our_last_offer:,.0f}

SELLER'S REPLY:
{seller_message}

Classify the reply and extract info. Return JSON:
{{
  "intent": "accept" | "counter" | "reject" | "question" | "info" | "unclear",
  "seller_counter_price": <number or null if not a counter-offer>,
  "sentiment": "positive" | "neutral" | "negative" | "firm",
  "key_points": ["list of important things the seller said"],
  "recommended_action": "accept" | "counter" | "hold" | "walk_away"
}}"""


# ---------------------------------------------------------------------------
# Negotiation engine
# ---------------------------------------------------------------------------

class NegotiationEngine:
    """AI-powered negotiation engine for vehicle purchases."""

    def __init__(self):
        self._gemini: Optional[GeminiClient] = None

    def _get_gemini(self) -> GeminiClient:
        if self._gemini is None:
            settings = get_settings()
            self._gemini = GeminiClient(api_key=settings.GEMINI_API_KEY)
        return self._gemini

    # ------------------------------------------------------------------
    # Opening message
    # ------------------------------------------------------------------

    async def generate_opening_message(
        self,
        listing: dict,
        scoring_data: Optional[dict] = None,
        target_price: Optional[float] = None,
        strategy: str = "balanced",
    ) -> dict:
        """
        Generate a personalized opening DM for a Marketplace listing.

        Args:
            listing:      Listing dict (title, price, year, make, model, mileage, etc.)
            scoring_data: Enriched scoring data from the pipeline (optional).
            target_price: Desired purchase price. Defaults to 85% of asking.
            strategy:     "aggressive" (lowball), "balanced", or "friendly" (near asking).

        Returns:
            dict with: message (str), target_price (float), strategy_notes (str)
        """
        price = float(listing.get("price") or 0)
        if not target_price:
            target_price = self._calculate_target_price(price, scoring_data, strategy)

        scoring_summary = self._build_scoring_summary(listing, scoring_data)
        strategy_text = self._get_strategy_text(strategy, price, target_price, scoring_data)

        prompt = _OPENING_PROMPT.format(
            title=listing.get("title", "Vehicle"),
            price=price,
            year=listing.get("year", ""),
            make=listing.get("make", ""),
            model=listing.get("model", ""),
            mileage=f"{listing.get('mileage', 'N/A'):,}" if listing.get("mileage") else "N/A",
            location=listing.get("location", ""),
            scoring_summary=scoring_summary,
            target_price=target_price,
            strategy=strategy_text,
        )

        gemini = self._get_gemini()
        message = await gemini.generate(
            prompt=prompt,
            system_instruction=_NEGOTIATOR_SYSTEM,
            temperature=0.7,
        )

        return {
            "message": message.strip(),
            "target_price": target_price,
            "strategy_notes": strategy_text,
        }

    # ------------------------------------------------------------------
    # Counter-offer / reply
    # ------------------------------------------------------------------

    async def generate_counter(
        self,
        listing: dict,
        seller_message: str,
        conversation_history: list[dict],
        scoring_data: Optional[dict] = None,
        target_price: Optional[float] = None,
        max_price: Optional[float] = None,
        strategy: str = "balanced",
    ) -> dict:
        """
        Generate a counter-offer response to a seller's message.

        Args:
            listing:              Listing dict.
            seller_message:       The seller's latest reply.
            conversation_history: List of {role: "buyer"|"seller", message: str}.
            scoring_data:         Enriched scoring data (optional).
            target_price:         Our ideal price.
            max_price:            Absolute max we'll pay.
            strategy:             Negotiation strategy.

        Returns:
            dict with: message (str), analysis (dict), should_send (bool)
        """
        price = float(listing.get("price") or 0)
        if not target_price:
            target_price = self._calculate_target_price(price, scoring_data, strategy)
        if not max_price:
            max_price = target_price * 1.10  # 10% above target as max

        # First, analyze the seller's reply
        analysis = await self.analyze_reply(
            listing=listing,
            seller_message=seller_message,
            our_last_offer=self._get_last_offer(conversation_history, target_price),
        )

        # If seller accepted, no need to counter
        if analysis.get("intent") == "accept":
            return {
                "message": "That works for me! When would be a good time to come see it?",
                "analysis": analysis,
                "should_send": True,
            }

        # If seller's counter is within our max, consider accepting
        seller_counter = analysis.get("seller_counter_price")
        if seller_counter and seller_counter <= max_price:
            if seller_counter <= target_price:
                return {
                    "message": f"${seller_counter:,.0f} works for me. When can I come take a look?",
                    "analysis": analysis,
                    "should_send": True,
                }

        scoring_summary = self._build_scoring_summary(listing, scoring_data)
        strategy_text = self._get_strategy_text(strategy, price, target_price, scoring_data)

        history_text = "\n".join(
            f"{'Us' if m['role'] == 'buyer' else 'Seller'}: {m['message']}"
            for m in conversation_history[-6:]  # last 6 messages for context
        )

        prompt = _COUNTER_PROMPT.format(
            title=listing.get("title", "Vehicle"),
            asking_price=price,
            year=listing.get("year", ""),
            make=listing.get("make", ""),
            model=listing.get("model", ""),
            mileage=f"{listing.get('mileage', 'N/A'):,}" if listing.get("mileage") else "N/A",
            scoring_summary=scoring_summary,
            target_price=target_price,
            max_price=max_price,
            conversation_history=history_text or "(opening message)",
            seller_message=seller_message,
            strategy=strategy_text,
        )

        gemini = self._get_gemini()
        message = await gemini.generate(
            prompt=prompt,
            system_instruction=_NEGOTIATOR_SYSTEM,
            temperature=0.7,
        )

        # Don't auto-send walk-away messages
        recommended = analysis.get("recommended_action", "counter")
        should_send = recommended in ("counter", "accept")

        return {
            "message": message.strip(),
            "analysis": analysis,
            "should_send": should_send,
        }

    # ------------------------------------------------------------------
    # Reply analysis
    # ------------------------------------------------------------------

    async def analyze_reply(
        self,
        listing: dict,
        seller_message: str,
        our_last_offer: float,
    ) -> dict:
        """Analyze a seller's reply to understand intent and extract counter-price."""
        prompt = _REPLY_ANALYSIS_PROMPT.format(
            year=listing.get("year", ""),
            make=listing.get("make", ""),
            model=listing.get("model", ""),
            asking_price=float(listing.get("price") or 0),
            our_last_offer=our_last_offer,
            seller_message=seller_message,
        )

        gemini = self._get_gemini()
        try:
            result = await gemini.generate_structured(
                prompt=prompt,
                system_instruction="You are a negotiation analysis assistant. Return structured JSON only.",
                response_schema={
                    "type": "object",
                    "properties": {
                        "intent": {"type": "string"},
                        "seller_counter_price": {"type": "number"},
                        "sentiment": {"type": "string"},
                        "key_points": {"type": "array", "items": {"type": "string"}},
                        "recommended_action": {"type": "string"},
                    },
                    "required": ["intent", "sentiment", "recommended_action"],
                },
                temperature=0.1,
            )
            return result
        except Exception as exc:
            logger.error("Reply analysis failed: %s", exc)
            return {
                "intent": "unclear",
                "sentiment": "neutral",
                "recommended_action": "hold",
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _calculate_target_price(
        self,
        asking_price: float,
        scoring_data: Optional[dict],
        strategy: str,
    ) -> float:
        """Calculate a target offer price based on market data and strategy."""
        if not asking_price or asking_price <= 0:
            return 0

        # Start from market value if available
        market = (scoring_data or {}).get("data", {}).get("market_value", {})
        estimated_value = float(market.get("estimated_value", 0) or 0)
        value_low = float(market.get("value_low", 0) or 0)

        if estimated_value > 0:
            base = estimated_value
        else:
            base = asking_price

        # Adjust by strategy
        multipliers = {
            "aggressive": 0.80,
            "balanced": 0.88,
            "friendly": 0.95,
        }
        target = base * multipliers.get(strategy, 0.88)

        # Use value_low as a floor if available
        if value_low > 0:
            target = max(target, value_low)

        # Apply penalties for issues found in scoring
        score_data = scoring_data or {}
        recalls = (score_data.get("data", {}).get("recalls", {})
                   .get("recall_count", 0))
        complaints = (score_data.get("data", {}).get("complaints", {})
                      .get("complaint_count", 0))

        if recalls and recalls > 0:
            target *= 0.97  # 3% discount per recall concern
        if complaints and complaints > 20:
            target *= 0.98  # 2% discount for high complaints

        return round(target, -2)  # round to nearest $100

    def _build_scoring_summary(
        self,
        listing: dict,
        scoring_data: Optional[dict],
    ) -> str:
        """Build a text summary of scoring data for the LLM prompt."""
        if not scoring_data:
            return "No scoring data available."

        lines = []
        data = scoring_data.get("data", {})
        score = scoring_data.get("score", {})

        # Market value
        mv = data.get("market_value", {})
        est_val = mv.get("estimated_value")
        if est_val:
            price = float(listing.get("price") or 0)
            diff = price - est_val
            if diff > 0:
                lines.append(f"- Market value: ${est_val:,.0f} (OVERPRICED by ${diff:,.0f})")
            elif diff < 0:
                lines.append(f"- Market value: ${est_val:,.0f} (underpriced by ${abs(diff):,.0f})")
            else:
                lines.append(f"- Market value: ${est_val:,.0f} (fairly priced)")

        # Recalls
        recalls = data.get("recalls", {})
        rc = recalls.get("recall_count", 0)
        if rc > 0:
            lines.append(f"- Open recalls: {rc} (leverage point — safety concern)")

        # Complaints
        complaints = data.get("complaints", {})
        cc = complaints.get("complaint_count", 0)
        if cc > 10:
            lines.append(f"- NHTSA complaints: {cc} (above average — reliability concern)")

        # Safety
        safety = data.get("safety", {})
        sr = safety.get("overall_rating")
        if sr:
            lines.append(f"- Safety rating: {sr}/5 stars")

        # Ownership cost
        oc = data.get("ownership_cost", {})
        annual = oc.get("annual_average")
        if annual:
            lines.append(f"- Annual ownership cost: ${annual:,.0f}/yr")

        # Composite score
        cs = score.get("composite_score")
        if cs:
            lines.append(f"- Overall CarFINDa score: {cs}/100")

        return "\n".join(lines) if lines else "Limited scoring data available."

    def _get_strategy_text(
        self,
        strategy: str,
        asking_price: float,
        target_price: float,
        scoring_data: Optional[dict],
    ) -> str:
        """Build strategy instructions for the LLM."""
        discount_pct = ((asking_price - target_price) / asking_price * 100
                        if asking_price > 0 else 0)

        base = {
            "aggressive": (
                f"Open with a strong lowball ({discount_pct:.0f}% below asking). "
                "Reference specific issues (recalls, complaints, overpriced vs market). "
                "Be respectful but make it clear we know the true value."
            ),
            "balanced": (
                f"Open friendly but mention you've done research. "
                f"Offer ~{discount_pct:.0f}% below asking. "
                "Casually reference one data point that justifies a lower price."
            ),
            "friendly": (
                f"Open very friendly and express genuine interest. "
                f"Gently suggest a small discount ({discount_pct:.0f}% below asking). "
                "Focus on enthusiasm for the car, not problems with it."
            ),
        }

        text = base.get(strategy, base["balanced"])

        # Add specific leverage points
        if scoring_data:
            data = scoring_data.get("data", {})
            mv = data.get("market_value", {})
            est = mv.get("estimated_value")
            if est and asking_price > est:
                text += f" KEY: Car is overpriced — market value is ${est:,.0f}."

            rc = data.get("recalls", {}).get("recall_count", 0)
            if rc > 0:
                text += f" KEY: {rc} open recall(s) — safety leverage."

        return text

    def _get_last_offer(
        self,
        conversation_history: list[dict],
        target_price: float,
    ) -> float:
        """Extract our last mentioned price from conversation, or use target."""
        import re
        for msg in reversed(conversation_history):
            if msg.get("role") == "buyer":
                matches = re.findall(r'\$[\d,]+', msg.get("message", ""))
                if matches:
                    try:
                        return float(matches[-1].replace("$", "").replace(",", ""))
                    except ValueError:
                        pass
        return target_price


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_engine: Optional[NegotiationEngine] = None


def get_negotiation_engine() -> NegotiationEngine:
    global _engine
    if _engine is None:
        _engine = NegotiationEngine()
    return _engine
