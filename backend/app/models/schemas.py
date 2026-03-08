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
    radius_miles: int = 250
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
    recall: float = 0.0
    composite: float = 0.0
    breakdown: dict = {}


class DealInfo(BaseModel):
    """Deal rating and cross-source price comparison."""
    rating: str = "Unknown"  # Great Deal, Good Deal, Fair Price, Above Market, Overpriced
    savings: float = 0.0  # $ below market (positive = below, negative = above)
    savings_pct: float = 0.0
    source_badge: Optional[str] = None  # Original source deal badge
    cross_source: Optional[dict] = None  # Cross-source price comparison


class ListingWithScore(BaseModel):
    """A listing combined with its computed score and deal info."""
    listing: Listing
    score: ListingScore
    deal: Optional[DealInfo] = None


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
# Negotiate + DM (AI-powered outreach)
# ---------------------------------------------------------------------------

class SendDMRequest(BaseModel):
    """Request to generate an AI negotiation message and send it via Facebook DM."""
    listing: dict = Field(..., description="Listing dict (year, make, model, price, listing_url, etc.)")
    scoring_data: Optional[dict] = Field(None, description="Enriched scoring data from the pipeline")
    target_price: Optional[float] = Field(None, description="Desired price. Auto-calculated if omitted.")
    strategy: str = Field("balanced", description="'aggressive', 'balanced', or 'friendly'")
    send: bool = Field(True, description="If true, send the DM. If false, preview only.")


class SendDMResponse(BaseModel):
    """Result of AI-generated DM send."""
    success: bool
    message_sent: Optional[str] = None
    target_price: Optional[float] = None
    strategy_notes: Optional[str] = None
    conversation_url: Optional[str] = None
    error: Optional[str] = None


class NegotiateReplyRequest(BaseModel):
    """Request to generate an AI counter-offer and optionally send it."""
    listing: dict = Field(..., description="The listing under negotiation")
    seller_message: str = Field(..., description="The seller's latest reply text")
    conversation_history: list[dict] = Field(
        default_factory=list,
        description="Previous messages: [{role: 'buyer'|'seller', message: str}]",
    )
    conversation_url: Optional[str] = Field(None, description="Messenger conversation URL")
    scoring_data: Optional[dict] = None
    target_price: Optional[float] = None
    max_price: Optional[float] = None
    strategy: str = "balanced"
    auto_send: bool = Field(True, description="If true, auto-send safe replies (counters/accepts)")


class NegotiateReplyResponse(BaseModel):
    """Result of AI counter-offer generation."""
    message: str
    analysis: dict = {}
    auto_sent: bool = False
    should_send: bool = False
    error: Optional[str] = None


class CheckNegotiationsRequest(BaseModel):
    """Request to check inbox and auto-respond to active negotiations."""
    active_negotiations: list[dict] = Field(
        ...,
        description=(
            "List of active negotiation dicts, each with: listing (dict), "
            "conversation_url (str), target_price (float), max_price (float), "
            "scoring_data (dict), history (list)"
        ),
    )
    strategy: str = "balanced"


class CheckNegotiationsResponse(BaseModel):
    """Result of inbox check + auto-negotiation."""
    replies_found: int = 0
    responses: list[dict] = []


class FacebookSearchRequest(BaseModel):
    """Request to search Facebook Marketplace specifically."""
    query: Optional[str] = None
    makes: list[str] = []
    models: list[str] = []
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    min_year: Optional[int] = None
    max_mileage: Optional[int] = None
    location: Optional[str] = None
    radius_miles: Optional[int] = None
    max_pages: int = Field(3, ge=1, le=10)


class FacebookSearchResponse(BaseModel):
    """Response from Facebook Marketplace search."""
    success: bool
    listings: list[dict] = []
    total: int = 0
    logged_in: bool = False
    error: Optional[str] = None


class FacebookLoginRequest(BaseModel):
    """Request to trigger Facebook login."""
    email: Optional[str] = Field(None, description="FB email. Uses env var if omitted.")
    password: Optional[str] = Field(None, description="FB password. Uses env var if omitted.")


class FacebookLoginResponse(BaseModel):
    """Result of Facebook login attempt."""
    success: bool
    status: str = ""
    needs_2fa: bool = False
    error: Optional[str] = None


class Facebook2FARequest(BaseModel):
    """Request to submit a 2FA code."""
    code: str


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


# ---------------------------------------------------------------------------
# Email Notifications (AgentMail)
# ---------------------------------------------------------------------------

class EmailSubscribeRequest(BaseModel):
    """Subscribe to email alerts for a listing or search."""
    email: str = Field(..., description="User email address")
    alert_type: str = Field("negotiation", description="'negotiation', 'price_drop', or 'new_matches'")
    listing: Optional[dict] = Field(None, description="Listing to watch (for negotiation/price_drop)")
    search_filters: Optional[dict] = Field(None, description="Search filters (for new_matches)")
    car_title: Optional[str] = None
    car_price: Optional[float] = None
    image_url: Optional[str] = None


class EmailSubscribeResponse(BaseModel):
    """Confirmation of email alert subscription."""
    success: bool
    agent_email: str = ""
    subscription_id: str = ""
    message: str = ""


class SendOutreachSummaryRequest(BaseModel):
    """Request to email an outreach summary to the user."""
    email: str
    search_query: str
    messages_sent: int
    listings: list[dict] = []


class EmailNotificationResponse(BaseModel):
    """Generic email send result."""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
