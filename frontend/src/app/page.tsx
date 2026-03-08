'use client';

import React, { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Image from 'next/image';

const TYPEWRITER_PROMPTS = [
  'Mid-size SUV under $25k with less than 30k miles',
  'Score and rank electric cars under $35k near me',
  'Reliable sedan under $15k, under 50k miles',
  'Truck under $35k, 2018 or newer',
];

const CHIP_PROMPTS = [
  'Mid-size SUV under $25k, less than 30k miles',
  'Sedan under $15k with under 50k miles',
  'Truck under $35k, 2018 or newer',
  'Compact car under $20k, low mileage',
];

const FILTER_OPTIONS = {
  budget: ['Under $10k', 'Under $20k', 'Under $30k', 'Under $50k'],
  type: ['Sedan', 'SUV', 'Truck', 'Coupe', 'Hatchback', 'Van'],
  fuel: ['Gas', 'Hybrid', 'Electric', 'Diesel'],
  year: ['2020+', '2018+', '2015+', '2010+'],
};

export default function LandingPage() {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [userLocation, setUserLocation] = useState('');
  const [placeholder, setPlaceholder] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const filtersRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMounted(true);
    const timer = setTimeout(() => inputRef.current?.focus(), 800);

    // Ask for location permission
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          try {
            const res = await fetch(
              `https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${pos.coords.latitude}&longitude=${pos.coords.longitude}&localityLanguage=en`
            );
            const data = await res.json();
            const city = data.city || data.locality || '';
            const state = data.principalSubdivisionCode?.replace('US-', '') || '';
            if (city && state) setUserLocation(`${city}, ${state}`);
          } catch {
            // Silent fail — location is optional
          }
        },
        () => {}, // User denied — that's fine
        { timeout: 5000 }
      );
    }

    return () => clearTimeout(timer);
  }, []);

  // Typewriter cycling placeholder
  useEffect(() => {
    if (query) return; // Stop animating when user is typing
    let promptIndex = 0;
    let charIndex = 0;
    let isDeleting = false;
    let timeout: ReturnType<typeof setTimeout>;

    const tick = () => {
      const current = TYPEWRITER_PROMPTS[promptIndex];
      if (!isDeleting) {
        charIndex++;
        setPlaceholder(current.slice(0, charIndex));
        if (charIndex === current.length) {
          // Pause at full text, then start deleting
          timeout = setTimeout(() => { isDeleting = true; tick(); }, 2000);
          return;
        }
        timeout = setTimeout(tick, 60);
      } else {
        charIndex--;
        setPlaceholder(current.slice(0, charIndex));
        if (charIndex === 0) {
          isDeleting = false;
          promptIndex = (promptIndex + 1) % TYPEWRITER_PROMPTS.length;
          timeout = setTimeout(tick, 400);
          return;
        }
        timeout = setTimeout(tick, 30);
      }
    };

    // Start after a brief delay
    timeout = setTimeout(tick, 1000);
    return () => clearTimeout(timeout);
  }, [query]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (filtersRef.current && !filtersRef.current.contains(e.target as Node)) {
        setFiltersOpen(false);
      }
    };
    if (filtersOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [filtersOpen]);

  const toggleFilter = (category: string, value: string) => {
    setFilters(prev => {
      if (prev[category] === value) {
        const next = { ...prev };
        delete next[category];
        return next;
      }
      return { ...prev, [category]: value };
    });
  };

  const activeCount = Object.keys(filters).length;

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() && activeCount === 0) return;

    setIsLoading(true);
    const searchParams = new URLSearchParams();
    if (query.trim()) searchParams.set('query', query.trim());
    Object.entries(filters).forEach(([k, v]) => searchParams.set(k, v));
    if (userLocation && !filters.location) searchParams.set('location', userLocation);
    router.push(`/results?${searchParams.toString()}`);
  };

  return (
    <div className="landing-root">
      <Image
        src="/hero-bg.png"
        alt=""
        fill
        priority
        className="landing-bg"
        sizes="100vw"
      />
      <div className="landing-overlay" />

      <div className={`landing-content ${mounted ? 'landing-content--visible' : ''}`}>
        <h1 className="landing-wordmark" style={{ fontFamily: 'var(--font-serif)' }}>
          Carfinda
        </h1>
        <p className="landing-tagline">
          Your car agent. Finds it. Scores it. Negotiates it.
        </p>

        <form onSubmit={handleSearch} className="glass search-bar">
          {/* Filters toggle */}
          <div className="filters-anchor" ref={filtersRef}>
            <button
              type="button"
              onClick={() => setFiltersOpen(o => !o)}
              className={`search-bar__filters-btn ${filtersOpen || activeCount > 0 ? 'search-bar__filters-btn--active' : ''}`}
              aria-label="Filters"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="4" y1="6" x2="20" y2="6" />
                <line x1="8" y1="12" x2="16" y2="12" />
                <line x1="11" y1="18" x2="13" y2="18" />
              </svg>
              {activeCount > 0 && <span className="filters-badge">{activeCount}</span>}
            </button>

            {filtersOpen && (
              <div className="glass filters-dropdown">
                {Object.entries(FILTER_OPTIONS).map(([category, options]) => (
                  <div key={category} className="filters-group">
                    <span className="filters-group__label">{category}</span>
                    <div className="filters-group__options">
                      {options.map(opt => (
                        <button
                          key={opt}
                          type="button"
                          className={`filters-chip ${filters[category] === opt ? 'filters-chip--active' : ''}`}
                          onClick={() => toggleFilter(category, opt)}
                        >
                          {opt}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            className="search-bar__input"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isLoading || (!query.trim() && activeCount === 0)}
            className="search-bar__btn"
            aria-label="Search"
          >
            {isLoading ? (
              <span className="search-bar__spinner" />
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
            )}
          </button>
        </form>

        <div className="example-prompts">
          {CHIP_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              className="example-prompt-chip"
              onClick={() => {
                setQuery(prompt);
                inputRef.current?.focus();
              }}
            >
              {prompt}
            </button>
          ))}
        </div>

      </div>
    </div>
  );
}
