'use client';

import React, { useState } from 'react';

export function AdvancedFilters() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="w-full max-w-2xl mx-auto mt-4 px-2">
      <button 
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-center w-full pb-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors gap-1 text-sm font-medium"
      >
        More filters {isOpen ? '▴' : '▾'}
      </button>

      <div 
        className={`overflow-hidden transition-all duration-300 ease-in-out ${isOpen ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'}`}
      >
        <div className="mt-4 p-6 bg-white border border-[var(--border)] rounded-[var(--radius-card)] shadow-sm grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-[var(--text-primary)]">Reliability Priority</label>
            <select className="border border-[var(--border)] rounded-md p-2 text-sm bg-white text-[var(--text-primary)] focus:outline-[var(--blue-mid)]">
              <option>Low</option>
              <option>Medium</option>
              <option>High</option>
            </select>
          </div>
          
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-[var(--text-primary)]">Ownership Cost Concern</label>
            <select className="border border-[var(--border)] rounded-md p-2 text-sm bg-white text-[var(--text-primary)] focus:outline-[var(--blue-mid)]">
              <option>Not important</option>
              <option>Important</option>
              <option>Critical</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-[var(--text-primary)]">Seller Type</label>
            <select className="border border-[var(--border)] rounded-md p-2 text-sm bg-white text-[var(--text-primary)] focus:outline-[var(--blue-mid)]">
              <option>Any</option>
              <option>Dealer only</option>
              <option>Private only</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-[var(--text-primary)]">Transmission</label>
            <select className="border border-[var(--border)] rounded-md p-2 text-sm bg-white text-[var(--text-primary)] focus:outline-[var(--blue-mid)]">
              <option>Any</option>
              <option>Automatic</option>
              <option>Manual</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5 md:col-span-2">
            <label className="text-sm font-medium text-[var(--text-primary)]">Primary Use</label>
            <select className="border border-[var(--border)] rounded-md p-2 text-sm bg-white text-[var(--text-primary)] focus:outline-[var(--blue-mid)]">
              <option>Daily commute</option>
              <option>Road trips</option>
              <option>Family</option>
              <option>Hauling</option>
            </select>
          </div>
        </div>
      </div>
    </div>
  );
}
