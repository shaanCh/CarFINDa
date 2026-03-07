'use client';

import React, { useState, useRef, useEffect } from 'react';
import { ChatMessage } from '@/lib/types';

interface ChatPanelProps {
  carId: string;
  score: number;
}

export function ChatPanel({ carId, score }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content: `This car scored **${score}/100** for your needs. Here's why: It strongly fits your budget and primary use case.\n\nAsk me anything about this listing, negotiation tips, or red flags to watch for.`
    }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage: ChatMessage = { role: 'user', content: input };
    const newMessagesHistory = [...messages, userMessage];
    setMessages(newMessagesHistory);
    setInput('');
    setIsLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          listingId: carId,
          userMessage: userMessage.content,
          conversationHistory: newMessagesHistory
        })
      });

      if (!response.ok) throw new Error('Network response was not ok');
      if (!response.body) throw new Error('No readable stream');

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      
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
              
              setMessages(prev => {
                const newArr = [...prev];
                const last = newArr[newArr.length - 1];
                if (last.role === 'assistant') {
                  let text = data;
                  try {
                    const parsed = JSON.parse(data);
                    if (parsed.text) text = parsed.text;
                  } catch (e) {
                    // ignore format errors for raw strings
                  }
                  last.content += text.replace(/\\n/g, '\n');
                }
                return newArr;
              });
            }
          }
        }
      }
    } catch (error) {
      console.error('Error in chat:', error);
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white border border-[var(--border)] rounded-[var(--radius-card)] shadow-sm overflow-hidden sticky top-20">
      <div className="p-4 border-b border-[var(--border)] bg-[var(--bg-secondary)] flex items-center gap-2">
        <span className="text-xl">🤖</span>
        <h2 className="font-sora font-semibold text-[var(--text-primary)]">CarFINDa Advisor</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
        {messages.map((msg, i) => (
          <div 
            key={i} 
            className={`flex w-full ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div 
              className={`max-w-[85%] px-4 py-3 text-sm flex flex-col gap-2 ${
                msg.role === 'user' 
                  ? 'bg-[var(--blue-dark)] text-white rounded-[1.5rem] rounded-br-[0.25rem]' 
                  : 'bg-[var(--bg-secondary)] text-[var(--text-primary)] border border-[var(--border)] rounded-[1.5rem] rounded-bl-[0.25rem]'
              }`}
            >
              <div 
                dangerouslySetInnerHTML={{ 
                  __html: msg.content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br/>') 
                }} 
              />
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-[var(--bg-secondary)] border border-[var(--border)] text-[var(--text-primary)] rounded-[1.5rem] rounded-bl-[0.25rem] px-4 py-3 text-sm flex gap-1">
              <span className="animate-bounce font-bold">.</span>
              <span className="animate-bounce font-bold" style={{ animationDelay: '0.2s' }}>.</span>
              <span className="animate-bounce font-bold" style={{ animationDelay: '0.4s' }}>.</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-4 border-t border-[var(--border)] bg-white">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this car..."
            className="flex-1 border border-[var(--border)] rounded-full px-4 py-2 text-sm focus:outline-none focus:border-[var(--blue-mid)] focus:ring-1 focus:ring-[var(--blue-light)] placeholder:text-[var(--text-secondary)]"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="bg-[var(--blue-dark)] text-white w-10 h-10 rounded-full flex items-center justify-center disabled:opacity-50 transition-opacity hover:opacity-90"
            aria-label="Send message"
          >
            &uarr;
          </button>
        </form>
      </div>
    </div>
  );
}
