'use client';

import React from 'react';
import { scoreToColor } from '@/lib/score';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Props {
  breakdown: {
    safety: number;
    reliability: number;
    value: number;
    efficiency: number;
    recall: number;
  };
  composite: number;
}

const DIMENSIONS: { key: keyof Props['breakdown']; label: string; icon: React.ReactNode }[] = [
  {
    key: 'safety',
    label: 'Safety',
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    ),
  },
  {
    key: 'reliability',
    label: 'Reliability',
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
      </svg>
    ),
  },
  {
    key: 'value',
    label: 'Value',
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="12" y1="1" x2="12" y2="23" />
        <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
      </svg>
    ),
  },
  {
    key: 'efficiency',
    label: 'Efficiency',
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2a10 10 0 0 1 0 20C7 22 3 17 3 12c4-1 7-4 9-10z" />
      </svg>
    ),
  },
  {
    key: 'recall',
    label: 'Recall',
    icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    ),
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ScoreBreakdown({ breakdown, composite }: Props) {
  return (
    <div className="border border-[var(--border)] rounded-[var(--radius-card)] p-5">
      {/* Header: composite score */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-[var(--text-primary)]">Score Breakdown</h3>
        <div className="flex items-center gap-2">
          <span className="text-xs text-[var(--text-secondary)]">Overall</span>
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-bold font-mono"
            style={{ backgroundColor: scoreToColor(composite), opacity: 0.9 }}
          >
            {composite}
          </div>
        </div>
      </div>

      {/* Dimension bars */}
      <div className="space-y-3">
        {DIMENSIONS.map(({ key, label, icon }) => {
          const value = breakdown[key] ?? 0;
          const color = scoreToColor(value);
          return (
            <div key={key} className="flex items-center gap-3">
              {/* Icon + label */}
              <div className="flex items-center gap-1.5 w-24 flex-shrink-0">
                <span className="text-[var(--text-secondary)] opacity-50">{icon}</span>
                <span className="text-xs text-[var(--text-secondary)]">{label}</span>
              </div>

              {/* Bar */}
              <div className="flex-1 h-2 bg-[var(--bg-secondary)] rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-700 ease-out"
                  style={{
                    width: `${Math.max(value, 3)}%`,
                    backgroundColor: color,
                    opacity: 0.85,
                  }}
                />
              </div>

              {/* Score number */}
              <span
                className="text-xs font-bold font-mono w-7 text-right"
                style={{ color }}
              >
                {value}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
