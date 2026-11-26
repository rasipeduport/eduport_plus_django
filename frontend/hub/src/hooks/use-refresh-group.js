import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

/**
 * One Refresh for a page whose parts each read their own data -- a student's
 * Finance tab: its overview, payment history, additional hours and any
 * allocation open in them. The page hands `group` to its parts; each joins it
 * while mounted (useRefreshPart), reads again whenever `group.key` changes and
 * calls `group.settled(name, key)` once that read is done, answered or failed.
 *
 * `refresh()` starts a round with a new key: `pending` until every part
 * mounted at that moment has settled it, or has gone. A newer round replaces
 * an older one, whose late answers settle nothing. The reads on mount are no
 * round (key 0): each part shows its own skeleton for those.
 */
export function useRefreshGroup() {
  const members = useRef(new Set());
  const [round, setRound] = useState({ key: 0, waiting: [] });

  // `key` undefined: the part has gone, whatever round it was in.
  const settled = useCallback(
    (name, key) =>
      setRound((current) =>
        (key === undefined || key === current.key) && current.waiting.includes(name)
          ? {
              ...current,
              waiting: current.waiting.filter((other) => other !== name),
            }
          : current
      ),
    []
  );
  const join = useCallback(
    (name) => {
      members.current.add(name);
      return () => {
        members.current.delete(name);
        settled(name);
      };
    },
    [settled]
  );
  const refresh = useCallback(
    () =>
      setRound((current) => ({
        key: current.key + 1,
        waiting: [...members.current],
      })),
    []
  );

  return useMemo(
    () => ({
      key: round.key,
      pending: round.waiting.length > 0,
      refresh,
      settled,
      join,
    }),
    [round, refresh, settled, join]
  );
}

/** Takes part in `group` (when there is one) as `name` while mounted. */
export function useRefreshPart(group, name) {
  const join = group?.join;
  useEffect(() => (join ? join(name) : undefined), [join, name]);
}
