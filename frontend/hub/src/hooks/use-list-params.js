import { useSearchParams } from 'react-router-dom';

/**
 * A list's search, filters and page, kept in the URL so a reload, a shared
 * link or Back shows the same list. `update({ q, status, page, ... })` sets
 * each value, or removes it when null or empty; any change but the page
 * itself goes back to the first page. `clear()` drops every parameter.
 * The page reads and validates the values itself (from `searchParams`).
 */
export function useListParams() {
  const [searchParams, setSearchParams] = useSearchParams();

  const update = (updates) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === undefined || value === '') params.delete(key);
      else params.set(key, String(value));
    }
    if (!('page' in updates)) params.delete('page');
    setSearchParams(params);
  };

  const clear = () => setSearchParams(new URLSearchParams());

  return { searchParams, update, clear };
}
