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
      mpg: data.listing.mpg || undefined,
      location: data.listing.location || 'Unknown',
      sellerType: 'dealer',
      transmission: data.listing.transmission || undefined,
      motor_type: data.listing.motor_type || undefined,
      fuel_type: data.listing.fuel_type || undefined,
      exterior_color: data.listing.exterior_color || undefined,
      interior_color: data.listing.interior_color || undefined,
      drivetrain: data.listing.drivetrain || undefined,
      imageUrl: data.listing.image_urls?.[0] || '',
      score: Math.round(data.score.composite || 0),
      scoreBreakdown: {
        safety: Math.round(data.score.safety || 0),
        reliability: Math.round(data.score.reliability || 0),
        value: Math.round(data.score.value || 0),
        efficiency: Math.round(data.score.efficiency || 0),
        recall: Math.round(data.score.recall || data.score.recall_penalty || 0),
      },
      recallCount: 0,
      source_url: data.listing.source_url,
      source_name: data.listing.source_name,
      vin: data.listing.vin,
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
