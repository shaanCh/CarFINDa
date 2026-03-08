'use client';

import React, { useState, useRef, useEffect, useCallback } from 'react';

interface SliderInputProps {
  label: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (val: number) => void;
  formatValue: (val: number) => string;
}

export function SliderInput({ label, min, max, step = 1, value, onChange, formatValue }: SliderInputProps) {
  const [isDragging, setIsDragging] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);

  // Calculate percentage for styling
  const percentage = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));

  const updateValueFromPointer = useCallback((clientX: number) => {
    if (!trackRef.current) return;
    
    const rect = trackRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(clientX - rect.left, rect.width));
    const percent = x / rect.width;
    
    let rawValue = min + percent * (max - min);
    // Snap to step
    rawValue = Math.round(rawValue / step) * step;
    // Bound
    rawValue = Math.max(min, Math.min(max, rawValue));
    
    onChange(rawValue);
  }, [min, max, step, onChange]);

  const handlePointerDown = (e: React.PointerEvent) => {
    e.preventDefault(); // prevent text selection
    setIsDragging(true);
    if (trackRef.current) {
        trackRef.current.setPointerCapture(e.pointerId);
    }
    updateValueFromPointer(e.clientX);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!isDragging) return;
    updateValueFromPointer(e.clientX);
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    setIsDragging(false);
    if (trackRef.current) {
        trackRef.current.releasePointerCapture(e.pointerId);
    }
  };

  // Accessible keyboard controls via native hidden input
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(Number(e.target.value));
  };

  return (
    <div className="w-full py-4 select-none relative pb-6 border-b border-dashed border-[var(--border)] last:border-0">
      <div className="flex justify-between items-center mb-8">
        <label className="text-sm font-bold text-[var(--text-primary)]">{label}</label>
        <div className="text-xs font-bold text-[var(--text-secondary)] tracking-wide bg-[var(--bg-secondary)] px-2 py-1 rounded-md">
           {formatValue(value)}
        </div>
      </div>

      <div 
        className="relative h-8 flex items-center group cursor-pointer"
        ref={trackRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
      >
        {/* Track Line (Unfilled) */}
        <div className="absolute w-full h-[6px] bg-[var(--border)] rounded-full z-0 overflow-hidden">
             {/* Track Line (Filled) */}
            <div 
              className="absolute top-0 left-0 h-full bg-[var(--blue-mid)] transition-all duration-75"
              style={{ width: `${percentage}%` }}
            />
        </div>

        {/* Floating Bubble */}
        <div 
          className={`
            absolute top-[-44px] -ml-[35px] w-[70px] text-center
            bg-[var(--text-primary)] text-white text-[11px] font-bold py-1.5 px-2 rounded-[var(--radius-bubble)] shadow-md
            transition-all duration-200 pointer-events-none z-20 origin-bottom
            ${isDragging ? 'scale-110 -translate-y-2 opacity-100' : 'scale-100 opacity-0 group-hover:opacity-100'}
          `}
          style={{ left: `${percentage}%` }}
        >
          {formatValue(value)}
          {/* Arrow pointing down */}
          <div className="absolute left-[calc(50%-4px)] -bottom-1 w-0 h-0 border-l-[4px] border-l-transparent border-t-[4px] border-t-[var(--text-primary)] border-r-[4px] border-r-transparent" />
        </div>

        {/* Draggable Thumb */}
        <div 
          className={`
            absolute h-6 w-6 ml-[-12px] bg-white border-2 border-[var(--blue-mid)] rounded-full z-10
            shadow-[0_2px_8px_rgba(74,159,224,0.3)] transition-transform duration-100 ease-out
            ${isDragging ? 'scale-125 shadow-[0_4px_12px_rgba(74,159,224,0.4)]' : 'hover:scale-110'}
          `}
          style={{ left: `${percentage}%` }}
        />

        {/* Accessible screen-reader / keyboard input layer */}
        <input 
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={handleInputChange}
          className="absolute inset-0 w-full opacity-0 cursor-pointer z-30"
          aria-label={label}
        />
      </div>
      
      <div className="flex justify-between text-[10px] text-[var(--text-secondary)] font-medium mt-1 px-1">
         <span>{formatValue(min)}</span>
         <span>{formatValue(max)}</span>
      </div>
    </div>
  );
}
