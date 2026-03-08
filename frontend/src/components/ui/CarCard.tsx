import React from 'react';
import { Car } from '@/lib/types';
import { ScoreBadge } from './ScoreBadge';
import Link from 'next/link';

interface CarCardProps {
  car: Car;
}

export function CarCard({ car }: CarCardProps) {
  const priceFormatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0
  }).format(car.price);

  const mileageFormatted = car.mileage
    ? new Intl.NumberFormat('en-US').format(car.mileage) + ' mi'
    : 'N/A';

  const sourceLabel = car.source_name || (car.sellerType === 'private' ? 'Private seller' : 'Dealer');
  const transmissionStr = car.transmission
    ? car.transmission.charAt(0).toUpperCase() + car.transmission.slice(1)
    : '';

  return (
    <div className="group relative bg-white border border-[var(--border)] rounded-[var(--radius-card)] overflow-hidden transition-all duration-200 hover:-translate-y-1 hover:shadow-[var(--shadow-card)] flex flex-col">
      {/* Recommendation badge */}
      {car.headline && (
        <div className="absolute top-0 left-0 right-0 z-10 bg-gradient-to-r from-[var(--blue-dark)] to-[var(--blue-mid)] text-white text-xs font-bold px-4 py-1.5 text-center">
          {car.headline}
        </div>
      )}

      {/* Image */}
      <div className={`relative w-full aspect-video bg-[var(--bg-secondary)] overflow-hidden ${car.headline ? 'mt-7' : ''}`}>
        {car.imageUrl ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={car.imageUrl}
            alt={`${car.year} ${car.make} ${car.model}`}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[var(--text-secondary)]">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" />
            </svg>
          </div>
        )}
        <div className="absolute top-3 right-3">
          <ScoreBadge score={car.score} size="md" />
        </div>
      </div>

      {/* Content */}
      <div className="p-5 flex flex-col flex-grow">
        <h3 className="font-sora text-xl font-semibold mb-2 text-[var(--text-primary)]">
          {car.year} {car.make} {car.model} {car.trim || ''}
        </h3>

        <p className="text-[var(--text-secondary)] text-sm mb-1 font-medium">
          <span className="text-[var(--text-primary)] font-bold">{priceFormatted}</span>
          {' '}&middot;{' '}{mileageFormatted}
          {car.location && <>{' '}&middot;{' '}{car.location}</>}
        </p>
        <p className="text-[var(--text-secondary)] text-sm mb-3">
          {sourceLabel}
          {transmissionStr && <>{' '}&middot;{' '}{transmissionStr}</>}
        </p>

        {/* Recommendation explanation */}
        {car.explanation && (
          <p className="text-sm text-[var(--text-primary)] mb-3 leading-relaxed bg-[var(--bg-secondary)] p-3 rounded-lg border border-[var(--border)]">
            {car.explanation}
          </p>
        )}

        {/* Strengths & concerns chips */}
        {(car.strengths?.length || car.concerns?.length) ? (
          <div className="flex flex-wrap gap-1.5 mb-4">
            {car.strengths?.slice(0, 2).map((s, i) => (
              <span key={`s-${i}`} className="inline-flex items-center text-xs font-medium bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full">
                &#10003; {s}
              </span>
            ))}
            {car.concerns?.slice(0, 1).map((c, i) => (
              <span key={`c-${i}`} className="inline-flex items-center text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded-full">
                &#9888; {c}
              </span>
            ))}
          </div>
        ) : null}

        {/* Buttons */}
        <div className="mt-auto flex flex-col sm:flex-row gap-3">
          <Link
            href={`/car/${car.id}`}
            className="flex-1 bg-[var(--blue-dark)] text-white text-center py-2.5 rounded-lg font-medium transition-colors hover:bg-opacity-90"
          >
            View Details &rarr;
          </Link>
          <Link
            href={`/car/${car.id}?chat=open`}
            className="flex-1 border-2 border-[var(--blue-mid)] text-[var(--blue-dark)] text-center py-2.5 rounded-lg font-medium transition-colors hover:bg-[var(--blue-light)]"
          >
            Ask About It
          </Link>
        </div>
      </div>
    </div>
  );
}
