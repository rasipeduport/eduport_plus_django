import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

import { isAllTime, rangeQuery, rangeUpdates, readRange } from '@/lib/dashboard-range';

/**
 * A dashboard's span, kept in its URL (lib/dashboard-range): `[range,
 * pickRange, query]`. `range` is `{ range, from, to }` (`fallback` -- the
 * dashboard's own default -- unless another was picked);
 * `pickRange({ range, from, to })` keeps a picked preset or Custom range,
 * replacing the URL's entry rather than adding one; `query` is what to ask
 * the API, the same object while the dates are the same, so a dashboard reads
 * again only when they change -- never for picking the span already shown, or
 * a Custom range of a preset's own dates.
 */
export function useDashboardRange(fallback) {
  const [searchParams, setSearchParams] = useSearchParams();
  const range = readRange(searchParams, fallback);
  const { from, to } = range;
  const allTime = isAllTime(range);
  const query = useMemo(() => rangeQuery(allTime, from, to), [allTime, from, to]);

  const pickRange = (picked) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(rangeUpdates(picked, fallback))) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    if (params.toString() !== searchParams.toString()) setSearchParams(params, { replace: true });
  };

  return [range, pickRange, query];
}
