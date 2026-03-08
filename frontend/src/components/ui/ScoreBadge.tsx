import React from 'react';
import { scoreToColor } from '@/lib/score';

interface ScoreBadgeProps {
  score: number;
  className?: string;
  size?: 'md' | 'lg';
}

export function ScoreBadge({ score, className = '', size = 'md' }: ScoreBadgeProps) {
  const color = scoreToColor(score);
  const dim = size === 'lg' ? 64 : 44;
  const stroke = size === 'lg' ? 4 : 3;
  const radius = (dim - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const fontSize = size === 'lg' ? 20 : 14;

  return (
    <div className={`relative ${className}`} style={{ width: dim, height: dim }}>
      {/* Frosted backdrop */}
      <div
        className="absolute inset-0 rounded-full"
        style={{
          background: 'rgba(0,0,0,0.45)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
        }}
      />
      <svg width={dim} height={dim} className="relative rotate-[-90deg]">
        <circle
          cx={dim / 2}
          cy={dim / 2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.15)"
          strokeWidth={stroke}
        />
        <circle
          cx={dim / 2}
          cy={dim / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{
            transition: 'stroke-dashoffset 0.6s ease',
            filter: `drop-shadow(0 0 4px ${color}88)`,
          }}
        />
      </svg>
      <span
        className="absolute inset-0 flex items-center justify-center font-semibold text-white"
        style={{
          fontSize,
          fontFamily: 'var(--font-serif, Georgia, serif)',
          textShadow: '0 1px 3px rgba(0,0,0,0.5)',
        }}
      >
        {score}
      </span>
    </div>
  );
}
