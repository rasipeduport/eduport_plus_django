// What the Hub reads again on its own, on a clock these tests move by hand:
// the BDE's Follow-ups and dashboard every minute while their tab is shown and
// on coming back to it, never while it is hidden; a booking's communication
// every five seconds while its plan is PENDING (six times at most) and once
// about 20 seconds after a change in its workspace; and Sessions on request
// (Refresh) and on coming back to the tab -- each refresh once, however many
// events bring it, and nothing left running after the page goes; and the BDE
// sidebar's count of follow-ups due today, on the same minute; and the Admin
// Hub sidebar's counts of assignments still to make, on the same minute and at
// once after the Hub assigns a tutor or reassigns a student. The pages
// and hooks are rendered for real in jsdom (harness.jsx), with the API stood
// in for (../sessions/api-stub.js).
//
//   npm run test:data-freshness
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';
import { JSDOM, VirtualConsole } from 'jsdom';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const hubDir = path.resolve(here, '../..');
const src = path.join(hubDir, 'src');
const stub = path.resolve(here, '../sessions/api-stub.js');

// ------------------------------------------------------------------ bundle
const bundle = path.join(tmpdir(), `hub-data-freshness-${process.pid}.mjs`);
await esbuild.build({
  entryPoints: [path.join(here, 'harness.jsx')],
  outfile: bundle,
  bundle: true,
  format: 'esm',
  platform: 'browser',
  jsx: 'automatic',
  loader: { '.css': 'empty', '.svg': 'dataurl', '.png': 'dataurl' },
  define: {
    'process.env.NODE_ENV': '"development"',
    'import.meta.env': JSON.stringify({ VITE_LEARN_URL: 'http://learn.test', VITE_HUB_URL: 'http://localhost:3000', MODE: 'test', DEV: true, PROD: false }),
  },
  banner: { js: "import { createRequire as __hubCreateRequire } from 'node:module'; const require = __hubCreateRequire(import.meta.url);" },
  logLevel: 'warning',
  plugins: [{
    name: 'hub-resolve',
    setup(build) {
      for (const dep of ['react', 'react-dom', 'react-router-dom']) build.onResolve({ filter: new RegExp('^' + dep + '(/.*)?$') }, (args) => ({ path: require.resolve(args.path, { paths: [hubDir] }) }));
      build.onResolve({ filter: /lib\/api$/ }, (args) => (args.importer.includes('/frontend/') ? { path: stub } : undefined));
      build.onResolve({ filter: /^@\// }, (args) => build.resolve(`./${args.path.slice(2)}`, { resolveDir: src, kind: args.kind }));
    },
  }],
});

// ------------------------------------------------------------- browser env
const virtualConsole = new VirtualConsole();
const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>', { url: 'http://localhost:3000/', pretendToBeVisual: true, virtualConsole });
const { window } = dom;
for (const key of Object.getOwnPropertyNames(window)) {
  if (!(key in globalThis)) {
    try { globalThis[key] = window[key]; } catch { /* read-only */ }
  }
}
for (const key of ['window', 'document', 'navigator', 'location', 'history', 'Event', 'CustomEvent', 'EventTarget', 'Node',
  'Element', 'HTMLElement', 'MouseEvent', 'KeyboardEvent', 'FocusEvent', 'getComputedStyle', 'requestAnimationFrame',
  'cancelAnimationFrame', 'localStorage', 'sessionStorage', 'MutationObserver', 'DOMRect', 'AbortController', 'AbortSignal']) {
  try { Object.defineProperty(globalThis, key, { value: window[key], configurable: true, writable: true }); } catch { /* fixed */ }
}
window.matchMedia = (media) => ({ matches: false, media, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent() { return false; } });
class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
window.ResizeObserver = globalThis.ResizeObserver = ResizeObserverStub;
window.scrollTo = () => {};
window.HTMLElement.prototype.scrollIntoView = () => {};
window.HTMLElement.prototype.hasPointerCapture = () => false;
window.HTMLElement.prototype.releasePointerCapture = () => {};
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const quiet = console.error;
console.error = () => {};
process.on('unhandledRejection', () => {});

// Whether the tab is shown is the test's to say.
let visibility = 'visible';
Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
Object.defineProperty(document, 'hidden', { configurable: true, get: () => visibility === 'hidden' });

const { mount, act, BDE_DASHBOARD_URL, BDE_FOLLOW_UPS_URL, bookingCommunicationUrl, pendingAssignmentsChanged } =
  await import(pathToFileURL(bundle).href);

// -------------------------------------------------------------- the clock
// Every timer the app sets (setTimeout / setInterval, read at call time) and
// Date.now run on this clock, moved only by advance(); React and jsdom keep
// their own, captured before it was installed.
const realSetTimeout = globalThis.setTimeout;
const clock = { now: Date.now(), seq: 0, timers: new Map() };
const addTimer = (fn, ms, args, repeat) => {
  const id = ++clock.seq;
  const wait = Math.max(repeat ? 1 : 0, Number(ms) || 0);
  clock.timers.set(id, { id, at: clock.now + wait, every: repeat ? wait : 0, fn: () => fn(...args) });
  return id;
};
globalThis.setTimeout = (fn, ms, ...args) => addTimer(fn, ms, args, false);
globalThis.setInterval = (fn, ms, ...args) => addTimer(fn, ms, args, true);
globalThis.clearTimeout = globalThis.clearInterval = (id) => { clock.timers.delete(id); };
Date.now = () => clock.now;

const settle = async () => { for (let i = 0; i < 6; i++) await act(async () => new Promise((resolve) => realSetTimeout(resolve, 0))); };
/** Moves the clock on by `ms`, firing every timer due on the way, in order. */
async function advance(ms) {
  const target = clock.now + ms;
  for (let guard = 0; guard < 10_000; guard++) {
    let next = null;
    for (const timer of clock.timers.values()) {
      if (timer.at <= target && (!next || timer.at < next.at || (timer.at === next.at && timer.id < next.id))) next = timer;
    }
    if (!next) break;
    clock.now = next.at;
    if (next.every) next.at += next.every;
    else clock.timers.delete(next.id);
    await act(async () => next.fn());
    await settle();
  }
  clock.now = target;
  await settle();
}

// ------------------------------------------------------------------ helpers
const tests = [];
let current;
const test = (name, fn) => tests.push({ name, fn });
const clean = (value) => value.replace(/\s+/g, ' ').trim();
const fire = async (target, type) => { await act(async () => target.dispatchEvent(new window.Event(type))); await settle(); };
const hide = async () => { visibility = 'hidden'; await fire(document, 'visibilitychange'); };
const show = async () => { visibility = 'visible'; await fire(document, 'visibilitychange'); };
const focus = () => fire(window, 'focus');
const click = async (element) => {
  assert.ok(element, 'nothing to click');
  await act(async () => element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })));
  await settle();
};
const button = (label, root = document.body) => [...root.querySelectorAll('button')].find(
  (element) => clean(element.textContent) === label || element.getAttribute('aria-label') === label);
const topDialog = () => [...document.querySelectorAll('[role="dialog"]')].at(-1);
const radio = (label) => {
  const tag = [...document.querySelectorAll('label')].find((element) => clean(element.textContent).startsWith(label));
  assert.ok(tag, `no option ${label}`);
  return tag.querySelector('input[type="radio"], [role="radio"]');
};
/** The API answers from `routes` ("GET /url": answer, or (entry) => answer; a function may throw or reject). */
const serve = (routes) => {
  globalThis.__sessionsApi = {
    calls: [],
    handler: async (entry) => {
      const answer = routes[`${entry.method} ${entry.url}`];
      if (answer === undefined) return { data: {} };
      return { data: typeof answer === 'function' ? await answer(entry) : answer };
    },
  };
};
const calls = (method, url) => globalThis.__sessionsApi.calls.filter((entry) => entry.method === method && entry.url === url);
const gets = (url) => calls('GET', url).length;
const open = async (kind, props) => { current = await mount(kind, props); await settle(); return current; };
const refused = (status, data) => Promise.reject(Object.assign(new Error(`HTTP ${status}`), { response: { status, data } }));
const MINUTE = 60_000;

// ---------------------------------------------------------------- fixtures
const BDE = { id: 'bde-1', role: 'BDE', full_name: 'Bde One', email: 'bde@hub.test',
  permissions: ['accounts.view_own_enquiries', 'accounts.view_own_lead_communications'] };
const ADMIN = { id: 'admin', role: 'ADMIN', full_name: 'Admin One', email: 'admin@hub.test',
  permissions: ['accounts.view_all_bookings', 'accounts.view_all_communications', 'accounts.view_all_sessions'] };
const FOLLOW_UPS = { results: [], count: 0, page: 1, page_size: 25, summary: { total: 0, today: 0, upcoming: 0 } };
const DASHBOARD = { enquiries: { total: 0, last_7_days: 0 }, bookings: {}, upcoming: { total: 0, rows: [] },
  agenda: { date: '2026-11-20', total: 0, rows: [] }, recent_enquiries: [] };
const COMMS = (id) => bookingCommunicationUrl('DEMO', id);
const communication = (id, plan_status) => ({
  booking: { id, booking_type: 'DEMO', status: 'BOOKED' }, plan_status, planned: plan_status === 'PLANNED', redemo: false,
  parent_confirmation: { status: 'NOT_REQUESTED', at: null, by: null, reason: null }, tasks: [], messages: [], actions: {},
});
/** Answers each read with the next status, the last one from then on. */
const statuses = (id, ...each) => { let i = 0; return () => communication(id, each[Math.min(i++, each.length - 1)]); };
const slot = { id: 's-1', booking_type: 'DEMO', date: '2026-11-21', time: '19:30', starts_at: '2026-11-21T14:00:00+00:00',
  ends_at: '2026-11-21T15:00:00+00:00', started: false, ended: false };
const RIYA = { id: 'b-riya', booking_type: 'DEMO', status: 'BOOKED', slot, student_name: 'Riya', grade: 'Class 8',
  parent_name: 'Asha Nair', phone: '+971 501234567', tutor: null, bde: null, booked_at: '2026-11-18T09:00:00+00:00',
  activity_state: 'UPCOMING', started_at: null, timezone: 'Asia/Kolkata', seat: 1,
  lead: { id: 'lead-riya', phone_dial_code: '+971', phone_number: '501234567', school_name: 'Delhi Private School',
    syllabus: 'CBSE', country: 'United Arab Emirates', source: 'BOOKING_PAGE', owner_bde: null },
  referral_status: 'NO_REF', tutor_assigned_at: null, tutor_assigned_by: null, tutor_changeable: true,
  tutor_change_refusal: null, cancelled_at: null, cancelled_by: null, cancel_reason: '',
  actions: { cancel: true, no_show: false, reschedule: false } };

// ======================================================== P3: useLiveRefresh
const probe = async (options = { intervalMs: MINUTE }) => {
  const seen = { count: 0 };
  await open('live', { onRefresh: () => { seen.count += 1; }, options });
  return seen;
};

test('P3 hook: every 60 seconds while the tab is shown, never on mount', async () => {
  const seen = await probe();
  assert.equal(seen.count, 0, 'the page reads its own data on mount');
  await advance(MINUTE - 1);
  assert.equal(seen.count, 0);
  await advance(1);
  assert.equal(seen.count, 1, 'once at 60 s');
  await advance(MINUTE);
  assert.equal(seen.count, 2, 'again at 120 s');
});

test('P3 hook: nothing while hidden; once on coming back, then every minute from then', async () => {
  const seen = await probe();
  await advance(10_000);
  await hide();
  await advance(10 * MINUTE);
  assert.equal(seen.count, 0, 'no polling while the tab is hidden');
  await show();
  assert.equal(seen.count, 1, 'read again on coming back');
  await advance(MINUTE - 1);
  assert.equal(seen.count, 1, 'the interval starts afresh from that refresh');
  await advance(1);
  assert.equal(seen.count, 2);
});

test('P3 hook: focus and visibility together read once; a return just after mount or a refresh reads nothing', async () => {
  const seen = await probe();
  await focus();
  await show();
  assert.equal(seen.count, 0, 'just mounted: no duplicate of the first read');
  await advance(5_000);
  await hide();
  await advance(30_000);
  await show();
  await focus();
  assert.equal(seen.count, 1, 'visibilitychange then focus: one refresh');
  await advance(1_000);
  await focus();
  assert.equal(seen.count, 1, 'a second focus within the gap: nothing');
  await advance(5_000);
  await focus();
  assert.equal(seen.count, 2, 'a later return reads again');
});

test('P3 hook: a return within the gap after hiding still restarts the minute', async () => {
  const seen = await probe();
  await hide();
  await show();
  assert.equal(seen.count, 0);
  await advance(MINUTE);
  assert.equal(seen.count, 1, 'the interval was set again on coming back');
});

test('P3 hook: no timer or listener outlives the page; enabled: false does nothing', async () => {
  const seen = await probe();
  await advance(MINUTE);
  assert.equal(seen.count, 1);
  await current.unmount();
  current = null;
  assert.equal(clock.timers.size, 0, 'no timer left');
  await advance(5 * MINUTE);
  await hide();
  await show();
  await focus();
  assert.equal(seen.count, 1, 'nothing after unmount');

  const off = await probe({ intervalMs: MINUTE, enabled: false });
  await advance(5 * MINUTE);
  await hide();
  await show();
  await focus();
  assert.equal(off.count, 0);
  assert.equal(clock.timers.size, 0);
});

