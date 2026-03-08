import React from 'react';
import { scoreToColor } from '@/lib/score';

interface RadialScoreProps {
  value: number; // 0-100
  label: string;
  size?: number;
}

export function RadialScore({ value, label, size = 48 }: RadialScoreProps) {
  const stroke = 3.5;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;
  const color = scoreToColor(value);
  const center = size / 2;

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="rotate-[-90deg]">
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke="var(--border)"
            strokeWidth={stroke}
          />
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            style={{ transition: 'stroke-dashoffset 0.6s ease' }}
          />
        </svg>
        <span
          className="absolute inset-0 flex items-center justify-center font-bold font-mono"
          style={{ fontSize: size * 0.28, color }}
        >
          {value}
        </span>
      </div>
      <span className="text-[10px] text-[var(--text-secondary)] font-medium leading-none">
        {label}
      </span>
    </div>
  );
}
