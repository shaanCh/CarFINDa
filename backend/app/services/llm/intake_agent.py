"""
Intake Agent -- parses natural language car preferences into structured filters.

Uses Gemini structured output to guarantee a clean JSON response matching
the CarFINDa filter schema.
"""

import logging
from typing import Optional

from app.config import get_settings
from app.services.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

INTAKE_SYSTEM_PROMPT = """\
You are the CarFINDa Intake Agent. Your job is to parse a user's natural language
description of what kind of car they want into a structured JSON filter object.

## Rules

1. Extract EVERY preference the user mentions, even if implied.
2. If the user says "under $X" or "less than $X", set budget_max to X and budget_min to 0.
3. If the user says "between $X and $Y", set budget_min to X and budget_max to Y.
4. If the user says "around $X" or "about $X", set budget_min to X * 0.85 and budget_max to X * 1.15 (15% range).
5. Normalize body types to standard names: "Sedan", "SUV", "Crossover", "Truck", "Coupe", "Convertible", "Hatchback", "Wagon", "Van", "Minivan".
6. Normalize make names to proper capitalisation (e.g. "toyota" -> "Toyota", "bmw" -> "BMW", "mercedes" -> "Mercedes-Benz").
7. If the user mentions a specific model, include both the make and model. Put the make in "makes" and the model in "models".
   Infer the make from a model name if not explicit (e.g. "Camry" -> makes: ["Toyota"], models: ["Camry"]).
8. Convert mileage references: "under 80K miles" -> max_mileage = 80000, "low mileage" -> max_mileage = 50000.
9. Dealbreakers are things the user explicitly does NOT want: accidents, salvage title, frame damage, flood damage, liens, smoking, etc.
10. If the user mentions a location, normalise it to "City, ST" format (e.g. "near Boulder" -> "Boulder, CO").
    Use the provided location context if available.
11. Default radius_miles to 100 if not specified (wider default for better results).
12. If the user says "newer" without a specific year, set min_year to current_year - 5.
    If they say "2018 or newer", set min_year to 2018.
13. If the user mentions fuel type preferences (hybrid, electric, diesel, EV, plug-in), include them in fuel_types.
14. **Semantic understanding** -- Infer structured filters from descriptive/lifestyle language:
    - "family car/family-friendly" -> body_types: ["SUV", "Sedan", "Minivan"], implies safety priority
    - "commuter" or "daily driver" -> body_types: ["Sedan", "Hatchback"], implies fuel efficiency
    - "reliable" -> makes: ["Toyota", "Honda", "Lexus", "Mazda"] (if no make specified)
    - "luxury" -> makes: ["BMW", "Mercedes-Benz", "Audi", "Lexus", "Genesis"] (if no make specified)
    - "sporty" or "fast" or "fun to drive" -> body_types: ["Coupe", "Sedan"]
    - "off-road" or "adventure" -> body_types: ["SUV", "Truck"], drivetrain preference: AWD/4WD
    - "towing" or "hauling" -> body_types: ["Truck", "SUV"]
    - "fuel efficient" or "good gas mileage" or "economical" -> implies hybrid or efficient makes
    - "safe" or "safest" or "good safety" -> implies high safety priority, family makes
    - "cheap" or "affordable" or "budget" with no price -> budget_max: 15000
    - "good in snow" or "winter driving" -> transmission preference for AWD
    - "first car" or "new driver" -> budget_max: 15000, body_types: ["Sedan", "Hatchback"], implies safety
    - "road trip" -> body_types: ["SUV", "Sedan"], implies comfort and fuel efficiency
    - "small/compact" -> body_types: ["Hatchback", "Sedan"]
    - "large/big/spacious/third row" -> body_types: ["SUV", "Minivan"]
15. If certain fields are not mentioned at all, use sensible defaults:
    - budget_min: 0
    - budget_max: 0 (no upper limit)
    - body_types: [] (any)
    - makes: [] (any)
    - models: [] (any)
    - max_mileage: 0 (no limit)
    - min_year: 0 (no limit)
    - dealbreakers: []
    - fuel_types: []
    - transmission: "" (any)
    - radius_miles: 100
16. When the user mentions multiple preferences, capture ALL of them. Never ignore stated preferences.
17. "CPO" or "certified" is not a filter but a preference -- note it but don't restrict results.

## Output

Return ONLY the JSON object. Do not include any commentary.
"""