// =================================================== P3: the pages that use it
test('P3 Follow-ups: read every minute while shown, not while hidden, once on return; nothing after leaving', async () => {
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS });
  const page = await open('page', { path: '/follow-ups?due=today', user: BDE });
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 1);
  await advance(MINUTE - 1);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 1);
  await advance(1);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2, 'read again after 60 s');
  assert.deepEqual(calls('GET', BDE_FOLLOW_UPS_URL).at(-1).params, { page: 1, page_size: 25, due: 'today' }, 'with its filters');
  await hide();
  await advance(5 * MINUTE);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2, 'nothing while hidden');
  await show();
  await focus();
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 3, 'one read for visibility + focus');
  assert.match(clean(document.body.textContent), /Follow-ups/);
  await page.unmount();
  current = null;
  await advance(5 * MINUTE);
  await focus();
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 3, 'nothing after leaving');
});

test('P3 Follow-ups: a page the reader may not see is not read again', async () => {
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: () => refused(403, { code: 'NOT_A_BDE', message: 'Follow-ups belong to BDE accounts.' }) });
  await open('page', { path: '/follow-ups', user: BDE });
  assert.match(clean(document.body.textContent), /Follow-ups belong to BDE accounts\./);
  await advance(3 * MINUTE);
  await hide();
  await show();
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 1);
});

test('P3 BDE dashboard: the dashboard and its follow-up counts every minute while shown, once on return', async () => {
  serve({ [`GET ${BDE_DASHBOARD_URL}`]: DASHBOARD, [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS });
  await open('page', { path: '/dashboard', user: BDE });
  assert.equal(gets(BDE_DASHBOARD_URL), 1);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 1);
  assert.match(clean(document.body.textContent), /Total Enquiries/);
  await advance(MINUTE);
  assert.equal(gets(BDE_DASHBOARD_URL), 2);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2);
  await hide();
  await advance(5 * MINUTE);
  assert.equal(gets(BDE_DASHBOARD_URL), 2, 'nothing while hidden');
  await show();
  await focus();
  assert.equal(gets(BDE_DASHBOARD_URL), 3, 'one read for visibility + focus');
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 3);
  assert.match(clean(document.body.textContent), /Total Enquiries/, 'still shows the dashboard, no skeleton');
});

