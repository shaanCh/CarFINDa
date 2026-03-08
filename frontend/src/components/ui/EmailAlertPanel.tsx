'use client';

import React, { useState } from 'react';
import { Car } from '@/lib/types';

interface Props {
  car: Car;
  alertType?: 'negotiation' | 'price_drop';
}

export function EmailAlertPanel({ car, alertType = 'negotiation' }: Props) {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [subscribed, setSubscribed] = useState(false);
  const [agentEmail, setAgentEmail] = useState('');
  const [error, setError] = useState('');

  const carTitle = `${car.year} ${car.make} ${car.model} ${car.trim || ''}`.trim();

  const handleSubscribe = async () => {
    if (!email || !email.includes('@')) {
      setError('Enter a valid email');
      return;
    }
    setIsSubmitting(true);
    setError('');

    try {
      const res = await fetch('/api/notifications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'subscribe',
          email,
          alert_type: alertType,
          listing: {
            id: car.id,
            year: car.year,
            make: car.make,
            model: car.model,
            trim: car.trim,
            price: car.price,
            mileage: car.mileage,
            source_url: car.source_url,
            vin: car.vin,
          },
          car_title: carTitle,
          car_price: car.price,
          image_url: car.imageUrl,
        }),
      });

      const data = await res.json();
      if (data.success) {
        setSubscribed(true);
        setAgentEmail(data.agent_email || '');
      } else {
        setError(data.error || 'Failed to subscribe');
      }
    } catch {
      setError('Network error');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (subscribed) {
    return (
      <div className="border border-green-200 bg-green-50/60 rounded-[var(--radius-card)] p-5">
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 rounded-full bg-green-100 flex items-center justify-center flex-shrink-0 mt-0.5">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#15803d" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-green-800">Alerts active</p>
            <p className="text-xs text-green-700 mt-0.5">
              {alertType === 'negotiation'
                ? `We'll email ${email} when sellers reply with our suggested counter-offer.`
                : `We'll email ${email} if the price drops on this listing.`}
            </p>
            {agentEmail && (
              <p className="text-xs text-green-600 mt-2">
                Agent email: <span className="font-mono">{agentEmail}</span>
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="border border-[var(--border)] rounded-[var(--radius-card)] p-5">
      <div className="flex items-start gap-3 mb-3">
        <div className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center flex-shrink-0 mt-0.5">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <polyline points="22,6 12,13 2,6" />
          </svg>
        </div>
        <div>
          <p className="text-sm font-semibold text-[var(--text-primary)]">
            {alertType === 'negotiation' ? 'Get negotiation updates' : 'Watch for price drops'}
          </p>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
            {alertType === 'negotiation'
              ? 'Our agent will email you when a seller replies, with a suggested counter-offer ready to go.'
              : `Get emailed if ${carTitle} drops in price.`}
          </p>
        </div>
      </div>

      <div className="flex gap-2">
        <input
          type="email"
          value={email}
          onChange={(e) => { setEmail(e.target.value); setError(''); }}
          placeholder="your@email.com"
          className="flex-1 text-sm px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:border-[var(--blue-mid)] transition-colors"
          onKeyDown={(e) => e.key === 'Enter' && handleSubscribe()}
        />
        <button
          onClick={handleSubscribe}
          disabled={isSubmitting}
          className="text-sm font-medium text-white bg-[var(--text-primary)] px-4 py-2 rounded-lg hover:opacity-80 transition-opacity disabled:opacity-50 whitespace-nowrap"
        >
          {isSubmitting ? 'Saving...' : alertType === 'negotiation' ? 'Notify me' : 'Watch'}
        </button>
      </div>
      {error && (
        <p className="text-xs text-[var(--accent-red)] mt-1.5">{error}</p>
      )}
    </div>
  );
}
