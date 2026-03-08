'use client';

import React, { useState, useCallback, useEffect } from 'react';
import { useNegotiations } from '@/lib/NegotiationContext';
import type { ActiveNegotiation } from '@/lib/negotiations';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FBListing {
  id: string;
  title?: string;
  year?: number;
  make?: string;
  model?: string;
  price?: number;
  mileage?: number;
  location?: string;
  listing_url?: string;
  seller_name?: string;
  image_urls?: string[];
}

interface DMPreview {
  listingId: string;
  message: string;
  targetPrice: number | null;
  strategyNotes: string | null;
  approved: boolean;
  sent: boolean;
  sending: boolean;
  error: string | null;
  conversationUrl: string | null;
}

type Step = 'idle' | 'logging-in' | 'searching' | 'results' | 'generating' | 'review' | 'sending' | 'done';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fmt = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

const fmtMiles = (n: number) => new Intl.NumberFormat('en-US').format(n);

async function fbApi(body: Record<string, unknown>) {
  const res = await fetch('/api/facebook', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || data.detail || `Request failed (${res.status})`);
  }
  return data;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  /** Search filters from the current results page */
  searchFilters: {
    query?: string;
    makes?: string[];
    models?: string[];
    budget_max?: number;
    budget_min?: number;
    min_year?: number;
    max_mileage?: number;
    location?: string;
  };
  onClose: () => void;
}

