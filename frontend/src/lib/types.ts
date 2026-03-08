// ---------------------------------------------------------------------------
// Listings
// ---------------------------------------------------------------------------

export interface Listing {
  id: string;
  vin?: string;
  year: number;
  make: string;
  model: string;
  trim?: string;
  title?: string;
  price: number;
  monthly_payment?: string;
  mileage?: number;
  mpg?: string;
  location?: string;
  source_url?: string;
  source_name?: string;
  image_urls: string[];
  exterior_color?: string;
  interior_color?: string;
  fuel_type?: string;
  motor_type?: string;
  transmission?: string;
  drivetrain?: string;
}

export interface ListingScore {
  safety: number;
  reliability: number;
  value: number;
  efficiency: number;
  recall_penalty: number;
  composite: number;
  breakdown: Record<string, unknown>;
}

export interface ListingWithScore {
  listing: Listing;
  score: ListingScore;
}

// ---------------------------------------------------------------------------
// Synthesis / Recommendations
// ---------------------------------------------------------------------------

export interface Recommendation {
  listing_id: string;
  rank: number;
  headline: string;
  explanation: string;
  strengths: string[];
  concerns: string[];
}

export interface Synthesis {
  search_summary: string;
  recommendations: Recommendation[];
  red_flags: string[];
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

export interface SearchResponse {
  search_session_id: string;
  status: string;
  listings: ListingWithScore[];
  total_results: number;
  synthesis?: Synthesis;
}

// ---------------------------------------------------------------------------
// Negotiation
// ---------------------------------------------------------------------------

export interface FairPrice {
  low: number;
  mid: number;
  high: number;
  explanation: string;
}

export interface Offer {
  amount: number;
  reasoning: string;
}

export interface LeveragePoint {
  category: string;
  point: string;
  impact: string;
}

export interface QuestionToAsk {
  question: string;
  why: string;
}

export interface CompetingListing {
  description: string;
  price: number;
  advantage: string;
}

export interface NegotiationStrategy {
  opening_dm: string;
  fair_price: FairPrice;
  opening_offer: Offer;
  leverage_points: LeveragePoint[];
  questions_to_ask: QuestionToAsk[];
  competing_listings: CompetingListing[];
  walk_away_price: Offer;
  negotiation_tips: string[];
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

// ---------------------------------------------------------------------------
// Legacy compat (used by existing components)
// ---------------------------------------------------------------------------

export interface Car {
  id: string;
  make: string;
  model: string;
  year: number;
  trim?: string;
  title?: string;
  price: number;
  monthly_payment?: string;
  mileage: number;
  mpg?: string;
  location: string;
  sellerType: 'dealer' | 'private';
  transmission?: string;
  motor_type?: string;
  imageUrl: string;
  score: number;
  scoreBreakdown: {
    safety: number;
    reliability: number;
    value: number;
    efficiency: number;
    recall: number;
  };
  marketAvgPrice?: number;
  recallCount?: number;
  // Vehicle details
  fuel_type?: string;
  exterior_color?: string;
  interior_color?: string;
  drivetrain?: string;
  // Synthesis
  headline?: string;
  explanation?: string;
  strengths?: string[];
  concerns?: string[];
  // Source data
  source_url?: string;
  source_name?: string;
  vin?: string;
}

export interface SearchParams {
  query?: string;
  make?: string;
  model?: string;
  yearMin?: number;
  yearMax?: number;
  budget?: number;
  location?: string;
  mileage?: number;
}