test('P3 BDE dashboard: a failed refresh keeps what is shown', async () => {
  let fail = false;
  serve({
    [`GET ${BDE_DASHBOARD_URL}`]: () => (fail ? refused(500, {}) : { ...DASHBOARD, enquiries: { total: 7, last_7_days: 2 } }),
    [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS,
  });
  await open('page', { path: '/dashboard', user: BDE });
  fail = true;
  await advance(MINUTE);
  assert.equal(gets(BDE_DASHBOARD_URL), 2);
  assert.match(clean(document.body.textContent), /\+2 in the last 7 days/, 'the last good answer stays');
});

// ============================================ P4: a booking's communication
const comms = async (id, ...each) => {
  serve({ [`GET ${COMMS(id)}`]: statuses(id, ...each) });
  const holder = {};
  await open('comms', { type: 'DEMO', id, probe: holder });
  return holder;
};

test('P4: PENDING is read again after 5 seconds', async () => {
  await comms('b-1', 'PENDING', 'PLANNED');
  assert.equal(gets(COMMS('b-1')), 1);
  await advance(4_999);
  assert.equal(gets(COMMS('b-1')), 1);
  await advance(1);
  assert.equal(gets(COMMS('b-1')), 2, 'a second read at 5 s');
});

test('P4: polling stops as soon as the plan is PLANNED, or FAILED', async () => {
  const planned = await comms('b-1', 'PENDING', 'PENDING', 'PLANNED');
  await advance(10_000);
  assert.equal(gets(COMMS('b-1')), 3);
  assert.equal(planned.state.communication.plan_status, 'PLANNED');
  await advance(2 * MINUTE);
  assert.equal(gets(COMMS('b-1')), 3, 'nothing more once PLANNED');
  assert.equal(clock.timers.size, 0);
  await current.unmount();

  const failed = await comms('b-2', 'PENDING', 'FAILED');
  await advance(5_000);
  assert.equal(failed.state.communication.plan_status, 'FAILED');
  await advance(2 * MINUTE);
  assert.equal(gets(COMMS('b-2')), 2, 'nothing more once FAILED');

  const notPlanned = await comms('b-3', 'NOT_PLANNED');
  await advance(MINUTE);
  assert.equal(gets(COMMS('b-3')), 1, 'never polled when not PENDING');
  assert.ok(notPlanned.state.communication);
});

test('P4: six retries at most while it stays PENDING', async () => {
  await comms('b-1', 'PENDING');
  await advance(30_000);
  assert.equal(gets(COMMS('b-1')), 7, 'the first read and six retries');
  await advance(10 * MINUTE);
  assert.equal(gets(COMMS('b-1')), 7, 'no seventh retry');
  assert.equal(clock.timers.size, 0);
});

test('P4: a failed retry stops polling until the next read', async () => {
  let n = 0;
  serve({ [`GET ${COMMS('b-1')}`]: () => (++n === 2 ? refused(500, {}) : communication('b-1', 'PENDING')) });
  const holder = {};
  await open('comms', { type: 'DEMO', id: 'b-1', probe: holder });
  await advance(5_000);
  assert.ok(holder.state.failure, 'the failure shows as before');
  await advance(MINUTE);
  assert.equal(gets(COMMS('b-1')), 2, 'no polling on after a failure');
  await act(async () => holder.state.retry());
  await settle();
  assert.equal(gets(COMMS('b-1')), 3, 'Try again reads it');
  await advance(5_000);
  assert.equal(gets(COMMS('b-1')), 4, 'and PENDING polls again');
});

test('P4: refreshLater reads once ~20 s on, however often asked meanwhile', async () => {
  const holder = await comms('b-1', 'PLANNED');
  await act(async () => holder.state.refreshLater());
  await advance(19_999);
  assert.equal(gets(COMMS('b-1')), 1);
  await advance(1);
  assert.equal(gets(COMMS('b-1')), 2, 'one read at 20 s');
  await advance(MINUTE);
  assert.equal(gets(COMMS('b-1')), 2, 'and only one');

  await act(async () => holder.state.refreshLater());
  await advance(10_000);
  await act(async () => holder.state.refreshLater());
  await act(async () => holder.state.refreshLater());
  await advance(MINUTE);
  assert.equal(gets(COMMS('b-1')), 3, 'three asks close together: one read');
});

test('P4: timers go with the booking (another booking, or unmount)', async () => {
  serve({ [`GET ${COMMS('b-1')}`]: statuses('b-1', 'PENDING'), [`GET ${COMMS('b-2')}`]: statuses('b-2', 'PLANNED') });
  const holder = {};
  const hook = await open('comms', { type: 'DEMO', id: 'b-1', probe: holder });
  await act(async () => holder.state.refreshLater());
  await advance(2_000);
  await hook.rerender({ type: 'DEMO', id: 'b-2', probe: holder });
  await settle();
  await advance(2 * MINUTE);
  assert.equal(gets(COMMS('b-1')), 1, "neither b-1's PENDING retry nor its catch-up fires after switching");
  assert.equal(gets(COMMS('b-2')), 1);
  assert.equal(clock.timers.size, 0);

  await hook.rerender({ type: 'DEMO', id: 'b-1', probe: holder });
  await settle();
  assert.equal(gets(COMMS('b-1')), 2);
  await advance(5_000);
  assert.equal(gets(COMMS('b-1')), 3, "back on b-1: its retries start afresh");
  await act(async () => holder.state.refreshLater());
  await hook.unmount();
  current = null;
  assert.equal(clock.timers.size, 0, 'no timer left after unmount');
  await advance(5 * MINUTE);
  assert.equal(gets(COMMS('b-1')), 3);
});

test('P4 workspace: a change reads the communication at once and again ~20 s on', async () => {
  serve({
    [`GET /api/bookings/demo/${RIYA.id}/`]: RIYA,
    [`GET ${COMMS(RIYA.id)}`]: () => communication(RIYA.id, 'PLANNED'),
    [`POST /api/bookings/demo/${RIYA.id}/cancel/`]: { ...RIYA, status: 'CANCELLED', cancel_reason_code: 'PARENT_REQUEST', changed: true },
  });
  await open('page', { path: `/bookings/demo/${RIYA.id}`, user: ADMIN });
  assert.equal(gets(COMMS(RIYA.id)), 1);
  await click(button('Cancel booking'));
  await click(radio('Parent asked to cancel'));
  await click(button('Cancel booking', topDialog()));
  assert.equal(calls('POST', `/api/bookings/demo/${RIYA.id}/cancel/`).length, 1);
  assert.match(clean(document.body.textContent), /Cancelled Riya's demo class/);
  assert.equal(gets(COMMS(RIYA.id)), 2, 'read again at once, as before');
  await advance(19_000);
  assert.equal(gets(COMMS(RIYA.id)), 2);
  await advance(1_500);
  assert.equal(gets(COMMS(RIYA.id)), 3, 'once more about 20 s on');
  await advance(2 * MINUTE);
  assert.equal(gets(COMMS(RIYA.id)), 3, 'only once');
});

// ======================================================= P5: Hub Sessions
const sessionsPage = async () => {
  serve({ 'GET /api/sessions/': { sessions: [] }, 'GET /api/students/': [] });
  await open('page', { path: '/sessions', user: ADMIN });
  assert.equal(gets('/api/sessions/'), 1);
};

test('P5: Refresh reads the sessions once', async () => {
  await sessionsPage();
  const refresh = button('Refresh sessions');
  assert.ok(refresh, 'a Refresh button');
  assert.equal(clean(refresh.textContent), 'Refresh');
  assert.ok(!refresh.disabled);
  await click(refresh);
  assert.equal(gets('/api/sessions/'), 2, 'exactly one more GET');
  assert.equal(calls('GET', '/api/sessions/').at(-1).params, null, 'the full list, no content filter');
});

test('P5: coming back to the tab reads once; the 15 s clock reads nothing', async () => {
  await sessionsPage();
  const clockTimer = [...clock.timers.values()].find((timer) => timer.every === 15_000);
  assert.ok(clockTimer, "the page's 15 s display clock runs");
  const firstTick = clockTimer.at;
  await advance(2 * MINUTE);
  assert.equal(clockTimer.at, firstTick + 8 * 15_000, 'it ticked eight times');
  assert.equal(gets('/api/sessions/'), 1, 'without reading the API');
  await hide();
  await show();
  await focus();
  assert.equal(gets('/api/sessions/'), 2, 'one read for visibility + focus');
  await advance(2 * MINUTE);
  assert.equal(gets('/api/sessions/'), 2, 'no polling on Sessions');
});

// ============================================= P5 fix: Sessions refresh in the background
// A class under way that nobody started yet: whoever may start it gets Start Session.
const HOUR = 3600 * 1000;
// The page times Start by `new Date()` -- the real clock, not this suite's (moved on by earlier tests).
const at = (offset) => new Date(new Date().getTime() + offset).toISOString();
const TUTOR_PROFILE = { id: 't-a', full_name: 'Tutor A', email: 'a@hub.test' };
const underWay = (extra = {}) => ({
  id: 's-1', student_id: 'stu-1', title: 'Algebra', status: 'scheduled', series_id: null, class_number: null,
  start_time: at(-60_000), end_time: at(HOUR - 60_000), start_opens_at: at(-6 * 60_000),
  students: { student_code: 'EDP1', full_name: 'Riya', mentor_profile: null, avatar_url: null },
  tutor: 't-a', tutor_profile: TUTOR_PROFILE, tutor_meet_link: 'https://meet.google.com/aaa-aaaa-aaa',
  started_at: null, started_by_profile: null, completed_at: null, completed_by_profile: null, duration_hours: 1,
  recording_link: null, notes_link: null, homework_link: null, content_files: {}, homework: null, rating: null,
  outcome_reason: null, outcome_note: null, outcome_kind: null, consumes_credit: true, ...extra,
});
const MANAGER = { id: 'admin', role: 'ADMIN', full_name: 'Admin One', email: 'admin@hub.test', permissions: [
  'accounts.view_all_sessions', 'accounts.manage_session', 'accounts.create_session', 'accounts.cancel_session'] };
const START = 'Start Session with Riya';
const spinner = () => document.querySelector('.py-20 svg.animate-spin');
/** Sessions whose reads after the first wait for `release()`, as a network does; each read answers `rows()`. */
const heldSessions = (rows, extra = {}) => {
  const held = { release: null };
  serve({
    'GET /api/students/': [],
    'GET /api/sessions/': () => (gets('/api/sessions/') <= 1
      ? { sessions: rows() }
      : new Promise((resolve) => { held.release = () => resolve({ sessions: rows() }); })),
    ...extra,
  });
  return held;
};

test('P5 fix: the first read shows the spinner; a refresh on coming back keeps the table, only the Refresh icon turns', async () => {
  // Every read waits for the test to answer it, the first one included.
  const waiting = [];
  serve({ 'GET /api/students/': [], 'GET /api/sessions/': () => new Promise((resolve) => { waiting.push(resolve); }) });
  const answer = async () => { waiting.shift()({ sessions: [underWay()] }); await settle(); };
  await open('page', { path: '/sessions', user: MANAGER });
  assert.ok(spinner(), 'nothing to show yet: the full-page spinner');
  await answer();
  assert.ok(button(START) && !spinner(), 'the table is in');

  await advance(5_000);
  await hide();
  await show();
  assert.equal(gets('/api/sessions/'), 2, 'one read on coming back');
  assert.equal(waiting.length, 1, 'its answer still on the way');
  assert.ok(button(START), 'the table stays while the refresh runs');
  assert.ok(!spinner(), 'no full-page spinner over it');
  const refresh = button('Refresh sessions');
  assert.ok(refresh.disabled && refresh.querySelector('svg.animate-spin'), 'the Refresh icon turns meanwhile');
  await answer();
  assert.ok(button(START) && !refresh.disabled && !refresh.querySelector('svg.animate-spin'), 'the fresh list is in, the same table');
});

test('P5 fix: Refresh keeps the table too and reads once', async () => {
  const held = heldSessions(() => [underWay()]);
  await open('page', { path: '/sessions', user: MANAGER });
  await click(button('Refresh sessions'));
  assert.equal(gets('/api/sessions/'), 2);
  assert.ok(button(START) && !spinner(), 'the table stays while Refresh reads');
  held.release();
  await settle();
  assert.equal(gets('/api/sessions/'), 2);
});

test('P5 fix: a Start refusal stays readable when the browser comes back from the blank Meet tab; closing it reads the list once', async () => {
  // Read again, the list would say the class is cancelled -- its Start (and dialog) would go with its row.
  let cancelled = false;
  const held = heldSessions(() => [underWay(cancelled ? { status: 'cancelled' } : {})], {
    'POST /api/sessions/s-1/start/': () => {
      cancelled = true;
      return refused(409, { error: 'This session has been cancelled.', code: 'SESSION_CANCELLED' });
    },
  });
  await open('page', { path: '/sessions', user: MANAGER });
  await advance(5_000);
  await click(button(START));
  await click(button('Start Session', topDialog()));
  assert.match(clean(topDialog().textContent), /cancelled/i, 'the refusal, in the dialog');
  // Start opened a blank Meet tab before the API answered and closed it on the refusal: the Hub is shown again.
  await hide();
  await show();
  await focus();
  assert.equal(gets('/api/sessions/'), 1, 'no refresh under the open Start dialog');
  assert.ok(topDialog() && /cancelled/i.test(clean(topDialog().textContent)), 'the refusal is still there to read');
  await click(button('Not yet', topDialog()));
  assert.equal(gets('/api/sessions/'), 2, 'closing it reads the list once (its own refusal refresh)');
  assert.ok(!spinner(), 'with the table kept meanwhile');
  held.release();
  await settle();
  assert.ok(!button(START), 'the class reads as it now stands');
  await advance(5_000);
  await hide();
  await show();
  assert.equal(gets('/api/sessions/'), 3, 'coming back refreshes again once the dialog is closed');
  held.release();
  await settle();
});

test('P5 fix: a refusal arriving while a background refresh runs stays on screen with the table', async () => {
  const held = heldSessions(() => [underWay()], {
    'POST /api/sessions/s-1/start/': () => refused(409, { error: 'x', code: 'START_WINDOW_CLOSED' }),
  });
  await open('page', { path: '/sessions', user: MANAGER });
  await advance(5_000);
  await hide();
  await show();
  assert.equal(gets('/api/sessions/'), 2, 'the refresh runs, its answer held');
  await click(button(START));
  await click(button('Start Session', topDialog()));
  assert.ok(button(START, document.querySelector('table')), 'the table stays mounted');
  assert.match(clean(topDialog().textContent), /can no longer be started/, 'and the refusal shows while the refresh runs');
  held.release();
  await settle();
  assert.match(clean(topDialog().textContent), /can no longer be started/, 'still there once the refresh is in');
});

test('P5 fix: a refresh under way when Start is refused, whose list drops the row, waits until the dialog closes', async () => {
  let cancelled = false;
  const held = heldSessions(() => [underWay(cancelled ? { status: 'cancelled' } : {})], {
    'POST /api/sessions/s-1/start/': () => {
      cancelled = true;
      return refused(409, { error: 'x', code: 'SESSION_CANCELLED' });
    },
  });
  await open('page', { path: '/sessions', user: MANAGER });
  await advance(5_000);
  await hide();
  await show();
  assert.equal(gets('/api/sessions/'), 2, 'a refresh under way, its answer held');
  await click(button(START));
  await click(button('Start Session', topDialog()));
  assert.match(clean(topDialog().textContent), /This session was cancelled\./);
  held.release(); // the list comes in: the class is cancelled, its row (and Start) would go
  await settle();
  assert.ok(topDialog(), 'the dialog stays open');
  assert.match(clean(topDialog().textContent), /This session was cancelled\./, 'with the refusal');
  assert.ok(button(START, document.querySelector('table')), 'its row stays until the dialog closes');
  await click(button('Not yet', topDialog()));
  assert.ok(!topDialog(), 'closed');
  assert.ok(!button(START), 'the list that came in is shown: the class is cancelled');
  assert.equal(gets('/api/sessions/'), 3, 'and the refusal close reads the list once, as before');
  held.release();
  await settle();
  assert.ok(!button(START) && !spinner());
});

test('P5 fix: a list held under an open Start dialog is shown when it closes without a refusal, with no extra read', async () => {
  let renamed = false;
  const held = heldSessions(() => [underWay(renamed ? { title: 'Geometry' } : {})]);
  await open('page', { path: '/sessions', user: MANAGER });
  await advance(5_000);
  await hide();
  await show();
  assert.equal(gets('/api/sessions/'), 2);
  await click(button(START));
  assert.ok(topDialog(), 'Start Session? is open');
  renamed = true;
  held.release();
  await settle();
  assert.ok(topDialog(), 'still open');
  const table = () => clean(document.querySelector('table').textContent);
  assert.match(table(), /Algebra/, 'the table as it was while the dialog is open');
  await click(button('Not yet', topDialog()));
  assert.match(table(), /Geometry/, 'the list that came in, once it closes');
  assert.equal(gets('/api/sessions/'), 2, 'nothing read again for it');
});

// ======================================== P3 fix: Follow-ups keep an open dialog
const FOLLOW_UP_BDE = { id: 'bde', role: 'BDE', full_name: 'Bde One', email: 'bde@hub.test', permissions: [
  'accounts.record_parent_confirmation', 'accounts.send_lead_communications', 'accounts.share_booking_report',
  'accounts.view_own_enquiries', 'accounts.view_own_lead_communications', 'accounts.view_own_lead_reports'] };
const PRE_CALL = { id: 't-call', type: 'PRE_ACTIVITY_CALL', type_label: 'Pre-activity call', state: 'DUE_TODAY',
  state_label: 'Due today', due_at: '2026-11-20T14:00:00+00:00', opens_at: null, request: null,
  enquiry: { id: 'e-dona', parent_name: 'Asha Nair', student_name: 'Dona', grade: 'Class 8', phone: '+971 501234567',
    phone_dial_code: '+971', phone_number: '501234567' },
  booking: { id: 'b-dona', booking_type: 'DEMO', date: '2026-11-20', time: '19:30', starts_at: '2026-11-20T14:00:00+00:00',
    status: 'BOOKED', activity_state: 'UPCOMING', redemo: false },
  actions: { open_whatsapp: false, mark_request_sent: false, record_answer: false } };
// The pre-activity call only reminds, so the dialog these keep open is the parent's answer to a confirmation.
const CONFIRM = { ...PRE_CALL, id: 'b-dona', type: 'PARENT_CONFIRMATION', type_label: 'Parent confirmation',
  actions: { open_whatsapp: false, mark_request_sent: false, record_answer: true } };
const followUpsPage = (rows) => ({ results: rows, count: rows.length, page: 1, page_size: 25,
  summary: { total: rows.length, today: rows.length, upcoming: 0 } });
const PARENT_ANSWER = `${COMMS('b-dona')}parent-confirmation/`;

const answerDialog = async (later, extra = {}) => {
  serve({
    [`GET ${BDE_FOLLOW_UPS_URL}`]: () => followUpsPage(gets(BDE_FOLLOW_UPS_URL) <= 1 ? [CONFIRM] : later),
    ...extra,
  });
  await open('page', { path: '/follow-ups', user: FOLLOW_UP_BDE });
  await click(button('Record answer'));
  assert.ok(topDialog(), 'the answer dialog is open');
  await click(radio('Confirmed'));
  assert.ok(radio('Confirmed').checked, 'an answer picked');
};

test('P3 fix: the minute refresh that empties Follow-ups keeps the open answer dialog and what was picked', async () => {
  await answerDialog([]);
  await advance(MINUTE);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2, 'the minute refresh ran and found nothing left');
  assert.ok(topDialog(), 'the dialog is still open');
  assert.ok(radio('Confirmed').checked, 'with the answer still picked');
  assert.ok(!button('Record answer', topDialog()).disabled, 'and still ready to record');
  await click(button('Cancel', topDialog()) ?? button('Close', topDialog()));
  await settle();
  assert.match(clean(document.body.textContent), /You're all caught up/, 'the empty state, once it closes');
});

test('P3 fix: recording on a booking that changed meanwhile shows the API refusal in the dialog', async () => {
  await answerDialog([], {
    [`POST ${PARENT_ANSWER}`]: () => refused(409, { error: 'BOOKING_STARTED', message: 'The class has started.' }),
  });
  await advance(MINUTE);
  await click(button('Record answer', topDialog()));
  assert.equal(calls('POST', PARENT_ANSWER).length, 1, 'sent to the API, which decides');
  assert.deepEqual(calls('POST', PARENT_ANSWER)[0].data, { outcome: 'CONFIRMED' });
  assert.ok(topDialog(), 'the dialog stays');
  assert.match(clean(topDialog().textContent), /The class has started\./, 'with the API message');
});

test('P3 fix: while its row is still listed the dialog is untouched by the refresh', async () => {
  await answerDialog([CONFIRM]);
  await advance(MINUTE);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2);
  assert.ok(topDialog() && radio('Confirmed').checked);
});

// ============================================ Phase 3 -- P7: focus refresh where staff keep pages open
const GAP = 30_000;
const text = () => clean(document.body.textContent);
const listOf = (results) => ({ results, count: results.length, page: 1, page_size: 25 });
const LEADS_ADMIN = { id: 'admin', role: 'ADMIN', full_name: 'Admin One', email: 'admin@hub.test',
  permissions: ['accounts.view_all_leads', 'accounts.assign_lead_owner', 'accounts.add_lead', 'accounts.view_all_bookings'] };
const ENQUIRY_BDE = { id: 'bde', role: 'BDE', full_name: 'Bde One', email: 'bde@hub.test',
  permissions: ['accounts.view_own_enquiries', 'accounts.cancel_booking'] };
const WEB_LEAD = { id: 'lead-web', parent_name: 'Meera Menon', phone: '+91 9876543210', phone_dial_code: '+91', phone_number: '9876543210',
  parent_email: '', student_name: 'Kavya', grade: 'Class 7', source: 'WEBSITE', source_label: 'Website', status: 'NEW', status_label: 'New',
  next_booking: null, added_at: null, owner: null, created_at: '2026-11-06T04:00:00+00:00', school_name: 'Kendriya Vidyalaya',
  syllabus: 'CBSE', country: 'India', timezone: 'Asia/Kolkata', bookings: [], added_by: null, source_details: {} };
const reload = async () => { await hide(); await show(); await focus(); };

/** Read on coming back to the tab: never within 30 s of the page's last read, once after it, never on a timer. */
async function focusOnly(url, label) {
  assert.equal(gets(url), 1, `${label}: one read on opening`);
  await advance(10_000);
  await reload();
  assert.equal(gets(url), 1, `${label}: nothing within 30 s`);
  await advance(GAP);
  await reload();
  assert.equal(gets(url), 2, `${label}: one read on coming back (focus and visibility together)`);
  await advance(10 * MINUTE);
  assert.equal(gets(url), 2, `${label}: never on a timer`);
}

test('P7: Leads, a Lead, My Enquiries and BDE bookings read again on coming back, at most every 30 s, never on a timer', async () => {
  const pages = [
    ['/leads', LEADS_ADMIN, { 'GET /api/leads/': listOf([]), 'GET /api/leads/bdes/': { results: [] } }, '/api/leads/'],
    [`/leads/${WEB_LEAD.id}`, LEADS_ADMIN, { [`GET /api/leads/${WEB_LEAD.id}/`]: WEB_LEAD, 'GET /api/leads/bdes/': { results: [] } },
      `/api/leads/${WEB_LEAD.id}/`],
    ['/enquiries', ENQUIRY_BDE, { 'GET /api/bde/enquiries/': listOf([]) }, '/api/bde/enquiries/'],
    ['/demo-bookings', ENQUIRY_BDE, { 'GET /api/bde/bookings/demo/': listOf([]) }, '/api/bde/bookings/demo/'],
  ];
  for (const [path, user, routes, url] of pages) {
    serve(routes);
    await open('page', { path, user });
    await focusOnly(url, path);
    await current.unmount();
    current = null;
  }
});

// ---- the enquiry workspace (P7 + L6 + L3)
const ENQUIRY_URL = '/api/bde/enquiries/lead-1/';
const BDE_BOOKED = { id: 'b-1', booking_type: 'DEMO', date: '2026-10-31', time: '19:30', starts_at: '2026-10-31T14:00:00+00:00',
  status: 'BOOKED', ended: false, activity_state: 'UPCOMING', started_at: null, booked_at: '2026-10-28T09:00:00+00:00',
  cancelled_at: null, actions: { cancel: true, no_show: false } };
const enquiryOf = (bookings, extra = {}) => ({ id: 'lead-1', student_name: 'Riya', grade: 'Class 8', parent_name: 'Asha Nair',
  phone: '+971 501234567', phone_dial_code: '+971', phone_number: '501234567', status: 'BOOKED', status_label: 'Demo booked',
  source: 'BOOKING_PAGE', source_label: 'Booking page', added_at: '2026-10-27T09:00:00+00:00', school_name: 'Delhi Private School',
  syllabus: 'CBSE', country: 'United Arab Emirates', created_at: '2026-10-27T09:00:00+00:00', timezone: 'Asia/Kolkata',
  next_booking: null, bookings, ...extra });
const CANCEL_DEMO = 'Cancel the demo class on Sat, 31 Oct · 7:30 PM IST';
const httpError = (status, data) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data } });

