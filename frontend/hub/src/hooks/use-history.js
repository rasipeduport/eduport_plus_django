import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { bookingError } from '@/lib/bookings';

/**
 * A History response (GET …/history/ of the backend's bookings.timeline) as
 * `{ data, failure, retry }`, read again whenever `reloadKey` changes; no
 * `url`, nothing is read.
 */
export function useHistory(url, reloadKey) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  useEffect(() => {
    if (!url) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(url)
      .then((response) => {
        if (active) setData({ url, ...response.data });
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load the history.'));
      });
    return () => {
      active = false;
    };
  }, [url, reloadKey, retryKey]);
  return { data: data && data.url === url ? data : null, failure, retry: () => setRetryKey((key) => key + 1) };
}
