import React from 'react';

export function SkeletonCard() {
  return (
    <div className="bg-white border border-[var(--border)] rounded-[var(--radius-card)] overflow-hidden animate-pulse flex flex-col">
      {/* Image */}
      <div className="w-full aspect-video bg-gray-200" />
      
      {/* Content */}
      <div className="p-5 flex flex-col flex-grow">
        <div className="h-6 bg-gray-200 rounded w-3/4 mb-4" />
        <div className="h-4 bg-gray-200 rounded w-full mb-2" />
        <div className="h-4 bg-gray-200 rounded w-2/3 mb-6" />
        
        <div className="mt-auto flex flex-col sm:flex-row gap-3">
          <div className="h-10 bg-gray-200 rounded flex-1" />
          <div className="h-10 bg-gray-200 rounded flex-1" />
        </div>
      </div>
    </div>
  );
}