test('P7 + L6 + L3: the enquiry workspace reads again on coming back; an older answer never replaces a newer one; Cancel reads the booking first; a failed read keeps the workspace', async () => {
  const waiting = [];
  serve({ [`GET ${ENQUIRY_URL}`]: () => (gets(ENQUIRY_URL) === 1
    ? enquiryOf([BDE_BOOKED])
    : new Promise((resolve, reject) => waiting.push({ resolve, reject }))) });
  await open('page', { path: '/enquiries/lead-1?tab=bookings', user: ENQUIRY_BDE });
  assert.ok(button(CANCEL_DEMO), 'the booking offers Cancel');
  await advance(10_000);
  await reload();
  assert.equal(gets(ENQUIRY_URL), 1, 'nothing within 30 s');
  await advance(GAP);
  await reload();
  assert.equal(gets(ENQUIRY_URL), 2, 'one read on coming back');

  // Cancel opens at once and reads the enquiry again (L3); that later read answers first.
  await click(button(CANCEL_DEMO));
  assert.ok(topDialog(), 'the cancel dialog opens at once');
  assert.equal(gets(ENQUIRY_URL), 3);
  assert.ok(radio('No-show').disabled, 'No-show off, as the page last read it');
  await act(async () => waiting[1].resolve(enquiryOf([{ ...BDE_BOOKED, actions: { cancel: true, no_show: true } }], { grade: 'Class 9' })));
  await settle();
  assert.ok(!radio('No-show').disabled, 'No-show on, as the booking now stands');
  await act(async () => waiting[0].resolve(enquiryOf([BDE_BOOKED], { grade: 'Class 7' })));
  await settle();
  assert.match(text(), /Class 9/, 'the newer answer stays');
  assert.doesNotMatch(text(), /Class 7/, 'the older one, answered last, is dropped (L6)');
  assert.ok(!radio('No-show').disabled, 'and the dialog keeps the booking as it now stands');
  await click(button('Keep booking', topDialog()));

  // A read that fails says so above the workspace, which stays (L6).
  await advance(GAP);
  await reload();
  assert.equal(gets(ENQUIRY_URL), 4);
  await act(async () => waiting[2].reject(httpError(500, { message: 'Server down' })));
  await settle();
  assert.ok(button(CANCEL_DEMO), 'the workspace is still there');
  assert.match(text(), /Server down/, 'with the failure above it');
  assert.ok(button('Retry') || button('Try again'), 'and a way to read it again');
});

// ---- the administrators' booking workspace (P7, L2, L3, L7)
const BOOKING_URL = (id) => `/api/bookings/demo/${id}/`;

test("P7: the admin booking workspace reads again on coming back (30 s gap) and once its class ends", async () => {
  const endsSoon = { ...RIYA, slot: { ...RIYA.slot, ends_at: new Date(Date.now() + 2 * MINUTE).toISOString() } };
  serve({ [`GET ${BOOKING_URL(RIYA.id)}`]: endsSoon, [`GET ${COMMS(RIYA.id)}`]: () => communication(RIYA.id, 'PLANNED') });
  await open('page', { path: `/bookings/demo/${RIYA.id}`, user: ADMIN });
  assert.equal(gets(BOOKING_URL(RIYA.id)), 1);
  await advance(10_000);
  await reload();
  assert.equal(gets(BOOKING_URL(RIYA.id)), 1, 'nothing within 30 s');
  await advance(GAP);
  await reload();
  assert.equal(gets(BOOKING_URL(RIYA.id)), 2, 'one read on coming back');
  await advance(2 * MINUTE);
  assert.equal(gets(BOOKING_URL(RIYA.id)), 3, 'once its class has ended');
  await advance(10 * MINUTE);
  assert.equal(gets(BOOKING_URL(RIYA.id)), 3, 'nothing more on a timer');
});

test('L3 + L2: Cancel reads the booking as it now stands; a 409 stays in its dialog and closing it reads the booking again; a 400 does not', async () => {
  let refusal = 409;
  serve({
    [`GET ${BOOKING_URL(RIYA.id)}`]: () => (gets(BOOKING_URL(RIYA.id)) === 1 ? RIYA : { ...RIYA, actions: { ...RIYA.actions, no_show: true } }),
    [`GET ${COMMS(RIYA.id)}`]: () => communication(RIYA.id, 'PLANNED'),
    [`POST ${BOOKING_URL(RIYA.id)}cancel/`]: () => (refusal === 409
      ? refused(409, { error: 'BOOKING_STARTED', message: 'This booking has started meanwhile.' })
      : refused(400, { error: 'INVALID_REASON', message: 'Pick a reason from the list.' })),
  });
  await open('page', { path: `/bookings/demo/${RIYA.id}`, user: ADMIN });
  await click(button('Cancel booking'));
  assert.equal(gets(BOOKING_URL(RIYA.id)), 2, 'Cancel reads the booking again (L3)');
  assert.ok(!radio('No-show').disabled, 'No-show on, as the booking now stands');
  await click(radio('Parent asked to cancel'));
  await click(button('Cancel booking', topDialog()));
  assert.match(clean(topDialog().textContent), /This booking has started meanwhile\./, 'the refusal, in the dialog');
  assert.equal(gets(BOOKING_URL(RIYA.id)), 2, 'nothing read while it shows');
  await click(button('Keep booking', topDialog()));
  assert.equal(gets(BOOKING_URL(RIYA.id)), 3, 'closing it reads the booking again (L2)');

  refusal = 400;
  await click(button('Cancel booking'));
  assert.equal(gets(BOOKING_URL(RIYA.id)), 4);
  await click(radio('Parent asked to cancel'));
  await click(button('Cancel booking', topDialog()));
  assert.match(clean(topDialog().textContent), /Pick a reason from the list\./);
  await click(button('Keep booking', topDialog()));
  assert.equal(gets(BOOKING_URL(RIYA.id)), 4, 'a 400 says nothing of the page: nothing read');
});

test("L7: a move opens the new booking with the move's notice; another booking opens without one", async () => {
  const MOVED = { ...RIYA, id: 'b-riya-2', slot: { ...RIYA.slot, date: '2026-11-22', time: '19:30' } };
  const OTHER = { ...RIYA, id: 'b-zara', student_name: 'Zara' };
  const OPTIONS = { booking_id: RIYA.id, booking_type: 'DEMO', timezone: 'Asia/Kolkata', slot: RIYA.slot, tutor: null,
    reschedulable: true, refusal: null, dates: [{ date: '2026-11-22', slots: [{ time: '19:30', starts_at: '', ends_at: '',
      status: 'Available', seats_left: 3, bookable: true, unavailable_reason: null, lead_conflict: null, tutor_free: true, tutor_reason: null }] }] };
  serve({
    [`GET ${BOOKING_URL(RIYA.id)}`]: { ...RIYA, actions: { ...RIYA.actions, reschedule: true } },
    [`GET ${BOOKING_URL(RIYA.id)}reschedule-options/`]: OPTIONS,
    [`POST ${BOOKING_URL(RIYA.id)}reschedule/`]: { booking: MOVED, previous: { id: RIYA.id, status: 'RESCHEDULED' },
      tutor: { carried_over: false, tutor: null, reason: null } },
    [`GET ${BOOKING_URL(MOVED.id)}`]: MOVED,
    [`GET ${BOOKING_URL(OTHER.id)}`]: OTHER,
  });
  await open('page', { path: `/bookings/demo/${RIYA.id}`, user: ADMIN });
  await click(button('Reschedule'));
  await click(radio('7:30 PM'));
  await click(radio('Parent asked to move'));
  await click(button('Move booking', topDialog()));
  assert.equal(globalThis.__dfRouter.state.location.pathname, `/bookings/demo/${MOVED.id}`, 'the new booking opens');
  assert.match(text(), /Moved Riya's demo class to/, "with the move's notice");
  await act(async () => globalThis.__dfRouter.navigate(`/bookings/demo/${OTHER.id}`));
  await settle();
  assert.match(text(), /Zara/);
  assert.doesNotMatch(text(), /Moved Riya's demo class/, 'another booking opens without it');
});

// ---- the tutor's booking workspace (P7)
const TUTOR = { id: 't-a', role: 'TUTOR', full_name: 'Tutor A', email: 'a@hub.test',
  permissions: ['accounts.view_assigned_bookings', 'accounts.submit_booking_report'] };
const TUTOR_URL = '/api/tutor/bookings/demo/b-tr/';
const tutorRow = (extra = {}) => {
  const starts = Date.now() + 2 * MINUTE;
  return { id: 'b-tr', booking_type: 'DEMO', status: 'BOOKED',
    slot: { date: '2026-11-20', time: '19:30', starts_at: new Date(starts).toISOString(), ends_at: new Date(starts + 60 * MINUTE).toISOString(),
      started: false, ended: false },
    student_name: 'Riya', grade: 'Class 8', syllabus: 'CBSE', school_name: 'Delhi Private School', country: 'United Arab Emirates',
    student_timezone: null, tutor_meet_link: null, activity_state: 'UPCOMING', started_at: null,
    start_opens_at: new Date(starts - 5 * MINUTE).toISOString(), actions: { start: true }, start_refusal: null,
    has_report: false, report_state: 'NOT_STARTED', redemo: null, timezone: 'Asia/Kolkata', ...extra };
};

test('P7: the tutor workspace reads again on coming back (30 s gap) and once its class ends', async () => {
  const row = tutorRow({ slot: { ...tutorRow().slot, ends_at: new Date(Date.now() + 2 * MINUTE).toISOString() } });
  serve({ [`GET ${TUTOR_URL}`]: row });
  await open('page', { path: '/my-bookings/demo/b-tr', user: TUTOR });
  assert.equal(gets(TUTOR_URL), 1);
  await advance(10_000);
  await reload();
  assert.equal(gets(TUTOR_URL), 1, 'nothing within 30 s');
  await advance(GAP);
  await reload();
  assert.equal(gets(TUTOR_URL), 2, 'one read on coming back');
  await advance(2 * MINUTE);
  assert.equal(gets(TUTOR_URL), 3, 'once its class has ended');
});

test('P7: the tutor workspace never takes an open Start dialog away; a read under way waits until it closes', async () => {
  let cancelled = false;
  const waiting = [];
  const now = () => (cancelled
    ? tutorRow({ status: 'CANCELLED', actions: { start: false },
      start_refusal: { code: 'BOOKING_CANCELLED', message: 'This booking is cancelled, so it cannot be started.' } })
    : tutorRow());
  serve({
    [`GET ${TUTOR_URL}`]: () => (gets(TUTOR_URL) === 1 ? now() : new Promise((resolve) => waiting.push(() => resolve(now())))),
    [`POST ${TUTOR_URL}start/`]: () => {
      cancelled = true;
      return refused(409, { error: 'BOOKING_CANCELLED', message: 'This booking is cancelled, so it cannot be started.' });
    },
  });
  await open('page', { path: '/my-bookings/demo/b-tr', user: TUTOR });
  await advance(GAP + 1000);
  await reload();
  assert.equal(gets(TUTOR_URL), 2, 'a read under way');
  await click(button('Start Demo for Riya'));
  await click(button('Start Demo', topDialog()));
  const refusal = clean(topDialog().textContent);
  assert.match(refusal, /cancel/i, 'the refusal, in the dialog');
  await advance(GAP + 1000);
  await reload();
  assert.equal(gets(TUTOR_URL), 2, 'no read on coming back while the dialog is open');
  waiting.shift()();
  await settle();
  assert.equal(clean(topDialog()?.textContent ?? ''), refusal, 'the read that came in left the dialog as it was');
  await click(button('Not yet', topDialog()));
  assert.ok(!topDialog(), 'closed');
  assert.ok(!button('Start Demo for Riya'), 'the booking that came in is shown: no Start');
  assert.equal(gets(TUTOR_URL), 3, "and the refusal's close reads it once more");
  waiting.shift()();
  await settle();
  await advance(GAP + 1000);
  await reload();
  assert.equal(gets(TUTOR_URL), 4, 'coming back reads again once the dialog is closed');
  waiting.shift()?.();
  await settle();
});

// ---- the costly dashboards: Refresh on request only
test('P7: Tutor Main and Academics dashboards read again on Refresh only, never on coming back', async () => {
  serve({ 'GET /api/tutor/bookings/': listOf([]) });
  await open('page', { path: '/tutor-dashboard', user: { ...TUTOR, permissions: ['accounts.view_assigned_bookings'] } });
  const load = gets('/api/tutor/bookings/');
  assert.ok(load > 0, 'the dashboard read its bookings');
  await advance(2 * MINUTE);
  await reload();
  assert.equal(gets('/api/tutor/bookings/'), load, 'nothing on coming back or on a timer');
  await click(button('Refresh'));
  assert.equal(gets('/api/tutor/bookings/'), 2 * load, 'Refresh reads it all once more');
  await current.unmount();
  current = null;

  serve({ 'GET /api/dashboard/stats/': { students: 0, mentors: 0, tutors: 0, pending_invitations: 0, signup_data: [], recent_signups: [] },
    'GET /api/students/': [], 'GET /api/sessions/': { sessions: [] }, 'GET /api/homework/': { homework: [] }, 'GET /api/activity/': { results: [] } });
  await open('page', { path: '/academics-dashboard', user: { ...ADMIN, permissions: [...ADMIN.permissions, 'accounts.view_staff_dashboard'] } });
  assert.equal(gets('/api/dashboard/stats/'), 1);
  await advance(2 * MINUTE);
  await reload();
  assert.equal(gets('/api/dashboard/stats/'), 1, 'nothing on coming back or on a timer');
  await click(button('Refresh'));
  assert.equal(gets('/api/dashboard/stats/'), 2, 'Refresh reads it once more');
});

// ============================================ Phase 3 -- P8: the low fixes
test("L2: a 409 recording the parent's answer stays in the dialog; closing it reads the follow-ups again", async () => {
  await answerDialog([CONFIRM], {
    [`POST ${PARENT_ANSWER}`]: () => refused(409, { error: 'BOOKING_STARTED', message: 'The class has started.' }),
  });
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 1);
  await click(button('Record answer', topDialog()));
  assert.match(clean(topDialog().textContent), /The class has started\./);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 1, 'nothing read while it shows');
  await click(button('Cancel', topDialog()));
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2, 'closing it reads the follow-ups again');
});

