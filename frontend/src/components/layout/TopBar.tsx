import React from 'react';
import Link from 'next/link';

export function TopBar() {
  return (
    <div className="sticky top-0 z-50 bg-[var(--bg-primary)]/90 backdrop-blur-md border-b border-[var(--border)] w-full">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        <Link href="/" className="text-2xl tracking-tight text-[var(--text-primary)] hover:opacity-70 transition-opacity" style={{ fontFamily: 'var(--font-serif)' }}>
          <i>Carfinda</i>
        </Link>

        <Link
          href="/"
          className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
        >
          &larr; New search
        </Link>
      </div>
    </div>
  );
}
