'use client';

import React, { useEffect, useState, Suspense } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import { TopBar } from '@/components/layout/TopBar';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { ChatBubble } from '@/components/chat/ChatBubble';
import { ScoreBadge } from '@/components/ui/ScoreBadge';
import { BookmarkButton } from '@/components/ui/BookmarkButton';
import { Car, NegotiationStrategy } from '@/lib/types';

function NegotiationPanel({ car }: { car: Car }) {
  const [strategy, setStrategy] = useState<NegotiationStrategy | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [copiedDM, setCopiedDM] = useState(false);
  const [sendingDM, setSendingDM] = useState(false);
  const [dmSent, setDmSent] = useState(false);
  const [dmError, setDmError] = useState<string | null>(null);

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
            year: car.year, make: car.make, model: car.model, trim: car.trim,
            price: car.price, mileage: car.mileage, location: car.location,
            source_name: car.source_name, source_url: car.source_url, vin: car.vin,
          },
          score: car.scoreBreakdown,
          preferences: {},
        }),
      });
      if (res.ok) setStrategy(await res.json());
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

  const sendViaDM = async () => {
    if (!strategy?.opening_dm || !car.source_url) return;
    setSendingDM(true);
    setDmError(null);
    try {
      const res = await fetch('/api/facebook', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'send-dm',
          listing: {
            year: car.year, make: car.make, model: car.model, trim: car.trim,
            price: car.price, mileage: car.mileage, location: car.location,
            listing_url: car.source_url, source_url: car.source_url, vin: car.vin,
          },
          strategy: 'balanced',
          send: true,
        }),
      });
      const data = await res.json();
      if (data.success) {
        setDmSent(true);
      } else {
        setDmError(data.error || 'Failed to send DM');
      }
    } catch {
      setDmError('Network error');
    } finally {
      setSendingDM(false);
    }
  };

  const fmt = (n: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

  if (!isOpen) {
    return (
      <div className="border border-[var(--border)] rounded-[var(--radius-card)] p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="font-semibold text-[var(--text-primary)]">Negotiation Strategy</h3>
            <p className="text-xs text-[var(--text-secondary)] mt-0.5">Data-backed talking points and a ready-to-send message</p>
          </div>
          <button
            onClick={generateStrategy}
            disabled={isLoading}
            className="text-sm font-medium text-[var(--bg-primary)] bg-[var(--text-primary)] px-5 py-2 rounded-full hover:opacity-80 transition-opacity disabled:opacity-50 whitespace-nowrap"
          >
            {isLoading ? 'Generating...' : 'Generate'}
          </button>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="border border-[var(--border)] rounded-[var(--radius-card)] p-5 animate-pulse">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-4 h-4 border-2 border-[var(--text-secondary)] border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-[var(--text-secondary)]">Analyzing market data...</span>
        </div>
        <div className="space-y-3">
          <div className="h-3 bg-[var(--border)] rounded w-3/4" />
          <div className="h-3 bg-[var(--border)] rounded w-1/2" />
        </div>
      </div>
    );
  }

  if (!strategy) return null;

  return (
    <div className="space-y-4">
      {/* Opening DM */}
      <div className="border border-[var(--border)] rounded-[var(--radius-card)] p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-[var(--text-primary)]">Ready-to-Send Message</h3>
          <div className="flex items-center gap-3">
            <button onClick={copyDM} className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors">
              {copiedDM ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
        <div className="bg-[var(--bg-secondary)] p-4 rounded-lg text-sm leading-relaxed text-[var(--text-primary)] mb-3">
          {strategy.opening_dm}
        </div>
        {/* Send via Facebook DM */}
        {car.source_url && car.source_name?.includes('facebook') && (
          <div className="flex items-center gap-3">
            {dmSent ? (
              <span className="text-xs font-semibold text-green-700 bg-green-50 px-3 py-1.5 rounded-full">
                Message sent via Facebook DM
              </span>
            ) : (
              <button
                onClick={sendViaDM}
                disabled={sendingDM}
                className="text-xs font-medium text-white bg-[#1877F2] px-4 py-1.5 rounded-full hover:bg-[#166FE5] transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                {sendingDM ? (
                  <>
                    <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Sending...
                  </>
                ) : (
                  'Send via Facebook DM'
                )}
              </button>
            )}
            {dmError && (
              <span className="text-xs text-[var(--accent-red)]">{dmError}</span>
            )}
          </div>
        )}
      </div>

      {/* Fair Price Range */}
      <div className="border border-[var(--border)] rounded-[var(--radius-card)] p-5">
        <h3 className="font-semibold text-[var(--text-primary)] mb-4">Fair Price Range</h3>
        <div className="flex-1 h-2 bg-[var(--bg-secondary)] rounded-full relative overflow-hidden mb-3">
          <div className="absolute left-0 h-full bg-green-400 rounded-full" style={{ width: '33%' }} />
          <div className="absolute left-[33%] h-full bg-yellow-400" style={{ width: '34%' }} />
          <div className="absolute right-0 h-full bg-red-300 rounded-r-full" style={{ width: '33%' }} />
        </div>
        <div className="flex justify-between text-sm mb-2">
          <span className="text-green-700 font-semibold">{fmt(strategy.fair_price.low)}</span>
          <span className="text-yellow-700 font-semibold">{fmt(strategy.fair_price.mid)}</span>
          <span className="text-red-600 font-semibold">{fmt(strategy.fair_price.high)}</span>
        </div>
        <p className="text-xs text-[var(--text-secondary)]">{strategy.fair_price.explanation}</p>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="bg-green-50 p-3 rounded-lg">
            <span className="text-[10px] uppercase tracking-wider text-green-700 font-semibold block mb-1">Opening offer</span>
            <span className="text-base font-bold text-green-800">{fmt(strategy.opening_offer.amount)}</span>
            <p className="text-xs text-green-700 mt-1">{strategy.opening_offer.reasoning}</p>
          </div>
          <div className="bg-red-50 p-3 rounded-lg">
            <span className="text-[10px] uppercase tracking-wider text-red-700 font-semibold block mb-1">Walk-away price</span>
            <span className="text-base font-bold text-red-800">{fmt(strategy.walk_away_price.amount)}</span>
            <p className="text-xs text-red-700 mt-1">{strategy.walk_away_price.reasoning}</p>
          </div>
        </div>
      </div>

      {/* Leverage Points */}
      {strategy.leverage_points.length > 0 && (
        <div className="border border-[var(--border)] rounded-[var(--radius-card)] p-5">
          <h3 className="font-semibold text-[var(--text-primary)] mb-3">Leverage Points</h3>
          <div className="space-y-2">
            {strategy.leverage_points.map((lp, i) => (
              <div key={i} className="flex items-start gap-3">
                <span className="text-[10px] font-semibold uppercase text-[var(--text-secondary)] bg-[var(--bg-secondary)] px-2 py-0.5 rounded-full whitespace-nowrap mt-0.5">
                  {lp.category}
                </span>
                <div className="flex-1">
                  <p className="text-sm text-[var(--text-primary)]">{lp.point}</p>
                  <p className="text-xs text-[var(--text-secondary)]">{lp.impact}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Questions to Ask */}
      {strategy.questions_to_ask.length > 0 && (
        <div className="border border-[var(--border)] rounded-[var(--radius-card)] p-5">
          <h3 className="font-semibold text-[var(--text-primary)] mb-3">Questions for the Seller</h3>
          <div className="space-y-3">
            {strategy.questions_to_ask.map((q, i) => (
              <div key={i} className="border-l-2 border-[var(--border)] pl-3">
                <p className="text-sm text-[var(--text-primary)]">&ldquo;{q.question}&rdquo;</p>
                <p className="text-xs text-[var(--text-secondary)] mt-0.5">{q.why}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tips */}
      {strategy.negotiation_tips.length > 0 && (
        <div className="border-l-2 border-[var(--accent-orange)] pl-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--accent-orange)] mb-1.5">Tips</p>
          {strategy.negotiation_tips.map((tip, i) => (
            <p key={i} className="text-sm text-[var(--text-secondary)] leading-relaxed">{tip}</p>
          ))}
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
    const loadCar = async () => {
      // 1. Try sessionStorage (populated by the results page)
      try {
        const cached = sessionStorage.getItem('carvex-cars');
        if (cached) {
          const cars: Car[] = JSON.parse(cached);
          const found = cars.find(c => c.id === id);
          if (found) {
            setCar(found);
            setIsLoading(false);
            return;
          }
        }
      } catch { /* parse error — fall through */ }

      // 2. Fall back to API
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
    if (id) loadCar();
  }, [id]);

  if (isLoading) {
    return (
      <div className="flex-1 max-w-6xl mx-auto w-full p-4 sm:p-6 lg:p-8 animate-pulse">
        <div className="w-full h-[300px] sm:h-[400px] bg-[var(--border)] rounded-[var(--radius-card)] mb-6" />
        <div className="w-1/2 h-8 bg-[var(--border)] rounded mb-4" />
        <div className="w-1/3 h-5 bg-[var(--border)] rounded" />
      </div>
    );
  }

  if (!car) {
    return (
      <div className="flex items-center justify-center p-20 w-full">
        <h1 className="text-xl text-[var(--text-primary)]" style={{ fontFamily: 'var(--font-serif)' }}><i>Car not found</i></h1>
      </div>
    );
  }

  const price = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(car.price);
  const miles = car.mileage ? new Intl.NumberFormat('en-US').format(car.mileage) : 'N/A';

  return (
    <main className="flex-1 max-w-6xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col lg:flex-row gap-8">

      {/* Left Column */}
      <div className="w-full lg:w-[63%] flex flex-col gap-5">
        {/* Hero Image */}
        <div className="relative w-full h-[300px] sm:h-[420px] rounded-[var(--radius-card)] overflow-hidden bg-[var(--bg-secondary)]">
          {car.imageUrl ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={car.imageUrl}
              alt={`${car.year} ${car.make} ${car.model}`}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-[var(--text-secondary)] opacity-20">
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <path d="M21 15l-5-5L5 21" />
              </svg>
            </div>
          )}
          <div className="absolute top-4 right-4 flex items-center gap-2">
            <BookmarkButton car={car} size="md" className="!p-2 bg-white/90 rounded-full shadow-sm" />
            <ScoreBadge score={car.score} size="lg" />
          </div>
          {car.headline && (
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/50 to-transparent px-5 py-4">
              <span className="text-white text-sm font-medium">{car.headline}</span>
            </div>
          )}
        </div>

        {/* Title + specs */}
        <div>
          <h1 className="text-2xl sm:text-3xl text-[var(--text-primary)] leading-tight mb-1" style={{ fontFamily: 'var(--font-serif)' }}>
            {car.year} {car.make} {car.model} {car.trim || ''}
          </h1>
          <div className="flex items-baseline gap-3 mb-4">
            <span className="text-xl font-bold text-[var(--text-primary)]">{price}</span>
            {car.marketAvgPrice && car.price < car.marketAvgPrice && (
              <span className="text-xs font-semibold text-green-700 bg-green-50 px-2 py-0.5 rounded-full">Below market</span>
            )}
          </div>

          {car.explanation && (
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-5">
              {car.explanation}
            </p>
          )}

          {/* Spec grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-y-4 gap-x-6 text-sm border-t border-[var(--border)] pt-5">
            <div>
              <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">Mileage</span>
              <span className="text-[var(--text-primary)]">{miles} mi</span>
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">Location</span>
              <span className="text-[var(--text-primary)]">{car.location}</span>
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">Source</span>
              <span className="text-[var(--text-primary)] capitalize">{car.source_name || car.sellerType}</span>
            </div>
            {car.transmission && (
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">Transmission</span>
                <span className="text-[var(--text-primary)] capitalize">{car.transmission}</span>
              </div>
            )}
            {car.drivetrain && (
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">Drivetrain</span>
                <span className="text-[var(--text-primary)]">{car.drivetrain}</span>
              </div>
            )}
            {car.fuel_type && (
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">Fuel Type</span>
                <span className="text-[var(--text-primary)] capitalize">{car.fuel_type}</span>
              </div>
            )}
            {car.mpg && (
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">MPG</span>
                <span className="text-[var(--text-primary)]">{car.mpg}</span>
              </div>
            )}
            {car.exterior_color && (
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">Exterior</span>
                <span className="text-[var(--text-primary)] capitalize">{car.exterior_color}</span>
              </div>
            )}
            {car.interior_color && (
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">Interior</span>
                <span className="text-[var(--text-primary)] capitalize">{car.interior_color}</span>
              </div>
            )}
            {car.vin && (
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">VIN</span>
                <span className="text-[var(--text-primary)] font-mono text-xs">{car.vin}</span>
              </div>
            )}
            {car.source_url && (
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-secondary)] font-semibold block mb-0.5">Listing</span>
                <a href={car.source_url} target="_blank" rel="noopener noreferrer" className="text-[var(--blue-dark)] hover:underline text-sm">
                  View original &#x2197;
                </a>
              </div>
            )}
          </div>
        </div>

        {/* Strengths & Concerns */}
        {(car.strengths?.length || car.concerns?.length) ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {car.strengths && car.strengths.length > 0 && (
              <div className="border-l-2 border-green-400 pl-4">
                <p className="text-[10px] uppercase tracking-wider font-semibold text-green-700 mb-1.5">Strengths</p>
                {car.strengths.map((s, i) => (
                  <p key={i} className="text-sm text-[var(--text-primary)] leading-relaxed">{s}</p>
                ))}
              </div>
            )}
            {car.concerns && car.concerns.length > 0 && (
              <div className="border-l-2 border-amber-400 pl-4">
                <p className="text-[10px] uppercase tracking-wider font-semibold text-amber-700 mb-1.5">Concerns</p>
                {car.concerns.map((c, i) => (
                  <p key={i} className="text-sm text-[var(--text-primary)] leading-relaxed">{c}</p>
                ))}
              </div>
            )}
          </div>
        ) : null}

        {/* Recalls */}
        {car.recallCount !== undefined && car.recallCount > 0 && (
          <div className="border-l-2 border-[var(--accent-red)] pl-4">
            <p className="text-[10px] uppercase tracking-wider font-semibold text-[var(--accent-red)] mb-1">
              {car.recallCount} open recall{car.recallCount > 1 ? 's' : ''}
            </p>
            <p className="text-sm text-[var(--text-secondary)]">
              This vehicle has unrepaired NHTSA safety recalls. Ask the seller for proof of repair.
            </p>
          </div>
        )}

        {/* Negotiation */}
        <NegotiationPanel car={car} />
      </div>

      {/* Right Column - Chat */}
      <div className="hidden lg:block lg:w-[37%] h-[600px] sticky top-20">
        <ChatPanel car={car} />
      </div>

      <ChatBubble car={car} />
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
        <div className="flex-1 max-w-6xl mx-auto w-full p-4 sm:p-6 lg:p-8 animate-pulse">
          <div className="w-full h-[300px] sm:h-[400px] bg-[var(--border)] rounded-[var(--radius-card)] mb-6" />
          <div className="w-1/2 h-8 bg-[var(--border)] rounded mb-4" />
        </div>
      }>
        <DetailContent id={id} />
      </Suspense>
    </div>
  );
}
