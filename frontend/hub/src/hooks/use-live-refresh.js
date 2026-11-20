import { useEffect, useRef } from 'react';

const hidden = () => document.visibilityState === 'hidden';

/**
 * Calls `refresh` when the person comes back to the tab (the window regains
 * focus or the tab becomes visible) and, with `intervalMs`, every `intervalMs`
 * while the tab is visible -- never while it is hidden. A page reads its data
 * itself on mount; this only reads it again. Focus and visibility arrive
 * together on a tab switch, so a return within `minGapMs` of the last refresh
 * (or of mount) reads nothing again; each refresh starts the interval afresh.
 * `enabled: false` stops it all (a page its reader may not see, say). Every
 * timer and listener goes with the page.
 */
export function useLiveRefresh(refresh, { intervalMs = 0, minGapMs = 4000, enabled = true } = {}) {
  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  });

  useEffect(() => {
    if (!enabled) return undefined;
    // The page has just read its data.
    let last = Date.now();
    let timer = null;

    const stop = () => {
      clearTimeout(timer);
      timer = null;
    };
    const run = () => {
      last = Date.now();
      latest.current();
      schedule();
    };
    const tick = () => {
      timer = null;
      if (!hidden()) run();
    };
    const schedule = () => {
      stop();
      if (intervalMs > 0 && !hidden()) timer = setTimeout(tick, intervalMs);
    };
    const back = () => {
      if (hidden()) stop();
      else if (Date.now() - last >= minGapMs) run();
      else if (!timer) schedule();
    };

    schedule();
    window.addEventListener('focus', back);
    document.addEventListener('visibilitychange', back);
    return () => {
      stop();
      window.removeEventListener('focus', back);
      document.removeEventListener('visibilitychange', back);
    };
  }, [enabled, intervalMs, minGapMs]);
}
