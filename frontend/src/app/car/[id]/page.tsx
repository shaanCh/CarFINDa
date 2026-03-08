'use client';

import React, { useEffect, useState, Suspense } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import { TopBar } from '@/components/layout/TopBar';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { ChatBubble } from '@/components/chat/ChatBubble';
import { ScoreBadge } from '@/components/ui/ScoreBadge';
import { Car, NegotiationStrategy } from '@/lib/types';

function NegotiationPanel({ car }: { car: Car }) {
  const [strategy, setStrategy] = useState<NegotiationStrategy | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [copiedDM, setCopiedDM] = useState(false);

  const generateStrategy = async () => {
    setIsLoading(true);
    setIsOpen(true);
    try {
      const res = await fetch('/api/negotiate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          listingId: car.id,
          listing: {
            year: car.year,
            make: car.make,
            model: car.model,
            trim: car.trim,
            price: car.price,
            mileage: car.mileage,
            location: car.location,
            source_name: car.source_name,
            source_url: car.source_url,
            vin: car.vin,
          },
          score: car.scoreBreakdown,
          preferences: {},
        }),
      });
      if (res.ok) {
        setStrategy(await res.json());
      }
    } catch (error) {
      console.error('Failed to generate negotiation strategy:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const copyDM = () => {
    if (strategy?.opening_dm) {
      navigator.clipboard.writeText(strategy.opening_dm);
      setCopiedDM(true);
      setTimeout(() => setCopiedDM(false), 2000);
    }
  };

  const fmt = (n: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

  if (!isOpen) {
    return (
      <div className="bg-white p-6 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-sora font-semibold text-lg text-[var(--text-primary)]">Negotiation Strategy</h3>
            <p className="text-[var(--text-secondary)] text-sm">Get data-backed talking points + a ready-to-send DM</p>
          </div>
          <button
            onClick={generateStrategy}
            disabled={isLoading}
            className="bg-[var(--accent-orange)] text-white px-6 py-3 rounded-full font-bold hover:shadow-lg transition-all hover:-translate-y-0.5 disabled:opacity-50"
          >
            {isLoading ? 'Generating...' : 'Generate Strategy'}
          </button>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="bg-white p-6 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm animate-pulse">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-5 h-5 border-2 border-[var(--accent-orange)] border-t-transparent rounded-full animate-spin" />
          <span className="font-medium text-[var(--text-primary)]">Analyzing market data and building your strategy...</span>
        </div>
        <div className="space-y-3">
          <div className="h-4 bg-gray-200 rounded w-3/4" />
          <div className="h-4 bg-gray-200 rounded w-1/2" />
          <div className="h-4 bg-gray-200 rounded w-2/3" />
        </div>
      </div>
    );
  }

  if (!strategy) return null;

  return (
    <div className="space-y-4">
      {/* Opening DM */}
      <div className="bg-white p-6 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-sora font-semibold text-lg text-[var(--text-primary)]">Ready-to-Send Message</h3>
          <button
            onClick={copyDM}
            className="text-sm font-medium text-[var(--blue-dark)] hover:underline"
          >
            {copiedDM ? 'Copied!' : 'Copy to clipboard'}
          </button>
        </div>
        <div className="bg-[var(--bg-secondary)] p-4 rounded-lg border border-[var(--border)] text-sm leading-relaxed">
          {strategy.opening_dm}
        </div>
      </div>

      {/* Fair Price Range */}
      <div className="bg-white p-6 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
        <h3 className="font-sora font-semibold text-lg text-[var(--text-primary)] mb-4">Fair Price Range</h3>
        <div className="flex items-center gap-2 mb-3">
          <div className="flex-1 h-3 bg-gray-100 rounded-full relative overflow-hidden">
            <div className="absolute left-0 h-full bg-green-400 rounded-full" style={{ width: '33%' }} />
            <div className="absolute left-[33%] h-full bg-yellow-400" style={{ width: '34%' }} />
            <div className="absolute right-0 h-full bg-red-300 rounded-r-full" style={{ width: '33%' }} />
          </div>
        </div>
        <div className="flex justify-between text-sm mb-2">
          <span className="text-green-700 font-bold">{fmt(strategy.fair_price.low)}</span>
          <span className="text-yellow-700 font-bold">{fmt(strategy.fair_price.mid)}</span>
          <span className="text-red-600 font-bold">{fmt(strategy.fair_price.high)}</span>
        </div>
        <p className="text-xs text-[var(--text-secondary)]">{strategy.fair_price.explanation}</p>

        <div className="mt-4 grid grid-cols-2 gap-4">
          <div className="bg-green-50 border border-green-200 p-3 rounded-lg">
            <span className="text-xs text-green-700 font-bold block mb-1">Your Opening Offer</span>
            <span className="text-lg font-bold text-green-800">{fmt(strategy.opening_offer.amount)}</span>
            <p className="text-xs text-green-700 mt-1">{strategy.opening_offer.reasoning}</p>
          </div>
          <div className="bg-red-50 border border-red-200 p-3 rounded-lg">
            <span className="text-xs text-red-700 font-bold block mb-1">Walk-Away Price</span>
            <span className="text-lg font-bold text-red-800">{fmt(strategy.walk_away_price.amount)}</span>
            <p className="text-xs text-red-700 mt-1">{strategy.walk_away_price.reasoning}</p>
          </div>
        </div>
      </div>

      {/* Leverage Points */}
      {strategy.leverage_points.length > 0 && (
        <div className="bg-white p-6 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
          <h3 className="font-sora font-semibold text-lg text-[var(--text-primary)] mb-3">Leverage Points</h3>
          <div className="space-y-3">
            {strategy.leverage_points.map((lp, i) => (
              <div key={i} className="flex items-start gap-3 bg-[var(--bg-secondary)] p-3 rounded-lg">
                <span className="text-xs font-bold uppercase text-[var(--blue-dark)] bg-[var(--blue-light)] px-2 py-0.5 rounded-full whitespace-nowrap mt-0.5">
                  {lp.category}
                </span>
                <div className="flex-1">
                  <p className="text-sm text-[var(--text-primary)]">{lp.point}</p>
                  <p className="text-xs text-[var(--text-secondary)] mt-1">Potential savings: {lp.impact}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Questions to Ask */}
      {strategy.questions_to_ask.length > 0 && (
        <div className="bg-white p-6 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
          <h3 className="font-sora font-semibold text-lg text-[var(--text-primary)] mb-3">Questions to Ask the Seller</h3>
          <div className="space-y-3">
            {strategy.questions_to_ask.map((q, i) => (
              <div key={i} className="border-l-2 border-[var(--blue-mid)] pl-3">
                <p className="text-sm font-medium text-[var(--text-primary)]">&ldquo;{q.question}&rdquo;</p>
                <p className="text-xs text-[var(--text-secondary)] mt-0.5">{q.why}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Negotiation Tips */}
      {strategy.negotiation_tips.length > 0 && (
        <div className="bg-[#FFF7ED] border border-[#FED7AA] p-5 rounded-[var(--radius-card)]">
          <h3 className="font-bold text-[#92400E] mb-2">Negotiation Tips</h3>
          <ul className="space-y-1">
            {strategy.negotiation_tips.map((tip, i) => (
              <li key={i} className="text-sm text-[#92400E]">&bull; {tip}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function DetailContent({ id }: { id: string }) {
  const searchParams = useSearchParams();
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const openChatMode = searchParams.get('chat') === 'open';

  const [car, setCar] = useState<Car | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchCar = async () => {
      try {
        const res = await fetch(`/api/car/${id}`);
        if (res.ok) {
          const data = await res.json();
          setCar(data.car);
        }
      } catch (error) {
        console.error('Failed to fetch car details:', error);
      } finally {
        setIsLoading(false);
      }
    };
    if (id) fetchCar();
  }, [id]);

  if (isLoading) {
    return (
      <div className="flex-1 max-w-7xl mx-auto w-full p-4 sm:p-6 lg:p-8 animate-pulse">
         <div className="w-full h-[300px] sm:h-[400px] bg-gray-200 rounded-[var(--radius-card)] mb-6"/>
         <div className="w-1/2 h-10 bg-gray-200 rounded mb-4"/>
         <div className="w-1/3 h-6 bg-gray-200 rounded"/>
      </div>
    );
  }

  if (!car) {
    return (
      <div className="flex items-center justify-center p-20 w-full">
        <h1 className="text-2xl font-bold font-sora">Car not found</h1>
      </div>
    );
  }

  const priceFormatted = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(car.price);
  const mileageFormatted = car.mileage ? new Intl.NumberFormat('en-US').format(car.mileage) : 'N/A';

  return (
    <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col lg:flex-row gap-8">

      {/* Left Column - Car Details (65%) */}
      <div className="w-full lg:w-[65%] flex flex-col gap-6">
        {/* Hero Image */}
        <div className="relative w-full h-[300px] sm:h-[400px] rounded-[var(--radius-card)] overflow-hidden shadow-sm bg-gray-100">
          {car.imageUrl ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={car.imageUrl}
              alt={`${car.year} ${car.make} ${car.model}`}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-gray-400">
              <span className="text-6xl">&#x1F697;</span>
            </div>
          )}
          <div className="absolute top-4 right-4 z-10">
            <ScoreBadge score={car.score} size="lg" />
          </div>
          {car.headline && (
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-4">
              <span className="text-white font-bold text-sm">{car.headline}</span>
            </div>
          )}
        </div>

        {/* Title block */}
        <div className="bg-white p-6 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
          <h1 className="font-sora text-3xl sm:text-4xl font-bold text-[var(--text-primary)] mb-4 leading-tight">
            {car.year} {car.make} {car.model} {car.trim || ''}
          </h1>

          {/* Recommendation explanation */}
          {car.explanation && (
            <p className="text-[var(--text-primary)] text-sm leading-relaxed mb-4 bg-[var(--bg-secondary)] p-4 rounded-lg border border-[var(--border)]">
              {car.explanation}
            </p>
          )}

          {/* Spec Grid */}
          <div className="grid grid-cols-2 gap-y-4 gap-x-8 text-sm sm:text-base">
            <div>
              <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Price</span>
              <span className="font-bold text-xl text-[var(--text-primary)]">{priceFormatted}</span>
              {car.marketAvgPrice && car.price < car.marketAvgPrice && (
                <span className="ml-2 bg-[#FEF3C7] text-[#92400E] text-xs font-bold px-1.5 py-0.5 rounded">
                  GREAT DEAL
                </span>
              )}
            </div>
            <div>
              <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Mileage</span>
              <span className="font-medium text-[var(--text-primary)]">{mileageFormatted} mi</span>
            </div>
            <div>
              <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Location</span>
              <span className="font-medium text-[var(--text-primary)]">{car.location}</span>
            </div>
            <div>
              <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Source</span>
              <span className="font-medium text-[var(--text-primary)] capitalize">{car.source_name || car.sellerType}</span>
            </div>
            {car.transmission && (
              <div>
                <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Transmission</span>
                <span className="font-medium text-[var(--text-primary)] capitalize">{car.transmission}</span>
              </div>
            )}
            {car.source_url && (
              <div>
                <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Original Listing</span>
                <a href={car.source_url} target="_blank" rel="noopener noreferrer" className="text-[var(--blue-dark)] font-medium hover:underline text-sm">
                  View on {car.source_name || 'marketplace'} &#x2197;
                </a>
              </div>
            )}
          </div>
        </div>

        {/* Strengths & Concerns */}
        {(car.strengths?.length || car.concerns?.length) ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {car.strengths && car.strengths.length > 0 && (
              <div className="bg-green-50 border border-green-200 p-5 rounded-[var(--radius-card)]">
                <h3 className="font-bold text-green-800 mb-2">Strengths</h3>
                <ul className="space-y-1">
                  {car.strengths.map((s, i) => (
                    <li key={i} className="text-sm text-green-800">&#10003; {s}</li>
                  ))}
                </ul>
              </div>
            )}
            {car.concerns && car.concerns.length > 0 && (
              <div className="bg-amber-50 border border-amber-200 p-5 rounded-[var(--radius-card)]">
                <h3 className="font-bold text-amber-800 mb-2">Concerns</h3>
                <ul className="space-y-1">
                  {car.concerns.map((c, i) => (
                    <li key={i} className="text-sm text-amber-800">&#9888; {c}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : null}

        {/* Recalls / Safety block */}
        {car.recallCount !== undefined && car.recallCount > 0 && (
          <div className="bg-[#FEF2F2] border border-[#FECACA] p-5 rounded-[var(--radius-card)] flex items-start gap-4">
            <span className="text-2xl mt-0.5">&#9888;&#65039;</span>
            <div>
              <h3 className="font-bold text-[#991B1B] mb-1">Open Recalls ({car.recallCount})</h3>
              <p className="text-[#991B1B] text-sm">This vehicle has {car.recallCount} unrepaired NHTSA safety recalls. Ask the seller for proof of repair.</p>
            </div>
          </div>
        )}

        {/* Negotiation Strategy */}
        <NegotiationPanel car={car} />
      </div>

      {/* Right Column - Chat Panel (35%) Desktop Only */}
      <div className="hidden lg:block lg:w-[35%] h-[600px] sticky top-20">
        <ChatPanel carId={car.id} score={car.score} />
      </div>

      {/* Mobile Floating Chat */}
      <ChatBubble carId={car.id} score={car.score} />

    </main>
  );
}

export default function CarDetailPage() {
  const { id } = useParams();
  if (typeof id !== 'string') return null;

  return (
    <div className="min-h-screen bg-[var(--bg-secondary)] flex flex-col">
      <TopBar />
      <Suspense fallback={
        <div className="flex-1 max-w-7xl mx-auto w-full p-4 sm:p-6 lg:p-8 animate-pulse">
           <div className="w-full h-[300px] sm:h-[400px] bg-gray-200 rounded-[var(--radius-card)] mb-6"/>
           <div className="w-1/2 h-10 bg-gray-200 rounded mb-4"/>
        </div>
      }>
        <DetailContent id={id} />
      </Suspense>
    </div>
  );
}
