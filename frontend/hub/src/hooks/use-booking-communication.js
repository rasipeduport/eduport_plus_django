import { useCallback, useEffect, useRef, useState } from 'react';

import api from '@/lib/api';
import { bookingCommunicationUrl, communicationError } from '@/lib/communications';

// A plan still being written (plan_status PENDING: its event waits in the
// backend's outbox, worked through every 15 seconds) is read again every five
// seconds, six times at most for a booking.
const PENDING_RETRY_MS = 5_000;
const PENDING_RETRIES = 6;
// After a change to the booking, read once more about 20 seconds on, by when
// the outbox has applied it.
const CATCH_UP_MS = 20_000;

/**
 * One booking's communication (GET /api/communications/bookings/<type>/<id>/),
 * read while `bookingType` and `bookingId` are set and again when `reloadKey`
 * changes: `{ communication, failure, retry, update, refreshLater }` --
 * `update` takes the communication an action answered with, and
 * `refreshLater` reads it once more about 20 seconds on (once, however often
 * asked meanwhile). While its plan is PENDING it is read again on its own
 * (above); a read that fails stops that until the next one. Nothing of
 * another booking shows while this one loads, and no timer outlives it.
 */
export function useBookingCommunication(bookingType, bookingId, reloadKey) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  const pendingRetries = useRef(0);
  const catchUp = useRef(null);

  useEffect(() => {
    if (!bookingType || !bookingId) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(bookingCommunicationUrl(bookingType, bookingId))
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(communicationError(err, "Could not load this booking's communication."));
      });
    return () => {
      active = false;
    };
  }, [bookingType, bookingId, reloadKey, retryKey]);

  // Another booking starts afresh: its own retries, and no catch-up left over from the last one.
  useEffect(() => {
    pendingRetries.current = 0;
    return () => {
      clearTimeout(catchUp.current);
      catchUp.current = null;
    };
  }, [bookingType, bookingId]);

  const shown = data?.booking?.id === bookingId && data?.booking?.booking_type === bookingType ? data : null;

  // Each answer still PENDING sets the next read; any other status, another booking or leaving stops it.
  const planPending = shown?.plan_status === 'PENDING';
  useEffect(() => {
    if (!planPending || pendingRetries.current >= PENDING_RETRIES) return undefined;
    const timer = setTimeout(() => {
      pendingRetries.current += 1;
      setRetryKey((key) => key + 1);
    }, PENDING_RETRY_MS);
    return () => clearTimeout(timer);
  }, [planPending, shown]);

  const refreshLater = useCallback(() => {
    if (!bookingType || !bookingId) return;
    clearTimeout(catchUp.current);
    catchUp.current = setTimeout(() => {
      catchUp.current = null;
      setRetryKey((key) => key + 1);
    }, CATCH_UP_MS);
  }, [bookingType, bookingId]);

  return { communication: shown, failure, retry: () => setRetryKey((key) => key + 1), update: setData, refreshLater };
}
