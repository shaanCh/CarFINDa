'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Car, ChatMessage } from '@/lib/types';

/** Render inline markdown: **bold** and *italic* */
function InlineMarkdown({ text }: { text: string }) {
  const parts = text.split(/(\*\*.*?\*\*|\*.*?\*)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return <strong key={i}>{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
          return <em key={i}>{part.slice(1, -1)}</em>;
        }
        return <React.Fragment key={i}>{part}</React.Fragment>;
      })}
    </>
  );
}

/** Render chat text safely — headings, bold, lists, newlines */
function ChatContent({ text }: { text: string }) {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let listItems: string[] = [];

  const flushList = () => {
    if (listItems.length > 0) {
      elements.push(
        <ul key={`ul-${elements.length}`} className="list-disc list-inside my-1 space-y-0.5">
          {listItems.map((item, i) => (
            <li key={i}><InlineMarkdown text={item} /></li>
          ))}
        </ul>
      );
      listItems = [];
    }
  };

  lines.forEach((line, i) => {
    const trimmed = line.trimStart();

    // Headings
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.*)/);
    if (headingMatch) {
      flushList();
      const level = headingMatch[1].length;
      const content = headingMatch[2];
      const cls = level <= 2 ? 'text-sm font-bold mt-3 mb-1' : 'text-sm font-semibold mt-2 mb-0.5';
      elements.push(
        <p key={i} className={cls}><InlineMarkdown text={content} /></p>
      );
      return;
    }

    // List items (- or *)
    const listMatch = trimmed.match(/^[-*]\s+(.*)/);
    if (listMatch) {
      listItems.push(listMatch[1]);
      return;
    }

    // Regular line
    flushList();
    if (trimmed === '') {
      elements.push(<br key={i} />);
    } else {
      elements.push(
        <span key={i} className="block"><InlineMarkdown text={line} /></span>
      );
    }
  });

  flushList();

  return <div>{elements}</div>;
}

interface ChatPanelProps {
  car: Car;
}

export function ChatPanel({ car }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content: `This **${car.year} ${car.make} ${car.model}** scored **${car.score}/100**. Ask me anything — red flags, negotiation tips, comparisons, or what to ask the seller.`
    }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage: ChatMessage = { role: 'user', content: input };
    const newHistory = [...messages, userMessage];
    setMessages(newHistory);
    setInput('');
    setIsLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          listingId: car.id,
          userMessage: userMessage.content,
          sessionId,
          context: {
            listings: [{
              id: car.id,
              year: car.year,
              make: car.make,
              model: car.model,
              trim: car.trim,
              price: car.price,
              mileage: car.mileage,
              location: car.location,
              source_name: car.source_name,
              source_url: car.source_url,
              vin: car.vin,
              transmission: car.transmission,
              sellerType: car.sellerType,
            }],
            scores: [{
              listing_id: car.id,
              composite: car.score,
              breakdown: car.scoreBreakdown,
            }],
            strengths: car.strengths,
            concerns: car.concerns,
            headline: car.headline,
            explanation: car.explanation,
            recallCount: car.recallCount,
          },
        })
      });

      if (!response.ok) throw new Error('Network response was not ok');
      if (!response.body) throw new Error('No readable stream');

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');

      let assistantContent = '';
      setMessages(prev => [...prev, { role: 'assistant', content: '' }]);

      let done = false;
      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6);
              if (data === '[DONE]') break;

              try {
                const parsed = JSON.parse(data);
                if (parsed.sessionId || parsed.session_id) {
                  setSessionId(parsed.sessionId || parsed.session_id);
                  continue;
                }
                if (parsed.text) {
                  assistantContent += parsed.text.replace(/\\n/g, '\n');
                }
              } catch {
                assistantContent += data.replace(/\\n/g, '\n');
              }

              setMessages(prev => {
                const updated = [...prev];
                updated[updated.length - 1] = { role: 'assistant', content: assistantContent };
                return updated;
              });
            }
          }
        }
      }
    } catch (error) {
      console.error('Error in chat:', error);
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, something went wrong. Try again.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full border border-[var(--border)] rounded-[var(--radius-card)] overflow-hidden bg-[var(--bg-primary)]">
      <div className="px-4 py-3 border-b border-[var(--border)]">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">Advisor</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
        {messages.map((msg, i) => (
          <div key={i} className={`flex w-full ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] px-3.5 py-2.5 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-[var(--text-primary)] text-[var(--bg-primary)] rounded-2xl rounded-br-sm'
                  : 'bg-[var(--bg-secondary)] text-[var(--text-primary)] rounded-2xl rounded-bl-sm'
              }`}
            >
              <ChatContent text={msg.content} />
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-[var(--bg-secondary)] text-[var(--text-secondary)] rounded-2xl rounded-bl-sm px-3.5 py-2.5 text-sm flex gap-0.5">
              <span className="animate-bounce">.</span>
              <span className="animate-bounce" style={{ animationDelay: '0.15s' }}>.</span>
              <span className="animate-bounce" style={{ animationDelay: '0.3s' }}>.</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-3 border-t border-[var(--border)]">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this car..."
            className="flex-1 border border-[var(--border)] rounded-full px-4 py-2 text-sm bg-[var(--bg-primary)] focus:outline-none focus:border-[var(--text-secondary)] placeholder:text-[var(--text-secondary)]"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="bg-[var(--text-primary)] text-[var(--bg-primary)] w-9 h-9 rounded-full flex items-center justify-center disabled:opacity-30 transition-opacity text-sm"
            aria-label="Send"
          >
            &uarr;
          </button>
        </form>
      </div>
    </div>
  );
}
