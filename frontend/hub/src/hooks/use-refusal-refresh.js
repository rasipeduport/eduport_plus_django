import { useRef } from 'react';

// The refusals that say what the page shows is out of date: gone (404), or changed meanwhile (409).
const STALE = [404, 409];

/**
 * A dialog whose action the API refused because the page behind it is out of
 * date (404, 409): the refusal stays in the dialog to be read, and once the
 * dialog closes `onRefused` lets the page read what it shows again -- as
 * Start and the Demo invite do. Call `refused(failure)` after a refusal (a
 * bookingError-shaped `{ status }`) and `accepted()` after a success; pass
 * `onOpenChange` to the dialog in place of its own.
 */
export function useRefusalRefresh(onOpenChange, onRefused) {
  const stale = useRef(false);
  return {
    refused(failure) {
      if (STALE.includes(failure?.status)) stale.current = true;
    },
    accepted() {
      stale.current = false;
    },
    onOpenChange(next) {
      if (!next && stale.current) {
        stale.current = false;
        onRefused?.();
      }
      onOpenChange?.(next);
    },
  };
}
