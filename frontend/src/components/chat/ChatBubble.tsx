'use client';

import React, { useState } from 'react';
import { ChatPanel } from './ChatPanel';

interface ChatBubbleProps {
  carId: string;
  score: number;
}

export function ChatBubble({ carId, score }: ChatBubbleProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className={`fixed bottom-6 right-6 z-40 w-14 h-14 bg-[var(--blue-dark)] text-white rounded-full shadow-[var(--shadow-card)] flex items-center justify-center text-2xl transition-transform hover:scale-105 ${isOpen ? 'hidden' : 'flex'} md:hidden`}
        aria-label="Open Chat"
      >
        💬
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 bg-white md:hidden flex flex-col animate-in slide-in-from-bottom-full duration-300">
          <div className="flex justify-between items-center p-4 bg-white border-b border-[var(--border)]">
            <h2 className="font-sora font-bold text-[var(--text-primary)] flex items-center gap-2">
               <span className="text-xl">🤖</span> Advisor
            </h2>
            <button 
              onClick={() => setIsOpen(false)}
              className="w-8 h-8 flex items-center justify-center rounded-full bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] font-bold text-xl transition-colors"
              aria-label="Close chat"
            >
              &times;
            </button>
          </div>
          <div className="flex-1 overflow-hidden relative pb-safe">
            <div className="h-full [&>div]:border-none [&>div]:rounded-none [&>div>div:first-child]:hidden [&>div]:shadow-none">
              <ChatPanel carId={carId} score={score} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
