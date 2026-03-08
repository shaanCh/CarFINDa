'use client';

import React, { useState } from 'react';
import { useNegotiations } from '@/lib/NegotiationContext';

const fmt = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

const timeAgo = (iso: string) => {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
};

export function NegotiationPanel() {
  const {
    negotiations,
    replies,
    isPolling,
    lastChecked,
    panelOpen,
    togglePanel,
    approveReply,
    rejectReply,
    checkNow,
    clearAll,
  } = useNegotiations();

  const [checking, setChecking] = useState(false);
  const [sendingId, setSendingId] = useState<string | null>(null);

  if (!panelOpen) return null;

  const needsReview = replies.filter(r => r.userApproved === null);
  const activeNegs = negotiations.filter(n => n.status === 'active');
  const completedNegs = negotiations.filter(n =>
    n.status === 'replied' || n.status === 'accepted' || n.status === 'rejected'
  );

  const handleCheck = async () => {
    setChecking(true);
    try { await checkNow(); } finally { setChecking(false); }
  };

  const handleApprove = async (negId: string) => {
    setSendingId(negId);
    try { await approveReply(negId); } finally { setSendingId(null); }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={togglePanel} />

      {/* Panel */}
      <div className="relative w-full max-w-md bg-[var(--bg-primary)] border-l border-[var(--border)] shadow-2xl flex flex-col h-full">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]" style={{ fontFamily: 'var(--font-serif)' }}>
              <i>Negotiations</i>
            </h2>
            <p className="text-xs text-[var(--text-secondary)] mt-0.5">
              {negotiations.length} conversation{negotiations.length !== 1 ? 's' : ''}
              {isPolling && (
                <span className="ml-2 text-green-600">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500 mr-1 animate-pulse" />
                  Monitoring
                </span>
              )}
            </p>
          </div>
          <button
            onClick={togglePanel}
            className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-[var(--bg-secondary)] transition-colors text-[var(--text-secondary)]"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-6">

          {/* Needs Review */}
          {needsReview.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--accent-orange)] mb-3">
                Needs Review ({needsReview.length})
              </h3>
              <div className="space-y-3">
                {needsReview.map(reply => {
                  const neg = negotiations.find(n => n.id === reply.negotiationId);
                  if (!neg) return null;
                  const title = neg.listing.title ||
                    `${neg.listing.year || ''} ${neg.listing.make || ''} ${neg.listing.model || ''}`.trim() || 'Vehicle';
                  const isSending = sendingId === reply.negotiationId;

                  return (
                    <div
                      key={reply.negotiationId}
                      className="rounded-xl border border-[var(--accent-orange)]/30 bg-orange-50/30 p-4"
                    >
                      {/* Listing info */}
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-sm font-medium text-[var(--text-primary)] truncate">{title}</p>
                        {neg.listing.price && (
                          <span className="text-xs font-semibold text-[var(--text-secondary)] ml-2 flex-shrink-0">
                            {fmt(neg.listing.price)}
                          </span>
                        )}
                      </div>

                      {/* Intent badge */}
                      <div className="flex items-center gap-2 mb-2">
                        <IntentBadge intent={reply.analysis.intent} />
                        <span className="text-[11px] text-[var(--text-secondary)]">{reply.sellerName}</span>
                        <span className="text-[11px] text-[var(--text-secondary)]">{timeAgo(reply.timestamp)}</span>
                      </div>

                      {/* Seller message */}
                      <div className="bg-[var(--bg-secondary)] rounded-lg p-3 mb-2">
                        <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">Seller</p>
                        <p className="text-sm text-[var(--text-primary)] leading-relaxed">{reply.sellerMessage}</p>
                      </div>

                      {/* AI counter-offer */}
                      <div className="border border-[var(--border)] rounded-lg p-3 mb-3">
                        <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">AI Counter-Offer</p>
                        <p className="text-sm text-[var(--text-primary)] leading-relaxed">{reply.aiCounterOffer}</p>
                      </div>

                      {/* Actions */}
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => rejectReply(reply.negotiationId)}
                          disabled={isSending}
                          className="text-xs font-medium text-[var(--text-secondary)] px-4 py-1.5 rounded-full border border-[var(--border)] hover:bg-[var(--bg-secondary)] transition-colors disabled:opacity-40"
                        >
                          Reject
                        </button>
                        <button
                          onClick={() => handleApprove(reply.negotiationId)}
                          disabled={isSending}
                          className="text-xs font-medium text-white bg-green-600 px-4 py-1.5 rounded-full hover:bg-green-700 transition-colors disabled:opacity-60 flex items-center gap-1.5"
                        >
                          {isSending ? (
                            <>
                              <span className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                              Sending...
                            </>
                          ) : (
                            'Approve & Send'
                          )}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Active — waiting for reply */}
          {activeNegs.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">
                Waiting for Reply ({activeNegs.length})
              </h3>
              <div className="space-y-2">
                {activeNegs.map(neg => {
                  const title = neg.listing.title ||
                    `${neg.listing.year || ''} ${neg.listing.make || ''} ${neg.listing.model || ''}`.trim() || 'Vehicle';

                  return (
                    <div key={neg.id} className="rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3">
                      <div className="flex items-center justify-between mb-1">
                        <p className="text-sm font-medium text-[var(--text-primary)] truncate">{title}</p>
                        {neg.listing.price && (
                          <span className="text-xs text-[var(--text-secondary)] ml-2 flex-shrink-0">{fmt(neg.listing.price)}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-[var(--text-secondary)]">
                        {neg.targetPrice && <span>Target: {fmt(neg.targetPrice)}</span>}
                        <span>Sent {timeAgo(neg.sentAt)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Completed */}
          {completedNegs.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">
                Completed ({completedNegs.length})
              </h3>
              <div className="space-y-2">
                {completedNegs.map(neg => {
                  const title = neg.listing.title ||
                    `${neg.listing.year || ''} ${neg.listing.make || ''} ${neg.listing.model || ''}`.trim() || 'Vehicle';
                  const reply = replies.find(r => r.negotiationId === neg.id);

                  return (
                    <div key={neg.id} className="rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3 opacity-70">
                      <div className="flex items-center justify-between mb-1">
                        <p className="text-sm font-medium text-[var(--text-primary)] truncate">{title}</p>
                        <StatusBadge status={neg.status} approved={reply?.userApproved} />
                      </div>
                      {reply && (
                        <p className="text-xs text-[var(--text-secondary)] truncate mt-1">
                          &ldquo;{reply.sellerMessage}&rdquo;
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Empty state */}
          {negotiations.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-12 h-12 rounded-full bg-[var(--bg-secondary)] flex items-center justify-center mb-3">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--text-secondary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.5">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </div>
              <p className="text-sm text-[var(--text-secondary)]">No active negotiations</p>
              <p className="text-xs text-[var(--text-secondary)] mt-1 max-w-xs">
                Send DMs via the Facebook Marketplace agent and negotiations will appear here.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-[var(--border)] px-5 py-3 flex items-center justify-between">
          <div className="text-[11px] text-[var(--text-secondary)]">
            {lastChecked ? `Last checked ${timeAgo(lastChecked)}` : 'Not checked yet'}
          </div>
          <div className="flex items-center gap-2">
            {negotiations.length > 0 && (
              <button
                onClick={clearAll}
                className="text-[11px] text-[var(--text-secondary)] hover:text-[var(--accent-red)] transition-colors"
              >
                Clear all
              </button>
            )}
            <button
              onClick={handleCheck}
              disabled={checking || activeNegs.length === 0}
              className="text-xs font-medium text-[var(--text-primary)] border border-[var(--border)] px-3 py-1.5 rounded-full hover:bg-[var(--bg-secondary)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              {checking ? (
                <>
                  <span className="w-3 h-3 border-2 border-[var(--border)] border-t-[var(--text-primary)] rounded-full animate-spin" />
                  Checking...
                </>
              ) : (
                'Check Now'
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function IntentBadge({ intent }: { intent: string }) {
  const config: Record<string, { label: string; cls: string }> = {
    accept: { label: 'Accepted', cls: 'text-green-800 bg-green-100' },
    counter: { label: 'Counter-Offer', cls: 'text-amber-800 bg-amber-100' },
    reject: { label: 'Rejected', cls: 'text-red-800 bg-red-100' },
    question: { label: 'Question', cls: 'text-blue-800 bg-blue-100' },
  };
  const c = config[intent] || { label: intent, cls: 'text-gray-800 bg-gray-100' };

  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${c.cls}`}>
      {c.label}
    </span>
  );
}

function StatusBadge({ status, approved }: { status: string; approved?: boolean | null }) {
  if (status === 'rejected' || approved === false) {
    return <span className="text-[10px] font-semibold text-red-700 bg-red-100 px-2 py-0.5 rounded-full">Rejected</span>;
  }
  if (approved === true) {
    return <span className="text-[10px] font-semibold text-green-700 bg-green-100 px-2 py-0.5 rounded-full">Replied</span>;
  }
  return <span className="text-[10px] font-semibold text-gray-600 bg-gray-100 px-2 py-0.5 rounded-full">{status}</span>;
}
