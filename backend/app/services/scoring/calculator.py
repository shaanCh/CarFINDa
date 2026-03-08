"""
Composite score calculator for vehicle listings.

Combines safety ratings, reliability data, value analysis, fuel efficiency,
ownership cost, and recall status into a single 0-100 composite score with
a human-readable breakdown.
"""

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ListingScore:
    """Composite score result for a vehicle listing."""

    composite_score: int  # 0-100 overall score

    # Individual component scores (each 0-100)
    safety_score: float
    reliability_score: float
    value_score: float
    efficiency_score: float
    ownership_cost_score: float
    recall_score: float

    # Human-readable breakdown
    breakdown: dict = field(default_factory=dict)


def calculate_composite_score(
    safety_rating: Optional[float],
    complaint_count: int,
    price: float,
    estimated_value: float,
    mpg_combined: Optional[float],
    open_recalls: int,
    annual_ownership_cost: Optional[float] = None,
) -> ListingScore:
    """
    Calculate a composite score (0-100) from individual data points.

    Weights:
        - Safety:          20%  (NHTSA star rating)
        - Reliability:     20%  (NHTSA complaint count)
        - Value:           25%  (listing price vs estimated market value)
        - Ownership Cost:  15%  (5-year projected annual cost)
        - Efficiency:      10%  (EPA combined MPG)
        - Recall:          10%  (open recall penalty)

    Args:
        safety_rating:         NHTSA overall star rating (1-5), or None.
        complaint_count:       Number of NHTSA consumer complaints.
        price:                 Listing/asking price in dollars.
        estimated_value:       Estimated fair market value in dollars.
        mpg_combined:          EPA combined MPG, or None.
        open_recalls:          Number of open (unresolved) recalls.
        annual_ownership_cost: Projected average annual cost of ownership, or None.

    Returns:
        ListingScore with composite score, component scores, and breakdown.
    """
    # ----- Safety (20%) -----
    if safety_rating is not None and safety_rating > 0:
        safety_score = (safety_rating / 5.0) * 100.0
        safety_explanation = (
            f"{safety_rating}/5 stars -> {safety_score:.0f}/100"
        )
    else:
        safety_score = 60.0
        safety_explanation = "No NHTSA rating available; using default 60/100"

    # ----- Reliability (20%) -----
    if complaint_count == 0:
        reliability_score = 100.0
        reliability_explanation = "0 complaints -> 100/100"
    else:
        reliability_score = max(0.0, 100.0 - (15.0 * math.log10(complaint_count + 1)))
        reliability_explanation = (
            f"{complaint_count} complaints (log-scaled) -> "
            f"{reliability_score:.0f}/100"
        )

    # ----- Value (25%) -----
    if estimated_value > 0 and price > 0:
        price_ratio = price / estimated_value

        if price_ratio <= 1.0:
            # Price at or below estimated value — great deal
            value_score = 100.0 - (price_ratio * 25.0)
        else:
            # Price above estimated value
            overpay_pct = (price_ratio - 1.0) * 100.0
            value_score = max(0.0, 75.0 - (overpay_pct * 2.5))

        if price < estimated_value:
            savings = estimated_value - price
            value_explanation = (
                f"Price ${price:,.0f} is ${savings:,.0f} below estimated "
                f"value ${estimated_value:,.0f} -> {value_score:.0f}/100"
            )
        elif price > estimated_value:
            overpay = price - estimated_value
            value_explanation = (
                f"Price ${price:,.0f} is ${overpay:,.0f} above estimated "
                f"value ${estimated_value:,.0f} -> {value_score:.0f}/100"
            )
        else:
            value_explanation = (
                f"Price ${price:,.0f} equals estimated value -> "
                f"{value_score:.0f}/100"
            )
    else:
        value_score = 50.0
        value_explanation = "Insufficient data for value comparison; using default 50/100"

    # ----- Ownership Cost (15%) -----
    # Scale: $4k/yr = 100, $7k/yr = 70, $10k/yr = 40, $13k/yr+ = 0
    if annual_ownership_cost is not None and annual_ownership_cost > 0:
        ownership_cost_score = max(
            0.0, min(100.0, 100.0 - ((annual_ownership_cost - 4000) / 90))
        )
        ownership_cost_explanation = (
            f"${annual_ownership_cost:,.0f}/yr avg ownership cost -> "
            f"{ownership_cost_score:.0f}/100"
        )
    else:
        ownership_cost_score = 50.0
        ownership_cost_explanation = (
            "No ownership cost data (VIN required); using default 50/100"
        )

    # ----- Efficiency (10%) -----
    if mpg_combined is not None and mpg_combined > 0:
        # Cap MPGe at 50 so EVs don't auto-max this score
        capped_mpg = min(mpg_combined, 50.0)
        efficiency_score = min(100.0, (capped_mpg / 40.0) * 100.0)
        if mpg_combined > 50:
            efficiency_explanation = (
                f"{mpg_combined:.0f} MPGe (capped at 50 for scoring) -> "
                f"{efficiency_score:.0f}/100"
            )
        else:
            efficiency_explanation = (
                f"{mpg_combined:.1f} combined MPG (40 MPG = 100) -> "
                f"{efficiency_score:.0f}/100"
            )
    else:
        efficiency_score = 50.0
        efficiency_explanation = "No MPG data available; using default 50/100"

    # ----- Recall Penalty (10%) -----
    recall_score = max(40.0, 100.0 - (open_recalls * 15.0))
    if open_recalls == 0:
        recall_score = 100.0
        recall_explanation = "No open recalls -> 100/100"
    else:
        recall_explanation = (
            f"{open_recalls} open recall(s) (x15 penalty each, min 40) -> "
            f"{recall_score:.0f}/100"
        )

    # ----- Composite -----
    composite_raw = (
        safety_score * 0.20
        + reliability_score * 0.20
        + value_score * 0.25
        + ownership_cost_score * 0.15
        + efficiency_score * 0.10
        + recall_score * 0.10
    )
    composite = max(0, min(100, round(composite_raw)))

    breakdown = {
        "safety": {
            "score": round(safety_score, 1),
            "weight": "20%",
            "explanation": safety_explanation,
        },
        "reliability": {
            "score": round(reliability_score, 1),
            "weight": "20%",
            "explanation": reliability_explanation,
        },
        "value": {
            "score": round(value_score, 1),
            "weight": "25%",
            "explanation": value_explanation,
        },
        "ownership_cost": {
            "score": round(ownership_cost_score, 1),
            "weight": "15%",
            "explanation": ownership_cost_explanation,
        },
        "efficiency": {
            "score": round(efficiency_score, 1),
            "weight": "10%",
            "explanation": efficiency_explanation,
        },
        "recall": {
            "score": round(recall_score, 1),
            "weight": "10%",
            "explanation": recall_explanation,
        },
        "composite": {
            "score": composite,
            "formula": (
                "0.20*safety + 0.20*reliability + 0.25*value "
                "+ 0.15*ownership + 0.10*efficiency + 0.10*recall"
            ),
        },
    }

    return ListingScore(
        composite_score=composite,
        safety_score=round(safety_score, 1),
        reliability_score=round(reliability_score, 1),
        value_score=round(value_score, 1),
        efficiency_score=round(efficiency_score, 1),
        ownership_cost_score=round(ownership_cost_score, 1),
        recall_score=round(recall_score, 1),
        breakdown=breakdown,
    )
