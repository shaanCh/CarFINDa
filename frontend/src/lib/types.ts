export interface Car {
  id: string;
  make: string;
  model: string;
  year: number;
  trim?: string;
  price: number;
  mileage: number;
  location: string;
  sellerType: 'dealer' | 'private';
  transmission: 'automatic' | 'manual';
  imageUrl: string;
  score: number;           // 0–100, computed by backend
  scoreBreakdown: {
    budgetFit: number;
    mileageScore: number;
    reliability: number;
    priceVsMarket: number;
  };
  marketAvgPrice?: number;
  recallCount?: number;
}

export interface SearchParams {
  make?: string;
  model?: string;
  yearMin?: number;
  yearMax?: number;
  budget?: number;
  location?: string;
  mileage?: number;
  reliabilityPriority?: string;
  ownershipCostConcern?: string;
  sellerType?: string;
  transmission?: string;
  primaryUse?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}
