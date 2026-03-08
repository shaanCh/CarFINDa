from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    """Car search request with optional natural-language and structured filters."""
    natural_language: str = ""
    location: str = ""
    radius_miles: int = 50
    makes: list[str] = []
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    min_year: Optional[int] = None
    max_mileage: Optional[int] = None
    body_types: list[str] = []


class Recommendation(BaseModel):
    """A single recommendation from the LLM synthesizer."""
    listing_id: str
    rank: int
    headline: str
    explanation: str
    strengths: list[str] = []
    concerns: list[str] = []


class Synthesis(BaseModel):
    """LLM synthesis output for a set of search results."""
    search_summary: str = ""
    recommendations: list[Recommendation] = []
    red_flags: list[str] = []


class SearchResponse(BaseModel):
    """Status envelope returned while a search session is processed."""
    search_session_id: str
    status: str = "pending"  # pending | scraping | scoring | complete
    listings: list["ListingWithScore"] = []
    total_results: int = 0
    synthesis: Optional[Synthesis] = None


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

class Listing(BaseModel):
    """A single vehicle listing scraped from a marketplace."""
    id: str
    vin: Optional[str] = None
    year: int
    make: str
    model: str
    trim: Optional[str] = None
    title: Optional[str] = None
    price: float
    monthly_payment: Optional[str] = None
    mileage: Optional[int] = None
    mpg: Optional[str] = None
    location: Optional[str] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    image_urls: list[str] = []
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None
    fuel_type: Optional[str] = None
    motor_type: Optional[str] = None
    transmission: Optional[str] = None
    drivetrain: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ListingScore(BaseModel):
    """Score breakdown for a single listing."""
    safety: float = 0.0
    reliability: float = 0.0
    value: float = 0.0
    efficiency: float = 0.0
    recall_penalty: float = 0.0
    composite: float = 0.0
    breakdown: dict = {}


class ListingWithScore(BaseModel):
    """A listing combined with its computed score."""
    listing: Listing
    score: ListingScore


class ListingResponse(BaseModel):
    """Paginated listing results."""
    listings: list[ListingWithScore] = []
    total: int = 0
    limit: int = 20
    offset: int = 0


# ---------------------------------------------------------------------------
# User Preferences
# ---------------------------------------------------------------------------

class UserPreferences(BaseModel):
    """Saved user preferences for vehicle searches."""
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    vehicle_types: list[str] = []
    max_mileage: Optional[int] = None
    location: Optional[str] = None
    radius_miles: int = 50
    dealbreakers: list[str] = []
    preferred_makes: list[str] = []
    min_year: Optional[int] = None


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Message sent to the LLM assistant."""
    message: str
    listing_ids: list[str] = []
    session_id: Optional[str] = None
    search_session_id: Optional[str] = None
    context: Optional[dict] = None


class ChatResponse(BaseModel):
    """Reply from the LLM assistant."""
    message: str
    session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Negotiation
# ---------------------------------------------------------------------------

class NegotiationRequest(BaseModel):
    """Request to generate a negotiation strategy for a listing."""
    listing_id: str
    listing: Optional[dict] = None
    score: Optional[dict] = None
    data: Optional[dict] = None
    preferences: Optional[dict] = None
    competing_listings: list[dict] = []


class FairPrice(BaseModel):
    """Fair price range breakdown."""
    low: float
    mid: float
    high: float
    explanation: str


class Offer(BaseModel):
    """A suggested price offer."""
    amount: float
    reasoning: str


class LeveragePoint(BaseModel):
    """A data-backed negotiation leverage point."""
    category: str
    point: str
    impact: str


class QuestionToAsk(BaseModel):
    """A question to ask the seller, with rationale."""
    question: str
    why: str


class CompetingListing(BaseModel):
    """A competing listing to reference during negotiation."""
    description: str
    price: float
    advantage: str


class NegotiationResponse(BaseModel):
    """Full negotiation strategy output."""
    opening_dm: str
    fair_price: FairPrice
    opening_offer: Offer
    leverage_points: list[LeveragePoint] = []
    questions_to_ask: list[QuestionToAsk] = []
    competing_listings: list[CompetingListing] = []
    walk_away_price: Offer
    negotiation_tips: list[str] = []


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class MonitorRequest(BaseModel):
    """Request to create a background monitoring watch."""
    preferences_snapshot: dict
    frequency: str = "daily"


class MonitorResponse(BaseModel):
    """Details of an active monitor."""
    monitor_id: str
    preferences_snapshot: dict
    frequency: str
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)