export function FacebookOutreach({ searchFilters, onClose }: Props) {
  const { addNegotiations } = useNegotiations();
  const [step, setStep] = useState<Step>('idle');
  const [statusText, setStatusText] = useState('');
  const [listings, setListings] = useState<FBListing[]>([]);
  const [dmPreviews, setDmPreviews] = useState<DMPreview[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [notifyEmail, setNotifyEmail] = useState('');
  const [emailSent, setEmailSent] = useState(false);
  const [emailSending, setEmailSending] = useState(false);

  // Pre-check Facebook session on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fbApi({ action: 'login' });
        if (!cancelled && res.success) setSessionReady(true);
      } catch {
        // Session not ready — that's fine, login will happen on start
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // ── Start the full flow ──
  const startFlow = useCallback(async () => {
    setError(null);

    try {
      // Step 1: Login (skip if session pre-checked)
      if (!sessionReady) {
        setStep('logging-in');
        setStatusText('Checking Facebook login...');

        const loginStatus = await fbApi({ action: 'login' });
        if (loginStatus.needs_2fa) {
          setError('Facebook requires 2FA. Please complete login manually and try again.');
          setStep('idle');
          return;
        }
        if (!loginStatus.success && loginStatus.error) {
          setError(`Login failed: ${loginStatus.error}`);
          setStep('idle');
          return;
        }
        setSessionReady(true);
      }

      // Step 2: Search
      setStep('searching');
      setStatusText('Searching Facebook Marketplace...');

      const searchResult = await fbApi({
        action: 'search',
        query: searchFilters.query,
        makes: searchFilters.makes || [],
        models: searchFilters.models || [],
        budget_min: searchFilters.budget_min,
        budget_max: searchFilters.budget_max,
        min_year: searchFilters.min_year,
        max_mileage: searchFilters.max_mileage,
        location: searchFilters.location,
        max_pages: 3,
      });

      if (!searchResult.success || !searchResult.listings?.length) {
        setError(searchResult.error || 'No listings found on Facebook Marketplace.');
        setStep('idle');
        return;
      }

      setListings(searchResult.listings);
      setStep('results');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'An unexpected error occurred';
      console.error('[FacebookOutreach] startFlow error:', err);
      setError(msg);
      setStep('idle');
    }
  }, [searchFilters, sessionReady]);

  // ── Generate AI messages for selected listings ──
  const generateMessages = useCallback(async (selected: FBListing[]) => {
    setStep('generating');
    setStatusText('Crafting negotiation messages...');

    try {
      const previews: DMPreview[] = [];

      for (let i = 0; i < selected.length; i++) {
        const listing = selected[i];
        setStatusText(`Crafting message ${i + 1} of ${selected.length}...`);

        try {
          const result = await fbApi({
            action: 'preview-dm',
            listing: {
              ...listing,
              listing_url: listing.listing_url,
              source_url: listing.listing_url,
            },
            strategy: 'balanced',
            send: false,
          });

          previews.push({
            listingId: listing.id,
            message: result.message_sent || 'Failed to generate message',
            targetPrice: result.target_price || null,
            strategyNotes: result.strategy_notes || null,
            approved: false,
            sent: false,
            sending: false,
            error: null,
            conversationUrl: null,
          });
        } catch (err) {
          previews.push({
            listingId: listing.id,
            message: err instanceof Error ? err.message : 'Failed to generate message',
            targetPrice: null,
            strategyNotes: null,
            approved: false,
            sent: false,
            sending: false,
            error: err instanceof Error ? err.message : 'Generation failed',
            conversationUrl: null,
          });
        }
      }

      setDmPreviews(previews);
      setStep('review');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to generate messages';
      console.error('[FacebookOutreach] generateMessages error:', err);
      setError(msg);
      setStep('results');
    }
  }, []);

  // ── Toggle approval on a single message ──
  const toggleApproval = (listingId: string) => {
    setDmPreviews(prev =>
      prev.map(p => p.listingId === listingId ? { ...p, approved: !p.approved } : p)
    );
  };

  // ── Approve all ──
  const approveAll = () => {
    setDmPreviews(prev => prev.map(p => ({ ...p, approved: !p.error })));
  };

  // ── Send approved messages ──
  const sendApproved = useCallback(async () => {
    const toSend = dmPreviews.filter(p => p.approved && !p.sent && !p.error);
    if (toSend.length === 0) return;

    setStep('sending');

    for (let i = 0; i < toSend.length; i++) {
      const preview = toSend[i];
      const listing = listings.find(l => l.id === preview.listingId);
      if (!listing) continue;

      setStatusText(`Sending message ${i + 1} of ${toSend.length}...`);

      // Mark as sending
      setDmPreviews(prev =>
        prev.map(p => p.listingId === preview.listingId ? { ...p, sending: true } : p)
      );

      try {
        const result = await fbApi({
          action: 'send-dm',
          listing: {
            ...listing,
            listing_url: listing.listing_url,
            source_url: listing.listing_url,
          },
          strategy: 'balanced',
          send: true,
        });

        setDmPreviews(prev =>
          prev.map(p =>
            p.listingId === preview.listingId
              ? {
                  ...p,
                  sending: false,
                  sent: result.success,
                  error: result.error || null,
                  conversationUrl: result.conversation_url || null,
                }
              : p
          )
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Send failed';
        setDmPreviews(prev =>
          prev.map(p =>
            p.listingId === preview.listingId
              ? { ...p, sending: false, sent: false, error: msg }
              : p
          )
        );
      }

      // Delay between sends
      if (i < toSend.length - 1) {
        await new Promise(r => setTimeout(r, 5000));
      }
    }

    setStep('done');
  }, [dmPreviews, listings]);

  const approvedCount = dmPreviews.filter(p => p.approved && !p.sent && !p.error).length;
  const sentCount = dmPreviews.filter(p => p.sent).length;

  // ── Render ──
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-[var(--bg-primary)] rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden border border-[var(--border)]">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <div>
            <h2 className="text-lg font-semibold text-[var(--text-primary)]" style={{ fontFamily: 'var(--font-serif)' }}>
              <i>Facebook Marketplace Agent</i>
            </h2>
            <p className="text-xs text-[var(--text-secondary)] mt-0.5">
              Find listings, craft offers, send DMs
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-[var(--bg-secondary)] transition-colors text-[var(--text-secondary)]"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">

          {/* ── Idle: Start button ── */}
          {step === 'idle' && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="w-14 h-14 rounded-full bg-blue-50 flex items-center justify-center mb-4">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#1877F2" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M15.5 8.5H14c-1.1 0-2 .9-2 2v2h3l-.5 3H12v5" />
                  <path d="M9 13h3" />
                </svg>
              </div>
              <h3 className="text-base font-semibold text-[var(--text-primary)] mb-1">
                Search Facebook Marketplace
              </h3>
              <p className="text-sm text-[var(--text-secondary)] max-w-sm mb-4">
                The agent will open a browser, search Facebook Marketplace with your filters,
                and craft personalized negotiation messages for each listing.
              </p>
              {sessionReady && (
                <div className="flex items-center gap-1.5 mb-4">
                  <div className="w-2 h-2 rounded-full bg-green-500" />
                  <span className="text-xs font-medium text-green-700">Session active</span>
                </div>
              )}
              {error && (
                <div className="mb-4 text-sm text-[var(--accent-red)] bg-red-50 px-4 py-2.5 rounded-lg max-w-sm">
                  {error}
                </div>
              )}
              <button
                onClick={startFlow}
                className="text-sm font-medium text-white bg-[#1877F2] px-6 py-2.5 rounded-full hover:bg-[#166FE5] transition-colors"
              >
                Find Listings & Negotiate
              </button>
            </div>
          )}

          {/* ── Loading states ── */}
          {(step === 'logging-in' || step === 'searching' || step === 'generating') && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-10 h-10 border-3 border-[var(--border)] border-t-[#1877F2] rounded-full animate-spin mb-5" />
              <p className="text-sm font-medium text-[var(--text-primary)] mb-1">{statusText}</p>
              <p className="text-xs text-[var(--text-secondary)]">
                {step === 'logging-in' && 'Connecting to Facebook...'}
                {step === 'searching' && 'The browser is actively searching. This may take a moment.'}
                {step === 'generating' && 'AI is analyzing each listing and crafting personalized offers.'}
              </p>
            </div>
          )}

          {/* ── Results: Select listings ── */}
          {step === 'results' && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <p className="text-sm text-[var(--text-secondary)]">
                  Found <span className="font-semibold text-[var(--text-primary)]">{listings.length}</span> listings on Facebook Marketplace
                </p>
              </div>
              <div className="space-y-2 mb-6">
                {listings.slice(0, 20).map(listing => (
                  <ListingRow key={listing.id} listing={listing} />
                ))}
              </div>
              <div className="flex gap-3 justify-end">
                <button
                  onClick={onClose}
                  className="text-sm font-medium text-[var(--text-secondary)] px-5 py-2 rounded-full border border-[var(--border)] hover:bg-[var(--bg-secondary)] transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => generateMessages(listings.slice(0, 10))}
                  className="text-sm font-medium text-white bg-[var(--text-primary)] px-5 py-2 rounded-full hover:opacity-80 transition-opacity"
                >
                  Generate Messages for Top {Math.min(listings.length, 10)}
                </button>
              </div>
            </div>
          )}

          {/* ── Review: Approve messages before sending ── */}
          {(step === 'review' || step === 'sending' || step === 'done') && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <p className="text-sm text-[var(--text-secondary)]">
                  {step === 'done'
                    ? <><span className="font-semibold text-green-700">{sentCount}</span> messages sent</>
                    : <>Review messages before sending &mdash; <span className="font-semibold text-[var(--text-primary)]">{approvedCount}</span> approved</>
                  }
                </p>
                {step === 'review' && (
                  <button
                    onClick={approveAll}
                    className="text-xs font-medium text-[#1877F2] hover:underline"
                  >
                    Approve All
                  </button>
                )}
              </div>

              <div className="space-y-3 mb-6">
                {dmPreviews.map(preview => {
                  const listing = listings.find(l => l.id === preview.listingId);
                  if (!listing) return null;
                  return (
                    <DMPreviewCard
                      key={preview.listingId}
                      listing={listing}
                      preview={preview}
                      onToggle={() => toggleApproval(preview.listingId)}
                      disabled={step !== 'review'}
                    />
                  );
                })}
              </div>

              {step === 'review' && (
                <div className="flex gap-3 justify-end">
                  <button
                    onClick={onClose}
                    className="text-sm font-medium text-[var(--text-secondary)] px-5 py-2 rounded-full border border-[var(--border)] hover:bg-[var(--bg-secondary)] transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={sendApproved}
                    disabled={approvedCount === 0}
                    className="text-sm font-medium text-white bg-[#1877F2] px-5 py-2 rounded-full hover:bg-[#166FE5] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Send {approvedCount} Message{approvedCount !== 1 ? 's' : ''}
                  </button>
                </div>
              )}

              {step === 'sending' && (
                <div className="flex items-center gap-3 justify-center py-2">
                  <div className="w-4 h-4 border-2 border-[var(--border)] border-t-[#1877F2] rounded-full animate-spin" />
                  <span className="text-sm text-[var(--text-secondary)]">{statusText}</span>
                </div>
              )}

              {step === 'done' && (
                <div className="flex flex-col items-center gap-4">
                  {/* Email notification opt-in */}
                  {sentCount > 0 && !emailSent && (
                    <div className="w-full border border-[var(--border)] rounded-xl p-4 bg-[var(--bg-primary)]">
                      <div className="flex items-start gap-3 mb-3">
                        <div className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center flex-shrink-0">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                            <polyline points="22,6 12,13 2,6" />
                          </svg>
                        </div>
                        <div>
                          <p className="text-sm font-semibold text-[var(--text-primary)]">Get emailed when sellers reply</p>
                          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                            Our agent will email you with counter-offer suggestions when sellers respond.
                          </p>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <input
                          type="email"
                          value={notifyEmail}
                          onChange={(e) => setNotifyEmail(e.target.value)}
                          placeholder="your@email.com"
                          className="flex-1 text-sm px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:border-[var(--blue-mid)] transition-colors"
                        />
                        <button
                          onClick={async () => {
                            if (!notifyEmail.includes('@')) return;
                            setEmailSending(true);
                            try {
                              const sentItems = dmPreviews.filter(p => p.sent);
                              await fetch('/api/notifications', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                  action: 'outreach-summary',
                                  email: notifyEmail,
                                  search_query: searchFilters.query || [
                                    ...(searchFilters.makes || []),
                                    ...(searchFilters.models || []),
                                  ].join(' ') || 'Car search',
                                  messages_sent: sentItems.length,
                                  listings: sentItems.map(p => {
                                    const l = listings.find(x => x.id === p.listingId);
                                    return {
                                      title: l?.title || `${l?.year || ''} ${l?.make || ''} ${l?.model || ''}`.trim(),
                                      price: l?.price || 0,
                                      target_price: p.targetPrice,
                                      status: 'sent',
                                    };
                                  }),
                                }),
                              });
                              // Also subscribe for negotiation updates
                              await fetch('/api/notifications', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                  action: 'subscribe',
                                  email: notifyEmail,
                                  alert_type: 'negotiation',
                                }),
                              });
                              setEmailSent(true);
                            } catch {
                              // Non-critical
                            } finally {
                              setEmailSending(false);
                            }
                          }}
                          disabled={emailSending || !notifyEmail.includes('@')}
                          className="text-sm font-medium text-white bg-[var(--text-primary)] px-4 py-2 rounded-lg hover:opacity-80 transition-opacity disabled:opacity-50 whitespace-nowrap"
                        >
                          {emailSending ? 'Sending...' : 'Notify me'}
                        </button>
                      </div>
                    </div>
                  )}
                  {emailSent && (
                    <div className="w-full flex items-center gap-2 text-sm text-green-700 bg-green-50 px-4 py-3 rounded-xl">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12" /></svg>
                      Summary sent to {notifyEmail} — we&apos;ll email you when sellers reply
                    </div>
                  )}
                  {sentCount > 0 && (
                    <button
                      onClick={() => {
                        const sentItems = dmPreviews.filter(p => p.sent);
                        const negs: ActiveNegotiation[] = sentItems.map(p => {
                          const listing = listings.find(l => l.id === p.listingId);
                          return {
                            id: crypto.randomUUID(),
                            listingId: p.listingId,
                            listing: listing || { id: p.listingId },
                            conversationUrl: p.conversationUrl,
                            targetPrice: p.targetPrice,
                            maxPrice: null,
                            messageSent: p.message,
                            sentAt: new Date().toISOString(),
                            status: 'active' as const,
                          };
                        });
                        addNegotiations(negs);
                        onClose();
                      }}
                      className="text-sm font-medium text-white bg-green-600 px-6 py-2.5 rounded-full hover:bg-green-700 transition-colors"
                    >
                      Track & Monitor Replies
                    </button>
                  )}
                  <button
                    onClick={onClose}
                    className="text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                  >
                    Close
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ListingRow({ listing }: { listing: FBListing }) {
  const title = listing.title || `${listing.year || ''} ${listing.make || ''} ${listing.model || ''}`.trim() || 'Unknown Vehicle';

  return (
    <div className="flex items-center gap-3 p-3 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
      {/* Thumbnail */}
      <div className="w-14 h-14 rounded-lg bg-[var(--bg-secondary)] flex-shrink-0 overflow-hidden">
        {listing.image_urls?.[0] ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img src={listing.image_urls[0]} alt="" className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[var(--text-secondary)] opacity-20">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="M21 15l-5-5L5 21" />
            </svg>
          </div>
        )}
      </div>
      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[var(--text-primary)] truncate">{title}</p>
        <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
          {listing.price && <span className="font-semibold text-[var(--text-primary)]">{fmt(listing.price)}</span>}
          {listing.mileage && <span>{fmtMiles(listing.mileage)} mi</span>}
          {listing.location && <span>{listing.location}</span>}
        </div>
      </div>
      {listing.seller_name && (
        <span className="text-xs text-[var(--text-secondary)] flex-shrink-0">{listing.seller_name}</span>
      )}
    </div>
  );
}

