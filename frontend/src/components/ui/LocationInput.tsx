'use client';

import React from 'react';

interface LocationInputProps {
  value: string;
  onChange: (val: string) => void;
}

export function LocationInput({ value, onChange }: LocationInputProps) {
  return (
    <div className="w-full">
      <label htmlFor="location-input" className="block text-sm font-bold text-[var(--text-primary)] mb-3">
        Location
      </label>
      <div className="relative">
        <span className="absolute left-4 top-1/2 -translate-y-1/2 text-xl text-[var(--text-secondary)] pointer-events-none">📍</span>
        <input
          id="location-input"
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Enter City, State, or Zip"
          className="w-full pl-12 pr-4 py-3 border border-[var(--border)] rounded-[var(--radius-card)] bg-white text-sm text-[var(--text-primary)] placeholder-[var(--text-secondary)] font-medium
                     transition-colors outline-none focus:border-[var(--blue-mid)] focus:ring-1 focus:ring-[var(--blue-mid)] shadow-sm"
        />
      </div>
    </div>
  );
}
