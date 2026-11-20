import { useEffect, useState } from 'react';

/**
 * Re-renders the component every `intervalMs` (30 s by default) and returns
 * the moment, so what it works out from the clock -- "starts in N minutes",
 * a step now open or missed, Today and Yesterday -- moves with time while the
 * page stays open. It reads nothing from the API.
 */
export function useClockTick(intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
