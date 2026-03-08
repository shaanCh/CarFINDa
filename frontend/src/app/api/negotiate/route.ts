import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

export async function POST(request: Request) {
  try {
    const body = await request.json();

    const backendRes = await fetch(`${BACKEND_URL}/api/negotiate/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        listing_id: body.listingId,
        listing: body.listing,
        score: body.score,
        data: body.data,
        preferences: body.preferences,
        competing_listings: body.competingListings || [],
      }),
    });

    if (!backendRes.ok) {
      const errorText = await backendRes.text();
      console.error('Backend negotiate error:', backendRes.status, errorText);
      return NextResponse.json(
        { error: 'Failed to generate negotiation strategy' },
        { status: backendRes.status }
      );
    }

    const data = await backendRes.json();
    return NextResponse.json(data);

  } catch (error) {
    console.error('Negotiate API error:', error);
    return NextResponse.json(
      { error: 'Negotiation failed' },
      { status: 500 }
    );
  }
}
