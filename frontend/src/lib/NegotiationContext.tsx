'use client';

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
  useCallback,
} from 'react';
import {
  type ActiveNegotiation,
  type SellerReply,
  type NegotiationState,
  INITIAL_STATE,
  saveState,
  loadState,
} from './negotiations';

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

interface NegotiationContextValue extends NegotiationState {
  addNegotiations: (items: ActiveNegotiation[]) => void;
  approveReply: (negotiationId: string) => Promise<void>;
  rejectReply: (negotiationId: string) => void;
  checkNow: () => Promise<void>;
  markRead: () => void;
  togglePanel: () => void;
  clearAll: () => void;
}

const NegotiationContext = createContext<NegotiationContextValue | null>(null);

export function useNegotiations() {
  const ctx = useContext(NegotiationContext);
  if (!ctx) throw new Error('useNegotiations must be used within NegotiationProvider');
  return ctx;
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

async function fbApi(body: Record<string, unknown>) {
  const res = await fetch('/api/facebook', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || data.detail || `Request failed (${res.status})`);
  return data;
}

// ---------------------------------------------------------------------------
// Polling intervals (ms) with backoff
// ---------------------------------------------------------------------------

const POLL_BASE = 2 * 60_000;      // 2 minutes
const POLL_MAX = 5 * 60_000;        // 5 minutes
const POLL_BACKOFF_STEP = 60_000;    // +1 min per empty check

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function NegotiationProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<NegotiationState>(INITIAL_STATE);
  const stateRef = useRef(state);
  const intervalRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollDelayRef = useRef(POLL_BASE);
  const mountedRef = useRef(false);

  // Keep ref in sync
  useEffect(() => { stateRef.current = state; }, [state]);

  // Persist to sessionStorage on changes (skip initial mount with default state)
  useEffect(() => {
    if (mountedRef.current) saveState(state);
  }, [state]);

  // Rehydrate from sessionStorage on mount
  useEffect(() => {
    const saved = loadState();
    setState(saved);
    mountedRef.current = true;
  }, []);

  // ------------------------------------------------------------------
  // Polling
  // ------------------------------------------------------------------

  const runCheck = useCallback(async () => {
    const s = stateRef.current;
    const active = s.negotiations.filter(n => n.status === 'active');
    if (active.length === 0) return;

    try {
      const payload = active.map(n => ({
        listing: n.listing,
        conversation_url: n.conversationUrl,
        target_price: n.targetPrice,
        max_price: n.maxPrice,
        history: [{ role: 'buyer', message: n.messageSent }],
      }));

      const result = await fbApi({
        action: 'check-negotiations',
        active_negotiations: payload,
        strategy: 'balanced',
      });

      const responses: Array<{
        seller_name?: string;
        seller_message?: string;
        message?: string;
        analysis?: Record<string, string>;
        auto_sent?: boolean;
        should_send?: boolean;
      }> = result.responses || [];

      if (responses.length > 0) {
        // Reset backoff on new replies
        pollDelayRef.current = POLL_BASE;

        const newReplies: SellerReply[] = responses.map(r => {
          // Match to negotiation by seller name
          const sellerName = r.seller_name || 'Unknown';
          const matched = active.find(n =>
            n.listing.seller_name?.toLowerCase() === sellerName.toLowerCase()
          );

          return {
            negotiationId: matched?.id || active[0].id,
            sellerName,
            sellerMessage: r.seller_message || '',
            aiCounterOffer: r.message || '',
            analysis: {
              intent: r.analysis?.intent || 'unknown',
              sentiment: r.analysis?.sentiment,
              recommended_action: r.analysis?.recommended_action,
            },
            autoSent: r.auto_sent || false,
            shouldSend: r.should_send || false,
            userApproved: r.auto_sent ? true : null,
            timestamp: new Date().toISOString(),
          };
        });

        setState(prev => {
          // Avoid duplicate replies
          const existingIds = new Set(prev.replies.map(r => r.negotiationId));
          const unique = newReplies.filter(r => !existingIds.has(r.negotiationId));
          const pendingCount = unique.filter(r => r.userApproved === null).length;

          // Update negotiation statuses
          const repliedIds = new Set(unique.map(r => r.negotiationId));
          const updatedNegotiations = prev.negotiations.map(n =>
            repliedIds.has(n.id) ? { ...n, status: 'replied' as const } : n
          );

          return {
            ...prev,
            negotiations: updatedNegotiations,
            replies: [...prev.replies, ...unique],
            unreadCount: prev.unreadCount + pendingCount,
            lastChecked: new Date().toISOString(),
          };
        });
      } else {
        // No replies — increase backoff
        pollDelayRef.current = Math.min(
          pollDelayRef.current + POLL_BACKOFF_STEP,
          POLL_MAX,
        );
        setState(prev => ({ ...prev, lastChecked: new Date().toISOString() }));
      }
    } catch (err) {
      console.error('[NegotiationPoller] check failed:', err);
      setState(prev => ({ ...prev, lastChecked: new Date().toISOString() }));
    }
  }, []);

  const startPolling = useCallback(() => {
    if (intervalRef.current) return;

    const poll = () => {
      runCheck().finally(() => {
        // Schedule next poll with current backoff delay
        const active = stateRef.current.negotiations.filter(n => n.status === 'active');
        if (active.length > 0) {
          intervalRef.current = setTimeout(poll, pollDelayRef.current);
        } else {
          intervalRef.current = null;
          setState(prev => ({ ...prev, isPolling: false }));
        }
      });
    };

    setState(prev => ({ ...prev, isPolling: true }));
    // First check after a short delay
    intervalRef.current = setTimeout(poll, 10_000);
  }, [runCheck]);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearTimeout(intervalRef.current);
      intervalRef.current = null;
    }
    setState(prev => ({ ...prev, isPolling: false }));
  }, []);

  // Start/stop polling based on active negotiations
  useEffect(() => {
    if (!mountedRef.current) return;
    const hasActive = state.negotiations.some(n => n.status === 'active');
    if (hasActive && !intervalRef.current) {
      startPolling();
    } else if (!hasActive && intervalRef.current) {
      stopPolling();
    }
  }, [state.negotiations, startPolling, stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) clearTimeout(intervalRef.current);
    };
  }, []);

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------

  const addNegotiations = useCallback((items: ActiveNegotiation[]) => {
    setState(prev => ({
      ...prev,
      negotiations: [...prev.negotiations, ...items],
    }));
    pollDelayRef.current = POLL_BASE;
  }, []);

  const approveReply = useCallback(async (negotiationId: string) => {
    const s = stateRef.current;
    const reply = s.replies.find(r => r.negotiationId === negotiationId);
    const neg = s.negotiations.find(n => n.id === negotiationId);
    if (!reply || !neg) return;

    try {
      await fbApi({
        action: 'send-reply',
        listing: neg.listing,
        seller_message: reply.sellerMessage,
        conversation_history: [
          { role: 'buyer', message: neg.messageSent },
          { role: 'seller', message: reply.sellerMessage },
        ],
        conversation_url: neg.conversationUrl,
        target_price: neg.targetPrice,
        max_price: neg.maxPrice,
        strategy: 'balanced',
        auto_send: true,
      });

      setState(prev => ({
        ...prev,
        replies: prev.replies.map(r =>
          r.negotiationId === negotiationId
            ? { ...r, userApproved: true, autoSent: true }
            : r
        ),
        unreadCount: Math.max(0, prev.unreadCount - 1),
      }));
    } catch (err) {
      console.error('[NegotiationContext] approve+send failed:', err);
    }
  }, []);

  const rejectReply = useCallback((negotiationId: string) => {
    setState(prev => ({
      ...prev,
      replies: prev.replies.map(r =>
        r.negotiationId === negotiationId ? { ...r, userApproved: false } : r
      ),
      negotiations: prev.negotiations.map(n =>
        n.id === negotiationId ? { ...n, status: 'rejected' as const } : n
      ),
      unreadCount: Math.max(0, prev.unreadCount - 1),
    }));
  }, []);

  const checkNow = useCallback(async () => {
    await runCheck();
  }, [runCheck]);

  const markRead = useCallback(() => {
    setState(prev => ({ ...prev, unreadCount: 0 }));
  }, []);

  const togglePanel = useCallback(() => {
    setState(prev => ({
      ...prev,
      panelOpen: !prev.panelOpen,
      unreadCount: prev.panelOpen ? prev.unreadCount : 0,
    }));
  }, []);

  const clearAll = useCallback(() => {
    stopPolling();
    setState({ ...INITIAL_STATE });
  }, [stopPolling]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  const value: NegotiationContextValue = {
    ...state,
    addNegotiations,
    approveReply,
    rejectReply,
    checkNow,
    markRead,
    togglePanel,
    clearAll,
  };

  return (
    <NegotiationContext.Provider value={value}>
      {children}
    </NegotiationContext.Provider>
  );
}
