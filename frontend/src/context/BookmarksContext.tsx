'use client';

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { Car } from '@/lib/types';

const STORAGE_KEY = 'carfinda-bookmarks';

function loadBookmarks(): Car[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveBookmarks(cars: Car[]) {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cars));
  } catch {
    // quota exceeded or disabled
  }
}

interface BookmarksContextValue {
  bookmarks: Car[];
  isBookmarked: (carId: string) => boolean;
  addBookmark: (car: Car) => void;
  removeBookmark: (carId: string) => void;
  toggleBookmark: (car: Car) => void;
  mounted: boolean;
}

const BookmarksContext = createContext<BookmarksContextValue | null>(null);

export function BookmarksProvider({ children }: { children: React.ReactNode }) {
  const [bookmarks, setBookmarks] = useState<Car[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setBookmarks(loadBookmarks());
    setMounted(true);
  }, []);

  const isBookmarked = useCallback(
    (carId: string) => bookmarks.some((c) => c.id === carId),
    [bookmarks]
  );

  const addBookmark = useCallback((car: Car) => {
    setBookmarks((prev) => {
      if (prev.some((c) => c.id === car.id)) return prev;
      const next = [...prev, car];
      saveBookmarks(next);
      return next;
    });
  }, []);

  const removeBookmark = useCallback((carId: string) => {
    setBookmarks((prev) => {
      const next = prev.filter((c) => c.id !== carId);
      saveBookmarks(next);
      return next;
    });
  }, []);

  const toggleBookmark = useCallback(
    (car: Car) => {
      setBookmarks((prev) => {
        const existing = prev.find((c) => c.id === car.id);
        const next = existing ? prev.filter((c) => c.id !== car.id) : [...prev, car];
        saveBookmarks(next);
        return next;
      });
    },
    []
  );

  const value: BookmarksContextValue = {
    bookmarks,
    isBookmarked,
    addBookmark,
    removeBookmark,
    toggleBookmark,
    mounted,
  };

  return (
    <BookmarksContext.Provider value={value}>
      {children}
    </BookmarksContext.Provider>
  );
}

export function useBookmarks() {
  const ctx = useContext(BookmarksContext);
  if (!ctx) {
    throw new Error('useBookmarks must be used within BookmarksProvider');
  }
  return ctx;
}
