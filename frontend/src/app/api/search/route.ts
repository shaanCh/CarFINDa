import { NextResponse } from 'next/server';
import { Car } from '@/lib/types';

const BACKEND_URL = 'http://127.0.0.1:8000';

export async function POST(request: Request) {
  try {
    const body = await request.json();

    // Map Next.js params to FastAPI format
    const queryParams = new URLSearchParams();

    if (body.make) queryParams.append('makes', body.make);
    if (body.model) queryParams.append('model', body.model);
    if (body.budget) queryParams.append('max_price', String(body.budget));
    if (body.mileage) queryParams.append('max_mileage', String(body.mileage));
    if (body.location) queryParams.append('location', body.location);
    if (body.reliabilityPriority)
      queryParams.append('reliability_priority', String(body.reliabilityPriority));
    if (body.ownershipCostConcern)
      queryParams.append('ownership_cost_concern', String(body.ownershipCostConcern));
    if (body.sellerType) queryParams.append('seller_type', body.sellerType);
    if (body.transmission) queryParams.append('transmission', body.transmission);
    if (body.primaryUse) queryParams.append('primary_use', body.primaryUse);

    const res = await fetch(
      `${BACKEND_URL}/api/listings/?${queryParams.toString()}`,
      {
        headers: {
          // Authorization header can be added later if needed
          'Content-Type': 'application/json',
        },
      }
    );

    if (!res.ok) {
      console.error('Backend error:', res.status);
      throw new Error('Failed to fetch listings');
    }

    const data = await res.json();

    // Transform backend ListingWithScore into frontend Car shape
    const mappedCars: Car[] = (data.listings || []).map((item: any) => ({
      id: item.listing.id,
      make: item.listing.make,
      model: item.listing.model,
      year: item.listing.year,
      trim: item.listing.trim,
      price: item.listing.price,
      mileage: item.listing.mileage ?? 0,
      location: item.listing.location ?? 'Unknown',
      sellerType: item.listing.seller_type ?? 'dealer',
      transmission: item.listing.transmission ?? 'automatic',
      imageUrl:
        item.listing.image_urls?.[0] ??
        'https://images.unsplash.com/photo-1590362891991-f776e747a588?auto=format&fit=crop&q=80&w=800',

      // Convert backend 0–10 score → frontend 0–100
      score: Math.round((item.score?.composite ?? 0) * 10),

      scoreBreakdown: {
        budgetFit: Math.round((item.score?.value ?? 0) * 10),
        mileageScore: Math.round((item.score?.safety ?? 0) * 10),
        reliability: Math.round((item.score?.reliability ?? 0) * 10),
        priceVsMarket: Math.round((item.score?.composite ?? 0) * 10),
      },

      marketAvgPrice: item.listing.price + 1500, // temporary fallback
      recallCount: 0, // temporary fallback
    }));

    return NextResponse.json({
      cars: mappedCars,
      searchId: 'search-api',
    });
  } catch (error) {
    console.error('Search API error:', error);

    return NextResponse.json(
      { error: 'Invalid request' },
      { status: 400 }
    );
  }
}