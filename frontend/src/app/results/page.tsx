'use client';

import React, { useEffect, useState, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { TopBar } from '@/components/layout/TopBar';
import { CarCard } from '@/components/ui/CarCard';
import { SkeletonCard } from '@/components/ui/SkeletonCard';
import { ScoreBadge } from '@/components/ui/ScoreBadge';
import { RadialScore } from '@/components/ui/RadialScore';
import { ActivityFeed, ActivityResultData } from '@/components/ui/ActivityFeed';
import { FacebookOutreach } from '@/components/outreach/FacebookOutreach';
import { Car, Synthesis } from '@/lib/types';
import Link from 'next/link';

// ---------------------------------------------------------------------------
// Top Pick Card — large card with full LLM reasoning
// ---------------------------------------------------------------------------

function TopPickCard({ car, rank }: { car: Car; rank: number }) {
  const price = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(car.price);

  const miles = car.mileage
    ? new Intl.NumberFormat('en-US').format(car.mileage) + ' mi'
    : '';

  return (
    <Link
      href={`/car/${car.id}`}
      className="group bg-[var(--bg-primary)] rounded-[var(--radius-card)] overflow-hidden border border-[var(--border)] transition-shadow duration-200 hover:shadow-[0_4px_24px_rgba(0,0,0,0.08)] flex flex-col md:flex-row"
    >
      {/* Image */}
      <div className="relative w-full md:w-[300px] lg:w-[340px] flex-shrink-0 aspect-[4/3] md:aspect-auto bg-[var(--bg-secondary)] overflow-hidden">
        {car.imageUrl ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={car.imageUrl}
            alt={`${car.year} ${car.make} ${car.model}`}
            className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-[1.02]"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[var(--text-secondary)] opacity-30">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" />
            </svg>
          </div>
        )}
        {/* Rank badge */}
        <div
          className="absolute top-3 left-3 w-7 h-7 rounded-full text-white text-xs font-semibold flex items-center justify-center"
          style={{
            background: 'rgba(0,0,0,0.45)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            border: '1px solid rgba(255,255,255,0.15)',
            fontFamily: 'var(--font-serif, Georgia, serif)',
            textShadow: '0 1px 3px rgba(0,0,0,0.5)',
          }}
        >
          {rank}
        </div>
        <div className="absolute top-3 right-3">
          <ScoreBadge score={car.score} size="lg" />
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 p-6 md:p-8 flex flex-col min-w-0">
        {/* Headline from LLM */}
        {car.headline && (
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--accent-orange)] mb-2">
            {car.headline}
          </p>
        )}

        <h3 className="text-3xl font-bold text-[var(--text-primary)] mb-1.5 leading-snug" style={{ fontFamily: 'var(--font-serif)' }}>
          {car.year} {car.make} {car.model} {car.trim || ''}
        </h3>

        <div className="flex items-baseline gap-3 mb-1">
          <span className="text-2xl font-bold text-[var(--text-primary)]">{price}</span>
          {miles && <span className="text-sm text-[var(--text-secondary)]">{miles}</span>}
          {car.marketAvgPrice && car.price < car.marketAvgPrice && (
            <span className="text-xs font-semibold text-green-700 bg-green-50 px-2 py-0.5 rounded-full">
              {Math.round(((car.marketAvgPrice - car.price) / car.marketAvgPrice) * 100)}% below market
            </span>
          )}
        </div>

        <p className="text-xs text-[var(--text-secondary)] mb-4">
          {car.source_name || 'Dealer'}
          {car.location && <> &middot; {car.location}</>}
        </p>

        {/* Score breakdown rings */}
        {car.scoreBreakdown && (
          <div className="flex gap-4 mb-4">
            <RadialScore value={car.scoreBreakdown.safety} label="Safety" size={56} />
            <RadialScore value={car.scoreBreakdown.reliability} label="Reliability" size={56} />
            <RadialScore value={car.scoreBreakdown.value} label="Value" size={56} />
            <RadialScore value={car.scoreBreakdown.efficiency} label="Efficiency" size={56} />
          </div>
        )}

        {/* LLM explanation — truncated */}
        {car.explanation && (
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-3 line-clamp-2">
            {car.explanation}
          </p>
        )}

        {/* Strengths & Concerns */}
        {(car.strengths?.length || car.concerns?.length) ? (
          <div className="flex flex-wrap gap-1.5 mt-auto">
            {car.strengths?.slice(0, 3).map((s, i) => (
              <span key={`s-${i}`} className="text-[11px] font-medium text-green-800 bg-green-50 px-2.5 py-1 rounded-full">
                {s}
              </span>
            ))}
            {car.concerns?.slice(0, 2).map((c, i) => (
              <span key={`c-${i}`} className="text-[11px] font-medium text-amber-800 bg-amber-50 px-2.5 py-1 rounded-full">
                {c}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Results Content
// ---------------------------------------------------------------------------

function ResultsContent() {
  const searchParams = useSearchParams();
  const [cars, setCars] = useState<Car[]>([]);
  const [synthesis, setSynthesis] = useState<Synthesis | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [activityData, setActivityData] = useState<ActivityResultData | undefined>(undefined);
  const [showAllMore, setShowAllMore] = useState(false);
  const [showFBOutreach, setShowFBOutreach] = useState(false);

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
  const subtitle = titleParts.length > 0 ? titleParts.join(' \u00b7 ') : 'All Cars';

  useEffect(() => {
    // Build a stable cache key from the search params
    const paramEntries: [string, string][] = [];
    searchParams.forEach((value, key) => paramEntries.push([key, value]));
    paramEntries.sort(([a], [b]) => a.localeCompare(b));
    const cacheKey = 'carfinda-results:' + new URLSearchParams(paramEntries).toString();

    // Try restoring from sessionStorage (instant back-nav)
    try {
      const cached = sessionStorage.getItem(cacheKey);
      if (cached) {
        const { cars: cachedCars, synthesis: cachedSynthesis } = JSON.parse(cached);
        setCars(cachedCars);
        setSynthesis(cachedSynthesis);
        setIsLoading(false);
        return; // skip fetch
      }
    } catch { /* cache miss or parse error — fetch fresh */ }

    const fetchCars = async () => {
      try {
        const res = await fetch('/api/search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.fromEntries(searchParams.entries()))
        });
        if (res.ok) {
          const data = await res.json();
          const carList: Car[] = data.cars || [];
          setCars(carList);
          setSynthesis(data.synthesis || null);

          // Build activity result data from response
          const sourceBreakdown: Record<string, number> = {};
          carList.forEach(c => {
            const src = c.source_name || 'Unknown';
            sourceBreakdown[src] = (sourceBreakdown[src] || 0) + 1;
          });
          const topPickCount = carList.filter(c => c.headline || c.explanation).length;
          setActivityData({
            totalCars: carList.length,
            topPickCount,
            sourceBreakdown,
          });

          // Cache full results for back-navigation + detail pages
          try {
            sessionStorage.setItem(cacheKey, JSON.stringify({ cars: carList, synthesis: data.synthesis || null }));
            sessionStorage.setItem('carvex-cars', JSON.stringify(carList));
          } catch { /* quota exceeded — non-critical */ }
        }
      } catch (error) {
        console.error('Failed to fetch cars:', error);
        setActivityData({ totalCars: 0, topPickCount: 0, sourceBreakdown: {} });
      } finally {
        // Brief delay so the activity feed cascade can play before switching to results
        await new Promise(r => setTimeout(r, 900));
        setIsLoading(false);
      }
    };

    fetchCars();
  }, [searchParams]);

  // Split cars into top picks (those with synthesis recommendations) and the rest
  const topPicks = cars.filter(c => c.headline || c.explanation);
  const moreCars = cars.filter(c => !c.headline && !c.explanation);

  // How many "more" to show initially
  const MORE_INITIAL = 12;
  const visibleMore = showAllMore ? moreCars : moreCars.slice(0, MORE_INITIAL);

  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pt-10 pb-20">
      {/* Header */}
      <div className="mb-10">
        <p className="text-xs uppercase tracking-widest text-[var(--text-secondary)] font-medium mb-2">
          {isLoading ? 'Searching' : `${cars.length} results`}
        </p>
        <h1 className="text-3xl font-normal text-[var(--text-primary)] leading-tight" style={{ fontFamily: 'var(--font-serif)' }}>
          <i>{subtitle}</i>
        </h1>
      </div>

      {isLoading ? (
        <div className="flex flex-col lg:flex-row gap-8">
          {/* Activity feed */}
          <div className="lg:w-[380px] flex-shrink-0">
            <div className="bg-[var(--bg-primary)] border border-[var(--border)] rounded-[var(--radius-card)] p-5">
              <div className="flex items-center gap-2 mb-4">
                <div className={`w-2 h-2 rounded-full ${activityData ? 'bg-green-500' : 'bg-blue-500 animate-pulse'}`} />
                <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                  {activityData ? 'Pipeline Complete' : 'Pipeline Active'}
                </span>
              </div>
              <ActivityFeed
                query={query || subtitle}
                isComplete={!!activityData}
                resultData={activityData}
              />
            </div>
          </div>

          {/* Skeleton cards */}
          <div className="flex-1">
            <div className="space-y-4 mb-8">
              {[...Array(2)].map((_, i) => (
                <div key={i} className="bg-[var(--bg-primary)] border border-[var(--border)] rounded-[var(--radius-card)] overflow-hidden animate-pulse flex flex-col md:flex-row">
                  <div className="w-full md:w-[260px] aspect-[4/3] md:aspect-auto md:min-h-[180px] bg-[var(--border)]" />
                  <div className="flex-1 p-5">
                    <div className="h-3 bg-[var(--border)] rounded w-32 mb-3" />
                    <div className="h-5 bg-[var(--border)] rounded w-3/4 mb-3" />
                    <div className="h-4 bg-[var(--border)] rounded w-1/3 mb-4" />
                    <div className="h-3 bg-[var(--border)] rounded w-full mb-2" />
                    <div className="h-3 bg-[var(--border)] rounded w-2/3" />
                  </div>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
            </div>
          </div>
        </div>
      ) : cars.length > 0 ? (
        <div>
          {/* Search summary */}
          {synthesis?.search_summary && (
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-8 max-w-2xl">
              {synthesis.search_summary}
            </p>
          )}

          {/* Red flags */}
          {synthesis?.red_flags && synthesis.red_flags.length > 0 && (
            <div className="mb-8 border-l-2 border-[var(--accent-red)] pl-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-[var(--accent-red)] mb-1.5">Things to watch</p>
              {synthesis.red_flags.map((flag, i) => (
                <p key={i} className="text-sm text-[var(--text-secondary)]">{flag}</p>
              ))}
            </div>
          )}

          {/* ── Facebook Marketplace CTA ── */}
          <div className="mb-10 border border-[var(--border)] rounded-[var(--radius-card)] p-5 flex items-center justify-between gap-4 bg-[var(--bg-primary)]">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center flex-shrink-0">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="#1877F2">
                  <path d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047v-2.66c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.971H15.83c-1.491 0-1.956.93-1.956 1.886v2.264h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073" />
                </svg>
              </div>
              <div>
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Find on Facebook Marketplace</h3>
                <p className="text-xs text-[var(--text-secondary)]">
                  Search Facebook with the same filters and auto-negotiate with sellers via DM
                </p>
              </div>
            </div>
            <button
              onClick={() => setShowFBOutreach(true)}
              className="text-sm font-medium text-white bg-[#1877F2] px-5 py-2 rounded-full hover:bg-[#166FE5] transition-colors whitespace-nowrap flex-shrink-0"
            >
              Find & Negotiate
            </button>
          </div>

          {/* Facebook Outreach Modal */}
          {showFBOutreach && (
            <FacebookOutreach
              searchFilters={{
                query: query || undefined,
                makes: make ? [make] : undefined,
                models: model ? [model] : undefined,
                budget_max: budget ? (() => {
                  const num = parseFloat(budget.replace(/[^0-9.]/g, ''));
                  // Handle "Under $20k" -> 20 -> 20000
                  return num < 1000 ? num * 1000 : num;
                })() : undefined,
                location: location || undefined,
              }}
              onClose={() => setShowFBOutreach(false)}
            />
          )}

          {/* ── Top Picks ── */}
          {topPicks.length > 0 && (
            <section className="mb-12">
              <div className="flex items-baseline gap-3 mb-6">
                <h2 className="text-2xl font-semibold text-[var(--text-primary)]" style={{ fontFamily: 'var(--font-serif)' }}>
                  <i>Top Picks</i>
                </h2>
                <span className="text-xs text-[var(--text-secondary)] bg-[var(--bg-secondary)] px-2.5 py-1 rounded-full">
                  AI recommended
                </span>
              </div>
              <div className="space-y-4">
                {topPicks.map((car, i) => (
                  <TopPickCard key={car.id} car={car} rank={i + 1} />
                ))}
              </div>
            </section>
          )}

          {/* ── More Results ── */}
          {moreCars.length > 0 && (
            <section>
              <h2 className="text-2xl font-semibold text-[var(--text-primary)] mb-6" style={{ fontFamily: 'var(--font-serif)' }}>
                <i>More Results</i>
                <span className="text-sm font-normal text-[var(--text-secondary)] ml-3">
                  {moreCars.length} listings
                </span>
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {visibleMore.map(car => (
                  <CarCard key={car.id} car={car} />
                ))}
              </div>
              {moreCars.length > MORE_INITIAL && !showAllMore && (
                <div className="flex justify-center mt-8">
                  <button
                    onClick={() => setShowAllMore(true)}
                    className="text-sm font-medium text-[var(--text-primary)] border border-[var(--border)] px-6 py-2.5 rounded-full hover:bg-[var(--bg-primary)] transition-colors"
                  >
                    Show all {moreCars.length} results
                  </button>
                </div>
              )}
            </section>
          )}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <h2 className="text-2xl text-[var(--text-primary)] mb-2" style={{ fontFamily: 'var(--font-serif)' }}>
            <i>No matches found</i>
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-8 max-w-md">
            We couldn&apos;t find cars matching those criteria. Try broadening your search.
          </p>
          <Link
            href="/"
            className="text-sm font-medium text-[var(--text-primary)] border border-[var(--border)] px-5 py-2.5 rounded-full hover:bg-[var(--bg-secondary)] transition-colors"
          >
            &larr; New search
          </Link>
        </div>
      )}
    </main>
  );
}

export default function ResultsPage() {
  return (
    <div className="min-h-screen bg-[var(--bg-secondary)]">
      <TopBar />
      <Suspense fallback={
        <div className="max-w-6xl mx-auto px-4 pt-10">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {[...Array(6)].map((_, i) => <SkeletonCard key={i} />)}
          </div>
        </div>
      }>
        <ResultsContent />
      </Suspense>
    </div>
  );
}
