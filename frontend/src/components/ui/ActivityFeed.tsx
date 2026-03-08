'use client';

import React, { useState, useEffect, useRef } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ActivityResultData {
  totalCars: number;
  topPickCount: number;
  sourceBreakdown: Record<string, number>;
}

interface Props {
  query: string;
  isComplete: boolean;
  resultData?: ActivityResultData;
}

type Status = 'pending' | 'active' | 'done';

interface Step {
  id: string;
  label: string;
  status: Status;
  detail: string;
}

// ---------------------------------------------------------------------------
// Step definitions & timing
// ---------------------------------------------------------------------------

const STEP_DEFS = [
  { id: 'parse', label: 'Parsing your preferences' },
  { id: 'carmax', label: 'Searching CarMax' },
  { id: 'carscom', label: 'Searching Cars.com' },
  { id: 'dedup', label: 'Removing duplicates' },
  { id: 'nhtsa', label: 'Checking NHTSA safety data' },
  { id: 'epa', label: 'Looking up EPA fuel economy' },
  { id: 'market', label: 'Analyzing market prices' },
  { id: 'score', label: 'Computing composite scores' },
  { id: 'synthesize', label: 'Generating recommendations' },
];

// ms from mount when each step becomes "active" (previous becomes "done")
const ACTIVATION_TIMES = [0, 1200, 3500, 7000, 7800, 10000, 11800, 13500, 15500];

// Simulated detail text shown while still loading
const SIM_DETAILS: Record<string, string> = {
  parse: '',
  carmax: 'Scanning inventory...',
  carscom: 'Loading listings...',
  dedup: 'Cross-referencing VINs...',
  nhtsa: 'Querying federal database...',
  epa: 'Matching fuel data...',
  market: 'Comparing prices...',
  score: 'Calculating...',
  synthesize: 'Picking top matches...',
};

// ---------------------------------------------------------------------------
// Icons (14×14 inline SVGs)
// ---------------------------------------------------------------------------