test("L4: a follow-up's \"starts in N minutes\" moves with the clock, reading nothing", async () => {
  const soon = (ms) => new Date(Date.now() + ms).toISOString();
  const call = { ...PRE_CALL, opens_at: soon(-MINUTE), due_at: soon(14.5 * MINUTE) };
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: () => followUpsPage([call]) });
  await open('page', { path: '/follow-ups', user: FOLLOW_UP_BDE });
  assert.match(text(), /starts in 15 minutes/);
  await advance(31_000);
  assert.match(text(), /starts in 14 minutes/, 'the label moved on its own');
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 1, 'no read for it');
});

test('L8: "Classes to come that need a tutor" opens the list its count is: booked, no tutor, still to come', async () => {
  serve({ 'GET /api/admissions/dashboard/': { timezone: 'Asia/Kolkata', range: { from: '2026-11-14', to: '2026-11-20' },
    leads: { received: 0, new: 0 }, pipeline: [], bookings: { DEMO: { total: 0, upcoming: 0 }, DIAGNOSTIC: { total: 0, upcoming: 0 } },
    today_bookings: { date: '2026-11-20', total: 0, rows: [] },
    pending: { unassigned_leads: 0, needs_tutor: { DEMO: 2, DIAGNOSTIC: 0 }, report_due: { DEMO: 0, DIAGNOSTIC: 0 },
      redemo_scheduling: 0, awaiting_confirmation: { DEMO: 0, DIAGNOSTIC: 0 } },
    recent_leads: [], activity: [] } });
  await open('page', { path: '/admissions', user: LEADS_ADMIN });
  const link = [...document.querySelectorAll('a')].find((a) => /need a tutor/i.test(a.textContent));
  assert.ok(link, 'the item links to its list');
  const [path, query] = link.getAttribute('href').split('?');
  const params = new URLSearchParams(query);
  assert.equal(path, '/bookings/demo');
  assert.deepEqual([params.get('status'), params.get('assigned'), params.get('when')], ['BOOKED', 'false', 'upcoming']);
});

// ---- Learn: one load per child switch, and only the latest load counts (L12)
const LEARN_A = { id: 'sA', full_name: 'Riya Nair', status: 'ACTIVE', total_class_quota: 10, timezone: 'Asia/Kolkata' };
const LEARN_B = { id: 'sB', full_name: 'Arjun Nair', status: 'ACTIVE', total_class_quota: 20, timezone: 'Asia/Kolkata' };
const meOf = (selected) => ({ user: { id: 'u1', role: 'STUDENT', email: 'p@x.test' }, student_profiles: [LEARN_A, LEARN_B],
  student_profile: selected, selected_student_id: selected?.id ?? null, must_change_password: false });
const statsOf = (selected) => ({ student_id: selected.id, student_name: selected.full_name, scheduled_count: 0, attended_count: 0,
  next_session: null, last_session: null, next_exam: null, last_exam: null });
/** Learn's API: the selection is the server's (a cookie); `hold` keeps the next /me's answer -- as it stood then -- until released. */
function learnApi(state) {
  serve({
    'GET /api/auth/me/': () => {
      const answer = meOf(state.selected);
      if (!state.hold) return answer;
      state.hold = false;
      return new Promise((resolve) => { state.release = () => resolve(answer); });
    },
    'GET /api/student/dashboard/': () => statsOf(state.selected),
    'POST /api/auth/select-student/': (entry) => {
      state.selected = [LEARN_A, LEARN_B].find((student) => student.id === entry.data.student_id);
      return { selected_student_id: state.selected.id };
    },
  });
}

test('L12: switching child from another page loads once; on the dashboard, once too', async () => {
  for (const from of ['/select-profile', '/dashboard']) {
    const state = { selected: LEARN_A };
    learnApi(state);
    const probe = {};
    await open('learn', { path: from, probe });
    assert.equal(probe.student?.selectedStudent?.id, 'sA', `${from}: Riya first`);
    const [me, stats] = [gets('/api/auth/me/'), gets('/api/student/dashboard/')];
    await act(async () => probe.student.switchStudent('sB'));
    await settle();
    assert.equal(probe.path, '/dashboard');
    assert.equal(probe.student.selectedStudent.id, 'sB', `${from}: Arjun now`);
    assert.equal(probe.student.dashboardStats.student_id, 'sB');
    assert.deepEqual([gets('/api/auth/me/') - me, gets('/api/student/dashboard/') - stats], [1, 1], `${from}: one /me and one dashboard read`);
    await current.unmount();
    current = null;
  }
});

test('L12: a slower, earlier load never overwrites the child a later one resolved', async () => {
  const state = { selected: LEARN_A };
  learnApi(state);
  const probe = {};
  await open('learn', { path: '/dashboard', probe });
  state.hold = true;
  await act(async () => probe.navigate('/exams'));  // a load whose /me (Riya) is slow to answer
  await settle();
  await act(async () => probe.student.switchStudent('sB'));  // the switch: Arjun, loaded at once
  await settle();
  assert.equal(probe.student.selectedStudent.id, 'sB');
  await act(async () => state.release());  // the slow answer arrives last
  await settle();
  assert.equal(probe.student.selectedStudent.id, 'sB', 'the later load stands');
  assert.equal(probe.student.dashboardStats.student_id, 'sB', "and its stats are Arjun's");
});

// ======================================= Sidebar: the Follow-ups badge (due today)
// The count beside the BDE's Follow-ups item is the API's summary.today -- the
// Follow-ups page's Due today tab -- never upcoming, overdue or every open one.
// The Follow-ups page and the BDE dashboard share the summary they read; on
// every other page the sidebar reads it itself, on their minute.
const FOLLOW_UPS_DUE = (today, upcoming = 0, overdue) => ({ ...FOLLOW_UPS,
  summary: { total: today + upcoming + (overdue ?? 0), today, upcoming, ...(overdue == null ? {} : { overdue }) } });
const dueBadge = () => document.querySelector('[data-counter="follow-ups-due-today"]');
const followUpsItem = () => document.querySelector('a[href="/follow-ups"]');
const dueTab = () => [...document.querySelectorAll('[role="tab"]')].find((tab) => clean(tab.textContent).startsWith('Due today'));
const go = async (to) => { await act(async () => globalThis.__dfRouter.navigate(to)); await settle(); };
/** The Hub at `path`, its sidebar's first read let through (it waits for the page arriving with it). */
const openHub = async (path, user = BDE) => { await open('hub', { path, user }); await advance(0); return current; };
const sidebarReads = () => calls('GET', BDE_FOLLOW_UPS_URL).filter((entry) => entry.params?.page_size === 1).length;

test("Sidebar badge: today's follow-ups only -- 5 due today of 15 open (7 upcoming, 3 overdue) shows 5", async () => {
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS_DUE(5, 7, 3) });
  await openHub('/enquiries');
  assert.equal(clean(dueBadge().textContent), '5');
  assert.equal(dueBadge().getAttribute('aria-hidden'), 'true', 'read out with the item instead');
  assert.match(dueBadge().className, /bg-destructive/);
  assert.match(dueBadge().className, /rounded-full/);
  assert.equal(clean(followUpsItem().textContent), 'Follow-ups (5 due today)');
  assert.deepEqual(calls('GET', BDE_FOLLOW_UPS_URL).map((entry) => entry.params), [{ page_size: 1 }], 'one read, nothing filtered');
});

test('Sidebar badge: one due today shows 1; none hides it, the item as it always was', async () => {
  let today = 1;
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: () => FOLLOW_UPS_DUE(today, 4) });
  await openHub('/enquiries');
  assert.equal(clean(dueBadge().textContent), '1');
  today = 0;
  await advance(MINUTE);
  assert.equal(dueBadge(), null, 'hidden at zero');
  assert.equal(clean(followUpsItem().textContent), 'Follow-ups');
});

test('Sidebar badge: the same number as the Due today tab, from the Follow-ups page’s own read -- the sidebar reads nothing', async () => {
  let today = 5;
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: () => FOLLOW_UPS_DUE(today, 7, 3) });
  await openHub('/follow-ups?due=upcoming');
  assert.equal(clean(dueTab().textContent), 'Due today5');
  assert.equal(clean(dueBadge().textContent), '5', 'the whole count, whichever tab is open');
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 1, "the page's read only");
  // A follow-up done (or fallen due) meanwhile: the page's next read moves the tab and the badge together.
  today = 4;
  await advance(MINUTE);
  assert.equal(clean(dueTab().textContent), 'Due today4');
  assert.equal(clean(dueBadge().textContent), '4');
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2);
  assert.equal(sidebarReads(), 0, 'no read of its own while the page reads them');
});

test('Sidebar badge: the BDE dashboard shares its follow-up counts too; one read a minute between them', async () => {
  serve({ [`GET ${BDE_DASHBOARD_URL}`]: DASHBOARD, [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS_DUE(3, 2) });
  await openHub('/dashboard');
  assert.equal(clean(dueBadge().textContent), '3');
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 1);
  await advance(MINUTE);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2, "the dashboard's minute read, nothing more");
});

test('Sidebar badge: kept while moving between BDE pages, a change of page reading nothing again', async () => {
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS_DUE(5, 7) });
  await openHub('/enquiries');
  assert.equal(sidebarReads(), 1);
  for (const to of ['/demo-bookings', '/follow-ups', '/enquiries', '/demo-bookings']) {
    await go(to);
    assert.equal(clean(dueBadge()?.textContent ?? ''), '5', `still shown on ${to}`);
  }
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2, "the first read and the Follow-ups page's own");
  await advance(MINUTE);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 3, 'then once a minute');
});

test('Sidebar badge: elsewhere it follows changes on the minute, as the Follow-ups page does; nothing while hidden, once on return', async () => {
  let today = 5;
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: () => FOLLOW_UPS_DUE(today, 1) });
  await openHub('/enquiries');
  today = 2;
  await advance(MINUTE - 1);
  assert.equal(clean(dueBadge().textContent), '5', 'nothing read before the minute');
  await advance(1);
  assert.equal(clean(dueBadge().textContent), '2');
  await hide();
  today = 0;
  await advance(5 * MINUTE);
  assert.equal(sidebarReads(), 2, 'nothing while hidden');
  await show();
  await focus();
  assert.equal(sidebarReads(), 3, 'one read for visibility + focus');
  assert.equal(dueBadge(), null);
});

test('Sidebar badge: 120 due today reads 99+ without widening the sidebar; the full number is read out', async () => {
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS_DUE(120, 3) });
  await openHub('/enquiries');
  assert.equal(clean(dueBadge().textContent), '99+');
  assert.equal(clean(followUpsItem().textContent), 'Follow-ups (120 due today)');
  assert.match(followUpsItem().className, /\bpr-10\b/, 'the title keeps clear of the badge');
});

test('Sidebar badge: a failed read keeps the count shown; the next minute reads again', async () => {
  let fail = false;
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: () => (fail ? refused(500, {}) : FOLLOW_UPS_DUE(5)) });
  await openHub('/enquiries');
  fail = true;
  await advance(MINUTE);
  assert.equal(clean(dueBadge().textContent), '5');
  fail = false;
  await advance(MINUTE);
  assert.equal(sidebarReads(), 3);
});

test("Sidebar badge: signing out drops it; the next BDE never sees the last one's count", async () => {
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS_DUE(5) });
  await openHub('/enquiries');
  assert.equal(clean(dueBadge().textContent), '5');
  await current.unmount();
  current = null;
  await advance(5 * MINUTE);
  assert.equal(sidebarReads(), 1, 'nothing read after signing out');
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS_DUE(2) });
  await open('hub', { path: '/enquiries', user: { ...BDE, id: 'bde-2', email: 'bde2@hub.test' } });
  assert.equal(dueBadge(), null, 'nothing shown before their own read');
  await advance(0);
  assert.equal(clean(dueBadge().textContent), '2');
});

