import React from 'react';
import { scoreToColor } from '@/lib/score';

interface ScoreBadgeProps {
  score: number;
  className?: string;
  size?: 'md' | 'lg';
}

export function ScoreBadge({ score, className = '', size = 'md' }: ScoreBadgeProps) {
  const bgColor = scoreToColor(score);
  
  const sizeClasses = {
    md: 'w-[52px] h-[52px] text-base',
    lg: 'w-[80px] h-[80px] text-2xl',
  };

  return (
    <div
      className={`rounded-full flex items-center justify-center font-bold text-white shadow-card font-mono ${sizeClasses[size]} ${className}`}
      style={{ backgroundColor: bgColor }}
    >
      {score}/100
    </div>
  );
}