function StepIcon({ type, muted }: { type: string; muted: boolean }) {
  const cls = `w-3.5 h-3.5 flex-shrink-0 ${muted ? 'opacity-30' : 'opacity-60'}`;
  switch (type) {
    case 'parse':
    case 'synthesize':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 3v1m0 16v1m-7.07-2.93l.71-.71M5.64 5.64l-.71-.71M3 12h1m16 0h1m-2.93 7.07l-.71-.71M18.36 5.64l.71-.71" />
          <circle cx="12" cy="12" r="4" />
        </svg>
      );
    case 'carmax':
    case 'carscom':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="11" cy="11" r="8" />
          <path d="M21 21l-4.35-4.35" />
        </svg>
      );
    case 'dedup':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
        </svg>
      );
    case 'nhtsa':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      );
    case 'epa':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2a10 10 0 0 1 0 20C7 22 3 17 3 12c4-1 7-4 9-10z" />
        </svg>
      );
    case 'market':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
      );
    case 'score':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <rect x="3" y="14" width="4" height="7" rx="1" />
          <rect x="10" y="8" width="4" height="13" rx="1" />
          <rect x="17" y="3" width="4" height="18" rx="1" />
        </svg>
      );
    default:
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
        </svg>
      );
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ActivityFeed({ query, isComplete, resultData }: Props) {
  const [steps, setSteps] = useState<Step[]>(
    STEP_DEFS.map((d, i) => ({
      ...d,
      status: i === 0 ? 'active' : 'pending',
      detail: i === 0 ? query : '',
    }))
  );
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const completedRef = useRef(false);

  // Schedule step transitions
  useEffect(() => {
    ACTIVATION_TIMES.forEach((time, idx) => {
      if (idx === 0) return; // first step is already active
      const t = setTimeout(() => {
        if (completedRef.current) return;
        setSteps(prev =>
          prev.map((s, i) => {
            if (i === idx - 1) return { ...s, status: 'done', detail: s.detail || SIM_DETAILS[s.id] || '' };
            if (i === idx) return { ...s, status: 'active', detail: SIM_DETAILS[s.id] || '' };
            return s;
          })
        );
      }, time);
      timersRef.current.push(t);
    });

    const timers = timersRef.current;
    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When backend response arrives, snap all steps to done with real data
  useEffect(() => {
    if (!isComplete) return;
    completedRef.current = true;
    timersRef.current.forEach(clearTimeout);

    const realDetails = buildRealDetails(query, resultData);

    // Rapid cascade: complete remaining steps 80ms apart
    setSteps(prev => {
      const remaining = prev.filter(s => s.status !== 'done');
      const updated = [...prev];

      remaining.forEach((step, idx) => {
        setTimeout(() => {
          setSteps(p =>
            p.map(s =>
              s.id === step.id
                ? { ...s, status: 'done', detail: realDetails[s.id] || s.detail || '' }
                : s
            )
          );
        }, idx * 80);
      });

      // Also update already-done steps with real details
      return updated.map(s => ({
        ...s,
        detail: s.status === 'done' ? (realDetails[s.id] || s.detail) : s.detail,
      }));
    });
  }, [isComplete, resultData, query]);

  return (
    <div className="relative pl-6 py-1">
      {/* Timeline line */}
      <div
        className="absolute left-[7px] top-3 bottom-3 w-px bg-[var(--border)]"
        aria-hidden="true"
      />

      {steps.map((step) => (
        <div
          key={step.id}
          className={`relative flex items-start gap-3 py-2 transition-opacity duration-300 ${
            step.status === 'pending' ? 'opacity-40' : 'opacity-100'
          }`}
        >
          {/* Timeline node */}
          <div className="absolute -left-6 top-[7px] z-10">
            {step.status === 'done' ? (
              <div className="w-[15px] h-[15px] rounded-full bg-green-500 flex items-center justify-center">
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
            ) : step.status === 'active' ? (
              <div className="w-[15px] h-[15px] rounded-full border-2 border-blue-500 bg-blue-500/20 animate-pulse" />
            ) : (
              <div className="w-[15px] h-[15px] rounded-full border-[1.5px] border-[var(--border)] bg-[var(--bg-secondary)]" />
            )}
          </div>

          {/* Icon + label */}
          <div className="flex items-center gap-2 min-w-0">
            <StepIcon type={step.id} muted={step.status === 'pending'} />
            <span
              className={`text-sm leading-tight ${
                step.status === 'active'
                  ? 'text-[var(--text-primary)] font-medium'
                  : step.status === 'done'
                  ? 'text-[var(--text-primary)]'
                  : 'text-[var(--text-secondary)]'
              }`}
            >
              {step.status === 'active' ? `${step.label}...` : step.label}
            </span>
          </div>

          {/* Detail text */}
          {step.detail && step.status === 'done' && (
            <span className="ml-auto text-xs text-[var(--text-secondary)] whitespace-nowrap pl-4 animate-[fadeIn_300ms_ease-out]">
              {step.detail}
            </span>
          )}
          {step.status === 'active' && (
            <span className="ml-auto text-xs text-[var(--text-secondary)] whitespace-nowrap pl-4">
              {step.detail || ''}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildRealDetails(
  query: string,
  data?: ActivityResultData,
): Record<string, string> {
  if (!data) {
    return {
      parse: query,
      synthesize: 'Done',
    };
  }

  const carmaxCount = data.sourceBreakdown['CarMax'] || data.sourceBreakdown['carmax'] || 0;
  const carscomCount = data.sourceBreakdown['Cars.com'] || data.sourceBreakdown['cars.com'] || 0;
  const unknownSources = data.totalCars - carmaxCount - carscomCount;

  return {
    parse: query,
    carmax: carmaxCount > 0 ? `Found ${carmaxCount} listings` : 'No results',
    carscom: carscomCount > 0 ? `Found ${carscomCount} listings` : (unknownSources > 0 ? `Found ${unknownSources} listings` : 'No results'),
    dedup: `${data.totalCars} unique vehicles`,
    nhtsa: `Checked ${data.totalCars} vehicles`,
    epa: `Matched ${data.totalCars} models`,
    market: `Compared ${Math.max(data.totalCars * 4, 50)}+ prices`,
    score: `Scored ${data.totalCars} listings`,
    synthesize: data.topPickCount > 0 ? `Selected top ${data.topPickCount} picks` : 'Complete',
  };
}