test("Sidebar badge: an administrator's sidebar, or a BDE's without Follow-ups, has none and reads nothing", async () => {
  serve({ [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS_DUE(5) });
  for (const user of [ADMIN, { ...BDE, permissions: ['accounts.view_own_enquiries'] }]) {
    await openHub(user.role === 'ADMIN' ? '/leads' : '/enquiries', user);
    await advance(3 * MINUTE);
    await focus();
    assert.equal(gets(BDE_FOLLOW_UPS_URL), 0, `${user.role}: no follow-ups read`);
    assert.equal(dueBadge(), null);
    assert.equal(followUpsItem(), null, 'no Follow-ups item to badge');
    await current.unmount();
    current = null;
  }
});

// ============================= Sidebar: the Admin Hub's pending assignment badges
// Beside Bookings' Demo and Diagnostic, the bookings that need a tutor (booked,
// no tutor, the class still to come: the Bookings lists' filter); beside
// Enrolled Students, the students missing a mentor or a tutor, each once
// (backend ?assignment=pending). The API counts each; the sidebar reads them on
// arrival, every minute while shown, on return, and at once after the Hub
// assigns a tutor or changes a student's mentor or tutor.
const DEMO_LIST = '/api/bookings/demo/';
const DIAGNOSTIC_LIST = '/api/bookings/diagnostic/';
const STUDENTS_LIST = '/api/students/';
const NEEDS_TUTOR_READ = { status: 'BOOKED', assigned: 'false', when: 'upcoming', page_size: 1 };
const PENDING_STUDENTS_READ = { assignment: 'pending', page: 1, page_size: 1 };
const COUNTERS = { demo: 'demo-needs-tutor', diagnostic: 'diagnostic-needs-tutor', students: 'students-pending-assignment' };
const ASSIGNER = { id: 'admin', role: 'ADMIN', full_name: 'Admin One', email: 'admin@hub.test', permissions: [
  'accounts.view_all_bookings', 'accounts.assign_booking_tutor', 'accounts.view_all_students',
  'accounts.view_full_student_record', 'accounts.reassign_student_staff'] };
const countPage = (count) => ({ results: [], count, page: 1, page_size: 1 });
/** Each list's count read from `state` ({ demo, diagnostic, students }), as it stands when asked. */
const countRoutes = (state) => ({
  [`GET ${DEMO_LIST}`]: () => countPage(state.demo),
  [`GET ${DIAGNOSTIC_LIST}`]: () => countPage(state.diagnostic),
  [`GET ${STUDENTS_LIST}`]: () => countPage(state.students),
});
const pendingBadge = (name) => document.querySelector(`[data-counter="${COUNTERS[name]}"]`);
const shownCounts = () => Object.fromEntries(Object.keys(COUNTERS).map((name) => [name, pendingBadge(name) ? clean(pendingBadge(name).textContent) : null]));
const navLink = (href) => document.querySelector(`a[href="${href}"]`);
const countReads = () => [DEMO_LIST, DIAGNOSTIC_LIST, STUDENTS_LIST].map((url) => calls('GET', url).length);

test('Admin badges: Demo and Diagnostic count the bookings needing a tutor, Enrolled Students those missing a mentor or tutor', async () => {
  serve(countRoutes({ demo: 3, diagnostic: 1, students: 2 }));
  await openHub('/sessions', ASSIGNER);
  assert.deepEqual(shownCounts(), { demo: '3', diagnostic: '1', students: '2' });
  assert.equal(clean(navLink('/bookings/demo').textContent), 'Demo (3 need a tutor)');
  assert.equal(clean(navLink('/bookings/diagnostic').textContent), 'Diagnostic (1 need a tutor)');
  assert.equal(clean(navLink('/students').textContent), 'Enrolled Students (2 missing a mentor or tutor)');
  // Read once each, as the lists filter them: one row, the count of all.
  assert.deepEqual(calls('GET', DEMO_LIST).map((entry) => entry.params), [NEEDS_TUTOR_READ]);
  assert.deepEqual(calls('GET', DIAGNOSTIC_LIST).map((entry) => entry.params), [NEEDS_TUTOR_READ]);
  assert.deepEqual(calls('GET', STUDENTS_LIST).map((entry) => entry.params), [PENDING_STUDENTS_READ]);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 0, 'no follow-ups read');
});

test('Admin badges: the Follow-ups badge’s red pill, beside each item; Demo and Diagnostic on their submenu rows', async () => {
  serve(countRoutes({ demo: 3, diagnostic: 1, students: 2 }));
  await openHub('/sessions', ASSIGNER);
  for (const name of Object.keys(COUNTERS)) {
    const badge = pendingBadge(name);
    assert.equal(badge.getAttribute('aria-hidden'), 'true', `${name}: read out with the item instead`);
    assert.match(badge.className, /bg-destructive/);
    assert.match(badge.className, /rounded-full/);
    assert.match(badge.className, /text-white/);
  }
  for (const name of ['demo', 'diagnostic']) {
    assert.ok(pendingBadge(name).closest('[data-sidebar="menu-sub-item"]'), `${name}: in the Bookings submenu`);
    assert.match(pendingBadge(name).className, /\btop-1\b/, `${name}: centred on the submenu's row`);
  }
  assert.ok(pendingBadge('students').closest('[data-sidebar="menu-item"]'));
  for (const href of ['/bookings/demo', '/bookings/diagnostic', '/students']) {
    assert.match(navLink(href).className, /\bpr-10\b/, `${href}: the title keeps clear of the badge`);
  }
});

test('Admin badges: none to count hides that badge alone, its item as it always was', async () => {
  serve(countRoutes({ demo: 0, diagnostic: 2, students: 0 }));
  await openHub('/sessions', ASSIGNER);
  assert.deepEqual(shownCounts(), { demo: null, diagnostic: '2', students: null });
  assert.equal(clean(navLink('/bookings/demo').textContent), 'Demo');
  assert.equal(clean(navLink('/students').textContent), 'Enrolled Students');
  assert.doesNotMatch(navLink('/students').className, /\bpr-10\b/);
});

test('Admin badges: 120 reads 99+; the full number is read out', async () => {
  serve(countRoutes({ demo: 120, diagnostic: 1, students: 150 }));
  await openHub('/sessions', ASSIGNER);
  assert.deepEqual(shownCounts(), { demo: '99+', diagnostic: '1', students: '99+' });
  assert.equal(clean(navLink('/bookings/demo').textContent), 'Demo (120 need a tutor)');
  assert.equal(clean(navLink('/students').textContent), 'Enrolled Students (150 missing a mentor or tutor)');
});

test('Admin badges: changes made elsewhere show on the minute; nothing read while hidden, once on return', async () => {
  const state = { demo: 3, diagnostic: 1, students: 2 };
  serve(countRoutes(state));
  await openHub('/sessions', ASSIGNER);
  Object.assign(state, { demo: 4, diagnostic: 0, students: 1 });
  await advance(MINUTE - 1);
  assert.deepEqual(shownCounts(), { demo: '3', diagnostic: '1', students: '2' }, 'nothing read before the minute');
  await advance(1);
  assert.deepEqual(shownCounts(), { demo: '4', diagnostic: null, students: '1' });
  await hide();
  state.students = 5;
  await advance(5 * MINUTE);
  assert.deepEqual(countReads(), [2, 2, 2], 'nothing while hidden');
  await show();
  await focus();
  assert.deepEqual(countReads(), [3, 3, 3], 'one read each for visibility + focus');
  assert.equal(shownCounts().students, '5');
});

test('Admin badges: kept while moving between pages, a change of page reading nothing again', async () => {
  serve(countRoutes({ demo: 3, diagnostic: 1, students: 2 }));
  await openHub('/sessions', ASSIGNER);
  for (const to of ['/leads', '/exams', '/sessions']) {
    await go(to);
    assert.deepEqual(shownCounts(), { demo: '3', diagnostic: '1', students: '2' }, `still shown on ${to}`);
  }
  assert.deepEqual(countReads(), [1, 1, 1]);
});

test('Admin badges: a failed read keeps its count shown; the others still change; the next minute reads it again', async () => {
  const state = { demo: 3, diagnostic: 1, students: 2 };
  let fail = false;
  serve({ ...countRoutes(state), [`GET ${DEMO_LIST}`]: () => (fail ? refused(500, {}) : countPage(state.demo)) });
  await openHub('/sessions', ASSIGNER);
  fail = true;
  Object.assign(state, { demo: 0, students: 4 });
  await advance(MINUTE);
  assert.deepEqual(shownCounts(), { demo: '3', diagnostic: '1', students: '4' });
  fail = false;
  await advance(MINUTE);
  assert.deepEqual(shownCounts(), { demo: null, diagnostic: '1', students: '4' });
});

test('Admin badges: assigning a tutor reads the counts again at once -- the Demo badge drops without waiting for the minute', async () => {
  const BOOKING = { ...RIYA, tutor_changeable: true };
  const TUTOR_ONE = { id: 't-1', full_name: 'Tutor One', email: 't1@hub.test' };
  const state = { demo: 1, diagnostic: 0, students: 0 };
  serve({
    ...countRoutes(state),
    [`GET ${BOOKING_URL(RIYA.id)}`]: BOOKING,
    [`GET ${COMMS(RIYA.id)}`]: () => communication(RIYA.id, 'PLANNED'),
    [`GET ${BOOKING_URL(RIYA.id)}tutors/`]: { tutor_changeable: true, tutors: [{ ...TUTOR_ONE, status: 'AVAILABLE', current: false }] },
    [`PUT ${BOOKING_URL(RIYA.id)}tutor/`]: () => {
      state.demo = 0;
      return { ...BOOKING, tutor: TUTOR_ONE };
    },
  });
  await openHub(`/bookings/demo/${RIYA.id}`, ASSIGNER);
  assert.equal(shownCounts().demo, '1');
  await click(button('Assign Tutor'));
  await click(document.querySelector('input[type="radio"][value="t-1"]'));
  await click(button('Assign Tutor', topDialog()));
  assert.equal(calls('PUT', `${BOOKING_URL(RIYA.id)}tutor/`).length, 1);
  assert.equal(shownCounts().demo, null, 'gone at once');
  assert.equal(clean(navLink('/bookings/demo').textContent), 'Demo');
  assert.deepEqual(countReads(), [2, 2, 2], 'one read each on arrival and one after the assignment');
});

test("Admin badges: changing a student's mentor or tutor reads the counts again at once", async () => {
  const state = { demo: 0, diagnostic: 0, students: 1 };
  serve({
    ...countRoutes(state),
    'GET /api/mentors/': { mentors: [{ id: 'm-1', full_name: 'Mentor One' }] },
    'GET /api/tutors/': { tutors: [{ id: 't-1', full_name: 'Tutor One' }] },
    'POST /api/students/reassign/': () => {
      state.students = 0;
      return {};
    },
  });
  await openHub('/reassign', ASSIGNER);
  assert.equal(shownCounts().students, '1');
  const trigger = document.getElementById('reassign-tutor');
  trigger.focus();
  await act(async () => trigger.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })));
  await settle();
  await click([...document.querySelectorAll('[role="option"]')].find((option) => clean(option.textContent) === 'Tutor One'));
  await click(button('Save', topDialog()));
  assert.deepEqual(calls('POST', '/api/students/reassign/').map((entry) => entry.data), [{ id: 'st-riya', mentor: 'm-1', tutor: 't-1' }]);
  assert.equal(shownCounts().students, null, 'gone at once');
  assert.deepEqual(countReads(), [2, 2, 2]);
});

test('Admin badges: an answer read before a change never overwrites the one read after it', async () => {
  const state = { demo: 2, diagnostic: 0, students: 0 };
  const slow = held();
  let n = 0;
  serve({ ...countRoutes(state), [`GET ${DEMO_LIST}`]: () => (++n === 2 ? slow() : countPage(state.demo)) });
  await openHub('/sessions', ASSIGNER);
  await advance(MINUTE);  // the minute's read of Demo, slow to answer: it will say 2
  assert.equal(slow.waiting(), 1);
  state.demo = 0;
  await act(async () => pendingAssignmentsChanged());
  await settle();
  assert.equal(shownCounts().demo, null, 'the read after the change');
  await slow.release(countPage(2));
  assert.equal(shownCounts().demo, null, 'the earlier answer set aside');
});

test("Admin badges: signing out drops them; nothing read after; the next administrator never sees the last one's", async () => {
  serve(countRoutes({ demo: 3, diagnostic: 1, students: 2 }));
  await openHub('/sessions', ASSIGNER);
  await current.unmount();
  current = null;
  await advance(5 * MINUTE);
  await act(async () => pendingAssignmentsChanged());
  assert.deepEqual(countReads(), [1, 1, 1], 'nothing read after signing out');
  const first = held();
  serve({ ...countRoutes({ demo: 1, diagnostic: 0, students: 0 }), [`GET ${DEMO_LIST}`]: first });
  await openHub('/sessions', { ...ASSIGNER, id: 'admin-2', email: 'admin2@hub.test' });
  assert.equal(shownCounts().demo, null, 'nothing shown before their own read');
  await first.release(countPage(1));
  assert.equal(shownCounts().demo, '1');
});

test('Admin badges: only where the item opens -- an administrator without view_all_students reads the booking counts alone', async () => {
  serve(countRoutes({ demo: 3, diagnostic: 1, students: 2 }));
  await openHub('/sessions', ADMIN);
  assert.deepEqual(shownCounts(), { demo: '3', diagnostic: '1', students: null });
  assert.deepEqual(countReads(), [1, 1, 0]);
});

