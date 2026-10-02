import { useEffect, useRef } from 'react';

/**
 * Re-run `callback` when the tab regains focus (debounced), so a score a
 * mentor just entered in the Hub shows up when the student returns here.
 * Port of the Learn app's RefreshOnFocus (no realtime socket).
 */
export function useRefreshOnFocus(callback, debounceMs = 4000) {
  const last = useRef(0);
  const cb = useRef(callback);
  cb.current = callback;

  useEffect(() => {
    const handler = () => {
      if (document.visibilityState === 'hidden') return;
      const now = Date.now();
      if (now - last.current < debounceMs) return;
      last.current = now;
      cb.current?.();
    };
    window.addEventListener('focus', handler);
    document.addEventListener('visibilitychange', handler);
    return () => {
      window.removeEventListener('focus', handler);
      document.removeEventListener('visibilitychange', handler);
    };
  }, [debounceMs]);
}
