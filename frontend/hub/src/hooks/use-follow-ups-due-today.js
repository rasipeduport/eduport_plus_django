import { useEffect, useSyncExternalStore } from 'react';

import api from '@/lib/api';
import { BDE_FOLLOW_UPS_URL } from '@/lib/follow-ups';
import { useLiveRefresh } from '@/hooks/use-live-refresh';

// How many of the signed-in BDE's follow-ups are due today, for the sidebar's
// Follow-ups badge: `summary.today` of GET /api/bde/follow-ups/ -- the number
// the Follow-ups page's Due today tab shows. The API decides all of it: whose
// reminders they are (the BDE's own leads), which are due today (by the end of
// today's Indian date) and how each counts. Nothing is counted here.
//
// One count for the whole Hub, kept while the BDE moves between pages. A page
// that reads every follow-up itself (the Follow-ups page, the BDE dashboard)
// shares the summary it got (useSharedFollowUpSummary), and while such a page
// is on screen the sidebar reads nothing of its own. Elsewhere the sidebar
// reads the summary the way those pages do: on arrival, every minute while the
// tab is shown and on coming back to it (useLiveRefresh).

// As often as the Follow-ups page reads its reminders again.
const REFRESH_MS = 60_000;
// A count this recent -- shared by a page just left, say -- is not read again.
const FRESH_MS = 30_000;

let count = null;
let countAt = 0;
// Bumped with every count (and when it is forgotten), so a read answered after
// a newer count arrived -- or after the BDE signed out -- changes nothing.
let version = 0;
// Pages on screen that read the follow-ups themselves.
let sources = 0;
let inflight = null;
const listeners = new Set();

function publish(next) {
  count = next;
  countAt = next == null ? 0 : Date.now();
  version += 1;
  for (const listener of listeners) listener();
}

function forget() {
  inflight = null;
  publish(null);
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const snapshot = () => count;
const todayOf = (summary) => (Number.isInteger(summary?.today) ? summary.today : null);

function read() {
  if (sources > 0 || inflight || (count != null && Date.now() - countAt < FRESH_MS)) return;
  const seen = version;
  const request = api
    .get(BDE_FOLLOW_UPS_URL, { params: { page_size: 1 } })
    .then((response) => {
      const today = todayOf(response.data?.summary);
      if (version === seen && today != null) publish(today);
    })
    // A failed read keeps the count shown; the next refresh tries again.
    .catch(() => {})
    .finally(() => {
      if (inflight === request) inflight = null;
    });
  inflight = request;
}

/**
 * For a page that reads GET /api/bde/follow-ups/ for every lead (never one
 * enquiry's): while it is on screen (`enabled`) the sidebar leaves the reading
 * to it, and each `summary` it gets becomes the sidebar's count.
 */
export function useSharedFollowUpSummary(summary, enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined;
    sources += 1;
    return () => {
      sources -= 1;
    };
  }, [enabled]);

  useEffect(() => {
    const today = todayOf(summary);
    if (enabled && today != null) publish(today);
  }, [enabled, summary]);
}

/**
 * The Due today count of the signed-in BDE's follow-ups, or null while it is
 * not known. Reads nothing unless `enabled` (whoever may open the Follow-ups
 * page); the count goes with the sidebar, so the next account starts afresh.
 */
export function useFollowUpsDueToday(enabled) {
  const today = useSyncExternalStore(subscribe, snapshot);

  useEffect(() => {
    if (!enabled) return undefined;
    forget();
    // Once the page arriving with the sidebar has said whether it reads the follow-ups itself.
    const timer = setTimeout(read, 0);
    return () => {
      clearTimeout(timer);
      forget();
    };
  }, [enabled]);

  useLiveRefresh(read, { intervalMs: REFRESH_MS, enabled });
  return enabled ? today : null;
}
