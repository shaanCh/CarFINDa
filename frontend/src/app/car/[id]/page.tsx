'use client';

import React, { useEffect, useState, Suspense } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import { TopBar } from '@/components/layout/TopBar';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { ChatBubble } from '@/components/chat/ChatBubble';
import { ScoreBadge } from '@/components/ui/ScoreBadge';
import { Car } from '@/lib/types';

function DetailContent({ id }: { id: string }) {
  const searchParams = useSearchParams();
  // We grab it just to mount chat opened if needed, though bubble handles its own state
  const openChatMode = searchParams.get('chat') === 'open';
  
  const [car, setCar] = useState<Car | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchCar = async () => {
      try {
        const res = await fetch(`/api/car/${id}`);
        if (res.ok) {
          const data = await res.json();
          setCar(data.car);
        }
      } catch (error) {
        console.error('Failed to fetch car details:', error);
      } finally {
        setIsLoading(false);
      }
    };
    if (id) fetchCar();
  }, [id]);

  if (isLoading) {
    return (
      <div className="flex-1 max-w-7xl mx-auto w-full p-4 sm:p-6 lg:p-8 animate-pulse">
         <div className="w-full h-[300px] sm:h-[400px] bg-gray-200 rounded-[var(--radius-card)] mb-6"/>
         <div className="w-1/2 h-10 bg-gray-200 rounded mb-4"/>
         <div className="w-1/3 h-6 bg-gray-200 rounded"/>
      </div>
    );
  }

  if (!car) {
    return (
      <div className="flex items-center justify-center p-20 w-full">
        <h1 className="text-2xl font-bold font-sora">Car not found</h1>
      </div>
    );
  }

  const priceFormatted = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(car.price);
  const mileageFormatted = new Intl.NumberFormat('en-US').format(car.mileage);

  return (
    <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col lg:flex-row gap-8">
      
      {/* Left Column - Car Details (65%) */}
      <div className="w-full lg:w-[65%] flex flex-col gap-6">
        {/* Hero Image */}
        <div className="relative w-full h-[300px] sm:h-[400px] rounded-[var(--radius-card)] overflow-hidden shadow-sm bg-gray-100">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img 
            src={car.imageUrl || 'https://via.placeholder.com/1200x800?text=No+Image'} 
            alt={`${car.year} ${car.make} ${car.model}`}
            className="w-full h-full object-cover"
          />
          <div className="absolute top-4 right-4 z-10">
            <ScoreBadge score={car.score} size="lg" />
          </div>
        </div>

        {/* Title block */}
        <div className="bg-white p-6 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm">
          <h1 className="font-sora text-3xl sm:text-4xl font-bold text-[var(--text-primary)] mb-4 leading-tight">
            {car.year} {car.make} {car.model} {car.trim || ''}
          </h1>
          
          {/* Spec Grid */}
          <div className="grid grid-cols-2 gap-y-4 gap-x-8 text-sm sm:text-base">
            <div>
              <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Price</span>
              <span className="font-bold text-xl text-[var(--text-primary)]">{priceFormatted}</span>
              {car.marketAvgPrice && car.price < car.marketAvgPrice && (
                <span className="ml-2 bg-[#FEF3C7] text-[#92400E] text-xs font-bold px-1.5 py-0.5 rounded">
                  GREAT DEAL
                </span>
              )}
            </div>
            <div>
              <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Mileage</span>
              <span className="font-medium text-[var(--text-primary)]">{mileageFormatted} mi</span>
            </div>
            <div>
              <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Location</span>
              <span className="font-medium text-[var(--text-primary)]">{car.location}</span>
            </div>
            <div>
              <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Seller</span>
              <span className="font-medium text-[var(--text-primary)] capitalize">{car.sellerType}</span>
            </div>
            <div>
              <span className="text-[var(--text-secondary)] block text-xs uppercase tracking-wider font-bold mb-1">Transmission</span>
              <span className="font-medium text-[var(--text-primary)] capitalize">{car.transmission}</span>
            </div>
          </div>
        </div>

        {/* Recalls / Safety block */}
        {car.recallCount !== undefined && car.recallCount > 0 && (
          <div className="bg-[#FEF2F2] border border-[#FECACA] p-5 rounded-[var(--radius-card)] flex items-start gap-4">
            <span className="text-2xl mt-0.5">⚠️</span>
            <div>
              <h3 className="font-bold text-[#991B1B] mb-1">Open Recalls ({car.recallCount})</h3>
              <p className="text-[#991B1B] text-sm">This vehicle has {car.recallCount} unrepaired NHTSA safety recalls. Please ask the seller for proof of repair.</p>
            </div>
          </div>
        )}

        {/* Seller Action Card */}
        <div className="bg-white p-6 rounded-[var(--radius-card)] border border-[var(--border)] shadow-sm flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="text-center sm:text-left">
            <h3 className="font-sora font-semibold text-lg text-[var(--text-primary)]">Contact Seller</h3>
            <p className="text-[var(--text-secondary)] text-sm">Usually replies within 24 hours</p>
          </div>
          <button className="w-full sm:w-auto bg-[var(--blue-dark)] text-white px-8 py-3 rounded-full font-bold hover:shadow-[var(--shadow-card)] transition-all hover:-translate-y-0.5">
            Message Seller
          </button>
        </div>

      </div>

      {/* Right Column - Chat Panel (35%) Desktop Only */}
      <div className="hidden lg:block lg:w-[35%] h-[600px] sticky top-20">
        <ChatPanel carId={car.id} score={car.score} />
      </div>
      
      {/* Mobile Floating Chat */}
      <ChatBubble carId={car.id} score={car.score} />

    </main>
  );
}

export default function CarDetailPage() {
  const { id } = useParams();
  if (typeof id !== 'string') return null;

  return (
    <div className="min-h-screen bg-[var(--bg-secondary)] flex flex-col">
      <TopBar />
      <Suspense fallback={
        <div className="flex-1 max-w-7xl mx-auto w-full p-4 sm:p-6 lg:p-8 animate-pulse">
           <div className="w-full h-[300px] sm:h-[400px] bg-gray-200 rounded-[var(--radius-card)] mb-6"/>
           <div className="w-1/2 h-10 bg-gray-200 rounded mb-4"/>
        </div>
      }>
        <DetailContent id={id} />
      </Suspense>
    </div>
  );
}
