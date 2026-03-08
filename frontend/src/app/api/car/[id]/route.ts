import { NextResponse } from 'next/server';
import { Car } from '@/lib/types';

const BACKEND_URL = 'http://127.0.0.1:8000';

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const idValue = (await context.params).id;

  try {
    const res = await fetch(`${BACKEND_URL}/api/listings/${idValue}`);
    
    if (!res.ok) {
       return NextResponse.json({ error: 'Not Found' }, { status: 404 });
    }

    const data = await res.json();
    
    // Map backend ListingWithScore to frontend Car schema
    const car: Car = {
      id: data.listing.id,
      make: data.listing.make,
      model: data.listing.model,
      year: data.listing.year,
      trim: data.listing.trim,
      price: data.listing.price,
      mileage: data.listing.mileage || 0,
      location: data.listing.location || 'Unknown',
      sellerType: 'private', // stub backward compat
      transmission: data.listing.transmission || 'automatic',
      imageUrl: data.listing.image_urls?.[0] || 'https://images.unsplash.com/photo-1590362891991-f776e747a588?auto=format&fit=crop&q=80&w=800',
      score: Math.round((data.score.composite || 0) * 10), // convert 0-10 scale
      scoreBreakdown: {
        budgetFit: Math.round((data.score.value || 0) * 10),
        mileageScore: Math.round((data.score.safety || 0) * 10), 
        reliability: Math.round((data.score.reliability || 0) * 10),
        priceVsMarket: Math.round((data.score.composite || 0) * 10),
      },
      marketAvgPrice: data.listing.price + 1200, // stub backward compat
      recallCount: 0
    };

    return NextResponse.json({ 
      car,
      nhtsa: { issuesFound: car.recallCount || 0 },
      marketAvg: car.marketAvgPrice
    });
  } catch {
    return NextResponse.json({ error: 'Failed to fetch details' }, { status: 500 });
  }
}
