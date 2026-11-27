import { useEffect, useSyncExternalStore } from 'react';

import api from '@/lib/api';
import { bookingsUrl } from '@/lib/bookings';
import { useLiveRefresh } from '@/hooks/use-live-refresh';
import { DEMO_NEEDS_TUTOR, DIAGNOSTIC_NEEDS_TUTOR, STUDENTS_PENDING_ASSIGNMENT } from '@/lib/navigation';

// What still waits for an assignment, for the Admin Hub sidebar's badges: the
// Demo and the Diagnostic bookings that need a tutor -- booked, no tutor, the
// class still to come, the bookings a tutor may still be assigned to (the
// Admissions Dashboard's "Classes to come that need a tutor") -- and the
// current students missing a mentor or a tutor, each student once. The API
// counts each one (the `count` of a one-row read); nothing is counted here.
//
// One set of counts for the whole Hub, kept while the administrator moves
// between pages. The sidebar reads them on arrival, every minute while the tab
// is shown and on coming back to it (useLiveRefresh), and at once after the Hub
// assigns a tutor or changes a student's mentor or tutor
// (pendingAssignmentsChanged).

// As often as the BDE's Follow-ups badge is read again.
const REFRESH_MS = 60_000;

const STUDENTS_URL = '/api/students/';
// The Bookings lists' filter for the bookings that need a tutor (backend bookings.coordination).
const NEEDS_TUTOR = { status: 'BOOKED', assigned: 'false', when: 'upcoming' };

const READS = {
  [DEMO_NEEDS_TUTOR]: () => api.get(bookingsUrl('DEMO'), { params: { ...NEEDS_TUTOR, page_size: 1 } }),
  [DIAGNOSTIC_NEEDS_TUTOR]: () => api.get(bookingsUrl('DIAGNOSTIC'), { params: { ...NEEDS_TUTOR, page_size: 1 } }),
  // Backend students.services.pending_assignment.
  [STUDENTS_PENDING_ASSIGNMENT]: () =>
    api.get(STUDENTS_URL, { params: { assignment: 'pending', page: 1, page_size: 1 } }),
};

/** The counter keys (lib/navigation) these counts are shown under. */
export const PENDING_ASSIGNMENT_COUNTERS = Object.keys(READS);

const NONE = {};
// Each count by its counter key; absent while not known.
let counts = NONE;
// Bumped with every change of counts (and when they are forgotten or a change
// is reported), so a read answered after that changes nothing.
let version = 0;
// The counts the sidebar on screen shows.
let wanted = [];
let inflight = null;
const listeners = new Set();

function publish(next) {
  counts = next;
  version += 1;
  for (const listener of listeners) listener();
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const snapshot = () => counts;
const countOf = (response) => (Number.isInteger(response?.data?.count) ? response.data.count : null);

function read() {
  if (inflight || wanted.length === 0) return;
  const seen = version;
  const keys = wanted;
  const request = Promise.allSettled(keys.map((key) => READS[key]()))
    .then((results) => {
      if (version !== seen) return;
      const next = { ...counts };
      let changed = false;
      results.forEach((result, index) => {
        // A failed read keeps its count shown; the next refresh tries again.
        const count = result.status === 'fulfilled' ? countOf(result.value) : null;
        if (count != null && count !== next[keys[index]]) {
          next[keys[index]] = count;
          changed = true;
        }
      });
      if (changed) publish(next);
    })
    .finally(() => {
      if (inflight === request) inflight = null;
    });
  inflight = request;
}

function forget() {
  wanted = [];
  inflight = null;
  publish(NONE);
}

/**
 * Says the Hub has just changed an assignment -- a booking's tutor, a
 * student's mentor or tutor -- so the sidebar reads its counts again now
 * rather than within the minute. Does nothing while no sidebar shows them.
 */
export function pendingAssignmentsChanged() {
  if (wanted.length === 0) return;
  // A read already under way may have been answered before the change: its answer is set aside.
  version += 1;
  inflight = null;
  read();
}

/**
 * The counts under `keys` (of PENDING_ASSIGNMENT_COUNTERS: those the sidebar
 * shows), as `{ [key]: count }`, a key absent while its count is not known.
 * Reads nothing when `keys` is empty; the counts go with the sidebar, so the
 * next account starts afresh.
 */
export function usePendingAssignmentCounts(keys) {
  const shown = useSyncExternalStore(subscribe, snapshot);
  const key = keys.join(' ');

  useEffect(() => {
    if (!key) return undefined;
    wanted = key.split(' ');
    read();
    return forget;
  }, [key]);

  useLiveRefresh(read, { intervalMs: REFRESH_MS, enabled: Boolean(key) });
  return key ? shown : NONE;
}
