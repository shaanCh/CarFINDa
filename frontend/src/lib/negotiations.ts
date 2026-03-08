// ---------------------------------------------------------------------------
// Negotiation Tracking Types
// ---------------------------------------------------------------------------

export interface FBListingRef {
  id: string;
  title?: string;
  year?: number;
  make?: string;
  model?: string;
  price?: number;
  mileage?: number;
  location?: string;
  listing_url?: string;
  seller_name?: string;
  image_urls?: string[];
}

export interface ActiveNegotiation {
  id: string;
  listingId: string;
  listing: FBListingRef;
  conversationUrl: string | null;
  targetPrice: number | null;
  maxPrice: number | null;
  messageSent: string;
  sentAt: string;
  status: 'active' | 'replied' | 'accepted' | 'rejected' | 'expired';
}

export interface SellerReply {
  negotiationId: string;
  sellerName: string;
  sellerMessage: string;
  aiCounterOffer: string;
  analysis: {
    intent: string;
    sentiment?: string;
    recommended_action?: string;
  };
  autoSent: boolean;
  shouldSend: boolean;
  userApproved: boolean | null; // null = pending review
  timestamp: string;
}

export interface NegotiationState {
  negotiations: ActiveNegotiation[];
  replies: SellerReply[];
  isPolling: boolean;
  lastChecked: string | null;
  unreadCount: number;
  panelOpen: boolean;
}

export const INITIAL_STATE: NegotiationState = {
  negotiations: [],
  replies: [],
  isPolling: false,
  lastChecked: null,
  unreadCount: 0,
  panelOpen: false,
};

const STORAGE_KEY = 'carfinda-negotiations';

export function saveState(state: NegotiationState): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch { /* quota exceeded — non-critical */ }
}

export function loadState(): NegotiationState {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) return { ...INITIAL_STATE, ...JSON.parse(raw) };
  } catch { /* parse error — non-critical */ }
  return INITIAL_STATE;
}
