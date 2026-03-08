'use client';

import React from 'react';
import Link from 'next/link';
import { TopBar } from '@/components/layout/TopBar';
import { CarCard } from '@/components/ui/CarCard';
import { useBookmarks } from '@/context/BookmarksContext';

export default function SavedPage() {
  const { bookmarks, mounted } = useBookmarks();

  return (
    <div className="min-h-screen bg-[var(--bg-secondary)]">
      <TopBar />
      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pt-10 pb-20">
        <div className="mb-10">
          <p className="text-xs uppercase tracking-widest text-[var(--text-secondary)] font-medium mb-2">
            {mounted ? `${bookmarks.length} saved` : 'Loading...'}
          </p>
          <h1 className="text-3xl font-normal text-[var(--text-primary)] leading-tight" style={{ fontFamily: 'var(--font-serif)' }}>
            <i>Saved Cars</i>
          </h1>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Cars you&apos;ve bookmarked in this browser. No account needed.
          </p>
        </div>

        {!mounted ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="bg-[var(--bg-primary)] rounded-[var(--radius-card)] h-64 animate-pulse border border-[var(--border)]" />
            ))}
          </div>
        ) : bookmarks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center border border-dashed border-[var(--border)] rounded-[var(--radius-card)] bg-[var(--bg-primary)]/50">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-[var(--text-secondary)] opacity-40 mb-4">
              <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
            </svg>
            <h2 className="text-xl text-[var(--text-primary)] mb-2" style={{ fontFamily: 'var(--font-serif)' }}>
              <i>No saved cars yet</i>
            </h2>
            <p className="text-sm text-[var(--text-secondary)] mb-6 max-w-md">
              Search for cars and tap the bookmark icon to save your favorites here.
            </p>
            <Link
              href="/"
              className="text-sm font-medium text-[var(--text-primary)] border border-[var(--border)] px-5 py-2.5 rounded-full hover:bg-[var(--bg-secondary)] transition-colors"
            >
              Start searching &rarr;
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {bookmarks.map((car) => (
              <CarCard key={car.id} car={car} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
