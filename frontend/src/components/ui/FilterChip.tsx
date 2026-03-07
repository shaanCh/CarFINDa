'use client';

import React from 'react';

interface FilterChipProps {
  label: string;
  icon: string;
  value?: string;
  isActive?: boolean;
  onClick?: () => void;
  className?: string;
}

export function FilterChip({ label, icon, value, isActive = false, onClick, className = '' }: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`
        flex items-center gap-2 px-4 py-2 rounded-[var(--radius-bubble)] border transition-all duration-200
        hover:-translate-y-0.5 hover:shadow-[var(--shadow-card)]
        ${isActive 
          ? 'bg-[var(--blue-light)] border-[var(--blue-mid)] text-[var(--text-primary)]' 
          : 'bg-white border-[var(--border)] text-[var(--text-secondary)]'}
        ${className}
      `}
    >
      <span className="text-lg">{icon}</span>
      <span className="text-sm font-medium">
        {isActive && value ? value : label}
      </span>
    </button>
  );
}