function DMPreviewCard({
  listing,
  preview,
  onToggle,
  disabled,
}: {
  listing: FBListing;
  preview: DMPreview;
  onToggle: () => void;
  disabled: boolean;
}) {
  const title = listing.title || `${listing.year || ''} ${listing.make || ''} ${listing.model || ''}`.trim() || 'Unknown';

  return (
    <div className={`rounded-xl border p-4 transition-colors ${
      preview.sent
        ? 'border-green-300 bg-green-50/50'
        : preview.error
        ? 'border-red-200 bg-red-50/30'
        : preview.approved
        ? 'border-[#1877F2]/30 bg-blue-50/30'
        : 'border-[var(--border)] bg-[var(--bg-primary)]'
    }`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <p className="text-sm font-medium text-[var(--text-primary)] truncate">{title}</p>
          {listing.price && (
            <span className="text-xs font-semibold text-[var(--text-secondary)] flex-shrink-0">{fmt(listing.price)}</span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {preview.sent && (
            <span className="text-xs font-semibold text-green-700 bg-green-100 px-2 py-0.5 rounded-full">Sent</span>
          )}
          {preview.sending && (
            <div className="w-4 h-4 border-2 border-[var(--border)] border-t-[#1877F2] rounded-full animate-spin" />
          )}
          {preview.error && !preview.sent && (
            <span className="text-xs text-[var(--accent-red)]">Failed</span>
          )}
          {!preview.sent && !preview.sending && !preview.error && (
            <button
              onClick={onToggle}
              disabled={disabled}
              className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${
                preview.approved
                  ? 'border-[#1877F2] bg-[#1877F2]'
                  : 'border-[var(--border)] hover:border-[#1877F2]/50'
              } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
            >
              {preview.approved && (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Target price */}
      {preview.targetPrice && (
        <p className="text-xs text-[var(--text-secondary)] mb-2">
          Target: <span className="font-semibold">{fmt(preview.targetPrice)}</span>
          {listing.price && preview.targetPrice < listing.price && (
            <span className="text-green-700 ml-1">
              ({Math.round((1 - preview.targetPrice / listing.price) * 100)}% below asking)
            </span>
          )}
        </p>
      )}

      {/* Message preview */}
      <div className="bg-[var(--bg-secondary)] p-3 rounded-lg text-sm text-[var(--text-primary)] leading-relaxed">
        {preview.message}
      </div>
    </div>
  );
}
