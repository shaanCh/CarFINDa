import React from 'react';
import Link from 'next/link';

export function TopBar() {
  return (
    <div className="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-[var(--border)] w-full w-full">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <Link href="/" className="font-sora font-bold text-2xl text-[var(--text-primary)] tracking-tight hover:text-[var(--blue-dark)] transition-colors">
          Carvex
        </Link>
        
        <Link 
          href="/" 
          className="text-sm font-medium text-[var(--blue-dark)] hover:text-[var(--blue-mid)] transition-colors flex items-center gap-1 bg-[var(--blue-light)] py-1.5 px-3 rounded-full"
        >
          &larr; <span className="hidden sm:inline">Edit Search</span>
        </Link>
      </div>
    </div>
  );
}
