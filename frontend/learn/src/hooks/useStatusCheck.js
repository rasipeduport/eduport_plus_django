import { useEffect, useRef, useState } from 'react';
import { useStudent } from '../components/student/student-context';

/**
 * A gateway page's status check (the waiting room, access ended): the sign-in
 * resolve again (AuthProvider's recheck), which takes the student wherever
 * they now belong -- the dashboard, choosing a child, the waiting room or
 * access ended. `checking` while it runs (one check at a time: a click while
 * one is under way does nothing); once done, `outcome` says what it found
 * when it left them on this page -- 'waiting', 'ended', 'unreachable' (the
 * API did not answer). A page that has gone sets nothing.
 */
export function useStatusCheck() {
  const { recheck } = useStudent();
  const [checking, setChecking] = useState(false);
  const [outcome, setOutcome] = useState(null);
  const running = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const check = async () => {
    if (running.current) return;
    running.current = true;
    setChecking(true);
    setOutcome(null);
    try {
      const found = await recheck();
      if (mounted.current) setOutcome(found);
    } catch {
      if (mounted.current) setOutcome('unreachable');
    } finally {
      running.current = false;
      if (mounted.current) setChecking(false);
    }
  };

  return { checking, outcome, check };
}
