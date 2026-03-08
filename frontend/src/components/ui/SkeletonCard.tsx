import React from 'react';

export function SkeletonCard() {
  return (
    <div className="bg-[var(--bg-primary)] border border-[var(--border)] rounded-[var(--radius-card)] overflow-hidden animate-pulse flex flex-col">
      <div className="w-full aspect-[4/3] bg-[var(--border)]" />
      <div className="p-4 flex flex-col flex-grow">
        <div className="h-5 bg-[var(--border)] rounded w-3/4 mb-3" />
        <div className="h-4 bg-[var(--border)] rounded w-1/3 mb-2" />
        <div className="h-3 bg-[var(--border)] rounded w-1/2 mb-4" />
        <div className="mt-auto pt-3 border-t border-[var(--border)]">
          <div className="h-3 bg-[var(--border)] rounded w-24" />
        </div>
      </div>
    </div>
  );
}
