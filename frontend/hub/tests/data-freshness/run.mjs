// What the Hub reads again on its own, on a clock these tests move by hand:
// the BDE's Follow-ups and dashboard every minute while their tab is shown and
// on coming back to it, never while it is hidden; a booking's communication
// every five seconds while its plan is PENDING (six times at most) and once
// about 20 seconds after a change in its workspace; and Sessions on request
// (Refresh) and on coming back to the tab -- each refresh once, however many
// events bring it, and nothing left running after the page goes. The pages
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

const { mount, act, BDE_DASHBOARD_URL, BDE_FOLLOW_UPS_URL, bookingCommunicationUrl } = await import(pathToFileURL(bundle).href);

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
  actions: { record_outcome: true, request_confirmation: false, record_answer: false } };
const followUpsPage = (rows) => ({ results: rows, count: rows.length, page: 1, page_size: 25,
  summary: { total: rows.length, today: rows.length, upcoming: 0 } });
const CALL_OUTCOME = `${COMMS('b-dona')}call-outcome/`;

const outcomeDialog = async (later, extra = {}) => {
  serve({
    [`GET ${BDE_FOLLOW_UPS_URL}`]: () => followUpsPage(gets(BDE_FOLLOW_UPS_URL) <= 1 ? [PRE_CALL] : later),
    ...extra,
  });
  await open('page', { path: '/follow-ups', user: FOLLOW_UP_BDE });
  await click(button('Record outcome'));
  assert.ok(topDialog(), 'the outcome dialog is open');
  await click(radio('No answer'));
  assert.ok(radio('No answer').checked, 'an outcome picked');
};

test('P3 fix: the minute refresh that empties Follow-ups keeps the open outcome dialog and what was picked', async () => {
  await outcomeDialog([]);
  await advance(MINUTE);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2, 'the minute refresh ran and found nothing left');
  assert.ok(topDialog(), 'the dialog is still open');
  assert.ok(radio('No answer').checked, 'with the outcome still picked');
  assert.ok(!button('Record outcome', topDialog()).disabled, 'and still ready to record');
  await click(button('Cancel', topDialog()) ?? button('Close', topDialog()));
  await settle();
  assert.match(clean(document.body.textContent), /You're all caught up/, 'the empty state, once it closes');
});

test('P3 fix: recording on a window that closed meanwhile shows the API refusal in the dialog', async () => {
  await outcomeDialog([], {
    [`POST ${CALL_OUTCOME}`]: () => refused(409, { error: 'CALL_CLOSED', message: 'The call window has closed: the class has started.' }),
  });
  await advance(MINUTE);
  await click(button('Record outcome', topDialog()));
  assert.equal(calls('POST', CALL_OUTCOME).length, 1, 'sent to the API, which decides');
  assert.deepEqual(calls('POST', CALL_OUTCOME)[0].data, { outcome: 'NO_ANSWER' });
  assert.ok(topDialog(), 'the dialog stays');
  assert.match(clean(topDialog().textContent), /The call window has closed: the class has started\./, 'with the API message');
});

test('P3 fix: while its row is still listed the dialog is untouched by the refresh', async () => {
  await outcomeDialog([PRE_CALL]);
  await advance(MINUTE);
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 2);
  assert.ok(topDialog() && radio('No answer').checked);
});

// ============================================ Phase 3 -- P7: focus refresh where staff keep pages open
const GAP = 30_000;
const text = () => clean(document.body.textContent);
const listOf = (results) => ({ results, count: results.length, page: 1, page_size: 25 });
const LEADS_ADMIN = { id: 'admin', role: 'ADMIN', full_name: 'Admin One', email: 'admin@hub.test',
  permissions: ['accounts.view_all_leads', 'accounts.assign_lead_owner', 'accounts.add_lead', 'accounts.view_all_bookings'] };
const ENQUIRY_BDE = { id: 'bde', role: 'BDE', full_name: 'Bde One', email: 'bde@hub.test',
  permissions: ['accounts.view_own_enquiries', 'accounts.add_enquiry', 'accounts.cancel_booking'] };
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
test('L2: a 409 recording the call stays in the dialog; closing it reads the follow-ups again', async () => {
  await outcomeDialog([PRE_CALL], {
    [`POST ${CALL_OUTCOME}`]: () => refused(409, { error: 'CALL_CLOSED', message: 'The call window has closed.' }),
  });
  assert.equal(gets(BDE_FOLLOW_UPS_URL), 1);
  await click(button('Record outcome', topDialog()));
  assert.match(clean(topDialog().textContent), /The call window has closed\./);
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
