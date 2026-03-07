import { NextResponse } from 'next/server';
import { mockCars } from '@/lib/mock';

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  // Wait for dynamic route context params resolution in next@14
  const idValue = (await context.params).id;

  // Simulate network delay
  await new Promise(resolve => setTimeout(resolve, 500));

  const car = mockCars.find(c => c.id === idValue) || mockCars[0]; 

  return NextResponse.json({ 
    car,
    nhtsa: { issuesFound: car.recallCount || 0 },
    marketAvg: car.marketAvgPrice
  });
}
