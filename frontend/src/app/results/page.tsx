'use client';

import React, { useEffect, useState, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { TopBar } from '@/components/layout/TopBar';
import { CarCard } from '@/components/ui/CarCard';
import { SkeletonCard } from '@/components/ui/SkeletonCard';
import { Car } from '@/lib/types';
import Link from 'next/link';

function ResultsContent() {
  const searchParams = useSearchParams();
  const [cars, setCars] = useState<Car[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // Derive subtitle from search params
  const make = searchParams.get('make');
  const model = searchParams.get('model');
  const budget = searchParams.get('budget');
  const location = searchParams.get('location');
  
  const titleParts = [];
  if (make || model) titleParts.push(`${make || ''} ${model || ''}`.trim());
  if (budget) titleParts.push(`Under $${budget}`);
  if (location) titleParts.push(location);
  const subtitle = titleParts.length > 0 ? titleParts.join(' · ') : 'All Cars';

  useEffect(() => {
    const fetchCars = async () => {
      try {
        const res = await fetch('/api/search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.fromEntries(searchParams.entries()))
        });
        if (res.ok) {
          const data = await res.json();
          setCars(data.cars || []);
        }
      } catch (error) {
        console.error('Failed to fetch cars:', error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchCars();
  }, [searchParams]);

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8">
      <div className="mb-8">
        <h1 className="font-sora text-3xl font-bold text-[var(--text-primary)] mb-2">Your Top 5 Matches</h1>
        <p className="text-[var(--text-secondary)] font-medium text-lg">{subtitle}</p>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[...Array(5)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : cars.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {cars.map(car => (
            <CarCard key={car.id} car={car} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-20 text-center bg-white rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
          <span className="text-6xl mb-4">🏜️</span>
          <h2 className="font-sora text-2xl font-bold text-[var(--text-primary)] mb-2">No matches found</h2>
          <p className="text-[var(--text-secondary)] mb-6 max-w-md">We couldn't find any cars matching your exact criteria. Try widening your filters.</p>
          <Link 
            href="/" 
            className="bg-[var(--blue-dark)] text-white px-6 py-3 rounded-full font-medium hover:-translate-y-0.5 transition-transform shadow-md"
          >
            Adjust Search
          </Link>
        </div>
      )}
    </main>
  );
}

export default function ResultsPage() {
  return (
    <div className="min-h-screen bg-[var(--bg-secondary)] pb-20">
      <TopBar />
      <Suspense fallback={
        <div className="max-w-7xl mx-auto px-4 pt-8">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[...Array(5)].map((_, i) => <SkeletonCard key={i} />)}
          </div>
        </div>
      }>
        <ResultsContent />
      </Suspense>
    </div>
  );
}
