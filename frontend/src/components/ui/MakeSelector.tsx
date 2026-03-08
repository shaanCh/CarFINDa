'use client';

import React from 'react';

// Hardcoded for MVP UI
const AVAILABLE_MAKES = [
  'Honda', 'Toyota', 'Ford', 'Chevrolet', 'Nissan',
  'Hyundai', 'Kia', 'Volkswagen', 'Subaru', 'Mazda',
  'BMW', 'Mercedes-Benz', 'Audi', 'Lexus'
];

interface MakeSelectorProps {
  selectedMake: string | null;
  onSelect: (make: string) => void;
}

export function MakeSelector({ selectedMake, onSelect }: MakeSelectorProps) {
  return (
    <div className="w-full">
      <h3 className="text-sm font-bold text-[var(--text-primary)] mb-3">Select Make</h3>
      <div 
        className="max-h-[220px] overflow-y-auto rounded-[var(--radius-card)] border border-[var(--border)] bg-white shadow-inner custom-scrollbar"
        role="listbox"
        aria-label="Car Makes"
      >
        {AVAILABLE_MAKES.map((make) => {
          const isSelected = selectedMake === make;
          return (
            <button
              key={make}
              role="option"
              aria-selected={isSelected}
              onClick={() => onSelect(make)}
              className={`
                w-full text-left px-4 py-3 text-sm font-medium transition-colors border-b border-[var(--border)] last:border-b-0
                hover:bg-[var(--bg-secondary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--blue-mid)]
                ${isSelected 
                  ? 'bg-[var(--blue-light)] text-[var(--blue-dark)] font-bold' 
                  : 'text-[var(--text-primary)]'}
              `}
            >
              {make}
            </button>
          );
        })}
      </div>
    </div>
  );
}