test("Admin badges: the Admin Hub's only -- a BDE's, a tutor's and a mentor's sidebars read none of these counts", async () => {
  const MENTOR = { id: 'mentor', role: 'MENTOR', full_name: 'Mentor One', email: 'mentor@hub.test',
    permissions: ['accounts.view_mentored_students', 'accounts.view_mentored_sessions'] };
  const TUTOR_STAFF = { ...TUTOR, permissions: ['accounts.view_assigned_bookings', 'accounts.view_tutored_students'] };
  serve({ ...countRoutes({ demo: 3, diagnostic: 1, students: 2 }), [`GET ${BDE_FOLLOW_UPS_URL}`]: FOLLOW_UPS_DUE(0) });
  for (const user of [BDE, TUTOR_STAFF, MENTOR]) {
    await openHub('/sessions', user);
    await advance(3 * MINUTE);
    await focus();
    await act(async () => pendingAssignmentsChanged());
    assert.deepEqual(countReads(), [0, 0, 0], `${user.role}: no pending assignment count read`);
    assert.deepEqual(shownCounts(), { demo: null, diagnostic: null, students: null });
    await current.unmount();
    current = null;
  }
});

// =========================== Refresh audit: every Refresh, Check and Try again
// reads what it shows once more -- disabled and turning while that read is under
// way (a second click sends nothing), enabled again once it is answered or has
// failed -- and a failed read keeps what was shown, saying what failed.

/** An answer held until `release(data)` or `refuse(status)` (status 0: no answer at all); every call meanwhile waits on it. */
function held() {
  const waiting = [];
  const answer = () => new Promise((resolve, reject) => waiting.push({ resolve, reject }));
  answer.release = async (data) => { for (const call of waiting.splice(0)) call.resolve(data); await settle(); };
  answer.refuse = async (status = 500, data = { message: 'Server error.' }) => {
    for (const call of waiting.splice(0)) {
      call.reject(Object.assign(new Error(status ? `HTTP ${status}` : 'Network Error'), status ? { response: { status, data } } : {}));
    }
    await settle();
  };
  answer.waiting = () => waiting.length;
  return answer;
}
/** The first call answered with `first`; every later one by `later(entry)`. */
const thenHeld = (first, later) => { let n = 0; return (entry) => (n++ === 0 ? first : later(entry)); };
const spinning = (element) => Boolean(element?.querySelector('svg.animate-spin'));
const busy = (element) => Boolean(element?.disabled) && spinning(element);
// What each error on the page says (its message, without its Try again).
const alerts = () => [...document.querySelectorAll('[role="alert"]')].map((element) => clean((element.querySelector('p') ?? element).textContent));

// ------------------------------------------------ B4: the staff (Academics) dashboard
const STAFF = { ...ADMIN, permissions: [...ADMIN.permissions, 'accounts.view_staff_dashboard', 'accounts.view_all_students'] };
const STATS = { students: 1, mentors: 0, tutors: 0, pending_invitations: 0, signup_data: [], recent_signups: [] };
const MEERA = { id: 'st-1', full_name: 'Meera Pillai', student_code: 'EDP00001', status: 'active', created_at: '2026-11-01T06:00:00Z' };
const staffDashboard = (extra = {}) => ({ 'GET /api/dashboard/stats/': STATS, 'GET /api/students/': [MEERA],
  'GET /api/sessions/': { sessions: [] }, 'GET /api/homework/': { homework: [] }, 'GET /api/activity/': { results: [] }, ...extra });

test('Refresh audit B4: staff dashboard -- a refresh whose students and sessions fail keeps them on screen and names them', async () => {
  let failing = false;
  serve(staffDashboard({
    'GET /api/students/': () => (failing ? refused(500, {}) : [MEERA]),
    'GET /api/sessions/': () => (failing ? refused(500, {}) : { sessions: [] }),
  }));
  await open('page', { path: '/academics-dashboard', user: STAFF });
  assert.match(text(), /Meera Pillai/);
  assert.deepEqual(alerts(), [], 'nothing failed');
  failing = true;
  await click(button('Refresh'));
  assert.match(text(), /Meera Pillai/, 'the students loaded before stay (emptied before the fix)');
  assert.deepEqual(alerts(), ['Could not refresh students and sessions; showing what was loaded before.']);
  failing = false;
  await click(button('Try again'));
  assert.deepEqual(alerts(), [], 'the message goes once they read again');
  assert.equal(gets('/api/students/'), 3);
});

test('Refresh audit B4: staff dashboard -- a part that never loaded is said not to have loaded; the rest shows', async () => {
  serve(staffDashboard({ 'GET /api/homework/': () => refused(503, {}), 'GET /api/dashboard/stats/': () => refused(500, { message: 'Stats down.' }) }));
  await open('page', { path: '/academics-dashboard', user: STAFF });
  assert.deepEqual(alerts(), ['Could not load the dashboard figures and homework.']);
  assert.match(text(), /Meera Pillai/);
});

test('Refresh audit B4: staff dashboard Refresh is disabled and turning until its reads answer; a second click sends nothing', async () => {
  const stats = held();
  serve(staffDashboard({ 'GET /api/dashboard/stats/': thenHeld(STATS, () => stats()) }));
  await open('page', { path: '/academics-dashboard', user: STAFF });
  await click(button('Refresh'));
  assert.equal(gets('/api/dashboard/stats/'), 2);
  assert.ok(busy(button('Refresh')));
  await click(button('Refresh'));
  assert.equal(gets('/api/dashboard/stats/'), 2, 'a second click sends nothing');
  await stats.refuse(0);
  assert.equal(busy(button('Refresh')), false, 'enabled again after a network failure');
  assert.deepEqual(alerts(), ['Could not refresh the dashboard figures; showing what was loaded before.']);
});

// ------------------------------------------------ B4: the tutor's Main and Admissions dashboards
const TEACHER = { ...TUTOR, permissions: [...TUTOR.permissions, 'accounts.view_tutored_students', 'accounts.view_tutored_sessions'] };
const countOnly = (count) => ({ results: [], count, page: 1, page_size: 1 });

test('Refresh audit B4: Tutor Main -- failed reads keep their parts (bookings and students), each named; Try again reads them all', async () => {
  let failing = false;
  serve({
    'GET /api/tutor/bookings/': () => (failing ? refused(500, {}) : countOnly(3)),
    'GET /api/students/': () => (failing ? refused(500, {}) : [MEERA]),
    'GET /api/sessions/': { sessions: [] },
  });
  await open('page', { path: '/tutor-dashboard', user: TEACHER });
  assert.match(text(), /Assigned Bookings\s*6/);
  assert.match(text(), /Academic Students\s*1/);
  failing = true;
  await click(button('Refresh'));
  assert.match(text(), /Assigned Bookings\s*6/, 'the booking counts stay (0 before the fix)');
  assert.match(text(), /Academic Students\s*1/, 'the students tile stays (gone before the fix)');
  assert.deepEqual(alerts(), ['Could not refresh your bookings and students; showing what was loaded before.']);
  failing = false;
  const reads = gets('/api/tutor/bookings/');
  await click(button('Try again'));
  assert.equal(gets('/api/tutor/bookings/'), reads + 7, 'Try again is the Refresh: every read once more');
  assert.deepEqual(alerts(), []);
});

test('Refresh audit B4: Tutor Main Refresh and its Try again are disabled and turning while they read', async () => {
  const bookings = held();
  let holding = false;
  serve({ 'GET /api/tutor/bookings/': () => (holding ? bookings() : countOnly(1)), 'GET /api/students/': [], 'GET /api/sessions/': { sessions: [] } });
  await open('page', { path: '/tutor-dashboard', user: TEACHER });
  assert.equal(busy(button('Refresh')), false, 'idle once loaded');
  holding = true;
  await click(button('Refresh'));
  assert.ok(busy(button('Refresh')));
  const reads = gets('/api/tutor/bookings/');
  await click(button('Refresh'));
  assert.equal(gets('/api/tutor/bookings/'), reads, 'a second click sends nothing');
  await bookings.refuse(500);
  assert.equal(busy(button('Refresh')), false);
  await click(button('Try again'));
  assert.ok(busy(button('Try again')), 'Try again turns with it');
  assert.ok(busy(button('Refresh')));
  await bookings.release(countOnly(2));
  assert.deepEqual(alerts(), []);
});

test('Refresh audit B4: Tutor Admissions -- a failed refresh keeps the counts and names your bookings; a 403 still says whose dashboard it is', async () => {
  let failing = false;
  serve({ 'GET /api/tutor/bookings/': () => (failing ? refused(500, {}) : countOnly(3)) });
  await open('page', { path: '/admissions-dashboard', user: TUTOR });
  assert.match(text(), /Demo Bookings\s*3/);
  failing = true;
  await click(button('Refresh'));
  assert.match(text(), /Demo Bookings\s*3/, 'kept (0 before the fix)');
  assert.deepEqual(alerts(), ['Could not refresh your bookings; showing what was loaded before.']);
  await current.unmount();
  current = null;
  serve({ 'GET /api/tutor/bookings/': () => refused(403, { message: 'Only tutors have this dashboard.' }) });
  await open('page', { path: '/admissions-dashboard', user: TUTOR });
  assert.match(text(), /This dashboard belongs to tutor accounts\.\s*Only tutors have this dashboard\./);
});

// ------------------------------------------------ B2: Booking Slots
const SLOTS_ADMIN = { id: 'slots', role: 'ADMIN', full_name: 'Slots Admin', email: 's@hub.test', permissions: ['accounts.manage_booking_slots'] };
const SLOT_DAY = '/api/booking-slots/demo/2026-12-01/';
const slotsPath = '/booking-slots?type=demo&date=2026-12-01';
const SLOT_STATUSES = ['Available', 'Filling Fast', 'Only a Few Left', 'Fully Booked'];
const daySlot = (booked, extra = {}) => ({ time: '10:00', end_time: '11:00', scheduled: true, booked, capacity: 3,
  status: SLOT_STATUSES[booked], open_status: SLOT_STATUSES[booked], closed: false, closed_at: null, closed_by: null,
  close_reason: '', bookings: [], ...extra });
const slotDay = (...slots) => ({ booking_type: 'DEMO', date: '2026-12-01', timezone: 'Asia/Kolkata', slot_minutes: 60, capacity: 3,
  parent_state: 'open', window: { first: '2026-11-30', last: '2026-12-06' }, editable: true, slots });

test('Refresh audit B2: Booking Slots Refresh is disabled and turning while it reads; a second click sends nothing', async () => {
  const day = held();
  serve({ [`GET ${SLOT_DAY}`]: thenHeld(slotDay(daySlot(0)), () => day()) });
  await open('page', { path: slotsPath, user: SLOTS_ADMIN });
  assert.equal(gets(SLOT_DAY), 1);
  await click(button('Refresh'));
  assert.equal(gets(SLOT_DAY), 2);
  assert.ok(busy(button('Refresh')), 'it showed nothing while reading before the fix');
  await click(button('Refresh'));
  assert.equal(gets(SLOT_DAY), 2, 'a second click sends nothing (it sent one before the fix)');
  await day.release(slotDay(daySlot(1)));
  assert.equal(busy(button('Refresh')), false);
  assert.match(text(), /Filling Fast/);
});

test('Refresh audit B2: a failed refresh keeps the slots with the error above them; Try again turns while it reads', async () => {
  const again = held();
  let n = 0;
  serve({ [`GET ${SLOT_DAY}`]: () => { n += 1; return n === 1 ? slotDay(daySlot(1)) : n === 2 ? refused(500, { message: 'Slots are unavailable.' }) : again(); } });
  await open('page', { path: slotsPath, user: SLOTS_ADMIN });
  await click(button('Refresh'));
  assert.equal(button('Refresh').disabled, false, 'enabled again after the failure');
  assert.deepEqual(alerts(), ['Slots are unavailable.']);
  assert.match(text(), /Filling Fast/, 'the slots stay (the table was replaced by the error before the fix)');
  await click(button('Try again'));
  assert.ok(busy(button('Try again')));
  await click(button('Try again'));
  assert.equal(n, 3, 'a second click sends nothing');
  await again.refuse(0);
  assert.deepEqual(alerts(), ['Could not reach the server. Check your connection and try again.'], 'a network failure says so');
  assert.match(text(), /Filling Fast/);
});

test('Refresh audit B2: Refresh after a change shows the slots as they are now, the change’s message gone with the old ones', async () => {
  serve({
    [`GET ${SLOT_DAY}`]: () => slotDay(daySlot(1)),
    [`POST ${SLOT_DAY}`]: () => slotDay(daySlot(1, { status: 'Fully Booked', closed: true, closed_by: 'Slots Admin' })),
  });
  await open('page', { path: slotsPath, user: SLOTS_ADMIN });
  const trigger = document.querySelector('[aria-label^="Status of"]');
  trigger.focus();
  await act(async () => trigger.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })));
  await settle();
  await click([...document.querySelectorAll('[role="option"]')].find((option) => clean(option.textContent) === 'Fully Booked'));
  await click(button('Confirm', topDialog()));
  assert.equal(calls('POST', SLOT_DAY).length, 1);
  assert.ok(document.querySelector('[role="status"]'), 'the change says what it did');
  await click(button('Refresh'));
  assert.equal(Boolean(document.querySelector('[role="status"]')), false, 'gone with the refresh');
  assert.equal(gets(SLOT_DAY), 2);
});

