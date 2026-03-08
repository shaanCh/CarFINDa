'use client';

import React, { useState } from 'react';
import { ChatPanel } from './ChatPanel';
import { Car } from '@/lib/types';

interface ChatBubbleProps {
  car: Car;
}

export function ChatBubble({ car }: ChatBubbleProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className={`fixed bottom-6 right-6 z-40 w-12 h-12 bg-[var(--text-primary)] text-[var(--bg-primary)] rounded-full shadow-md flex items-center justify-center text-lg transition-transform hover:scale-105 ${isOpen ? 'hidden' : 'flex'} lg:hidden`}
        aria-label="Open Chat"
      >
        &uarr;
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 bg-[var(--bg-primary)] lg:hidden flex flex-col">
          <div className="flex justify-between items-center px-4 py-3 border-b border-[var(--border)]">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">Advisor</h2>
            <button
              onClick={() => setIsOpen(false)}
              className="w-8 h-8 flex items-center justify-center rounded-full text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-lg transition-colors"
              aria-label="Close chat"
            >
              &times;
            </button>
          </div>
          <div className="flex-1 overflow-hidden">
            <div className="h-full [&>div]:border-none [&>div]:rounded-none [&>div>div:first-child]:hidden [&>div]:shadow-none">
              <ChatPanel car={car} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
