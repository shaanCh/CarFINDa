'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { FilterChip } from '@/components/ui/FilterChip';
import { AdvancedFilters } from '@/components/layout/AdvancedFilters';
import { SearchParams } from '@/lib/types';

export default function LandingPage() {
  const router = useRouter();
  const [params, setParams] = useState<SearchParams>({});
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const updateParam = (key: keyof SearchParams, value: any) => {
    setParams(prev => ({ ...prev, [key]: value }));
    setError('');
  };

  const handleSearch = () => {
    if (!params.make && !params.model && !params.budget) {
      setError('Please select a Make, Model, or Max Budget to start searching.');
      return;
    }

    setIsLoading(true);
    
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value) searchParams.append(key, String(value));
    });
    
    router.push(`/results?${searchParams.toString()}`);
  };

  return (
    <div className="min-h-screen bg-white relative overflow-hidden flex flex-col">
      <div className="absolute -top-40 -right-40 w-[600px] h-[600px] bg-[var(--blue-light)] rounded-full blur-[100px] opacity-70 pointer-events-none" />

      <header className="p-6 md:p-10 relative z-10 w-full">
        <h1 className="font-sora font-bold text-3xl md:text-4xl text-[var(--text-primary)] tracking-tight">CarFINDa</h1>
        <p className="text-[var(--text-secondary)] font-medium mt-1">Find the right car. <span className="text-[var(--blue-dark)]">No BS.</span></p>
      </header>

      <main className="flex-1 flex flex-col justify-center items-center px-4 w-full max-w-4xl mx-auto relative z-10 pb-20">
        
        <div className="w-full text-center mb-10">
          <h2 className="font-sora text-4xl md:text-6xl font-bold text-[var(--text-primary)] tracking-tight mb-4">
            Your perfect ride, zero stress.
          </h2>
          <p className="text-xl text-[var(--text-secondary)]">Tell us what matters. We do the math.</p>
        </div>

        <div className="flex flex-wrap justify-center gap-3 w-full max-w-3xl">
          <FilterChip 
            label="Make" 
            icon="🚗" 
            value={params.make} 
            isActive={!!params.make} 
            onClick={() => {
              const p = prompt('Enter Make (e.g. Honda, Toyota)');
              if (p) updateParam('make', p);
            }} 
          />
          <FilterChip 
            label="Model" 
            icon="🔍" 
            value={params.model} 
            isActive={!!params.model} 
            onClick={() => {
              const p = prompt('Enter Model (e.g. Civic, Camry)');
              if (p) updateParam('model', p);
            }} 
          />
          <FilterChip 
            label="Max Budget" 
            icon="💰" 
            value={params.budget ? `$${params.budget}` : undefined} 
            isActive={!!params.budget} 
            onClick={() => {
              const p = prompt('Enter Maximum Budget');
              if (p && !isNaN(Number(p))) updateParam('budget', Number(p));
            }} 
          />
          <FilterChip 
            label="Max Mileage" 
            icon="🛣️" 
            value={params.mileage ? `${params.mileage} mi` : undefined} 
            isActive={!!params.mileage} 
            onClick={() => {
              const p = prompt('Enter Maximum Mileage');
              if (p && !isNaN(Number(p))) updateParam('mileage', Number(p));
            }} 
          />
          <FilterChip 
            label="Location" 
            icon="📍" 
            value={params.location} 
            isActive={!!params.location} 
            onClick={() => {
              const p = prompt('Enter City or Zip (e.g. Chicago, 60601)');
              if (p) updateParam('location', p);
            }} 
          />
        </div>

        <AdvancedFilters />

        {error && (
          <p className="text-[var(--accent-red)] text-sm font-medium mt-4 animate-in fade-in">{error}</p>
        )}

        <div className="mt-10 w-full max-w-sm">
          <button
            onClick={handleSearch}
            disabled={isLoading}
            className="w-full bg-[var(--blue-dark)] text-white font-bold text-lg py-4 px-8 rounded-full shadow-[var(--shadow-card)] transition-all hover:-translate-y-1 hover:shadow-lg disabled:opacity-70 disabled:hover:translate-y-0 disabled:hover:shadow-[var(--shadow-card)] flex items-center justify-center gap-2"
          >
            {isLoading ? 'Searching...' : 'Find My Car →'}
          </button>
        </div>

      </main>
    </div>
  );
}
