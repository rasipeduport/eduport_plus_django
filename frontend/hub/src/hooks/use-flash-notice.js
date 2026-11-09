import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/**
 * A notice a page was handed in its location's state (navigate(to, { state:
 * { notice } })), as `[notice, setNotice]`: shown once. The state is taken off
 * the history entry at once, so Back or a reload never shows it again.
 */
export function useFlashNotice() {
  const location = useLocation();
  const navigate = useNavigate();
  const [notice, setNotice] = useState(location.state?.notice ?? null);
  const handed = location.state?.notice;
  const { pathname, search, hash } = location;

  useEffect(() => {
    if (handed) navigate(`${pathname}${search}${hash}`, { replace: true, state: null });
  }, [handed, pathname, search, hash, navigate]);

  return [notice, setNotice];
}
