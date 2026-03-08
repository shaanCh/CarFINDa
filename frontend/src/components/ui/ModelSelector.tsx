'use client';

import React from 'react';

// Mock DB relation
const MODELS_BY_MAKE: Record<string, string[]> = {
  'Honda': ['Civic', 'Accord', 'CR-V', 'Pilot', 'Odyssey', 'HR-V'],
  'Toyota': ['Camry', 'Corolla', 'RAV4', 'Highlander', 'Tacoma', 'Prius'],
  'Ford': ['F-150', 'Escape', 'Explorer', 'Mustang', 'Bronco', 'Edge'],
  'Chevrolet': ['Silverado', 'Equinox', 'Malibu', 'Tahoe', 'Traverse', 'Camaro'],
  'Nissan': ['Rogue', 'Altima', 'Sentra', 'Pathfinder', 'Frontier'],
  'Hyundai': ['Tucson', 'Elantra', 'Santa Fe', 'Sonata', 'Palisade'],
  'Kia': ['Telluride', 'Sportage', 'Sorento', 'Forte', 'Optima'],
  'Volkswagen': ['Jetta', 'Tiguan', 'Atlas', 'Golf', 'Passat'],
  'Subaru': ['Outback', 'Forester', 'Crosstrek', 'Impreza', 'Ascent'],
  'Mazda': ['CX-5', 'Mazda3', 'Mazda6', 'CX-9', 'CX-30'],
  'BMW': ['3 Series', '5 Series', 'X3', 'X5', '4 Series'],
  'Mercedes-Benz': ['C-Class', 'E-Class', 'GLC', 'GLE', 'S-Class'],
  'Audi': ['A4', 'Q5', 'A6', 'Q7', 'A3'],
  'Lexus': ['RX', 'ES', 'NX', 'IS', 'GX']
};

interface ModelSelectorProps {
  selectedMake: string | null;
  selectedModel: string | null;
  onSelect: (model: string) => void;
}

export function ModelSelector({ selectedMake, selectedModel, onSelect }: ModelSelectorProps) {
  
  if (!selectedMake) {
    return (
      <div className="w-full h-full min-h-[150px] flex flex-col items-center justify-center border border-dashed border-[var(--border)] rounded-[var(--radius-card)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] p-6 text-center">
        <span className="text-3xl mb-2 opacity-50">🚗</span>
        <p className="text-sm font-medium">Select a Make first to see available models.</p>
      </div>
    );
  }

  const models = MODELS_BY_MAKE[selectedMake] || [];

  return (
    <div className="w-full h-full flex flex-col animate-in fade-in slide-in-from-right-4 duration-300">
      <h3 className="text-sm font-bold text-[var(--text-primary)] mb-3">Select Model <span className="text-[var(--text-secondary)] font-normal ml-1">for {selectedMake}</span></h3>
      
      <div 
        className="max-h-[220px] overflow-y-auto rounded-[var(--radius-card)] border border-[var(--border)] bg-white shadow-inner custom-scrollbar"
        role="listbox"
        aria-label="Car Models"
      >
        {models.length === 0 ? (
           <div className="px-4 py-6 text-center text-sm text-[var(--text-secondary)]">No models found for {selectedMake}.</div>
        ) : (
          models.map((model) => {
            const isSelected = selectedModel === model;
            return (
              <button
                key={model}
                role="option"
                aria-selected={isSelected}
                onClick={() => onSelect(model)}
                className={`
                  w-full text-left px-4 py-3 text-sm font-medium transition-colors border-b border-[var(--border)] last:border-b-0
                  hover:bg-[var(--bg-secondary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--blue-mid)]
                  ${isSelected 
                    ? 'bg-[var(--blue-light)] text-[var(--blue-dark)] font-bold' 
                    : 'text-[var(--text-primary)]'}
                `}
              >
                {model}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
