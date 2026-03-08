'use client';

import React from 'react';
import Link from 'next/link';
import { useBookmarks } from '@/context/BookmarksContext';

export function TopBar() {
  const { bookmarks, mounted } = useBookmarks();
  const count = mounted ? bookmarks.length : 0;

  return (
    <div className="sticky top-0 z-50 bg-[var(--bg-primary)]/90 backdrop-blur-md border-b border-[var(--border)] w-full">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        <Link href="/" className="text-2xl tracking-tight text-[var(--text-primary)] hover:opacity-70 transition-opacity" style={{ fontFamily: 'var(--font-serif)' }}>
          <i>Carfinda</i>
        </Link>

        <div className="flex items-center gap-4">
          <Link
            href="/saved"
            className="flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
            </svg>
            Saved
            {count > 0 && (
              <span className="text-[10px] font-semibold bg-[var(--accent-orange)] text-white px-1.5 py-0.5 rounded-full min-w-[18px] text-center">
                {count}
              </span>
            )}
          </Link>
          <Link
            href="/"
            className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            &larr; New search
          </Link>
        </div>
      </div>
    </div>
  );
}
