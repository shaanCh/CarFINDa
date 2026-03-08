'use client';

import React, { useEffect, useState, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { TopBar } from '@/components/layout/TopBar';
import { CarCard } from '@/components/ui/CarCard';
import { SkeletonCard } from '@/components/ui/SkeletonCard';
import { Car, Synthesis } from '@/lib/types';
import Link from 'next/link';

function ResultsContent() {
  const searchParams = useSearchParams();
  const [cars, setCars] = useState<Car[]>([]);
  const [synthesis, setSynthesis] = useState<Synthesis | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [stage, setStage] = useState<string>('Starting search...');

  const query = searchParams.get('query');
  const make = searchParams.get('make');
  const model = searchParams.get('model');
  const budget = searchParams.get('budget');
  const location = searchParams.get('location');

  const titleParts = [];
  if (query) titleParts.push(query);
  else {
    if (make || model) titleParts.push(`${make || ''} ${model || ''}`.trim());
    if (budget) titleParts.push(`Under $${budget}`);
    if (location) titleParts.push(location);
  }
  const subtitle = titleParts.length > 0 ? titleParts.join(' · ') : 'All Cars';

  useEffect(() => {
    const fetchCars = async () => {
      // Animate through pipeline stages
      const stages = [
        'Parsing your preferences...',
        'Searching marketplaces...',
        'Scoring vehicles...',
        'Generating recommendations...',
      ];
      let stageIdx = 0;
      const stageInterval = setInterval(() => {
        stageIdx = Math.min(stageIdx + 1, stages.length - 1);
        setStage(stages[stageIdx]);
      }, 3000);

      try {
        const res = await fetch('/api/search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.fromEntries(searchParams.entries()))
        });
        if (res.ok) {
          const data = await res.json();
          setCars(data.cars || []);
          setSynthesis(data.synthesis || null);
        }
      } catch (error) {
        console.error('Failed to fetch cars:', error);
      } finally {
        clearInterval(stageInterval);
        setIsLoading(false);
      }
    };

    fetchCars();
  }, [searchParams]);

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 pb-20">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-sora text-3xl font-bold text-[var(--text-primary)] mb-2">
          {isLoading ? 'Finding Your Cars...' : `Your Top ${Math.min(cars.length, 5)} Matches`}
        </h1>
        <p className="text-[var(--text-secondary)] font-medium text-lg">{subtitle}</p>
      </div>

      {isLoading ? (
        <div>
          {/* Pipeline status */}
          <div className="mb-8 flex items-center gap-3 bg-white p-4 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
            <div className="w-5 h-5 border-2 border-[var(--blue-mid)] border-t-transparent rounded-full animate-spin" />
            <span className="text-[var(--text-primary)] font-medium">{stage}</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[...Array(5)].map((_, i) => <SkeletonCard key={i} />)}
          </div>
        </div>
      ) : cars.length > 0 ? (
        <div>
          {/* Synthesis summary */}
          {synthesis?.search_summary && (
            <div className="mb-6 bg-white p-5 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
              <p className="text-[var(--text-primary)] leading-relaxed">{synthesis.search_summary}</p>
            </div>
          )}

          {/* Red flags */}
          {synthesis?.red_flags && synthesis.red_flags.length > 0 && (
            <div className="mb-6 bg-[#FEF2F2] border border-[#FECACA] p-5 rounded-[var(--radius-card)]">
              <h3 className="font-bold text-[#991B1B] mb-2 flex items-center gap-2">
                <span>&#9888;&#65039;</span> Things to Watch
              </h3>
              <ul className="space-y-1">
                {synthesis.red_flags.map((flag, i) => (
                  <li key={i} className="text-[#991B1B] text-sm">&bull; {flag}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Car grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {cars.map(car => (
              <CarCard key={car.id} car={car} />
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-20 text-center bg-white rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
          <span className="text-6xl mb-4">&#x1F3DC;&#xFE0F;</span>
          <h2 className="font-sora text-2xl font-bold text-[var(--text-primary)] mb-2">No matches found</h2>
          <p className="text-[var(--text-secondary)] mb-6 max-w-md">We couldn&apos;t find any cars matching your exact criteria. Try widening your filters.</p>
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
