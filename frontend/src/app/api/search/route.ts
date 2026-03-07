import { NextResponse } from 'next/server';
import { mockCars } from '@/lib/mock';

export async function POST(request: Request) {
  try {
    // const body = await request.json();
    
    // Simulate network delay to Supabase
    await new Promise(resolve => setTimeout(resolve, 800));

    // Sort by score for realistic output
    const sorted = [...mockCars].sort((a, b) => b.score - a.score);

    return NextResponse.json({ cars: sorted, searchId: 'search-xyz' });
  } catch (error) {
    return NextResponse.json({ error: 'Invalid request' }, { status: 400 });
  }
}