# ---------------------------------------------------------------------------
# Response schema for Gemini structured output
# ---------------------------------------------------------------------------

PREFERENCES_SCHEMA = {
    "type": "object",
    "properties": {
        "budget_min": {
            "type": "number",
            "description": "Minimum budget in USD. 0 if no lower bound.",
        },
        "budget_max": {
            "type": "number",
            "description": "Maximum budget in USD. 0 if no upper bound specified.",
        },
        "body_types": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of acceptable body types (Sedan, SUV, Crossover, Truck, etc.).",
        },
        "makes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Preferred vehicle makes (Toyota, Honda, BMW, etc.).",
        },
        "models": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific model names (Camry, Civic, X3, etc.).",
        },
        "max_mileage": {
            "type": "number",
            "description": "Maximum acceptable mileage. 0 if no limit.",
        },
        "min_year": {
            "type": "number",
            "description": "Earliest acceptable model year. 0 if no limit.",
        },
        "location": {
            "type": "string",
            "description": "Search centre location in 'City, ST' format.",
        },
        "radius_miles": {
            "type": "number",
            "description": "Search radius in miles from location. Default 50.",
        },
        "dealbreakers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Things the user explicitly does not want: accidents, salvage, flood, frame_damage, lien, smoking, etc.",
        },
        "fuel_types": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Preferred fuel types: gasoline, diesel, hybrid, plug-in_hybrid, electric.",
        },
        "transmission": {
            "type": "string",
            "description": "Preferred transmission: automatic, manual, or empty string if no preference.",
        },
    },
    "required": [
        "budget_min",
        "budget_max",
        "body_types",
        "makes",
        "models",
        "max_mileage",
        "min_year",
        "location",
        "radius_miles",
        "dealbreakers",
        "fuel_types",
        "transmission",
    ],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_preferences(natural_language: str, location: str = "") -> dict:
    """Parse natural language car preferences into structured filters using Gemini.

    Args:
        natural_language: Free-form text describing what the user wants.
            Examples:
            - "Under $18K, SUV or crossover, under 80K miles, near Boulder, no accidents"
            - "Looking for a reliable Toyota or Honda sedan, 2019+, automatic, under $25K"
            - "I want a truck for towing, diesel preferred, budget around $35K"
        location: Optional location context (e.g. "Boulder, CO") to help
            resolve ambiguous location references.

    Returns:
        A dict with structured filter fields:
        {
            "budget_min": 0,
            "budget_max": 18000,
            "body_types": ["SUV", "Crossover"],
            "makes": [],
            "models": [],
            "max_mileage": 80000,
            "min_year": 0,
            "location": "Boulder, CO",
            "radius_miles": 50,
            "dealbreakers": ["accidents"],
            "fuel_types": [],
            "transmission": "",
        }
    """
    settings = get_settings()
    gemini = GeminiClient(api_key=settings.GEMINI_API_KEY)

    # Build the user prompt with location context
    prompt_parts = [f'User request: "{natural_language}"']
    if location:
        prompt_parts.append(f"User's current location context: {location}")

    prompt = "\n".join(prompt_parts)

    logger.info("Intake agent parsing: %s", natural_language)

    result = await gemini.generate_structured(
        prompt=prompt,
        system_instruction=INTAKE_SYSTEM_PROMPT,
        response_schema=PREFERENCES_SCHEMA,
        temperature=0.2,
    )

    # Post-process: convert 0 sentinels back to None for optional fields
    if result.get("budget_max") == 0:
        result["budget_max"] = None
    if result.get("max_mileage") == 0:
        result["max_mileage"] = None
    if result.get("min_year") == 0:
        result["min_year"] = None

    logger.info("Intake agent result: %s", result)
    return result
