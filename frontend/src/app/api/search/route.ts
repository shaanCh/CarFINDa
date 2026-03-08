import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

/**
 * Parse filter values from the landing page and advanced filter components
 * into backend-compatible fields.
 *
 * Landing page sends:   { query, budget: "Under $20k", type: "SUV", year: "2020+", fuel: "Hybrid" }
 * Advanced filters:     { make: "Toyota", model: "Camry", mileage: "80000", location: "Denver, CO", ... }
 * Backend expects:      { natural_language, budget_max, body_types, min_year, makes, ... }
 */
function parseFilters(body: Record<string, string>) {
  const filters: Record<string, unknown> = {};

  // Natural language query — this is the primary input
  if (body.query) {
    filters.natural_language = body.query;
  }

  // Budget chip: "Under $10k" → 10000, "Under $20k" → 20000, "$15k-$25k" range, etc.
  if (body.budget) {
    const rangeMatch = body.budget.match(/\$(\d+)k?\s*[-–]\s*\$(\d+)k/i);
    if (rangeMatch) {
      const lo = parseInt(rangeMatch[1]);
      const hi = parseInt(rangeMatch[2]);
      filters.budget_min = lo < 200 ? lo * 1000 : lo;
      filters.budget_max = hi < 200 ? hi * 1000 : hi;
    } else {
      const match = body.budget.match(/\$(\d+)k/i);
      if (match) {
        filters.budget_max = parseInt(match[1]) * 1000;
      } else {
        const num = parseFloat(body.budget.replace(/[$,]/g, ''));
        if (!isNaN(num)) filters.budget_max = num < 200 ? num * 1000 : num;
      }
    }
  }

  // Type chip: "SUV" → body_types: ["SUV"]
  if (body.type) {
    filters.body_types = [body.type];
  }

  // Year chip: "2020+" → min_year: 2020
  if (body.year) {
    const yearMatch = body.year.match(/(\d{4})/);
    if (yearMatch) {
      filters.min_year = parseInt(yearMatch[1]);
    }
  }

  // Fuel chip — include both in NL (for semantic parsing) and mention in query
  if (body.fuel && body.fuel !== 'Gas') {
    const nl = (filters.natural_language as string) || '';
    filters.natural_language = nl ? `${nl}, prefer ${body.fuel.toLowerCase()}` : `prefer ${body.fuel.toLowerCase()}`;
  }

  // Direct structured fields (from advanced filter components)
  if (body.location) filters.location = body.location;
  if (body.make) filters.makes = [body.make];
  if (body.model) {
    // Include model in NL for semantic parsing AND as a hint
    const nl = (filters.natural_language as string) || '';
    filters.natural_language = nl ? `${nl} ${body.model}` : body.model;
  }
  if (body.mileage) {
    const mi = parseInt(body.mileage);
    if (!isNaN(mi)) filters.max_mileage = mi;
  }
  if (body.transmission && body.transmission !== 'Any') {
    const nl = (filters.natural_language as string) || '';
    filters.natural_language = nl ? `${nl}, ${body.transmission}` : body.transmission;
  }

  // Defaults
  if (!filters.location) filters.location = '';
  if (!filters.natural_language) filters.natural_language = '';

  return filters;
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const searchPayload = parseFilters(body);

    let backendRes: Response;
    try {
      backendRes = await fetch(`${BACKEND_URL}/api/search/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(searchPayload),
        signal: AbortSignal.timeout(120_000), // 2 min timeout for scraping
      });
    } catch (fetchErr) {
      console.error('Backend connection failed:', fetchErr);
      return NextResponse.json({
        cars: [],
        searchId: 'error',
        synthesis: null,
        error: 'Could not connect to backend. Make sure the backend is running on ' + BACKEND_URL,
      });
    }

    if (!backendRes.ok) {
      const errorText = await backendRes.text();
      console.error('Backend error:', backendRes.status, errorText);
      return NextResponse.json({
        cars: [],
        searchId: 'error',
        synthesis: null,
        error: `Backend returned ${backendRes.status}: ${errorText}`,
      });
    }

    const data = await backendRes.json();

    // Transform backend ListingWithScore[] to frontend Car[]
    const cars = (data.listings || []).map((item: Record<string, unknown>) => {
      const listing = item.listing as Record<string, unknown>;
      const score = item.score as Record<string, number>;
      const deal = item.deal as Record<string, unknown> | null;

      // Match recommendation from synthesis
      const rec = data.synthesis?.recommendations?.find(
        (r: Record<string, unknown>) => r.listing_id === listing.id
      );

      return {
        id: listing.id,
        make: listing.make,
        model: listing.model,
        year: listing.year,
        trim: listing.trim || '',
        title: listing.title || '',
        price: listing.price || 0,
        monthly_payment: listing.monthly_payment || undefined,
        mileage: listing.mileage || 0,
        mpg: listing.mpg || undefined,
        location: listing.location || 'Unknown',
        sellerType: (listing.source_name as string)?.toLowerCase().includes('private') ? 'private' : 'dealer',
        transmission: listing.transmission || undefined,
        motor_type: listing.motor_type || undefined,
        imageUrl: (listing.image_urls as string[])?.[0] || '',
        score: Math.round(score.composite || 0),
        scoreBreakdown: {
          safety: Math.round(score.safety || 0),
          reliability: Math.round(score.reliability || 0),
          value: Math.round(score.value || 0),
          efficiency: Math.round(score.efficiency || 0),
          recall: Math.round(score.recall || score.recall_penalty || 0),
        },
        recallCount: score.recall_penalty < 100 ? Math.max(1, Math.round((100 - score.recall_penalty) / 15)) : 0,
        // Deal info
        dealRating: deal?.rating || 'Unknown',
        dealSavings: (deal?.savings as number) || 0,
        dealSavingsPct: (deal?.savings_pct as number) || 0,
        dealSourceBadge: deal?.source_badge || undefined,
        crossSource: deal?.cross_source || undefined,
        fuel_type: listing.fuel_type || undefined,
        exterior_color: listing.exterior_color || undefined,
        interior_color: listing.interior_color || undefined,
        drivetrain: listing.drivetrain || undefined,
        headline: rec?.headline,
        explanation: rec?.explanation,
        strengths: rec?.strengths || [],
        concerns: rec?.concerns || [],
        source_url: listing.source_url,
        source_name: listing.source_name,
        vin: listing.vin,
      };
    });

    return NextResponse.json({
      cars,
      searchId: data.search_session_id,
      synthesis: data.synthesis || null,
    });

  } catch (error) {
    console.error('Search API error:', error);
    return NextResponse.json(
      { cars: [], searchId: 'error', synthesis: null, error: String(error) },
      { status: 500 }
    );
  }
}