// ------------------------------------------------ C1: Sessions reads its students on Refresh
test('Refresh audit C1: Sessions Refresh reads the students too, turning until both answer; a failed students read keeps the list and says so', async () => {
  const students = held();
  serve({ 'GET /api/sessions/': { sessions: [] }, 'GET /api/students/': thenHeld([MEERA], () => students()) });
  await open('page', { path: '/sessions', user: ADMIN });
  assert.deepEqual([gets('/api/sessions/'), gets('/api/students/')], [1, 1]);
  await click(button('Refresh sessions'));
  assert.deepEqual([gets('/api/sessions/'), gets('/api/students/')], [2, 2], 'the students are read again (not before the fix)');
  assert.ok(busy(button('Refresh sessions')), 'turning until the students answer too');
  await click(button('Refresh sessions'));
  assert.deepEqual([gets('/api/sessions/'), gets('/api/students/')], [2, 2], 'a second click sends nothing');
  await students.refuse(500);
  assert.equal(busy(button('Refresh sessions')), false);
  assert.match(text(), /Could not refresh the student list; showing the one loaded before\./);
  await click(button('Refresh sessions'));
  await students.release([MEERA]);
  assert.doesNotMatch(text(), /Could not refresh the student list/, 'gone once it reads');
});

// ------------------------------------------------ C2: Invitations' first read
const INVITER = { ...ADMIN, permissions: [...ADMIN.permissions, 'accounts.view_invitations'] };
const INVITATION = { id: 'invite', student_id: 'student', student_name: 'Enrolled Student', student_code: 'EDP12345', username: 'edp12345',
  role: 'STUDENT', status: 'PENDING', credentials_available: true, created_at: '2026-11-10T00:00:00Z' };

test('Refresh audit C2: Invitations -- a first read that fails shows only its error, never an empty list; Try again turns, then the list shows', async () => {
  const again = held();
  let n = 0;
  serve({ 'GET /api/invitations/': () => { n += 1; return n === 1 ? refused(500, { message: 'Invitations are unavailable.' }) : again(); } });
  await open('page', { path: '/invitations', user: INVITER });
  assert.deepEqual(alerts(), ['Invitations are unavailable.']);
  assert.doesNotMatch(text(), /No invitations yet/, 'not an empty list ("No invitations yet" before the fix)');
  await click(button('Try again'));
  assert.equal(n, 2);
  assert.ok(busy(button('Try again')));
  await click(button('Try again'));
  assert.equal(n, 2, 'a second click sends nothing');
  await again.release([INVITATION]);
  assert.deepEqual(alerts(), []);
  assert.match(text(), /Enrolled Student/);
});

// ------------------------------------------------ A3: Learn's waiting room and access ended
const GATE_A = { ...LEARN_A };
const GATE_B = { ...LEARN_B };
/** Learn's API for the gateway pages: `state.profiles` / `state.selected` as /me answers them; `state.me` (a function) overrides. */
function gatewayApi(state) {
  serve({
    'GET /api/auth/me/': () => (state.me ? state.me() : { user: { id: 'u1', role: 'STUDENT', email: 'p@x.test' },
      student_profiles: state.profiles, student_profile: state.selected ?? null, must_change_password: false }),
    'GET /api/student/dashboard/': () => {
      if (!state.profiles.length) return refused(404, { error: 'STUDENT_PROFILE_NOT_FOUND' });
      if (!state.selected) return refused(400, { error: 'STUDENT_NOT_SELECTED' });
      if (state.selected.status === 'EXPIRED') return refused(403, { error: 'STUDENT_ACCESS_ENDED' });
      return statsOf(state.selected);
    },
  });
}
const gateway = async (path, state) => {
  gatewayApi(state);
  const probe = {};
  await open('learnGateways', { path, probe });
  assert.equal(probe.path, path, `${path} first`);
  return probe;
};
const statusLine = () => clean(document.querySelector('[role="status"]')?.textContent ?? '');

test('Refresh audit A3: waiting room -- still not linked: Check Status says so and stays, one /me and no dashboard read', async () => {
  const state = { profiles: [] };
  const probe = await gateway('/waiting-room', state);
  const [me, dash] = [gets('/api/auth/me/'), gets('/api/student/dashboard/')];
  await click(button('Check Status'));
  assert.equal(probe.path, '/waiting-room');
  assert.equal(statusLine(), "Your profile isn't linked yet. You'll get in as soon as it is, so check again in a little while.");
  assert.deepEqual([gets('/api/auth/me/') - me, gets('/api/student/dashboard/') - dash], [1, 0]);
});

test('Refresh audit A3: waiting room -- linked to one child opens the dashboard', async () => {
  const state = { profiles: [] };
  const probe = await gateway('/waiting-room', state);
  Object.assign(state, { profiles: [GATE_A], selected: GATE_A });
  await click(button('Check Status'));
  assert.equal(probe.path, '/dashboard');
});

test('Refresh audit A3: waiting room -- several children and none chosen opens choosing one (it stayed in the waiting room before)', async () => {
  const state = { profiles: [] };
  const probe = await gateway('/waiting-room', state);
  Object.assign(state, { profiles: [GATE_A, GATE_B], selected: null });
  await click(button('Check Status'));
  assert.equal(probe.path, '/select-profile');
});

test('Refresh audit A3: waiting room -- linked but already expired opens access ended (it stayed before)', async () => {
  const state = { profiles: [] };
  const probe = await gateway('/waiting-room', state);
  Object.assign(state, { profiles: [{ ...GATE_A, status: 'EXPIRED' }], selected: null });
  await click(button('Check Status'));
  assert.equal(probe.path, '/access-ended');
});

test('Refresh audit A3: waiting room -- no answer from the API says so and stays (never the sign-in page); a refused session signs in again', async () => {
  const state = { profiles: [] };
  const probe = await gateway('/waiting-room', state);
  state.me = () => Promise.reject(new Error('Network Error'));
  await click(button('Check Status'));
  assert.equal(probe.path, '/waiting-room', 'not sent to /login for a network failure');
  assert.equal(statusLine(), "We couldn't check right now. Check your internet connection and try again.");
  assert.equal(button('Check Status').disabled, false, 'enabled again after the failure');
  state.me = () => refused(500, {});
  await click(button('Check Status'));
  assert.equal(probe.path, '/waiting-room', 'a server error stays too');
  assert.match(statusLine(), /couldn't check right now/);
  state.me = () => refused(401, { detail: 'Not signed in.' });
  await click(button('Check Status'));
  assert.equal(probe.path, '/login', 'a refused session goes to sign in');
});

test('Refresh audit A3: waiting room -- Check Status is disabled and turning while it checks; a second click sends nothing', async () => {
  const state = { profiles: [] };
  await gateway('/waiting-room', state);
  const me = held();
  state.me = () => me();
  const before = gets('/api/auth/me/');
  await click(button('Check Status'));
  const checking = button('Checking...');
  assert.ok(busy(checking), 'disabled and turning');
  await click(checking);
  assert.equal(gets('/api/auth/me/') - before, 1, 'one check at a time');
  await me.refuse(0);
  assert.equal(busy(button('Check Status')), false);
});

test('Refresh audit A3: access ended -- still ended says so and stays; restored opens the dashboard; no answer says so', async () => {
  const expired = { ...GATE_A, status: 'EXPIRED' };
  const state = { profiles: [expired] };
  const probe = await gateway('/access-ended', state);
  await click(button('Check Again'));
  assert.equal(probe.path, '/access-ended');
  assert.equal(statusLine(), 'Your access is still ended. Contact your mentor or our support team to restore it.');
  state.me = () => Promise.reject(new Error('Network Error'));
  await click(button('Check Again'));
  assert.equal(probe.path, '/access-ended');
  assert.equal(statusLine(), "We couldn't check right now. Check your internet connection and try again.");
  state.me = null;
  Object.assign(state, { profiles: [GATE_A], selected: GATE_A });
  await click(button('Check Again'));
  assert.equal(probe.path, '/dashboard');
});

test('Refresh audit A3: access ended -- restored as several children opens choosing one; the account reset opens the waiting room', async () => {
  for (const [after, where] of [[{ profiles: [GATE_A, GATE_B], selected: null }, '/select-profile'], [{ profiles: [], selected: null }, '/waiting-room']]) {
    const state = { profiles: [{ ...GATE_A, status: 'EXPIRED' }] };
    const probe = await gateway('/access-ended', state);
    Object.assign(state, after);
    await click(button('Check Again'));
    assert.equal(probe.path, where);
    await current.unmount();
    current = null;
  }
});

test('Refresh audit A3: access ended -- Check Again is disabled and turning while it checks', async () => {
  const state = { profiles: [{ ...GATE_A, status: 'EXPIRED' }] };
  await gateway('/access-ended', state);
  const me = held();
  state.me = () => me();
  await click(button('Check Again'));
  assert.ok(busy(button('Checking...')));
  await me.refuse(503);
  assert.equal(busy(button('Check Again')), false);
  assert.match(statusLine(), /couldn't check right now/);
});

// ------------------------------------------------ B1: every other header Refresh, the same way
const ADMISSIONS_ANSWER = { timezone: 'Asia/Kolkata', range: { from: '2026-11-14', to: '2026-11-20' },
  leads: { received: 0, new: 0 }, pipeline: [], bookings: { DEMO: { total: 0, upcoming: 0 }, DIAGNOSTIC: { total: 0, upcoming: 0 } },
  today_bookings: { date: '2026-11-20', total: 0, rows: [] },
  pending: { unassigned_leads: 0, needs_tutor: { DEMO: 0, DIAGNOSTIC: 0 }, report_due: { DEMO: 0, DIAGNOSTIC: 0 },
    redemo_scheduling: 0, awaiting_confirmation: { DEMO: 0, DIAGNOSTIC: 0 } },
  recent_leads: [], activity: [] };
const BOOKINGS_ADMIN = { ...ADMIN, permissions: [...ADMIN.permissions, 'accounts.assign_booking_tutor'] };

test('Refresh audit B1: Admissions, Tutor Admissions, Demo Bookings, Re-Demo requests and My Bookings Refresh -- disabled and turning while reading, one read a click, enabled again after a failure, data kept', async () => {
  const pages = [
    { path: '/admissions', user: LEADS_ADMIN, url: '/api/admissions/dashboard/', first: ADMISSIONS_ANSWER, shown: /Admissions Dashboard/ },
    { path: '/admissions-dashboard', user: TUTOR, url: '/api/tutor/bookings/', first: countOnly(2), shown: /Demo Bookings\s*2/ },
    { path: '/bookings/demo', user: BOOKINGS_ADMIN, url: '/api/bookings/demo/', first: listOf([]), shown: /Demo Bookings/ },
    { path: '/bookings/demo?tab=redemo', user: BOOKINGS_ADMIN, url: '/api/bookings/redemos/', first: { ...listOf([]), counts: {}, owners: [] }, shown: /Re-Demo requests/ },
    { path: '/my-bookings/demo', user: TUTOR, url: '/api/tutor/bookings/', first: listOf([]), shown: /Demo/ },
  ];
  for (const { path, user, url, first, shown } of pages) {
    const later = held();
    let holding = false;
    serve({ [`GET ${url}`]: () => (holding ? later() : first) });
    await open('page', { path, user });
    holding = true;
    const before = gets(url);
    assert.ok(before >= 1, `${path}: read on opening`);
    const refresh = button('Refresh');
    assert.ok(refresh, `${path}: a Refresh`);
    assert.equal(busy(refresh), false, `${path}: idle once loaded`);
    await click(refresh);
    const reads = gets(url) - before;
    assert.ok(reads >= 1, `${path}: Refresh reads`);
    assert.ok(busy(button('Refresh')), `${path}: disabled and turning while it reads`);
    await click(button('Refresh'));
    assert.equal(gets(url) - before, reads, `${path}: a second click sends nothing`);
    await later.refuse(500, { message: 'Unavailable for now.' });
    assert.equal(busy(button('Refresh')), false, `${path}: enabled again after the failure`);
    assert.match(text(), /Unavailable for now\.|Could not refresh/, `${path}: the failure is said`);
    assert.match(text(), shown, `${path}: what was shown stays`);
    await current.unmount();
    current = null;
  }
});

// ------------------------------------------------ C3: the BDE's booking links (an inline Try again)
test('Refresh audit C3: My Enquiries booking links -- Try again is disabled and turning while it reads; a second click sends nothing', async () => {
  const LINKS = '/api/bde/booking-links/';
  const again = held();
  let n = 0;
  serve({
    'GET /api/bde/enquiries/': listOf([]),
    [`GET ${LINKS}`]: () => { n += 1; return n === 1 ? refused(500, { message: 'Links are unavailable.' }) : again(); },
  });
  await open('page', { path: '/enquiries', user: { ...ENQUIRY_BDE, permissions: [...ENQUIRY_BDE.permissions, 'accounts.view_own_booking_links'] } });
  assert.match(text(), /Links are unavailable\./);
  await click(button('Try again'));
  assert.equal(n, 2);
  assert.ok(busy(button('Try again')), 'it stayed clickable with nothing to show before');
  await click(button('Try again'));
  assert.equal(n, 2, 'a second click sends nothing');
  await again.release({ links: [{ booking_type: 'DEMO', label: 'Demo class', url: 'https://eduportplus.com/demo?ref=b1' }] });
  assert.doesNotMatch(text(), /Links are unavailable\./);
  assert.equal(Boolean(button('Try again')), false);
});

// ---------------------------------------------------------------------- run
let failures = 0;
for (const { name, fn } of tests) {
  visibility = 'visible';
  try { await fn(); console.log(`PASS ${name}`); }
  catch (err) { failures++; console.log(`FAIL ${name}: ${err.stack}`); }
  finally {
    if (current) await current.unmount();
    current = null;
    clock.timers.clear();
    await settle();
  }
}
console.error = quiet;
console.log(`${tests.length - failures}/${tests.length} data freshness tests passed.`);
window.close(); process.exit(failures ? 1 : 0);
