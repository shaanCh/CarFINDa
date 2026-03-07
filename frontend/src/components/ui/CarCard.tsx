import React from 'react';
import { Car } from '@/lib/types';
import { ScoreBadge } from './ScoreBadge';
import Link from 'next/link';

interface CarCardProps {
  car: Car;
}

export function CarCard({ car }: CarCardProps) {
  // Format price
  const priceFormatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0
  }).format(car.price);

  // Format mileage
  const mileageFormatted = new Intl.NumberFormat('en-US').format(car.mileage);

  // Capitalize seller type and transmission
  const sellerTypeStr = car.sellerType.charAt(0).toUpperCase() + car.sellerType.slice(1) + ' seller';
  const transmissionStr = car.transmission.charAt(0).toUpperCase() + car.transmission.slice(1);

  return (
    <div className="group relative bg-white border border-[var(--border)] rounded-[var(--radius-card)] overflow-hidden transition-all duration-200 hover:-translate-y-1 hover:shadow-[var(--shadow-card)] flex flex-col">
      {/* Image container */}
      <div className="relative w-full aspect-video bg-[var(--bg-secondary)] overflow-hidden">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img 
          src={car.imageUrl || 'https://via.placeholder.com/800x450?text=No+Image'} 
          alt={`${car.year} ${car.make} ${car.model}`}
          className="w-full h-full object-cover"
        />
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
          <span className="text-[var(--text-primary)] font-bold">{priceFormatted}</span> &middot; {mileageFormatted} mi &middot; {car.location}
        </p>
        <p className="text-[var(--text-secondary)] text-sm mb-5">
          {sellerTypeStr} &middot; {transmissionStr}
        </p>

        {/* Buttons shrink-to-fit at bottom */}
        <div className="mt-auto flex flex-col sm:flex-row gap-3">
          <Link href={`/car/${car.id}`} className="flex-1 bg-[var(--blue-dark)] text-white text-center py-2.5 rounded-lg font-medium transition-colors hover:bg-opacity-90">
            View Details &rarr;
          </Link>
          <Link href={`/car/${car.id}?chat=open`} className="flex-1 border-2 border-[var(--blue-mid)] text-[var(--blue-dark)] text-center py-2.5 rounded-lg font-medium transition-colors hover:bg-[var(--blue-light)]">
            💬 Explain Score
          </Link>
        </div>
      </div>
    </div>
  );
}
