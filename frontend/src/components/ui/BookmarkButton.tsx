'use client';

import React from 'react';
import { Car } from '@/lib/types';
import { useBookmarks } from '@/context/BookmarksContext';

interface BookmarkButtonProps {
  car: Car;
  size?: 'sm' | 'md';
  className?: string;
}

export function BookmarkButton({ car, size = 'md', className = '' }: BookmarkButtonProps) {
  const { isBookmarked, toggleBookmark, mounted } = useBookmarks();

  if (!mounted) return null;

  const saved = isBookmarked(car.id);
  const dim = size === 'sm' ? 18 : 22;

  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        toggleBookmark(car);
      }}
      className={`rounded-full p-1.5 transition-colors hover:bg-black/10 focus:outline-none focus:ring-2 focus:ring-[var(--blue-dark)]/30 ${className}`}
      aria-label={saved ? 'Remove from saved' : 'Save car'}
    >
      {saved ? (
        <svg width={dim} height={dim} viewBox="0 0 24 24" fill="currentColor" className="text-[var(--accent-orange)]">
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
        </svg>
      ) : (
        <svg width={dim} height={dim} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
        </svg>
      )}
    </button>
  );
}
