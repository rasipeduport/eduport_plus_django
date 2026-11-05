import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { bookingCommunicationUrl, communicationError } from '@/lib/communications';

/**
 * One booking's communication (GET /api/communications/bookings/<type>/<id>/),
 * read while `bookingType` and `bookingId` are set and again when `reloadKey`
 * changes: `{ communication, failure, retry, update }` -- `update` takes the
 * communication an action answered with. Nothing of another booking shows
 * while this one loads.
 */
export function useBookingCommunication(bookingType, bookingId, reloadKey) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);

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

  const shown = data?.booking?.id === bookingId && data?.booking?.booking_type === bookingType ? data : null;
  return { communication: shown, failure, retry: () => setRetryKey((key) => key + 1), update: setData };
}
