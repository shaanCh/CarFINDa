'use client';

import React from 'react';
import { Car } from '@/lib/types';
import { ScoreBadge } from './ScoreBadge';
import { BookmarkButton } from './BookmarkButton';
import Link from 'next/link';

interface CarCardProps {
  car: Car;
}

export function CarCard({ car }: CarCardProps) {
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
      className="group bg-[var(--bg-primary)] rounded-[var(--radius-card)] overflow-hidden transition-shadow duration-200 hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)] flex flex-col border border-[var(--border)]"
    >
      {/* Image */}
      <div className="relative w-full aspect-[4/3] bg-[var(--bg-secondary)] overflow-hidden">
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
        <div className="absolute top-3 left-3">
          <BookmarkButton car={car} size="sm" />
        </div>
        <div className="absolute top-3 right-3">
          <ScoreBadge score={car.score} size="md" />
        </div>
        {car.headline && (
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/50 to-transparent px-4 py-3">
            <span className="text-white text-xs font-medium">{car.headline}</span>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-4 flex flex-col flex-grow">
        <h3 className="text-base font-semibold text-[var(--text-primary)] mb-1 leading-snug" style={{ fontFamily: 'var(--font-serif)' }}>
          {car.year} {car.make} {car.model} {car.trim || ''}
        </h3>

        <div className="flex items-baseline gap-2 mb-1">
          <span className="text-lg font-bold text-[var(--text-primary)]">{price}</span>
          {miles && <span className="text-sm text-[var(--text-secondary)]">{miles}</span>}
        </div>

        <p className="text-xs text-[var(--text-secondary)] mb-3">
          {car.source_name || (car.sellerType === 'private' ? 'Private' : 'Dealer')}
          {car.location && <> &middot; {car.location}</>}
        </p>

        {car.explanation && (
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-3 line-clamp-2">
            {car.explanation}
          </p>
        )}

        {(car.strengths?.length || car.concerns?.length) ? (
          <div className="flex flex-wrap gap-1 mb-3">
            {car.strengths?.slice(0, 2).map((s, i) => (
              <span key={`s-${i}`} className="text-[10px] font-medium text-green-800 bg-green-50 px-2 py-0.5 rounded-full">
                {s}
              </span>
            ))}
            {car.concerns?.slice(0, 1).map((c, i) => (
              <span key={`c-${i}`} className="text-[10px] font-medium text-amber-800 bg-amber-50 px-2 py-0.5 rounded-full">
                {c}
              </span>
            ))}
          </div>
        ) : null}

        <div className="mt-auto pt-3 border-t border-[var(--border)] flex items-center justify-between">
          <span className="text-xs font-medium text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors">
            View details &rarr;
          </span>
        </div>
      </div>
    </Link>
  );
}
