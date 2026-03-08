import React from 'react';
import { scoreToColor } from '@/lib/score';

interface ScoreBadgeProps {
  score: number;
  className?: string;
  size?: 'md' | 'lg';
}

export function ScoreBadge({ score, className = '', size = 'md' }: ScoreBadgeProps) {
  const color = scoreToColor(score);

  const sizes = {
    md: 'w-10 h-10 text-xs',
    lg: 'w-16 h-16 text-lg',
  };

  return (
    <div
      className={`rounded-full flex items-center justify-center font-bold text-white font-mono ${sizes[size]} ${className}`}
      style={{ backgroundColor: color, opacity: 0.9 }}
    >
      {score}
    </div>
  );
}
