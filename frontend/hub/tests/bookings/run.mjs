// Booking page tests: the real Bookings page (src/pages/BookingsPage.jsx) in
// jsdom, its API answered per test by api-stub.js, driven as an administrator
// would -- the Demo and Diagnostic tabs (each type its own list and URLs),
// filters, paging, the detail sheet, and assigning, reassigning and
// unassigning a tutor, including the API's refusals -- and the tutor's My
// Bookings page (src/pages/TutorBookingsPage.jsx), read-only, showing the
// child and the slot and never the parent, the BDE or the assignment.
//
//   npm run test:bookings
//
// Which callers the Hub routes to each page is the access tests' job
// (tests/access, paths /bookings and /my-bookings); the role gate itself
// (lib/access canOpenPage) is checked here too.
import assert from 'node:assert/strict';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';
import { JSDOM, VirtualConsole } from 'jsdom';

const here = path.dirname(fileURLToPath(import.meta.url));
const hub = path.resolve(here, '../..');
const src = path.join(hub, 'src');

// ------------------------------------------------------------------ bundle
const bundle = path.join(tmpdir(), `hub-bookings-${process.pid}.mjs`);
// The plain helpers some tests check on their own (libs.js), bundled the same way.
const libsBundle = path.join(tmpdir(), `hub-bookings-libs-${process.pid}.mjs`);
const build = (entry, outfile) => esbuild.build({
  entryPoints: [path.join(here, entry)],
  outfile,
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
      build.onResolve({ filter: /lib\/api$/ }, (args) => (args.importer.startsWith(src) ? { path: path.join(here, 'api-stub.js') } : undefined));
      build.onResolve({ filter: /^@\// }, (args) => build.resolve(`./${args.path.slice(2)}`, { resolveDir: src, kind: args.kind }));
    },
  }],
});
await build('harness.jsx', bundle);
await build('libs.js', libsBundle);

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
  'cancelAnimationFrame', 'localStorage', 'sessionStorage', 'MutationObserver', 'DOMRect']) {
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

const { mount, act, canOpenPage, homePage, ACTION_LABELS, actionLabel, describeActivity, meetLinkProblem, planMemberSave } =
  await import(pathToFileURL(bundle).href);
const { bdeBookingParams, classDateSpan, indianToday, readBdeBookingFilters, rangeLabel, enquiryTimezoneUrl, leadTimezoneUrl,
  TIMEZONE_OPTIONS, listedTimezone, savedTimezoneLabel, showsStudentTime, studentTime, studentTimeState,
  studentTimezoneLabel } = await import(pathToFileURL(libsBundle).href);

// ------------------------------------------------------------------ helpers
const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
const bodyText = () => clean(document.body.textContent);

async function settle(rounds = 8) {
  for (let i = 0; i < rounds; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

async function fire(element, event) {
  await act(async () => {
    element.dispatchEvent(event);
  });
  await settle();
}

const click = (element) => fire(element, new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
const mouseDown = (element) => fire(element, new window.MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
const keyDown = (element, key) => fire(element, new window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));

async function typeInto(input, value) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
}

const submit = (form) => fire(form, new window.Event('submit', { bubbles: true, cancelable: true }));

function button(label, root = document.body) {
  return [...root.querySelectorAll('button')].find(
    (element) => clean(element.textContent) === label || element.getAttribute('aria-label') === label
  );
}

/** The topmost open dialog (a tutor or confirm dialog over the sheet). */
const topDialog = () => [...document.querySelectorAll('[role="dialog"]')].at(-1);

/** Pick `option` from the Radix Select labelled `label`, as the keyboard would open it. */
async function choose(label, option) {
  const trigger = document.querySelector(`[aria-label="${label}"]`);
  assert.ok(trigger, `no select labelled ${label}`);
  trigger.focus();
  await keyDown(trigger, 'Enter');
  const item = [...document.querySelectorAll('[role="option"]')].find((element) => clean(element.textContent) === option);
  assert.ok(item, `no option ${option} in ${label}`);
  await click(item);
}

const rows = () => [...document.querySelectorAll('tbody tr')];
const tab = (name) => [...document.querySelectorAll('[role="tab"]')].find((element) => clean(element.textContent) === name);

/** Each tutor in the dialog as [name, its badges, the reason it is unavailable or null]. */
function tutorOptions(dialog) {
  return [...dialog.querySelectorAll('label')].map((label) => {
    const reason = [...label.querySelectorAll('span')].find((span) => /^Teaching /.test(clean(span.textContent)));
    return [
      clean(label.querySelector('.font-medium').textContent),
      [...label.querySelectorAll('[data-slot="badge"]')].map((badge) => clean(badge.textContent)).join(' '),
      reason ? clean(reason.textContent) : null,
    ];
  });
}

// Every page a test mounts, unmounted (once) after it.
const mounted = [];
async function open(path, user) {
  const page = await mount(path, user);
  let gone = false;
  const unmount = page.unmount;
  page.unmount = async () => {
    if (gone) return;
    gone = true;
    await unmount();
  };
  mounted.push(page);
  return page;
}

// ------------------------------------------------------------------ the API
const ok = (data) => Promise.resolve({ status: 200, data });
const fail = (status, data) => Promise.reject(Object.assign(new Error(`HTTP ${status}`), { response: { status, data } }));

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

/** Answers keyed "METHOD url"; a value is the body, a function is called with the request. */
function serve(table) {
  globalThis.__bookingsApi.handler = (entry) => {
    const answer = table[`${entry.method} ${entry.url}`];
    if (answer === undefined) return fail(404, { error: 'NOT_FOUND', message: `No answer for ${entry.method} ${entry.url}` });
    return typeof answer === 'function' ? answer(entry) : ok(answer);
  };
}

const calls = (method, url) => globalThis.__bookingsApi.calls.filter((entry) => entry.method === method && entry.url === url);

// ------------------------------------------------------------------ fixtures
// Each type is its own list, and a booking is named by its type and its id.
const LIST = '/api/bookings/demo/';
const DIAGNOSTIC_LIST = '/api/bookings/diagnostic/';
const at = (booking, rest = '') => `/api/bookings/${booking.booking_type.toLowerCase()}/${booking.id}/${rest}`;
const ADMIN = { id: 'admin', role: 'ADMIN', permissions: ['accounts.assign_booking_tutor', 'accounts.view_all_bookings'] };
const VIEWER = { id: 'viewer', role: 'ADMIN', permissions: ['accounts.view_all_bookings'] };

const slot = (id, booking_type, date, time) => ({ id, booking_type, date, time, starts_at: `${date}T14:00:00+00:00`,
  ends_at: `${date}T15:00:00+00:00`, started: false, ended: false });
// Where each booking stands as a class is the API's own activity_state (backend bookings.lifecycle), never the slot's clock.
const RIYA = { id: 'b-riya', booking_type: 'DEMO', status: 'BOOKED', slot: slot('s-1', 'DEMO', '2026-10-31', '19:30'),
  student_name: 'Riya', grade: 'Class 8', parent_name: 'Asha Nair', phone: '+971 501234567', tutor: null, bde: null,
  booked_at: '2026-10-28T09:00:00+00:00', activity_state: 'UPCOMING', started_at: null };
const ALI = { id: 'b-ali', booking_type: 'DIAGNOSTIC', status: 'BOOKED', slot: slot('s-2', 'DIAGNOSTIC', '2026-11-01', '10:00'),
  student_name: 'Ali', grade: 'Class 9', parent_name: 'Sara Khan', phone: '+91 9800000002',
  tutor: { id: 't-a', full_name: 'Tutor A' }, bde: { id: 'bde-1', full_name: 'Bde One' }, booked_at: '2026-10-28T10:00:00+00:00',
  activity_state: 'UPCOMING', started_at: null };
const ARUN = { id: 'b-arun', booking_type: 'DEMO', status: 'BOOKED', slot: slot('s-3', 'DEMO', '2026-11-01', '19:30'),
  student_name: 'Arun', grade: 'Class 7', parent_name: 'Meena Raj', phone: '+971 509999999',
  tutor: { id: 't-b', full_name: 'Tutor B' }, bde: null, booked_at: '2026-10-28T11:00:00+00:00', activity_state: 'UPCOMING',
  started_at: null };

const list = (results, count = results.length, page = 1) => ({ results, count, page, page_size: 25, timezone: 'Asia/Kolkata' });

const detail = (row, extra = {}) => ({
  ...row, timezone: 'Asia/Kolkata', seat: 1,
  lead: { id: `lead-${row.id}`, phone_dial_code: '+971', phone_number: '501234567', school_name: 'Delhi Private School',
    syllabus: 'CBSE', country: 'United Arab Emirates', source: 'BOOKING_PAGE', owner_bde: null },
  referral_status: row.bde ? 'ATTRIBUTED' : 'NO_REF',
  tutor_assigned_at: row.tutor ? '2026-10-29T06:00:00+00:00' : null,
  tutor_assigned_by: row.tutor ? { id: 'admin', full_name: 'Admin One' } : null,
  tutor_changeable: true, tutor_change_refusal: null, cancelled_at: null, cancelled_by: null, cancel_reason: '',
  ...extra,
});

const tutors = (booking, current = null, extra = {}) => ({
  booking_id: booking.id, slot: booking.slot, timezone: 'Asia/Kolkata', tutor_changeable: true, tutor_change_refusal: null,
  tutors: [
    { id: 't-a', full_name: 'Tutor A', email: 'a@hub.test', status: 'UNAVAILABLE', current: current === 't-a',
      reason: { code: 'CLASS_CONFLICT', message: 'Teaching a class from 7:00 PM to 8:00 PM IST on Sat 31 Oct 2026.',
        session_id: 'session-1', starts_at: '2026-10-31T13:30:00+00:00', ends_at: '2026-10-31T14:30:00+00:00' } },
    { id: 't-b', full_name: 'Tutor B', email: 'b@hub.test', status: 'AVAILABLE', reason: null, current: current === 't-b' },
    { id: 't-c', full_name: 'Tutor C', email: 'c@hub.test', status: 'AVAILABLE', reason: null, current: current === 't-c' },
  ],
  ...extra,
});

// ------------------------------------------------------------------ the tests
const tests = [];
const test = (name, fn) => tests.push({ name, fn });

test('loading, then the Demo bookings with assigned and unassigned ones told apart; Diagnostic is its own page', async () => {
  const answer = deferred();
  serve({ [`GET ${LIST}`]: () => answer.promise, [`GET ${DIAGNOSTIC_LIST}`]: list([ALI]) });
  const page = await open('/bookings/demo', ADMIN);
  assert.ok(document.querySelector('[data-slot="skeleton"]'), 'a loading skeleton while the list loads');
  assert.deepEqual(calls('GET', LIST)[0].params, { page: 1, page_size: 25, when: 'upcoming' });

  answer.resolve({ status: 200, data: list([RIYA, ARUN]) });
  await settle();
  assert.ok(!document.querySelector('[data-slot="skeleton"]'), 'the skeleton is gone');
  assert.deepEqual([...document.querySelectorAll('[role="tab"]')].map((element) => [clean(element.textContent),
    element.getAttribute('aria-selected')]), [['Bookings', 'true'], ['Re-Demo requests', 'false']],
  "Demo's bookings, and its Re-Demo requests");
  assert.deepEqual([...document.querySelectorAll('th')].map((th) => clean(th.textContent)),
    ['Date & Time', 'Student', 'Parent', 'Tutor', 'Status', 'Report', 'Actions'], 'one type per page, so no type column; a report column (P8)');
  const [riya, arun] = rows();
  assert.match(clean(riya.textContent), /Sat, 31 Oct.*7:30 PM.*Riya.*Class 8.*Asha Nair.*Unassigned.*Upcoming/);
  assert.match(clean(arun.textContent), /Arun.*Tutor B.*Upcoming/);
  assert.ok(!arun.textContent.includes('Unassigned'));
  assert.ok(button('Assign', riya) && !button('Change', riya), 'an unassigned booking offers Assign');
  assert.ok(button('Change', arun) && !button('Assign', arun), 'an assigned booking offers Change');
  assert.match(bodyText(), /Showing 1–2 of 2/);

  await page.unmount();
  const diagnostic = await open('/bookings/diagnostic', ADMIN);
  assert.deepEqual(calls('GET', DIAGNOSTIC_LIST).map((entry) => entry.params), [{ page: 1, page_size: 25, when: 'upcoming' }]);
  assert.equal(diagnostic.location().pathname, '/bookings/diagnostic');
  assert.equal(document.querySelectorAll('[role="tab"]').length, 0, 'only Demo has Re-Demo requests');
  assert.match(bodyText(), /^Diagnostic Bookings/);
  assert.deepEqual(rows().map((row) => clean(row.querySelector('td:nth-child(2) p').textContent)), ['Ali']);
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url === '/api/bookings/'), 'no combined list is asked for');
});

test("the former single page's links land on their type's page, every other parameter kept", async () => {
  serve({ [`GET ${LIST}`]: list([RIYA]), [`GET ${DIAGNOSTIC_LIST}`]: list([ALI]), [`GET ${at(ALI)}`]: detail(ALI),
    'GET /api/bookings/redemos/': list([]) });
  for (const [link, pathname, query] of [
    ['/bookings', '/bookings/demo', {}],
    [`/bookings?booking=${RIYA.id}`, '/bookings/demo', { booking: RIYA.id }],
    [`/bookings?type=DIAGNOSTIC&when=all&booking=${ALI.id}`, '/bookings/diagnostic', { when: 'all', booking: ALI.id }],
    ['/bookings?type=REDEMO&redemo=rd-9', '/bookings/demo', { tab: 'redemo', redemo: 'rd-9' }],
    ['/bookings?type=TRIAL', '/bookings/demo', {}],
  ]) {
    const page = await open(link, ADMIN);
    assert.equal(page.location().pathname, pathname, link);
    assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), query, link);
    await page.unmount();
  }
});

test('Completed and Rescheduled bookings say so, and offer no tutor change', async () => {
  const done = { ...ARUN, status: 'COMPLETED', slot: { ...ARUN.slot, started: true, ended: true } };
  const moved = { ...RIYA, status: 'RESCHEDULED' };
  serve({ [`GET ${LIST}`]: list([done, moved]) });
  await open('/bookings?when=all', ADMIN);
  const [completed, rescheduled] = rows();
  assert.match(clean(completed.textContent), /Arun.*Tutor B.*Completed/);
  assert.match(clean(rescheduled.textContent), /Riya.*Rescheduled/);
  assert.ok(!rescheduled.textContent.includes('Unassigned'), 'a moved booking needs no tutor');
  for (const row of [completed, rescheduled]) {
    assert.ok(!button('Assign', row) && !button('Change', row));
  }
});

test('an error, then Try again', async () => {
  let attempts = 0;
  serve({ [`GET ${LIST}`]: () => (attempts++ === 0 ? fail(500, { message: 'The bookings could not be read.' }) : ok(list([RIYA]))) });
  await open('/bookings', ADMIN);
  assert.match(bodyText(), /The bookings could not be read\./);
  assert.equal(rows().length, 0);
  await click(button('Try again'));
  assert.equal(rows().length, 1);
  assert.equal(calls('GET', LIST).length, 2);
});

test('empty: no upcoming bookings, or none matching the filters', async () => {
  serve({ [`GET ${LIST}`]: list([]), [`GET ${DIAGNOSTIC_LIST}`]: list([]) });
  let page = await open('/bookings/demo', ADMIN);
  assert.equal(rows().length, 0);
  assert.match(bodyText(), /No upcoming demo classes/);
  assert.ok(!bodyText().includes('Showing'), 'no paging for an empty list');
  await click(button('Show all schedules'));
  assert.equal(new URLSearchParams(page.location().search).get('when'), 'all');
  assert.equal('when' in calls('GET', LIST).at(-1).params, false);
  await page.unmount();
  page = await open('/bookings/diagnostic', ADMIN);
  assert.match(bodyText(), /No upcoming diagnostic tests/);
  await page.unmount();
  globalThis.__bookingsApi.calls = [];
  page = await open('/bookings/demo?status=CANCELLED', ADMIN);
  assert.match(bodyText(), /No demo classes match these filters/);
  assert.equal(calls('GET', LIST)[0].params.status, 'CANCELLED');
  await click(button('Clear all filters'));
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), {});
});

test('paging', async () => {
  serve({ [`GET ${LIST}`]: (entry) => ok(list([RIYA], 60, entry.params.page)) });
  const page = await open('/bookings', ADMIN);
  assert.match(bodyText(), /Showing 1–25 of 60.*Page 1 of 3/);
  assert.ok(button('Previous').disabled);
  await click(button('Next'));
  assert.equal(calls('GET', LIST).at(-1).params.page, 2);
  assert.match(bodyText(), /Showing 26–50 of 60.*Page 2 of 3/);
  assert.equal(new URLSearchParams(page.location().search).get('page'), '2');
  await click(button('Next'));
  await click(button('Previous'));
  assert.deepEqual(calls('GET', LIST).map((entry) => entry.params.page), [1, 2, 3, 2]);
});

test('search and filters reach the API and the URL, and start again at page 1', async () => {
  serve({ [`GET ${DIAGNOSTIC_LIST}`]: list([ALI]) });
  const page = await open('/bookings/diagnostic?page=2&from=2026-10-30&to=2026-11-02', ADMIN);
  assert.deepEqual(calls('GET', DIAGNOSTIC_LIST).at(-1).params,
    { page: 2, page_size: 25, from: '2026-10-30', to: '2026-11-02', when: 'upcoming' });
  assert.match(bodyText(), /Classes on 30 Oct 2026 – 2 Nov 2026 \(IST\)/, 'a link from before the presets is a Custom range');

  await typeInto(document.querySelector('[aria-label="Search bookings"]'), 'riya');
  await submit(document.querySelector('[aria-label="Search bookings"]').closest('form'));
  assert.deepEqual(calls('GET', DIAGNOSTIC_LIST).at(-1).params,
    { page: 1, page_size: 25, q: 'riya', from: '2026-10-30', to: '2026-11-02', when: 'upcoming' });
  await choose('Filter by booking status', 'Cancelled');
  assert.equal(calls('GET', DIAGNOSTIC_LIST).at(-1).params.status, 'CANCELLED');
  await choose('Filter by booking status', 'Completed');
  assert.equal(calls('GET', DIAGNOSTIC_LIST).at(-1).params.status, 'COMPLETED');
  await choose('Filter by tutor assignment', 'Needs a tutor');
  assert.equal(calls('GET', DIAGNOSTIC_LIST).at(-1).params.assigned, 'false');
  await choose('Filter by schedule', 'All Schedules');
  const last = calls('GET', DIAGNOSTIC_LIST).at(-1).params;
  assert.equal('when' in last, false, '"All Schedules" sends no when filter');
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)),
    { q: 'riya', from: '2026-10-30', to: '2026-11-02', status: 'COMPLETED', assigned: 'false', when: 'all' });

  // A class date preset: Indian dates, the Custom range gone.
  await click(button('Today'));
  const today = indianToday();
  assert.deepEqual(calls('GET', DIAGNOSTIC_LIST).at(-1).params,
    { page: 1, page_size: 25, q: 'riya', status: 'COMPLETED', assigned: 'false', from: today, to: today });
  assert.equal(new URLSearchParams(page.location().search).get('dates'), 'today');

  await click(button('Clear all filters'));
  assert.deepEqual(calls('GET', DIAGNOSTIC_LIST).at(-1).params, { page: 1, page_size: 25, when: 'upcoming' });
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), {});
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => !entry.params || !('type' in entry.params)),
    'no type parameter is ever sent');
});

test('an unknown filter value in the URL is dropped, never sent', async () => {
  serve({ [`GET ${LIST}`]: list([RIYA]) });
  await open('/bookings?type=TRIAL&status=done&assigned=maybe&when=tomorrow&from=31-10-2026', ADMIN);
  assert.deepEqual(calls('GET', LIST)[0].params, { page: 1, page_size: 25, when: 'upcoming' }, 'an unknown type shows Demo');
});

test('View opens the booking in full in the side sheet, under its own type', async () => {
  serve({ [`GET ${DIAGNOSTIC_LIST}`]: list([ALI]), [`GET ${at(ALI)}`]: detail(ALI), [`GET ${LIST}`]: list([RIYA]) });
  const page = await open('/bookings/diagnostic', ADMIN);
  await click(button('View', rows()[0]));
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { booking: ALI.id });
  assert.equal(calls('GET', '/api/bookings/diagnostic/b-ali/').length, 1);
  const sheet = topDialog();
  const text = clean(sheet.textContent);
  for (const shown of ['Ali', 'Tutor A', 'Assigned by', 'Admin One', 'Delhi Private School', 'Sara Khan', '+91 9800000002',
    "Through a BDE's link", 'Bde One', 'Diagnostic test']) {
    assert.ok(text.includes(shown), `the sheet shows ${shown}`);
  }
  assert.ok(button('Change tutor', sheet) && button('Unassign', sheet));
  assert.equal(calls('GET', LIST).length, 0, "the Demo list is another page's");
});

test('a booking opened under the other type is not found', async () => {
  serve({ [`GET ${LIST}`]: list([RIYA]) });
  await open(`/bookings?booking=${ALI.id}`, ADMIN);
  assert.equal(calls('GET', `/api/bookings/demo/${ALI.id}/`).length, 1, 'asked for as a Demo booking, the page it was opened on');
  assert.match(clean(topDialog().textContent), /Booking not found/);
});

// The Booking Slots page (src/pages/BookingSlotsPage.jsx): each booked seat links to its booking.
const SLOT_DAY = '/api/booking-slots/demo/2026-11-03/';
const SLOT_STATUSES = ['Available', 'Filling Fast', 'Only a Few Left', 'Fully Booked'];
const daySlot = (time, end_time, booked, bookings) => ({ time, end_time, scheduled: true, booked, capacity: 3,
  status: SLOT_STATUSES[booked], open_status: SLOT_STATUSES[booked], closed: false, closed_at: null, closed_by: null,
  close_reason: '', bookings });
const slotDay = (slots) => ({ booking_type: 'DEMO', date: '2026-11-03', timezone: 'Asia/Kolkata', slot_minutes: 60, capacity: 3,
  parent_state: 'open', window: { first: '2026-11-02', last: '2026-11-08' }, editable: true, slots });
const seat = (booking, number, status = 'BOOKED') => ({ id: booking.id, booking_type: booking.booking_type, seat: number, status,
  student_name: booking.student_name });

test('Booking slots: each booked seat links to its booking, which the Bookings page opens in its sheet', async () => {
  serve({
    [`GET ${SLOT_DAY}`]: slotDay([daySlot('10:00', '11:00', 0, []),
      daySlot('19:30', '20:30', 2, [seat(ARUN, 1, 'COMPLETED'), seat(RIYA, 2)])]),
    [`GET ${LIST}`]: list([RIYA]), [`GET ${at(RIYA)}`]: detail(RIYA),
  });
  const page = await open('/booking-slots?type=demo&date=2026-11-03', ADMIN);
  const [morning, evening] = rows();
  assert.equal(morning.querySelectorAll('a').length, 0, 'an empty slot links to nothing');
  assert.match(clean(morning.textContent), /0 \/ 3/);
  const links = [...evening.querySelectorAll('a')];
  assert.deepEqual(links.map((link) => [clean(link.textContent), link.getAttribute('aria-label'), link.getAttribute('href')]), [
    ['Seat 1: Arun (Completed)', 'Seat 1: Arun (Completed), 7:30 PM – 8:30 PM: open the booking', '/bookings/demo?booking=b-arun'],
    ['Seat 2: Riya', 'Seat 2: Riya, 7:30 PM – 8:30 PM: open the booking', '/bookings/demo?booking=b-riya'],
  ], 'one link per seat, in seat order, named by the child and the slot');
  const bookingsCell = evening.querySelector('td:nth-child(2)');
  assert.ok(clean(bookingsCell.textContent).startsWith('2 / 3') && bookingsCell.querySelectorAll('a').length === 2,
    'the seats are listed under the count, in the Bookings column');

  await click(links[1]);
  assert.equal(page.location().pathname, '/bookings/demo');
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { booking: RIYA.id });
  assert.equal(calls('GET', at(RIYA)).length, 1, 'the booking is read under its own type');
  assert.ok(clean(topDialog().textContent).includes('Asha Nair'), 'the sheet shows the booking in full');
});

test('Booking slots: for a slot manager who cannot see every booking, the API names nobody and the page shows counts only', async () => {
  serve({ [`GET ${SLOT_DAY}`]: slotDay([daySlot('10:00', '11:00', 0, null), daySlot('19:30', '20:30', 2, null)]) });
  await open('/booking-slots?type=demo&date=2026-11-03', { id: 'slots', role: 'ADMIN', permissions: ['accounts.manage_booking_slots'] });
  assert.deepEqual(rows().map((row) => clean(row.querySelector('td:nth-child(2)').textContent)), ['0 / 3', '2 / 3']);
  assert.equal(document.querySelectorAll('tbody a').length, 0);
});

test('the tutor list: every active tutor, Available or Unavailable with the reason; an unavailable one cannot be picked', async () => {
  serve({ [`GET ${LIST}`]: list([RIYA]), [`GET ${at(RIYA, 'tutors/')}`]: tutors(RIYA) });
  await open('/bookings', ADMIN);
  await click(button('Assign', rows()[0]));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /Assign tutor.*Riya · Demo class · Sat, 31 Oct · 7:30 PM IST/);
  assert.deepEqual(tutorOptions(dialog), [
    ['Tutor A', 'Unavailable', 'Teaching a class from 7:00 PM to 8:00 PM IST on Sat 31 Oct 2026.'],
    ['Tutor B', 'Available', null],
    ['Tutor C', 'Available', null],
  ]);
  const [busy, free] = [...dialog.querySelectorAll('input[type="radio"]')];
  assert.ok(busy.disabled, 'an unavailable tutor cannot be chosen');
  assert.ok(button('Assign', dialog).disabled, 'nothing chosen yet');
  // A browser never activates a disabled radio; jsdom still flips its DOM flag
  // for a synthetic click, so what counts is that the page's choice is unchanged.
  await click(busy);
  assert.ok(button('Assign', dialog).disabled, 'clicking an unavailable tutor chooses nothing');
  await click(free);
  assert.ok(free.checked && !button('Assign', dialog).disabled);
  assert.equal(calls('PUT', at(RIYA, 'tutor/')).length, 0);
});

test('assigning a tutor: PUT, then the list and the open booking are read again', async () => {
  const assigned = detail({ ...RIYA, tutor: { id: 't-b', full_name: 'Tutor B' } });
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA),
    [`GET ${at(RIYA, 'tutors/')}`]: tutors(RIYA),
    [`PUT ${at(RIYA, 'tutor/')}`]: () => ok({ ...assigned, changed: true }),
  });
  await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  await click(button('Assign tutor', topDialog()));
  const dialog = topDialog();
  await click(dialog.querySelectorAll('input[type="radio"]')[1]);
  await click(button('Assign', dialog));
  assert.deepEqual(calls('PUT', at(RIYA, 'tutor/')).map((entry) => entry.data), [{ tutor_id: 't-b' }]);
  assert.match(bodyText(), /Tutor B now teaches Riya's demo class\./);
  assert.equal(calls('GET', LIST).length, 2, 'the list is read again');
  assert.equal(calls('GET', at(RIYA)).length, 2, 'the open booking is read again');
  assert.ok(!bodyText().includes('Assign tutor Riya'), 'the dialog closed');
});

test('reassigning: the current tutor is marked and cannot be "reassigned" to themselves', async () => {
  serve({
    [`GET ${DIAGNOSTIC_LIST}`]: list([ALI]),
    [`GET ${at(ALI, 'tutors/')}`]: tutors(ALI, 't-c'),
    [`PUT ${at(ALI, 'tutor/')}`]: () => ok({ ...detail({ ...ALI, tutor: { id: 't-b', full_name: 'Tutor B' } }), changed: true }),
  });
  await open('/bookings?type=DIAGNOSTIC', ADMIN);
  await click(button('Change', rows()[0]));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /^Change tutor/);
  assert.deepEqual(tutorOptions(dialog)[2], ['Tutor C', 'Current Available', null]);
  const [, other, current] = [...dialog.querySelectorAll('input[type="radio"]')];
  await click(current);
  assert.ok(button('Reassign', dialog).disabled, 'the current tutor again changes nothing');
  await click(other);
  await click(button('Reassign', dialog));
  assert.deepEqual(calls('PUT', at(ALI, 'tutor/')).map((entry) => entry.data), [{ tutor_id: 't-b' }]);
  assert.match(bodyText(), /Tutor B now teaches Ali's diagnostic test\./);
});

test('unassigning: confirmed first, then DELETE and a fresh list', async () => {
  const unassigned = detail({ ...ALI, tutor: null });
  serve({
    [`GET ${DIAGNOSTIC_LIST}`]: list([ALI]),
    [`GET ${at(ALI)}`]: detail(ALI),
    [`DELETE ${at(ALI, 'tutor/')}`]: () => ok({ ...unassigned, changed: true }),
  });
  await open(`/bookings?type=DIAGNOSTIC&booking=${ALI.id}`, ADMIN);
  await click(button('Unassign', topDialog()));
  const confirm = topDialog();
  assert.match(clean(confirm.textContent), /Tutor A will no longer teach Ali's booking/);
  assert.equal(calls('DELETE', at(ALI, 'tutor/')).length, 0, 'nothing is sent before confirming');
  await click(button('Unassign', confirm));
  assert.equal(calls('DELETE', at(ALI, 'tutor/')).length, 1);
  assert.match(bodyText(), /Unassigned the tutor from Ali's booking\./);
  assert.equal(calls('GET', DIAGNOSTIC_LIST).length, 2);
});

test('a conflict the API finds at assignment time is shown, and the tutor list read again', async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA, 'tutors/')}`]: tutors(RIYA),
    [`PUT ${at(RIYA, 'tutor/')}`]: () => fail(409, {
      error: 'TUTOR_UNAVAILABLE', message: 'This tutor already has a class or another booking at this time.',
      conflict: { code: 'BOOKING_CONFLICT', message: 'Teaching another Demo or Diagnostic booking from 7:30 PM to 8:30 PM IST on Sat 31 Oct 2026.' },
    }),
  });
  await open('/bookings', ADMIN);
  await click(button('Assign', rows()[0]));
  let dialog = topDialog();
  await click(dialog.querySelectorAll('input[type="radio"]')[2]);
  await click(button('Assign', dialog));
  dialog = topDialog();
  assert.match(clean(dialog.textContent),
    /This tutor already has a class or another booking at this time\. Teaching another Demo or Diagnostic booking from 7:30 PM/);
  assert.equal(calls('GET', at(RIYA, 'tutors/')).length, 2, 'what is free is read again');
  assert.ok(button('Assign', dialog).disabled, 'the choice is cleared');
  assert.ok(!bodyText().includes('now teaches'));
});

test("a booking whose tutor can no longer change says why, and offers no assignment", async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA, 'tutors/')}`]: tutors(RIYA, null, {
      tutor_changeable: false,
      tutor_change_refusal: { code: 'BOOKING_STARTED', message: 'This booking has already started, so its tutor cannot be changed.' },
    }),
  });
  await open('/bookings', ADMIN);
  await click(button('Assign', rows()[0]));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /This booking has already started, so its tutor cannot be changed\./);
  assert.equal(dialog.querySelectorAll('input[type="radio"]').length, 0);
  assert.ok(button('Assign', dialog).disabled);
});

test('without accounts.assign_booking_tutor the page is read-only', async () => {
  serve({ [`GET ${DIAGNOSTIC_LIST}`]: list([ALI]), [`GET ${at(ALI)}`]: detail(ALI) });
  await open(`/bookings?type=DIAGNOSTIC&booking=${ALI.id}`, VIEWER);
  for (const label of ['Assign', 'Change', 'Assign tutor', 'Change tutor', 'Unassign', 'Reschedule', 'Cancel booking']) {
    assert.ok(!button(label), `no ${label} button`);
  }
  assert.ok(clean(topDialog().textContent).includes('Tutor A'), 'the booking still shows its tutor');
});

// ------------------------------------------------------- booking operations (P3)
const CAN_ALL = { cancel: true, no_show: false, reschedule: true };
const MOVED = { ...RIYA, id: 'b-riya-2', slot: slot('s-9', 'DEMO', '2026-11-02', '19:30'), tutor: { id: 't-a', full_name: 'Tutor A' } };
const choice = (label, root = topDialog()) => [...root.querySelectorAll('label')].find((element) => clean(element.textContent).startsWith(label));
const radio = (label, root) => choice(label, root).querySelector('input[type="radio"]');

const optionSlot = (time, extra = {}) => ({
  time, starts_at: '', ends_at: '', status: 'Available', seats_left: 3, bookable: true, unavailable_reason: null,
  lead_conflict: null, tutor_free: true, tutor_reason: null, ...extra,
});
const OPTIONS = {
  booking_id: RIYA.id, booking_type: 'DEMO', timezone: 'Asia/Kolkata', slot: RIYA.slot,
  tutor: { id: 't-a', full_name: 'Tutor A' }, reschedulable: true, refusal: null,
  dates: [
    { date: '2026-10-31', slots: [
      optionSlot('10:00', { tutor_free: false,
        tutor_reason: { code: 'CLASS_CONFLICT', message: 'Teaching a class from 10:00 AM to 11:00 AM IST on Sat 31 Oct 2026.' } }),
      optionSlot('19:30', { bookable: false, unavailable_reason: 'CURRENT', seats_left: 2 }),
    ] },
    { date: '2026-11-02', slots: [
      optionSlot('10:00', { bookable: false, unavailable_reason: 'LEAD_TIME_CONFLICT',
        lead_conflict: { code: 'LEAD_TIME_CONFLICT', message: 'Already has a Diagnostic booking from 10:00 AM to 11:00 AM IST on Mon 2 Nov 2026.' } }),
      optionSlot('19:30', { seats_left: 1 }),
    ] },
  ],
};

test('Reschedule: open slots with seats and the tutor, why others are out of reach; the move opens the new booking', async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA, { actions: CAN_ALL }),
    [`GET ${at(RIYA, 'reschedule-options/')}`]: OPTIONS,
    [`POST ${at(RIYA, 'reschedule/')}`]: () => ok({ booking: detail(MOVED, { rescheduled_from: { id: RIYA.id, status: 'RESCHEDULED', slot: RIYA.slot } }),
      previous: { id: RIYA.id, status: 'RESCHEDULED' }, tutor: { carried_over: true, tutor: { id: 't-a', full_name: 'Tutor A' }, reason: null } }),
    [`GET ${at(MOVED)}`]: detail(MOVED, { rescheduled_from: { id: RIYA.id, status: 'RESCHEDULED', slot: RIYA.slot } }),
  });
  const page = await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  await click(button('Reschedule', topDialog()));
  let dialog = topDialog();
  assert.match(clean(dialog.textContent), /^Reschedule booking.*Riya · Demo class · now Sat, 31 Oct · 7:30 PM IST/);
  assert.deepEqual([...dialog.querySelectorAll('[aria-label="Dates"] button')].map((b) => clean(b.textContent)),
    ['Sat, 31 Oct(1)', 'Mon, 2 Nov(1)']);
  assert.match(clean(choice('10:00 AM').textContent), /3 seats left.*Tutor busy.*Teaching a class from 10:00 AM/);
  assert.ok(radio('7:30 PM').disabled && clean(choice('7:30 PM').textContent).includes('Its current slot'));
  await click(radio('10:00 AM'));
  assert.match(clean(dialog.textContent), /Tutor A isn't free then, so the moved booking will need a tutor\./);

  await click([...dialog.querySelectorAll('[aria-label="Dates"] button')][1]);
  dialog = topDialog();
  assert.ok(radio('10:00 AM').disabled);
  assert.match(clean(choice('10:00 AM').textContent), /Already has a Diagnostic booking/);
  assert.match(clean(choice('7:30 PM').textContent), /1 seat left.*Tutor free/);
  await click(radio('7:30 PM'));
  assert.ok(button('Move booking', dialog).disabled, 'a reason is needed');
  await click(radio('Parent asked to move'));
  await click(button('Move booking', dialog));
  assert.deepEqual(calls('POST', at(RIYA, 'reschedule/')).map((entry) => entry.data),
    [{ date: '2026-11-02', time: '19:30', reason: 'PARENT_REQUEST' }]);
  assert.match(bodyText(), /Moved Riya's demo class to Mon, 2 Nov · 7:30 PM IST\. Tutor A still teaches it\./);
  assert.equal(new URLSearchParams(page.location().search).get('booking'), MOVED.id);
  assert.ok(calls('GET', at(MOVED)).length >= 1, 'the new booking opens');
  assert.match(clean(topDialog().textContent), /Moved from.*Sat, 31 Oct · 7:30 PM IST/);
});

test('Reschedule: a refusal at move time is shown and the slots read again; a booking that cannot move says why', async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA, { actions: CAN_ALL }),
    [`GET ${at(RIYA, 'reschedule-options/')}`]: OPTIONS,
    [`POST ${at(RIYA, 'reschedule/')}`]: () => fail(409, { error: 'SLOT_FULL', message: 'This slot is fully booked. Please choose another time.' }),
  });
  await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  await click(button('Reschedule', topDialog()));
  await click(radio('10:00 AM'));
  await click(radio('Other'));
  await click(button('Move booking', topDialog()));
  assert.match(clean(topDialog().textContent), /This slot is fully booked\. Please choose another time\./);
  assert.equal(calls('GET', at(RIYA, 'reschedule-options/')).length, 2, 'the slots are read again');
  assert.ok(button('Move booking', topDialog()).disabled, 'the choice is cleared');

  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA, { actions: CAN_ALL }),
    [`GET ${at(RIYA, 'reschedule-options/')}`]: { ...OPTIONS, reschedulable: false,
      refusal: { code: 'BOOKING_STARTED', message: 'This booking has already started, so it can no longer be moved.' } },
  });
  await click(button('Cancel', topDialog()));
  await click(button('Reschedule', topDialog()));
  assert.match(clean(topDialog().textContent), /This booking has already started, so it can no longer be moved\./);
  assert.ok(button('Move booking', topDialog()).disabled);
});

test('Cancel: a reason from the list, No-show only once the scheduled time has passed; then a fresh list', async () => {
  const cancelled = detail(RIYA, { status: 'CANCELLED', cancel_reason: 'Parent asked to cancel', cancel_reason_code: 'PARENT_REQUEST',
    actions: { cancel: false, no_show: false, reschedule: false } });
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA, { actions: CAN_ALL }),
    [`POST ${at(RIYA, 'cancel/')}`]: () => ok({ ...cancelled, changed: true }),
  });
  await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  await click(button('Cancel booking', topDialog()));
  let dialog = topDialog();
  assert.match(clean(dialog.textContent), /^Cancel booking.*Riya · Demo class · Sat, 31 Oct · 7:30 PM IST.*Why is it cancelled\?/);
  assert.deepEqual([...dialog.querySelectorAll('label')].map((label) => clean(label.textContent)), [
    'No-showAvailable once the scheduled time has passed.', 'Parent asked to cancel', 'Duplicate booking', 'Booked by mistake', 'Other',
  ]);
  assert.ok(radio('No-show').disabled);
  assert.ok(button('Cancel booking', dialog).disabled, 'nothing chosen yet');
  await click(button('Keep booking', dialog));
  assert.equal(calls('POST', at(RIYA, 'cancel/')).length, 0, 'keeping it sends nothing');

  await click(button('Cancel booking', topDialog()));
  dialog = topDialog();
  await click(radio('Parent asked to cancel'));
  await click(button('Cancel booking', dialog));
  assert.deepEqual(calls('POST', at(RIYA, 'cancel/')).map((entry) => entry.data), [{ reason: 'PARENT_REQUEST' }]);
  assert.match(bodyText(), /Cancelled Riya's demo class \(Parent asked to cancel\)\./);
  assert.equal(calls('GET', LIST).length, 2, 'the list is read again');
});

test('Cancel: No-show once the scheduled time has passed, and a refusal shown as it comes', async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA, { actions: { cancel: true, no_show: true, reschedule: false } }),
    [`POST ${at(RIYA, 'cancel/')}`]: () => fail(409, { error: 'NO_SHOW_BEFORE_START',
      message: 'A booking can be marked No-show only once its scheduled time has passed.' }),
  });
  await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  assert.ok(!button('Reschedule', topDialog()), 'not offered when the API says no (a booking its tutor started)');
  await click(button('Cancel booking', topDialog()));
  assert.ok(!radio('No-show').disabled);
  await click(radio('No-show'));
  await click(button('Cancel booking', topDialog()));
  assert.deepEqual(calls('POST', at(RIYA, 'cancel/')).map((entry) => entry.data), [{ reason: 'NO_SHOW' }]);
  assert.match(clean(topDialog().textContent), /A booking can be marked No-show only once its scheduled time has passed\./);
});

test('History: the timeline on request, across the reschedule chain, with who and why', async () => {
  const history = {
    booking_id: MOVED.id, timezone: 'Asia/Kolkata',
    chain: [{ id: RIYA.id, status: 'RESCHEDULED', slot: RIYA.slot, current: false }, { id: MOVED.id, status: 'CANCELLED', slot: MOVED.slot, current: true }],
    events: [
      { id: 'e1', booking_id: RIYA.id, kind: 'CREATED', kind_label: 'Created', at: '2026-10-28T09:00:00+00:00', actor: null,
        details: { slot: RIYA.slot, seat: 1, via: 'public_booking', referral_status: 'NO_REF' } },
      { id: 'e2', booking_id: RIYA.id, kind: 'TUTOR_ASSIGNED', kind_label: 'Tutor assigned', at: '2026-10-28T10:00:00+00:00',
        actor: { id: 'admin', full_name: 'Admin One' }, details: { old_tutor: null, new_tutor: { id: 't-a', full_name: 'Tutor A' } } },
      { id: 'e3', booking_id: RIYA.id, kind: 'RESCHEDULED', kind_label: 'Rescheduled', at: '2026-10-29T10:00:00+00:00',
        actor: { id: 'admin', full_name: 'Admin One' }, details: { from_status: 'BOOKED', to_status: 'RESCHEDULED',
          reason: { code: 'PARENT_REQUEST', label: 'Parent asked to move' }, old_slot: RIYA.slot, new_slot: MOVED.slot, replacement_id: MOVED.id } },
      { id: 'e4', booking_id: MOVED.id, kind: 'CREATED', kind_label: 'Created', at: '2026-10-29T10:00:01+00:00',
        actor: { id: 'admin', full_name: 'Admin One' }, details: { slot: MOVED.slot, seat: 1, via: 'reschedule', rescheduled_from_id: RIYA.id } },
      { id: 'e5', booking_id: MOVED.id, kind: 'TUTOR_ASSIGNED', kind_label: 'Tutor assigned', at: '2026-10-29T10:00:02+00:00',
        actor: { id: 'admin', full_name: 'Admin One' }, details: { old_tutor: null, new_tutor: { id: 't-a', full_name: 'Tutor A' }, via: 'reschedule' } },
      { id: 'e6', booking_id: MOVED.id, kind: 'CANCELLED', kind_label: 'Cancelled', at: '2026-11-02T15:00:00+00:00',
        actor: { id: 'admin', full_name: 'Admin One' }, details: { from_status: 'BOOKED', to_status: 'CANCELLED', reason: { code: 'NO_SHOW', label: 'No-show' } } },
    ],
  };
  serve({
    [`GET ${LIST}`]: list([MOVED]),
    [`GET ${at(MOVED)}`]: detail(MOVED, { status: 'CANCELLED', cancel_reason: 'No-show', cancel_reason_code: 'NO_SHOW' }),
    [`GET ${at(MOVED, 'history/')}`]: history,
  });
  await open(`/bookings?booking=${MOVED.id}`, ADMIN);
  assert.equal(calls('GET', at(MOVED, 'history/')).length, 0, 'not read until asked for');
  await click(button('Show history', topDialog()));
  const items = [...topDialog().querySelectorAll('[aria-label="History"] li')].map((li) => clean(li.textContent));
  assert.equal(items.length, 6);
  assert.match(items[0], /^Booked on the booking page for Sat, 31 Oct · 7:30 PM IST.* · by the booking page · on the booking it replaced$/);
  assert.match(items[1], /^Tutor A assigned.* · by Admin One · on the booking it replaced$/);
  assert.match(items[2], /^Moved from Sat, 31 Oct · 7:30 PM IST to Mon, 2 Nov · 7:30 PM IST — Parent asked to move/);
  assert.match(items[3], /^Booked in the new slot, Mon, 2 Nov · 7:30 PM IST.* · by Admin One$/);
  assert.match(items[4], /^Tutor A carried over to the new slot/);
  assert.match(items[5], /^Cancelled — No-show.* · by Admin One$/);
  assert.ok(!items.join(' ').includes('Asha Nair'), 'no parent in the timeline');
});

test('History: a completed booking shows its report submitted and each edit, by version and field, never their text', async () => {
  const history = {
    booking_id: RIYA.id, timezone: 'Asia/Kolkata',
    chain: [{ id: RIYA.id, status: 'COMPLETED', slot: RIYA.slot, current: true }],
    events: [
      { id: 'c1', booking_id: RIYA.id, kind: 'CREATED', kind_label: 'Created', at: '2026-10-28T09:00:00+00:00', actor: null,
        details: { slot: RIYA.slot, seat: 1, via: 'public_booking', referral_status: 'NO_REF' } },
      { id: 'c2', booking_id: RIYA.id, kind: 'COMPLETED', kind_label: 'Completed', at: '2026-10-31T15:00:00+00:00',
        actor: { id: 't-a', full_name: 'Tutor A' },
        details: { from_status: 'BOOKED', to_status: 'COMPLETED', report_id: 'r-1', version: 1 } },
      { id: 'c3', booking_id: RIYA.id, kind: 'REPORT_EDITED', kind_label: 'Report edited', at: '2026-11-01T06:00:00+00:00',
        actor: { id: 't-a', full_name: 'Tutor A' },
        details: { report_id: 'r-1', version: 2, changed_fields: ['score', 'teacher_remarks'] } },
      { id: 'c4', booking_id: RIYA.id, kind: 'REPORT_EDITED', kind_label: 'Report edited', at: '2026-11-01T07:00:00+00:00',
        actor: { id: 't-a', full_name: 'Tutor A' },
        details: { report_id: 'r-1', version: 3, changed_fields: ['suggested_plan', 'student_name_snapshot'] } },
    ],
  };
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA, { status: 'COMPLETED', actions: { cancel: false, no_show: false, reschedule: false } }),
    [`GET ${at(RIYA, 'history/')}`]: history,
  });
  await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  await click(button('Show history', topDialog()));
  const items = [...topDialog().querySelectorAll('[aria-label="History"] li')].map((li) => clean(li.textContent));
  assert.equal(items.length, 4);
  assert.match(items[1], /^Completed — the report was submitted.* · by Tutor A$/);
  assert.match(items[2], /^Report edited, now version 2 — Score, Teacher's remarks.* · by Tutor A$/);
  assert.match(items[3], /^Report edited, now version 3 — Suggested plan, Student name.* · by Tutor A$/);
  // Field names only: no raw codes, no report id.
  assert.ok(!items.join(' ').match(/teacher_remarks|snapshot|r-1/), items.join(' | '));
});

test('A moved booking says why and links to its replacement', async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA, { status: 'RESCHEDULED', rescheduled_at: '2026-10-29T10:00:00+00:00',
      rescheduled_by: { id: 'admin', full_name: 'Admin One' }, reschedule_reason: 'Parent asked to move',
      reschedule_reason_code: 'PARENT_REQUEST', rescheduled_to: { id: MOVED.id, status: 'BOOKED', slot: MOVED.slot },
      actions: { cancel: false, no_show: false, reschedule: false } }),
    [`GET ${at(MOVED)}`]: detail(MOVED),
  });
  const page = await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  const text = clean(topDialog().textContent);
  assert.match(text, /RescheduledMoved on29 Oct 2026ByAdmin OneReasonParent asked to moveMoved toMon, 2 Nov · 7:30 PM IST/);
  assert.ok(!button('Reschedule', topDialog()) && !button('Cancel booking', topDialog()));
  await click(button('Open the new booking', topDialog()));
  assert.equal(new URLSearchParams(page.location().search).get('booking'), MOVED.id);
});

// --------------------------------------------------------- BDE cancellation (Q22)
const ENQUIRY_URL = '/api/bde/enquiries/lead-1/';
const BDE_BOOKED = { id: 'b-1', booking_type: 'DEMO', date: '2026-10-31', time: '19:30', starts_at: '2026-10-31T14:00:00+00:00',
  status: 'BOOKED', ended: false, activity_state: 'UPCOMING', started_at: null, booked_at: '2026-10-28T09:00:00+00:00',
  cancelled_at: null, actions: { cancel: true, no_show: false } };
const BDE_CANCELLED = { id: 'b-2', booking_type: 'DIAGNOSTIC', date: '2026-10-29', time: '10:00', starts_at: '2026-10-29T04:30:00+00:00',
  status: 'CANCELLED', ended: true, booked_at: '2026-10-27T09:00:00+00:00', cancelled_at: '2026-10-28T09:00:00+00:00',
  actions: { cancel: false, no_show: false } };
const enquiry = (bookings) => ({ id: 'lead-1', student_name: 'Riya', grade: 'Class 8', parent_name: 'Asha Nair', phone: '+971 501234567',
  phone_dial_code: '+971', phone_number: '501234567', status: 'BOOKED', status_label: 'Demo booked', source: 'BOOKING_PAGE',
  source_label: 'Booking page', added_at: '2026-10-27T09:00:00+00:00', school_name: 'Delhi Private School', syllabus: 'CBSE',
  country: 'United Arab Emirates', created_at: '2026-10-27T09:00:00+00:00', timezone: 'Asia/Kolkata', next_booking: null, bookings });
const BDE = { id: 'bde', role: 'BDE', permissions: ['accounts.cancel_booking', 'accounts.view_own_enquiries'] };
const bookingRows = () => [...document.querySelectorAll('tbody tr')].map((row) => clean(row.textContent));

test('BDE: cancels a booking of their own enquiry with a reason from the list; the enquiry updates', async () => {
  serve({
    [`GET ${ENQUIRY_URL}`]: enquiry([BDE_BOOKED, BDE_CANCELLED]),
    [`POST /api/bde/bookings/demo/${BDE_BOOKED.id}/cancel/`]: () => ok({
      ...enquiry([{ ...BDE_BOOKED, status: 'CANCELLED', cancelled_at: '2026-10-30T09:00:00+00:00', actions: { cancel: false, no_show: false } }, BDE_CANCELLED]),
      changed: true }),
  });
  await open('/enquiries/lead-1?tab=bookings', BDE);
  assert.ok(button('Cancel the demo class on Sat, 31 Oct · 7:30 PM IST'), 'a booked booking offers Cancel');
  assert.equal([...document.querySelectorAll('tbody tr')][1].querySelectorAll('button').length, 0, 'a cancelled one does not');
  await click(button('Cancel the demo class on Sat, 31 Oct · 7:30 PM IST'));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /^Cancel booking.*Riya · Demo class · Sat, 31 Oct · 7:30 PM IST/);
  assert.ok(radio('No-show', dialog).disabled);
  await click(radio('Parent asked to cancel', dialog));
  await click(button('Cancel booking', dialog));
  assert.deepEqual(calls('POST', `/api/bde/bookings/demo/${BDE_BOOKED.id}/cancel/`).map((entry) => entry.data), [{ reason: 'PARENT_REQUEST' }]);
  assert.match(bodyText(), /Cancelled Riya's demo class on Sat, 31 Oct · 7:30 PM IST\./);
  assert.match(bookingRows()[0], /Cancelled/);
  assert.ok(!button('Cancel the demo class on Sat, 31 Oct · 7:30 PM IST'), 'nothing more to cancel');
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url.startsWith('/api/bookings/')), "the administrators' routes are never called");
});

test("BDE: the API's refusal is shown as it comes -- another BDE's booking is not found", async () => {
  serve({
    [`GET ${ENQUIRY_URL}`]: enquiry([BDE_BOOKED]),
    [`POST /api/bde/bookings/demo/${BDE_BOOKED.id}/cancel/`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such booking.' }),
  });
  await open('/enquiries/lead-1?tab=bookings', BDE);
  await click(button('Cancel the demo class on Sat, 31 Oct · 7:30 PM IST'));
  await click(radio('Other', topDialog()));
  await click(button('Cancel booking', topDialog()));
  assert.match(clean(topDialog().textContent), /No such booking\./);
  assert.ok(!/Cancelled Riya's/.test(bodyText()));
});

test('BDE: no Cancel unless the API offers it', async () => {
  serve({ [`GET ${ENQUIRY_URL}`]: enquiry([{ ...BDE_BOOKED, actions: { cancel: false, no_show: false } }, { ...BDE_BOOKED, id: 'b-3', actions: undefined }]) });
  await open('/enquiries/lead-1?tab=bookings', BDE);
  assert.equal(document.querySelectorAll('tbody button').length, 0);
});

// ------------------------------------------------------------ reports (Admin, P8)
// The report fields each row and detail carry (backend coordination.report_summary, report_brief).
const reportFields = (extra = {}) => ({ has_report: false, report_version: null, report_due: false, report: null, ...extra });
const OVER = { ...RIYA.slot, started: true, ended: true };
const TUTOR_A = { id: 't-a', full_name: 'Tutor A' };
const IRA = { ...RIYA, id: 'b-ira', student_name: 'Ira', status: 'COMPLETED', slot: OVER, tutor: TUTOR_A,
  ...reportFields({ has_report: true, report_version: 2, report: { id: 'r-ira', version: 2,
    submitted_at: '2026-10-31T15:10:00+00:00', submitted_by: TUTOR_A, updated_at: '2026-10-31T16:20:00+00:00' } }) };
const STARTED_AT = '2026-10-31T14:02:00+00:00';
const DEV = { ...RIYA, id: 'b-dev', student_name: 'Dev', slot: OVER, tutor: TUTOR_A, activity_state: 'IN_PROGRESS',
  started_at: STARTED_AT, ...reportFields({ report_due: true }) };
const NOOR = { ...RIYA, id: 'b-noor', student_name: 'Noor', slot: OVER, tutor: TUTOR_A, activity_state: 'NOT_STARTED',
  ...reportFields() };
const SAM = { ...RIYA, id: 'b-sam', student_name: 'Sam', slot: { ...RIYA.slot, started: true }, tutor: TUTOR_A,
  activity_state: 'IN_PROGRESS', started_at: STARTED_AT, ...reportFields() };
// Its scheduled time has passed, and its tutor has not started it: the slot's clock alone is no start.
const LEO = { ...RIYA, id: 'b-leo', student_name: 'Leo', slot: { ...RIYA.slot, started: true }, tutor: TUTOR_A,
  activity_state: 'LATE', ...reportFields() };
const SOON = { ...RIYA, ...reportFields() };
const IRA_V1 = { assessment_review: 'Scored 9 out of 12.', class_observation_review: 'Attentive.', suggested_strategy: 'Timed practice.' };
const IRA_V2 = { ...IRA_V1, suggested_strategy: 'Timed practice, twice a week.' };
const iraReport = { id: 'r-ira', booking_id: IRA.id, booking_type: 'DEMO', version: 2, fields: IRA_V2, student_name: 'Ira',
  grade: '8', tutor_name: 'Tutor A', submitted_at: '2026-10-31T15:10:00+00:00', updated_at: '2026-10-31T16:20:00+00:00' };
const iraVersion = (version, fields, changed) => ({ version, changed_fields: changed, edited_at: `2026-10-31T1${4 + version}:00:00+00:00`,
  edited_by: { id: 't-a', name: 'Tutor A' }, fields, student_name: 'Ira', grade: '8', tutor_name: 'Tutor A' });
const reportCell = (row) => row.querySelectorAll('td')[5];

/** Save what a download would, instead of a browser: [file name, ...]. Restores the browser's own afterwards. */
async function catchingDownloads(run) {
  const saved = [];
  const { createObjectURL, revokeObjectURL } = URL;
  const anchorClick = window.HTMLAnchorElement.prototype.click;
  URL.createObjectURL = () => 'blob:test/1';
  URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function click() {
    saved.push(this.download);
  };
  try {
    await run(saved);
  } finally {
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    window.HTMLAnchorElement.prototype.click = anchorClick;
  }
}
const pdfAnswer = (name) => () => Promise.resolve({ status: 200, data: new Blob(['%PDF-1.7']),
  headers: { 'content-disposition': `attachment; filename="${name}"` } });

test('reports: the Report column shows the version submitted, Report due, or nothing yet', async () => {
  serve({ [`GET ${LIST}`]: list([IRA, DEV, NOOR, SAM, SOON]) });
  await open('/bookings', ADMIN);
  const cells = rows().map(reportCell);
  // Report due only after a start: Noor's slot ended with none, so there is no report to be due.
  assert.deepEqual(cells.map((cell) => clean(cell.textContent)), ['Report v2', 'Report due', '—', '—', '—']);
  assert.deepEqual(cells.map((cell) => cell.querySelector('[data-slot="badge"]')?.dataset.variant ?? null),
    ['success', 'warning', null, null, null]);
});

test('reports: Filter by report reaches the API and the URL with search and every other filter; Report due looks at past slots', async () => {
  serve({ [`GET ${LIST}`]: list([IRA]) });
  const page = await open('/bookings/demo', ADMIN);
  const params = () => calls('GET', LIST).at(-1).params;
  const query = () => Object.fromEntries(new URLSearchParams(page.location().search));

  await choose('Filter by report', 'Report submitted');
  assert.deepEqual(params(), { page: 1, page_size: 25, report: 'submitted', when: 'upcoming' });
  await choose('Filter by report', 'No report yet');
  assert.equal(params().report, 'missing');
  await typeInto(document.querySelector('[aria-label="Search bookings"]'), 'Dev');
  await submit(document.querySelector('[aria-label="Search bookings"]').closest('form'));
  assert.deepEqual(params(), { page: 1, page_size: 25, q: 'Dev', report: 'missing', when: 'upcoming' });

  // Report due: only past slots can be due, so Upcoming becomes Past -- in the request and the URL.
  await choose('Filter by report', 'Report due');
  assert.deepEqual(params(), { page: 1, page_size: 25, q: 'Dev', report: 'due', when: 'past' });
  assert.deepEqual(query(), { q: 'Dev', report: 'due', when: 'past' });
  await choose('Filter by booking status', 'Booked');
  await choose('Filter by tutor assignment', 'Tutor assigned');
  assert.deepEqual(params(), { page: 1, page_size: 25, q: 'Dev', status: 'BOOKED', assigned: 'true', report: 'due', when: 'past' });
  await choose('Filter by schedule', 'All Schedules');
  assert.deepEqual(params(), { page: 1, page_size: 25, q: 'Dev', status: 'BOOKED', assigned: 'true', report: 'due' });
  // Back to Upcoming: no report is due there, so Report due goes rather than empty the list.
  await choose('Filter by schedule', 'Upcoming');
  assert.deepEqual(params(), { page: 1, page_size: 25, q: 'Dev', status: 'BOOKED', assigned: 'true', when: 'upcoming' });
  assert.equal(query().report, undefined);

  await choose('Filter by report', 'Report due');
  await click(button('Clear all filters'));
  assert.deepEqual(params(), { page: 1, page_size: 25, when: 'upcoming' });
  assert.deepEqual(query(), {});
  await page.unmount();

  // A link to the reports due shows them, whatever it says of Upcoming; an unknown value is dropped.
  for (const [link, sent] of [
    ['/bookings/demo?report=due', { page: 1, page_size: 25, report: 'due', when: 'past' }],
    ['/bookings/demo?report=due&when=upcoming', { page: 1, page_size: 25, report: 'due', when: 'past' }],
    ['/bookings/demo?report=due&when=all', { page: 1, page_size: 25, report: 'due' }],
    ['/bookings/demo?report=overdue', { page: 1, page_size: 25, when: 'upcoming' }],
  ]) {
    globalThis.__bookingsApi.calls = [];
    const opened = await open(link, ADMIN);
    assert.deepEqual(params(), sent, link);
    await opened.unmount();
  }
});

test('reports: the sheet shows a submitted report read-only -- who and when, the report itself, its PDF and every version', async () => {
  await catchingDownloads(async (saved) => {
    serve({
      [`GET ${LIST}`]: list([IRA]),
      [`GET ${at(IRA)}`]: detail(IRA),
      [`GET ${at(IRA, 'report/')}`]: iraReport,
      [`GET ${at(IRA, 'report/revisions/')}`]: { results: [iraVersion(1, IRA_V1, ['assessment_review',
        'class_observation_review', 'suggested_strategy']), iraVersion(2, IRA_V2, ['suggested_strategy'])], count: 2, version: 2 },
      [`GET ${at(IRA, 'report/pdf/')}`]: pdfAnswer('Demo-Report-Ira-2026-10-31.pdf'),
      [`GET ${at(IRA, 'report/revisions/1/pdf/')}`]: pdfAnswer('Demo-Report-Ira-2026-10-31-v1.pdf'),
    });
    await open(`/bookings?booking=${IRA.id}`, ADMIN);
    const section = [...topDialog().querySelectorAll('section')].find((element) => element.querySelector('h3')?.textContent === 'Report');
    assert.ok(section, 'a Report section');
    const text = clean(section.textContent);
    assert.match(text, /VersionVersion 2Submitted31 Oct 2026, .* by Tutor ALast saved31 Oct 2026, /);
    assert.match(text, /Read-only\. Only the booking’s tutor writes or edits its report\./);
    for (const value of Object.values(IRA_V2)) assert.ok(text.includes(value), `the report says "${value}"`);

    await click(button('Download PDF', section));
    assert.equal(calls('GET', at(IRA, 'report/pdf/')).length, 1, "the Admin's own PDF route");
    assert.deepEqual(saved, ['Demo-Report-Ira-2026-10-31.pdf']);

    await click(button('Show versions', section));
    assert.equal(calls('GET', at(IRA, 'report/revisions/')).length, 1, 'versions are read on request');
    assert.match(clean(section.textContent), /Version 2 · current.*Changed: Suggested strategy.*Version 1.*First version/);
    await click(button('Show version 1', section));
    assert.ok(clean(section.textContent).includes(IRA_V1.suggested_strategy), 'an earlier version as it was saved');
    await click(button('PDF of version 1', section));
    assert.deepEqual(saved, ['Demo-Report-Ira-2026-10-31.pdf', 'Demo-Report-Ira-2026-10-31-v1.pdf']);

    // Read-only: nothing writes a report here, and the tutor's routes are never used.
    for (const label of ['Edit report', 'Write report', 'Submit report', 'Save changes', 'Preview PDF']) {
      assert.equal(button(label), undefined, `no ${label}`);
    }
    assert.equal([...topDialog().querySelectorAll('a')].filter((link) => (link.getAttribute('href') || '').includes('/report')).length, 0);
    assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET'), 'only reads');
    assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url.startsWith('/api/tutor/')), "the tutor's API is never called");
  });
});

test('reports: a booking without its report says why -- due, started, late, never started, upcoming; none for a cancelled one', async () => {
  for (const [booking, says] of [
    [DEV, 'Report due. The class is over and the tutor has not written the report yet.'],
    [SAM, 'The tutor has started the class. They can write the report now.'],
    [LEO, 'The scheduled time has passed and the tutor has not started the class yet.'],
    [NOOR, 'The slot ended without the tutor starting the class, so no report can be written.'],
    [SOON, 'The tutor can write the report once they start the class.'],
  ]) {
    serve({ [`GET ${LIST}`]: list([booking]), [`GET ${at(booking)}`]: detail(booking) });
    const page = await open(`/bookings?booking=${booking.id}`, ADMIN);
    const section = [...topDialog().querySelectorAll('section')].find((element) => element.querySelector('h3')?.textContent === 'Report');
    assert.equal(clean(section.querySelector('p').textContent), says);
    assert.equal(button('Download PDF', section), undefined);
    assert.equal(button('Show versions', section), undefined);
    assert.equal(calls('GET', at(booking, 'report/')).length, 0, 'no report to read');
    await page.unmount();
  }
  const cancelled = { ...DEV, status: 'CANCELLED', report_due: false };
  serve({ [`GET ${LIST}`]: list([cancelled]), [`GET ${at(cancelled)}`]: detail(cancelled, { cancelled_at: '2026-10-31T16:00:00+00:00' }) });
  await open(`/bookings?booking=${cancelled.id}`, ADMIN);
  assert.ok(![...topDialog().querySelectorAll('h3')].some((heading) => heading.textContent === 'Report'));
});

test('reports: a report that cannot be read says so, and Try again reads it', async () => {
  let attempts = 0;
  serve({
    [`GET ${LIST}`]: list([IRA]),
    [`GET ${at(IRA)}`]: detail(IRA),
    [`GET ${at(IRA, 'report/')}`]: () => (attempts++ === 0 ? fail(500, { message: 'The report could not be read.' }) : ok(iraReport)),
  });
  await open(`/bookings?booking=${IRA.id}`, ADMIN);
  assert.match(clean(topDialog().textContent), /The report could not be read\./);
  await click(button('Try again', topDialog()));
  assert.ok(clean(topDialog().textContent).includes(IRA_V2.suggested_strategy));
});

// ------------------------------------------------------ BDE report sharing (P9)
// The owner BDE's Reports section on the enquiry page (design F.4). The BDE
// sends a report outside the Hub; sending it from here keeps the send (…/report/share/),
// which ends their reminder to share it.
const BDE_REPORTS = { ...BDE, permissions: [...BDE.permissions, 'accounts.view_own_lead_reports'] };
const REPORTS_URL = '/api/bde/enquiries/lead-1/reports/';
const DONE = { status: 'COMPLETED', ended: true, cancelled_at: null, actions: { cancel: false, no_show: false } };
const DONE_DEMO = { ...BDE_BOOKED, ...DONE, id: 'b-7' };
const DONE_DIAGNOSTIC = { ...BDE_CANCELLED, ...DONE, id: 'b-8' };
const DONE_DEMO_PDF = `/api/bde/bookings/demo/${DONE_DEMO.id}/report/pdf/`;
const DONE_DEMO_SHARE = `/api/bde/bookings/demo/${DONE_DEMO.id}/report/share/`;
// One report on the lead's list, as the API answers it (backend reports.payloads.lead_report_row).
const leadReport = (booking, version, fields) => ({
  booking: { id: booking.id, booking_type: booking.booking_type, date: booking.date, time: booking.time,
    starts_at: booking.starts_at, status: 'COMPLETED', completed_at: '2026-10-31T10:10:00+00:00' },
  report: { id: `r-${booking.id}`, booking_id: booking.id, booking_type: booking.booking_type, version, fields,
    student_name: 'Riya', grade: '8', tutor_name: 'Tutor A', submitted_at: '2026-10-31T10:10:00+00:00',
    updated_at: '2026-10-31T10:20:00+00:00' },
});
const DEMO_REPORT = leadReport(DONE_DEMO, 2, IRA_V2);
const DIAGNOSTIC_REPORT = leadReport(DONE_DIAGNOSTIC, 1, { score: 18, max_score: 25, performance_level: 'GOOD',
  strength_areas: ['Fractions'], skills_to_strengthen: ['Word problems'], teacher_remarks: 'Works carefully.',
  suggested_plan: 'Two sessions a week.' });
const reportsOf = (...results) => ({ results, count: results.length, timezone: 'Asia/Kolkata' });
const leadWithReports = (...results) => ({
  [`GET ${ENQUIRY_URL}`]: enquiry([DONE_DEMO, DONE_DIAGNOSTIC]),
  [`GET ${REPORTS_URL}`]: reportsOf(...results),
});
const reportItems = () => [...(document.querySelector('ul[aria-label="Reports"]')?.children ?? [])];
const message = (kind) => `Hello Asha Nair, please find Riya's ${kind} report from Eduport Plus attached.`;
const onlyReads = () => globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET');

/** A browser that shares files: navigator.canShare and navigator.share, each share recorded. Removed afterwards. */
async function sharingFiles(answer, run) {
  const shared = [];
  Object.defineProperty(navigator, 'canShare', { value: (data) => Array.isArray(data?.files), configurable: true });
  Object.defineProperty(navigator, 'share', { value: (data) => { shared.push(data); return answer(data); }, configurable: true });
  try {
    await run(shared);
  } finally {
    delete navigator.canShare;
    delete navigator.share;
  }
}

test('BDE reports: each submitted report shows its class, version and actions, the WhatsApp message ready', async () => {
  serve(leadWithReports(DEMO_REPORT, DIAGNOSTIC_REPORT));
  await open('/enquiries/lead-1?tab=feedback', BDE_REPORTS);
  // Newest class first, as the API lists them, each at its current version.
  const [demo, diagnostic] = reportItems();
  for (const [item, shown] of [[demo, ['Demo class', 'Sat, 31 Oct · 7:30 PM IST', 'Version 2', 'Last saved 31 Oct 2026']],
    [diagnostic, ['Diagnostic test', 'Thu, 29 Oct · 10:00 AM IST', 'Version 1', 'Last saved 31 Oct 2026']]]) {
    const text = clean(item.textContent);
    for (const part of shown) assert.ok(text.includes(part), `${part} in: ${text}`);
    assert.deepEqual([...item.querySelectorAll('button')].map((element) => clean(element.textContent)), ['View report', 'Download PDF']);
  }
  assert.equal(reportItems().length, 2);
  // Send via WhatsApp: the parent's registered number with the message filled in (A11), in a new tab or the app.
  const links = [...document.querySelectorAll('ul[aria-label="Reports"] a')];
  assert.deepEqual(links.map((link) => [clean(link.textContent), link.getAttribute('href'), link.getAttribute('target')]), [
    ['Send via WhatsApp', `https://wa.me/971501234567?text=${encodeURIComponent(message('Demo Class'))}`, '_blank'],
    ['Send via WhatsApp', `https://wa.me/971501234567?text=${encodeURIComponent(message('Diagnostic Test'))}`, '_blank'],
  ]);
  assert.match(bodyText(), /Send via WhatsApp opens the parent’s chat with the message ready, but it can’t attach the PDF\. Download the PDF, attach it in the chat, then send\./);
  // No Share PDF where the browser cannot share files (as here), and nothing about sending is tracked or claimed.
  assert.ok(!button('Share PDF') && !/Share PDF/.test(bodyText()));
  assert.ok(!/Mark as sent|\bSent\b|Not sent/.test(bodyText()));
  assert.deepEqual(globalThis.__bookingsApi.calls.map((entry) => `${entry.method} ${entry.url}`), [`GET ${ENQUIRY_URL}`, `GET ${REPORTS_URL}`]);
});

test('BDE reports: View report shows the report as it prints, in a dialog, with its PDF', async () => {
  serve(leadWithReports(DEMO_REPORT));
  await open('/enquiries/lead-1?tab=feedback', BDE_REPORTS);
  await click(button('View the demo class report'));
  const dialog = topDialog();
  assert.equal(clean(dialog.querySelector('h2').textContent), 'Demo class report');
  assert.ok(clean(dialog.textContent).includes('Sat, 31 Oct · 7:30 PM IST · Version 2 · As it prints'));
  // The report as it prints (ReportFieldsView): who it is for and by, then what the tutor wrote.
  const details = [...dialog.querySelectorAll('dt')].map((dt) => [clean(dt.textContent), clean(dt.nextElementSibling?.textContent)]);
  assert.ok(details.some(([label, value]) => label === 'Student Name' && value === 'Riya'), JSON.stringify(details));
  assert.ok(details.some(([label, value]) => label === 'Tutor Name' && value === 'Tutor A'), JSON.stringify(details));
  assert.ok(clean(dialog.textContent).includes(IRA_V2.suggested_strategy));
  assert.ok(button('Download PDF', dialog));
  await click(button('Close', topDialog()));
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0);
  assert.equal(globalThis.__bookingsApi.calls.length, 2, 'the list already holds each report');
});

test("BDE reports: Download PDF saves the current version from the BDE's own route under the server's name, or says why not", async () => {
  let answer = pdfAnswer('Demo-Report-Riya-2026-10-31.pdf');
  serve({ ...leadWithReports(DEMO_REPORT), [`GET ${DONE_DEMO_PDF}`]: (entry) => answer(entry) });
  await open('/enquiries/lead-1?tab=feedback', BDE_REPORTS);
  await catchingDownloads(async (saved) => {
    await click(button('Download the demo class report as a PDF'));
    assert.deepEqual(saved, ['Demo-Report-Riya-2026-10-31.pdf']);
    // The lead is no longer theirs: the API answers as for a booking that does not exist.
    answer = () => fail(404, new Blob([JSON.stringify({ error: 'NOT_FOUND', message: 'No such booking.' })]));
    await click(button('Download the demo class report as a PDF'));
    assert.match(clean(reportItems()[0].textContent), /This booking is not available to you any more\./);
    assert.equal(saved.length, 1);
  });
  assert.equal(calls('GET', DONE_DEMO_PDF).length, 2);
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => /^\/api\/(bookings|tutor)\//.test(entry.url)), "only the BDE's own routes");
  assert.ok(onlyReads());
});

test('BDE reports: none yet says so; a list that cannot be read says why, and Try again reads it again', async () => {
  let answer = () => fail(404, { error: 'NOT_FOUND', message: 'No such enquiry.' });
  serve({ [`GET ${ENQUIRY_URL}`]: enquiry([BDE_BOOKED]), [`GET ${REPORTS_URL}`]: (entry) => answer(entry) });
  await open('/enquiries/lead-1?tab=feedback', BDE_REPORTS);
  assert.match(bodyText(), /No such enquiry\./);
  answer = () => ok(reportsOf());
  await click(button('Try again'));
  assert.equal(calls('GET', REPORTS_URL).length, 2);
  assert.ok(bodyText().includes('No reports yet'));
  assert.ok(bodyText().includes('A Diagnostic or Demo report appears here once its tutor submits it after the class.'));
  assert.ok(!/No such enquiry/.test(bodyText()));
  assert.ok(!button('View report') && !document.querySelector('a[href*="?text="]'));
});

test('BDE reports: no Reports section, and no request for one, without accounts.view_own_lead_reports', async () => {
  serve(leadWithReports(DEMO_REPORT));
  await open('/enquiries/lead-1', BDE);
  assert.equal(calls('GET', REPORTS_URL).length, 0);
  assert.ok(!reportItems().length && !/Submitted reports as they print/.test(bodyText()));
});

test('BDE reports: Share PDF, where the browser shares files, hands the PDF to the share sheet; a dropped tap asks for another', async () => {
  let outcome = 'refused';
  const answer = () => {
    if (outcome === 'refused') return Promise.reject(Object.assign(new Error('Not allowed'), { name: 'NotAllowedError' }));
    if (outcome === 'closed') return Promise.reject(Object.assign(new Error('Cancelled'), { name: 'AbortError' }));
    return Promise.resolve();
  };
  await sharingFiles(answer, async (shared) => {
    serve({ ...leadWithReports(DEMO_REPORT), [`GET ${DONE_DEMO_PDF}`]: pdfAnswer('Demo-Report-Riya-2026-10-31.pdf'),
      [`POST ${DONE_DEMO_SHARE}`]: { report_version: 2, shared_at: '2026-10-31T11:00:00+00:00' } });
    await open('/enquiries/lead-1?tab=feedback', BDE_REPORTS);
    assert.match(bodyText(), /Share PDF hands the PDF to WhatsApp or another app on this device\. Pick the parent’s chat there\./);
    // The PDF arrived after the browser stopped counting the tap: kept, and the next tap shares it at once.
    await click(button('Share the demo class report PDF'));
    assert.match(clean(reportItems()[0].textContent), /The PDF is ready\. Tap Share PDF again to share it\./);
    assert.equal(calls('POST', DONE_DEMO_SHARE).length, 0, 'a share the browser refused is not kept');
    outcome = 'shared';
    await click(button('Share the demo class report PDF'));
    assert.equal(calls('GET', DONE_DEMO_PDF).length, 1, 'fetched once');
    const { files, title } = shared.at(-1);
    assert.deepEqual([files.length, files[0].name, files[0].type, title],
      [1, 'Demo-Report-Riya-2026-10-31.pdf', 'application/pdf', 'Demo class report: Riya']);
    assert.ok(!/Tap Share PDF again/.test(bodyText()));
    // Closing the share sheet without sharing is no error.
    outcome = 'closed';
    await click(button('Share the demo class report PDF'));
    assert.equal(shared.length, 3);
    assert.equal(reportItems()[0].querySelectorAll('[role="alert"], [role="status"]').length, 0);
  });
  // Only the share the sheet took is kept: never one refused or closed without sharing.
  assert.equal(calls('POST', DONE_DEMO_SHARE).length, 1);
});

test('BDE reports: Send via WhatsApp keeps the send, which ends the reminder to share the report', async () => {
  serve({ ...leadWithReports(DEMO_REPORT, DIAGNOSTIC_REPORT),
    [`POST ${DONE_DEMO_SHARE}`]: { report_version: 2, shared_at: '2026-10-31T11:00:00+00:00' } });
  await open('/enquiries/lead-1?tab=feedback', BDE_REPORTS);
  const [demo] = reportItems();
  await click(demo.querySelector('a[aria-label="Send the demo class report via WhatsApp"]'));
  assert.deepEqual(calls('POST', DONE_DEMO_SHARE).map((entry) => entry.data), [null]);
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.method === 'POST' && entry.url !== DONE_DEMO_SHARE),
    'only that report');
});

// ------------------------------------------------------------ My Bookings (tutors)
const MINE = '/api/tutor/bookings/';
const VIEW_ASSIGNED = 'accounts.view_assigned_bookings';
const TUTOR = { id: 'tutor', role: 'TUTOR', permissions: [VIEW_ASSIGNED, 'accounts.view_staff_dashboard'] };

// The tutor API's rows (backend bookings.tutor_bookings): the slot, without its id, and the child.
const mySlot = (date, time) => ({ date, time, starts_at: `${date}T14:00:00+00:00`, ends_at: `${date}T15:00:00+00:00`,
  started: false, ended: false });
// Its Start (backend tutor_bookings.start_refusal): offered only while the API says so, with why not otherwise.
const TOO_EARLY = { code: 'START_TOO_EARLY', message: 'A booking can be started from 5 minutes before its scheduled time.' };
const ALREADY_STARTED = { code: 'BOOKING_STARTED', message: 'This booking has already started.' };
const notStartable = (start_refusal) => ({ actions: { start: false }, start_refusal });
const MY_RIYA = { id: 'b-riya', booking_type: 'DEMO', status: 'BOOKED', slot: mySlot('2026-10-31', '19:30'),
  student_name: 'Riya', grade: 'Class 8', syllabus: 'CBSE', school_name: 'Delhi Private School', country: 'United Arab Emirates',
  activity_state: 'UPCOMING', started_at: null, start_opens_at: '2026-10-31T13:55:00+00:00', ...notStartable(TOO_EARLY) };
const MY_ALI = { id: 'b-ali', booking_type: 'DIAGNOSTIC', status: 'CANCELLED', slot: mySlot('2026-11-01', '10:00'),
  student_name: 'Ali', grade: 'Class 9', syllabus: 'IGCSE', school_name: 'Al Noor School', country: 'India',
  activity_state: 'CANCELLED', started_at: null, start_opens_at: '2026-11-01T13:55:00+00:00',
  ...notStartable({ code: 'BOOKING_CANCELLED', message: 'This booking is cancelled, so it cannot be started.' }) };
const mine = (results, count = results.length, page = 1) => ({ results, count, page, page_size: 25, timezone: 'Asia/Kolkata' });
const myDetail = (row) => ({ ...row, timezone: 'Asia/Kolkata' });
const myAt = (booking) => `${MINE}${booking.booking_type.toLowerCase()}/${booking.id}/`;
const opened = (booking) => `booking=${booking.id}&booking_type=${booking.booking_type}`;

// What the administrators' API carries and the tutor one never sends. Were it
// ever to arrive, the page must still render none of it.
const PRIVATE = {
  parent_name: 'Asha Nair', phone: '+971 501234567', phone_dial_code: '+971', phone_number: '501234567',
  tutor: { id: 't-a', full_name: 'Tutor A' }, bde: { id: 'bde-1', full_name: 'Bde One' }, referral_status: 'ATTRIBUTED',
  tutor_assigned_at: '2026-10-29T06:00:00+00:00', tutor_assigned_by: { id: 'admin', full_name: 'Admin One' },
  tutor_changeable: true, cancelled_by: { id: 'admin', full_name: 'Admin One' }, cancel_reason: 'Parent asked to move it',
  seat: 2, booked_at: '2026-10-28T09:00:00+00:00',
  lead: { id: 'lead-1', phone_number: '501234567', source: 'BOOKING_PAGE', owner_bde: { id: 'bde-2', full_name: 'Bde Two' } },
  details: { parent_name: 'Asha Nair', phone: '+971 501234567', display_time: '06:00 pm - 07:00 pm' },
};
const PRIVATE_TEXT = ['Asha Nair', '501234567', '+971', 'Tutor A', 'Bde One', 'Bde Two', 'Admin One', 'Parent asked',
  'ATTRIBUTED', "Through a BDE's link", 'Booking page', '06:00 pm', '28 Oct 2026', '29 Oct 2026', 'Parent', 'Phone',
  'Seat', 'Assigned by', 'Assigned on', 'Credited', 'Came in', 'BDE', 'Tutor'];

const labels = (root = document.body) => [...new Set([...root.querySelectorAll('button')].map(
  (element) => clean(element.textContent) || element.getAttribute('aria-label')))].sort();

test('My Bookings: loading, then the tutor\'s bookings -- the slot in IST, the child, and a cancelled one as Cancelled', async () => {
  const answer = deferred();
  serve({ [`GET ${MINE}`]: () => answer.promise });
  await open('/my-bookings', TUTOR);
  assert.ok(document.querySelector('[data-slot="skeleton"]'), 'a loading skeleton while the list loads');
  assert.deepEqual(calls('GET', MINE)[0].params, { page: 1, page_size: 25, when: 'upcoming' });

  answer.resolve({ status: 200, data: mine([MY_RIYA, MY_ALI]) });
  await settle();
  assert.ok(!document.querySelector('[data-slot="skeleton"]'), 'the skeleton is gone');
  assert.deepEqual([...document.querySelectorAll('th')].map((th) => clean(th.textContent)),
    ['When (IST)', 'Type', 'Student', 'Meet link', 'Syllabus', 'School', 'Country', 'Status', 'Actions']);
  const [riya, ali] = rows();
  // Riya's tutor (the caller) has no Meet link configured; a cancelled booking has no class to join.
  assert.match(clean(riya.textContent),
    /^Sat, 31 Oct7:30 PMDemo classRiyaClass 8Not configuredCBSEDelhi Private SchoolUnited Arab EmiratesUpcomingView$/);
  assert.match(clean(ali.textContent), /^Sun, 1 Nov10:00 AMDiagnostic testAliClass 9—IGCSEAl Noor SchoolIndiaCancelledView$/);
  assert.match(bodyText(), /My Bookings.*Times are Indian time \(IST\)\..*Showing 1–2 of 2/);
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url.startsWith('/api/bookings/')),
    "the administrators' API is never called");
});

test('My Bookings: read-only -- no assignment action in the list or the sheet, and nothing but reads', async () => {
  serve({ [`GET ${MINE}`]: mine([MY_RIYA]), [`GET ${myAt(MY_RIYA)}`]: myDetail(MY_RIYA) });
  await open(`/my-bookings?${opened(MY_RIYA)}`, TUTOR);
  assert.ok(clean(topDialog().textContent).includes('Delhi Private School'), 'the sheet is open');
  for (const label of ['Assign', 'Change', 'Assign tutor', 'Change tutor', 'Unassign', 'Reassign']) {
    assert.ok(!button(label), `no ${label} button`);
  }
  // Every control there is: the filters, paging, Refresh, View -- and the sheet's Close.
  assert.deepEqual(labels(topDialog()), ['Close']);
  assert.deepEqual(labels(rows()[0].closest('.container')),
    ['All', 'Demo', 'Diagnostic', 'Next', 'Previous', 'Refresh', 'Upcoming', 'View']);
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET'), 'only reads');
});

test('My Bookings: an error, then Try again', async () => {
  let attempts = 0;
  serve({ [`GET ${MINE}`]: () => (attempts++ === 0 ? fail(500, { message: 'Your bookings could not be read.' }) : ok(mine([MY_RIYA]))) });
  await open('/my-bookings', TUTOR);
  assert.match(bodyText(), /Your bookings could not be read\./);
  assert.equal(rows().length, 0);
  await click(button('Try again'));
  assert.equal(rows().length, 1);
  assert.equal(calls('GET', MINE).length, 2);
});

test('My Bookings: a refusal from the API shows no access, and no rows', async () => {
  serve({ [`GET ${MINE}`]: () => fail(403, { detail: 'You do not have permission to perform this action.' }) });
  await open('/my-bookings', TUTOR);
  assert.match(bodyText(), /You don't have access to My Bookings\.You do not have permission to perform this action\./);
  assert.equal(rows().length, 0);
});

test('My Bookings: empty -- none upcoming, or none matching the filters', async () => {
  serve({ [`GET ${MINE}`]: mine([]) });
  const page = await open('/my-bookings', TUTOR);
  assert.match(clean(rows()[0].textContent), /^No upcoming bookings assigned to you\.$/);
  assert.match(bodyText(), /No results/);
  await page.unmount();
  globalThis.__bookingsApi.calls = [];
  await open('/my-bookings?when=past', TUTOR);
  assert.match(clean(rows()[0].textContent), /^No bookings match these filters\.$/);
  assert.equal(calls('GET', MINE)[0].params.when, 'past');
});

test('My Bookings: Upcoming, Past and All, and Demo / Diagnostic, reach the API and the URL; paging', async () => {
  serve({ [`GET ${MINE}`]: (entry) => ok(mine([MY_RIYA], 60, entry.params.page)) });
  const page = await open('/my-bookings', TUTOR);
  const query = () => Object.fromEntries(new URLSearchParams(page.location().search));
  assert.match(bodyText(), /Showing 1–25 of 60.*Page 1 of 3/);
  assert.ok(button('Previous').disabled);
  await click(button('Next'));
  assert.deepEqual(calls('GET', MINE).at(-1).params, { page: 2, page_size: 25, when: 'upcoming' });
  assert.match(bodyText(), /Showing 26–50 of 60.*Page 2 of 3/);

  await choose('Filter by when', 'Past');
  assert.deepEqual(calls('GET', MINE).at(-1).params, { page: 1, page_size: 25, when: 'past' }, 'a filter starts again at page 1');
  await choose('Filter by when', 'All dates');
  assert.deepEqual(calls('GET', MINE).at(-1).params, { page: 1, page_size: 25, when: 'all' });
  await mouseDown(tab('Diagnostic'));
  assert.deepEqual(calls('GET', MINE).at(-1).params, { page: 1, page_size: 25, when: 'all', type: 'DIAGNOSTIC' });
  assert.deepEqual(query(), { when: 'all', type: 'DIAGNOSTIC' });
  await mouseDown(tab('Demo'));
  await choose('Filter by when', 'Upcoming');
  assert.deepEqual(calls('GET', MINE).at(-1).params, { page: 1, page_size: 25, when: 'upcoming', type: 'DEMO' });
  assert.deepEqual(query(), { type: 'DEMO' }, 'Upcoming is the default, so the URL leaves it out');

  await click(button('Clear'));
  assert.deepEqual(calls('GET', MINE).at(-1).params, { page: 1, page_size: 25, when: 'upcoming' });
  assert.deepEqual(query(), {});
});

test('My Bookings: an unknown filter value in the URL is dropped, and no other parameter is sent', async () => {
  serve({ [`GET ${MINE}`]: mine([MY_RIYA]) });
  await open('/my-bookings?type=TRIAL&when=tomorrow&tutor=t-other&status=BOOKED&q=Ali', TUTOR);
  assert.deepEqual(calls('GET', MINE)[0].params, { page: 1, page_size: 25, when: 'upcoming' });
});

test('My Bookings: View opens the booking read-only in the side sheet', async () => {
  serve({ [`GET ${MINE}`]: mine([MY_RIYA, MY_ALI]), [`GET ${myAt(MY_ALI)}`]: myDetail(MY_ALI) });
  const page = await open('/my-bookings', TUTOR);
  await click(button('View the booking for Ali'));
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)),
    { booking: MY_ALI.id, booking_type: 'DIAGNOSTIC' }, 'the link names the booking by its type and id');
  assert.equal(calls('GET', '/api/tutor/bookings/diagnostic/b-ali/').length, 1);
  const text = clean(topDialog().textContent);
  assert.match(text, /^Ali.*Sun, 1 Nov · 10:00 AM IST · Class 9.*Diagnostic test.*Cancelled/);
  assert.match(text, /This booking was cancelled\. There is no class to teach\./);
  assert.match(text,
    /BookingTypeDiagnostic testWhenSun, 1 Nov · 10:00 AM ISTStatusCancelled.*StudentNameAliClassClass 9SyllabusIGCSESchoolAl Noor SchoolCountryIndia/);
});

test('My Bookings: a booking no longer assigned to the tutor is not found', async () => {
  serve({
    [`GET ${MINE}`]: mine([]),
    [`GET ${MINE}demo/b-gone/`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such booking.' }),
  });
  await open('/my-bookings?booking=b-gone&booking_type=DEMO', TUTOR);
  assert.match(clean(topDialog().textContent), /Booking not found.*It may no longer be assigned to you/);
});

test('My Bookings: closing a booking never shows "Booking not found" on its way out', async () => {
  serve({ [`GET ${MINE}`]: mine([MY_RIYA]), [`GET ${myAt(MY_RIYA)}`]: myDetail(MY_RIYA) });
  const page = await open(`/my-bookings?${opened(MY_RIYA)}`, TUTOR);
  assert.ok(clean(topDialog().textContent).includes('Delhi Private School'), 'the sheet is open');
  // Everything rendered while the sheet closes, however briefly.
  const rendered = [];
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) rendered.push(node.textContent || '');
      if (record.type === 'characterData') rendered.push(record.target.textContent || '');
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  await click(button('Close', topDialog()));
  observer.disconnect();
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), {}, 'both booking parameters are gone');
  assert.ok(!rendered.some((text) => text.includes('Booking not found')), 'no "Booking not found" while closing');
});

test('My Bookings: a link without a known booking type names no booking, and asks the API for none', async () => {
  serve({ [`GET ${MINE}`]: mine([MY_RIYA]) });
  for (const query of [`booking=${MY_RIYA.id}`, `booking=${MY_RIYA.id}&booking_type=TRIAL`]) {
    globalThis.__bookingsApi.calls = [];
    const page = await open(`/my-bookings?${query}`, TUTOR);
    assert.match(clean(topDialog().textContent), /Booking not found/, query);
    assert.deepEqual(globalThis.__bookingsApi.calls.map((entry) => entry.url), [MINE], `only the list for ${query}`);
    await page.unmount();
  }
});

test('My Bookings: nothing but the child and the slot is rendered, whatever else the API sends', async () => {
  const leaky = { ...MY_RIYA, ...PRIVATE };
  serve({ [`GET ${MINE}`]: mine([leaky]), [`GET ${myAt(MY_RIYA)}`]: myDetail(leaky) });
  await open(`/my-bookings?${opened(MY_RIYA)}`, TUTOR);
  const text = bodyText();
  assert.ok(text.includes('Delhi Private School') && clean(topDialog().textContent).includes('United Arab Emirates'),
    'the booking itself is shown, in the list and the sheet');
  for (const value of PRIVATE_TEXT) {
    assert.ok(!text.includes(value), `${value} is not rendered`);
  }
  assert.ok(!document.querySelector('a[href^="tel:"], a[href*="wa.me"], a[href^="mailto:"]'), 'no contact links');
});

// Where each booking stands with its report (P8): the API's own has_report, report_version and report_due,
// and where it stands as a class -- its activity_state and the tutor's own start -- as the tutor's rows
// carry them (backend bookings.tutor_bookings). The slot's clock alone never starts a booking.
const reportOf = (row, slot, report) => ({ ...row, slot: { ...row.slot, ...slot }, has_report: false, report_version: null,
  report_due: false, ...report });
const MY_STARTED = { activity_state: 'IN_PROGRESS', started_at: '2026-10-31T14:02:00+00:00', ...notStartable(ALREADY_STARTED) };
const MY_UPCOMING = reportOf(MY_RIYA, {}, {});
const MY_RUNNING = reportOf({ ...MY_RIYA, id: 'b-sam', student_name: 'Sam' }, { started: true }, MY_STARTED);
const MY_DUE = reportOf({ ...MY_RIYA, id: 'b-dev', booking_type: 'DIAGNOSTIC', student_name: 'Dev' }, { started: true, ended: true },
  { ...MY_STARTED, report_due: true });
const MY_DONE = reportOf({ ...MY_RIYA, id: 'b-ira', status: 'COMPLETED', student_name: 'Ira' }, { started: true, ended: true },
  { ...MY_STARTED, activity_state: 'COMPLETED', has_report: true, report_version: 2,
    ...notStartable({ code: 'BOOKING_COMPLETED', message: 'This booking is already completed.' }) });
const MY_CANCELLED = reportOf(MY_ALI, { started: true, ended: true }, {});
// The slot ended and its tutor never started it: no report can follow.
const MY_MISSED = reportOf({ ...MY_RIYA, id: 'b-kai', student_name: 'Kai' }, { started: true, ended: true },
  { activity_state: 'NOT_STARTED',
    ...notStartable({ code: 'START_WINDOW_CLOSED', message: "This booking's slot has ended, so it can no longer be started." }) });

/** The report links in ``root``: [label, where it goes]. */
const reportLinks = (root) => [...root.querySelectorAll('a')].map((link) => [clean(link.textContent), link.getAttribute('href')]);

test('My Bookings: each booking says where it stands with its report, and offers Write report or Edit report', async () => {
  serve({ [`GET ${MINE}`]: mine([MY_UPCOMING, MY_RUNNING, MY_DUE, MY_DONE, MY_CANCELLED]) });
  await open('/my-bookings', TUTOR);
  // Status and the actions, after the Meet link column (Phase 1).
  const status = (row) => clean(row.querySelectorAll('td')[7].textContent);
  const actions = (row) => row.querySelectorAll('td')[8];
  const [upcoming, running, due, done, cancelled] = rows();

  assert.deepEqual([upcoming, running, due, done, cancelled].map(status),
    ['Upcoming', 'In progress', 'Report due', 'CompletedReport v2', 'Cancelled']);
  assert.deepEqual([upcoming, running, due, done, cancelled].map((row) => reportLinks(actions(row))), [
    [],
    [['Write report', '/my-bookings/demo/b-sam/report']],
    [['Write report', '/my-bookings/diagnostic/b-dev/report']],
    [['Edit report', '/my-bookings/demo/b-ira/report']],
    [],
  ]);
  assert.equal(actions(running).querySelector('a').getAttribute('aria-label'), 'Write report for Sam');
  assert.equal(actions(done).querySelector('a').getAttribute('aria-label'), 'Edit report for Ira');
  // A slot that is over is not a start: never started, it is Not started, with no report to write.
  serve({ [`GET ${MINE}`]: mine([MY_MISSED]) });
  await click(button('Refresh'));
  assert.equal(status(rows()[0]), 'Not started');
  assert.deepEqual(reportLinks(actions(rows()[0])), []);
  assert.equal(button('Start Demo', rows()[0]), undefined);
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET'), 'only reads');
});

test("My Bookings: the sheet's Report section -- what the report waits for, or its version, its PDF and Edit report", async () => {
  const cases = [
    [MY_UPCOMING, 'You can write the report once you start the class.', [], false],
    [MY_RUNNING, 'You have started the class. You can write the report now.', [['Write report', '/my-bookings/demo/b-sam/report']], false],
    [MY_DUE, 'The class is over. The report is due.', [['Write report', '/my-bookings/diagnostic/b-dev/report']], false],
    [MY_DONE, 'Submitted — version 2', [['Edit report', '/my-bookings/demo/b-ira/report']], true],
  ];
  for (const [booking, says, links, pdf] of cases) {
    serve({ [`GET ${MINE}`]: mine([booking]), [`GET ${myAt(booking)}`]: myDetail(booking) });
    const page = await open(`/my-bookings?${opened(booking)}`, TUTOR);
    const section = [...topDialog().querySelectorAll('section')].find((element) => element.querySelector('h3')?.textContent === 'Report');
    assert.ok(section, `a Report section for ${booking.student_name}`);
    assert.equal(clean(section.querySelector('dd').textContent), says);
    assert.deepEqual(reportLinks(section), links);
    assert.equal(Boolean(button('Download PDF', section)), pdf, `PDF for ${booking.student_name}`);
    await page.unmount();
  }
  // A cancelled booking has no report to write.
  serve({ [`GET ${MINE}`]: mine([MY_CANCELLED]), [`GET ${myAt(MY_CANCELLED)}`]: myDetail(MY_CANCELLED) });
  await open(`/my-bookings?${opened(MY_CANCELLED)}`, TUTOR);
  assert.ok(![...topDialog().querySelectorAll('h3')].some((heading) => heading.textContent === 'Report'));
  assert.deepEqual(reportLinks(topDialog()), []);
});

test("My Bookings: a booking completed before Start existed shows no start time, and still offers Edit report and its PDF", async () => {
  const legacy = { ...MY_DONE, started_at: null };
  serve({ [`GET ${MINE}`]: mine([legacy]), [`GET ${myAt(legacy)}`]: myDetail(legacy) });
  await open(`/my-bookings?${opened(legacy)}`, TUTOR);
  const [row] = rows();
  assert.match(clean(row.textContent), /Completed.*Report v2/);
  assert.deepEqual(reportLinks(row), [['Edit report', '/my-bookings/demo/b-ira/report']]);
  const sheet = topDialog();
  assert.match(clean(sheet.textContent), /StartedStart not recorded/);
  assert.ok(![...sheet.querySelectorAll('button')].some((element) => /^Start /.test(clean(element.textContent))), 'no Start');
  const report = [...sheet.querySelectorAll('section')].find((element) => element.querySelector('h3')?.textContent === 'Report');
  assert.equal(clean(report.querySelector('dd').textContent), 'Submitted — version 2');
  assert.deepEqual(reportLinks(report), [['Edit report', '/my-bookings/demo/b-ira/report']]);
  assert.ok(button('Download PDF', report), 'its PDF');
});

test("My Bookings: the sheet downloads the report's PDF from the tutor's own route, or says why it could not", async () => {
  const pdfUrl = '/api/tutor/bookings/demo/b-ira/report/pdf/';
  const saved = [];
  const { createObjectURL, revokeObjectURL } = URL;
  const anchorClick = window.HTMLAnchorElement.prototype.click;
  URL.createObjectURL = () => 'blob:test/1';
  URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function click() {
    saved.push(this.download);
  };
  try {
    let answer = () => ok({ size: 1 });
    serve({
      [`GET ${MINE}`]: mine([MY_DONE]),
      [`GET ${myAt(MY_DONE)}`]: myDetail(MY_DONE),
      [`GET ${pdfUrl}`]: (entry) => answer(entry),
    });
    await open(`/my-bookings?${opened(MY_DONE)}`, TUTOR);
    answer = () => Promise.resolve({ status: 200, data: new Blob(['%PDF-1.7']),
      headers: { 'content-disposition': 'attachment; filename="Demo-Report-Ira-2026-10-31.pdf"' } });
    await click(button('Download PDF', topDialog()));
    assert.equal(calls('GET', pdfUrl).length, 1);
    assert.deepEqual(saved, ['Demo-Report-Ira-2026-10-31.pdf']);

    answer = () => fail(429, new Blob([JSON.stringify({ detail: 'Request was throttled. Expected available in 20 seconds.' })]));
    await click(button('Download PDF', topDialog()));
    assert.match(clean(topDialog().querySelector('[role="alert"]').textContent), /Try again in 20 seconds\./);
    assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url.startsWith('/api/bookings/')),
      "the administrators' API is never called");
  } finally {
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    window.HTMLAnchorElement.prototype.click = anchorClick;
  }
});

// ------------------------------------------------------------ Start Demo / Start Diagnostic (tutors)
// A booking whose Start is open (the API's actions.start), and the same booking as the API answers it once started.
const MY_READY = reportOf({ ...MY_RIYA, id: 'b-zoe', student_name: 'Zoe' }, {},
  { activity_state: 'READY', actions: { start: true }, start_refusal: null });
const startedOf = (booking) => ({ ...booking, ...MY_STARTED });
const startAt = (booking) => `${myAt(booking)}start/`;

/**
 * Records each tab the page opens: what it was opened with, whether it was
 * still linked to the Hub, where it was sent and whether it was closed.
 * `refuse` acts as a browser blocking every new tab.
 */
function watchWindowOpen({ refuse = false } = {}) {
  const opened = [];
  window.open = (...args) => {
    const tab = { args, opener: window, closed: false, sentTo: null };
    tab.location = { replace: (url) => { tab.sentTo = url; } };
    tab.close = () => { tab.closed = true; };
    opened.push(tab);
    return refuse ? null : tab;
  };
  return opened;
}

test('Start: offered only where the API says so, confirmed first; then the list is read again and offers Write report', async () => {
  const windows = watchWindowOpen();
  let listed = [MY_READY, MY_UPCOMING, MY_MISSED];
  serve({
    [`GET ${MINE}`]: () => ok(mine(listed)),
    [`POST ${startAt(MY_READY)}`]: () => {
      listed = [startedOf(MY_READY), MY_UPCOMING, MY_MISSED];
      return ok({ booking: myDetail(startedOf(MY_READY)), changed: true });
    },
  });
  await open('/my-bookings', TUTOR);
  const [ready, upcoming, missed] = rows();
  assert.ok(button('Start Demo for Zoe', ready), 'offered where actions.start');
  assert.equal(button('Start Demo for Riya', upcoming), undefined, 'never just because the time is near');
  assert.equal(button('Start Demo for Kai', missed), undefined, 'nor once the slot is over');
  assert.deepEqual(reportLinks(ready), [], 'no report before the start');

  await click(button('Start Demo for Zoe', ready));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent),
    /^Start Demo\?.*Zoe · Demo class · Sat, 31 Oct · 7:30 PM IST.*started the Demo class now\. It cannot be undone\./);
  assert.match(clean(dialog.textContent), /This booking has no Meet link, so Google Meet will not open\./);
  await click(button('Not yet', dialog));
  assert.equal(calls('POST', startAt(MY_READY)).length, 0, 'Not yet sends nothing');

  await click(button('Start Demo for Zoe', rows()[0]));
  await click(button('Start Demo', topDialog()));
  assert.equal(calls('POST', startAt(MY_READY)).length, 1);
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0, 'the dialog closes');
  assert.equal(calls('GET', MINE).length, 2, 'the list is read again');
  const [started] = rows();
  assert.equal(button('Start Demo for Zoe', started), undefined, 'Start gives way to the report');
  assert.deepEqual(reportLinks(started), [['Write report', '/my-bookings/demo/b-zoe/report']]);
  assert.match(clean(started.textContent), /In progress/);
  assert.deepEqual(windows, [], 'no Meet link, so no tab');
});

test('Start: Google Meet opens in a new tab, opened on the click and sent to the link the API answers with', async () => {
  const windows = watchWindowOpen();
  const linked = { ...MY_READY, tutor_meet_link: MEET };
  // The tutor's link changed since the list was read: the API's answer is the one followed.
  const moved = 'https://meet.google.com/xyz-abcd-efg';
  let atPost = null;
  serve({
    [`GET ${MINE}`]: mine([linked]),
    [`POST ${startAt(linked)}`]: () => {
      atPost = windows.map((tab) => ({ args: tab.args, opener: tab.opener, sentTo: tab.sentTo }));
      return ok({ booking: myDetail({ ...startedOf(linked), tutor_meet_link: moved }), changed: true });
    },
  });
  await open('/my-bookings', TUTOR);
  await click(button('Start Demo for Zoe', rows()[0]));
  assert.match(clean(topDialog().textContent), /It cannot be undone\. Google Meet opens in a new tab\./);
  await click(button('Not yet', topDialog()));
  assert.deepEqual(windows, [], 'Not yet opens nothing');

  await click(button('Start Demo for Zoe', rows()[0]));
  await click(button('Start Demo', topDialog()));
  assert.deepEqual(atPost, [{ args: ['', '_blank'], opener: null, sentTo: null }],
    'a blank tab, cut from the Hub, is open before the API is asked');
  assert.equal(windows.length, 1, 'one tab');
  assert.equal(windows[0].sentTo, moved, "sent to the API's link");
  assert.equal(windows[0].closed, false);
});

test('Start: a refused start closes the tab it opened; a blocked tab still reaches Meet; a link gone by the answer opens nothing', async () => {
  const linked = { ...MY_READY, tutor_meet_link: MEET };
  let windows = watchWindowOpen();
  serve({
    [`GET ${MINE}`]: mine([linked]),
    [`POST ${startAt(linked)}`]: () => fail(409, { error: 'START_WINDOW_CLOSED',
      message: "This booking's slot has ended, so it can no longer be started." }),
  });
  let page = await open('/my-bookings', TUTOR);
  await click(button('Start Demo for Zoe', rows()[0]));
  await click(button('Start Demo', topDialog()));
  assert.match(clean(topDialog().textContent), /The slot has ended/);
  assert.equal(windows.length, 1);
  assert.equal(windows[0].closed, true, 'the blank tab is closed');
  assert.equal(windows[0].sentTo, null, 'and never sent to Meet');
  await page.unmount();

  const answered = (booking) => {
    let listed = [linked];
    return {
      [`GET ${MINE}`]: () => ok(mine(listed)),
      [`POST ${startAt(linked)}`]: () => {
        listed = [booking];
        return ok({ booking: myDetail(booking), changed: true });
      },
    };
  };
  windows = watchWindowOpen({ refuse: true });
  serve(answered(startedOf(linked)));
  page = await open('/my-bookings', TUTOR);
  await click(button('Start Demo for Zoe', rows()[0]));
  await click(button('Start Demo', topDialog()));
  assert.deepEqual(windows.map((tab) => tab.args), [['', '_blank'], [MEET, '_blank', 'noopener,noreferrer']],
    'the blank tab was refused, so Meet is opened directly once started');
  await page.unmount();

  windows = watchWindowOpen();
  serve(answered({ ...startedOf(linked), tutor_meet_link: null }));
  await open('/my-bookings', TUTOR);
  await click(button('Start Demo for Zoe', rows()[0]));
  await click(button('Start Demo', topDialog()));
  assert.equal(windows.length, 1);
  assert.equal(windows[0].closed, true, 'the link was removed meanwhile: the blank tab is closed');
  assert.equal(windows[0].sentTo, null);
  assert.match(clean(rows()[0].textContent), /In progress/, 'the start itself still counts');
});

test("Start: the sheet starts it, then shows when it started and Write report; a Diagnostic says so", async () => {
  let current = MY_READY;
  serve({
    [`GET ${MINE}`]: () => ok(mine([current])),
    [`GET ${myAt(MY_READY)}`]: () => ok(myDetail(current)),
    [`POST ${startAt(MY_READY)}`]: () => {
      current = startedOf(MY_READY);
      return ok({ booking: myDetail(current), changed: true });
    },
  });
  const page = await open(`/my-bookings?${opened(MY_READY)}`, TUTOR);
  let sheet = topDialog();
  assert.match(clean(sheet.textContent), /StartedNot started/);
  await click(button('Start Demo for Zoe', sheet));
  await click(button('Start Demo', topDialog()));
  sheet = topDialog();
  assert.match(clean(sheet.textContent), /StartedStarted 31 Oct 2026, 7:32 PM IST/);
  assert.equal(button('Start Demo for Zoe', sheet), undefined);
  const report = [...sheet.querySelectorAll('section')].find((element) => element.querySelector('h3')?.textContent === 'Report');
  assert.deepEqual(reportLinks(report), [['Write report', '/my-bookings/demo/b-zoe/report']]);
  await page.unmount();

  const diagnostic = { ...MY_READY, id: 'b-dia', booking_type: 'DIAGNOSTIC', student_name: 'Dia' };
  serve({ [`GET ${MINE}`]: mine([diagnostic]), [`GET ${myAt(diagnostic)}`]: myDetail(diagnostic) });
  await open(`/my-bookings?${opened(diagnostic)}`, TUTOR);
  await click(button('Start Diagnostic for Dia', topDialog()));
  assert.match(clean(topDialog().textContent), /^Start Diagnostic\?/);
});

test('Start: an early booking says when Start opens; a refusal shows in the dialog and the list is read again once it closes', async () => {
  serve({ [`GET ${MINE}`]: mine([MY_UPCOMING]), [`GET ${myAt(MY_UPCOMING)}`]: myDetail(MY_UPCOMING) });
  const page = await open(`/my-bookings?${opened(MY_UPCOMING)}`, TUTOR);
  assert.match(clean(topDialog().textContent), /You can start from 31 Oct 2026, 7:25 PM IST\./);
  await page.unmount();

  serve({
    [`GET ${MINE}`]: mine([MY_READY]),
    [`POST ${startAt(MY_READY)}`]: () => fail(409, { error: 'START_WINDOW_CLOSED',
      message: "This booking's slot has ended, so it can no longer be started." }),
  });
  await open('/my-bookings', TUTOR);
  const reads = calls('GET', MINE).length;
  await click(button('Start Demo for Zoe', rows()[0]));
  await click(button('Start Demo', topDialog()));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /The slot has ended, so this booking can no longer be started\./);
  assert.ok(button('Start Demo', dialog).disabled, 'not offered again');
  assert.equal(calls('GET', MINE).length, reads, 'read again only once the dialog closes');
  await click(button('Not yet', dialog));
  assert.equal(calls('GET', MINE).length, reads + 1);
});

test('Start: the Admin and the BDE read whether a booking was started, and are never offered Start', async () => {
  const started = { ...ARUN, activity_state: 'IN_PROGRESS', started_at: '2026-11-01T14:02:00+00:00' };
  const late = { ...RIYA, activity_state: 'LATE' };
  serve({
    [`GET ${LIST}`]: list([started, late]),
    [`GET ${at(started)}`]: detail(started, { started_by: { id: 't-b', full_name: 'Tutor B' }, tutor_changeable: false,
      tutor_change_refusal: { code: 'BOOKING_STARTED', message: 'This booking has already started, so its tutor cannot be changed.' } }),
  });
  const page = await open(`/bookings?booking=${started.id}`, ADMIN);
  const [first, second] = rows();
  assert.match(clean(first.textContent), /Arun.*In progress/);
  assert.match(clean(second.textContent), /Riya.*Not started yet/);
  assert.match(clean(topDialog().textContent), /StartedStarted 1 Nov 2026, 7:32 PM IST by Tutor B/);
  assert.ok(![...document.querySelectorAll('button')].some((element) => /^Start /.test(clean(element.textContent))), 'no Start');
  await page.unmount();

  const taught = { ...BDE_BOOKED, ended: true, activity_state: 'IN_PROGRESS', started_at: '2026-10-31T14:02:00+00:00' };
  const missed = { ...BDE_BOOKED, id: 'b-5', date: '2026-10-30', ended: true, activity_state: 'NOT_STARTED' };
  serve({ [`GET ${ENQUIRY_URL}`]: enquiry([taught, missed]) });
  await open('/enquiries/lead-1?tab=bookings', BDE);
  const [firstRow, secondRow] = bookingRows();
  assert.match(firstRow, /In progressStarted 31 Oct 2026, 7:32 PM IST/);
  assert.match(secondRow, /Not started/);
  assert.ok(!/Done/.test(secondRow), 'a slot that is over is never Done by itself');
  assert.ok(![...document.querySelectorAll('button')].some((element) => /^Start /.test(clean(element.textContent))), 'no Start');
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET'), 'only reads');
});

test('My Bookings: a report-aware booking still shows nothing of the parent, whatever else the API sends', async () => {
  const leaky = { ...MY_DONE, ...PRIVATE };
  serve({ [`GET ${MINE}`]: mine([leaky]), [`GET ${myAt(MY_DONE)}`]: myDetail(leaky) });
  await open(`/my-bookings?${opened(MY_DONE)}`, TUTOR);
  const text = bodyText();
  assert.ok(text.includes('Submitted — version 2') && text.includes('Edit report'), 'the report is shown');
  for (const value of PRIVATE_TEXT) {
    assert.ok(!text.includes(value), `${value} is not rendered`);
  }
});

test('My Bookings opens only for the Tutor role holding accounts.view_assigned_bookings', async () => {
  const account = (role, permissions, extra = {}) => ({ role, permissions, is_superuser: false, ...extra });
  assert.ok(canOpenPage(account('TUTOR', [VIEW_ASSIGNED]), '/my-bookings'), 'a tutor holding it');
  assert.ok(canOpenPage(account('TUTOR', [VIEW_ASSIGNED], { is_superuser: true }), '/my-bookings'),
    'a superuser with the Tutor role, who may be assigned bookings');
  const refused = {
    'a tutor without it': account('TUTOR', ['accounts.view_staff_dashboard', 'accounts.view_tutored_sessions']),
    // A superuser holds every permission (D1); the role decides.
    'a superuser with the Admin role': account('ADMIN', [VIEW_ASSIGNED, 'accounts.view_all_bookings'], { is_superuser: true }),
    'a superuser with the Mentor role': account('MENTOR', [VIEW_ASSIGNED], { is_superuser: true }),
    // Even holding it, no other role is offered the page.
    'an administrator': account('ADMIN', [VIEW_ASSIGNED, 'accounts.view_all_bookings', 'accounts.assign_booking_tutor']),
    'a mentor': account('MENTOR', [VIEW_ASSIGNED]),
    'a BDE': account('BDE', [VIEW_ASSIGNED, 'accounts.view_own_enquiries']),
    'a Sales TL': account('SALES_TL', [VIEW_ASSIGNED]),
    'a student': account('STUDENT', [VIEW_ASSIGNED]),
    'an unknown role': account('UNASSIGNED', [VIEW_ASSIGNED]),
    'nobody signed in': null,
  };
  for (const [who, user] of Object.entries(refused)) {
    assert.ok(!canOpenPage(user, '/my-bookings'), `not for ${who}`);
  }
  // Tutors keep their dashboard as home; the page is home only to a tutor with nothing else.
  assert.equal(homePage(TUTOR), '/dashboard');
  assert.equal(homePage(account('TUTOR', [VIEW_ASSIGNED])), '/my-bookings');
  // And the administrators' page stays theirs.
  assert.ok(!canOpenPage(TUTOR, '/bookings'));
});

// ------------------------------------------- a tutor's permanent Meet link (Phase 1)
const MEET = 'https://meet.google.com/abc-defg-hij';
const MEET_PROBLEM = 'Enter a Google Meet link such as https://meet.google.com/abc-defg-hij.';
const MANAGE_TEAM = 'accounts.manage_team';
const MANAGER = { ...ADMIN, permissions: [...ADMIN.permissions, MANAGE_TEAM, 'accounts.view_team'] };
const MEMBER_URL = '/api/team/t-a/';
const MEET_LINK_URL = '/api/team/t-a/meet-link/';
// A tutor's account as a team manager reads it (backend accounts.team.member_payload, full).
const member = (extra = {}) => ({ id: 't-a', username: 'tutor.a', email: 'a@hub.test', full_name: 'Tutor A', mobile_number: '',
  role: 'TUTOR', is_active: true, deactivated_at: null, created_at: '2026-10-01T09:00:00+00:00', is_superuser: false,
  deactivation_reason: null, must_change_password: false, has_password: true, locked_until: null, last_login: null,
  invited_by: null, permissions: [], tutor_meet_link: null, ...extra });
const meetInput = () => document.getElementById('team-member-meet-link');
const anchors = (root = document.body) => [...root.querySelectorAll('a[href]')].map((a) => [a.getAttribute('href'),
  a.getAttribute('target'), a.getAttribute('rel')]);

test("Meet link: the Hub's check mirrors the API's, and a role change never carries a Meet link", async () => {
  for (const good of [MEET, 'meet.google.com/ABC-defg-hij', `${MEET}?authuser=0`, `${MEET}/`, '', '   ']) {
    assert.equal(meetLinkProblem(good), null, good);
  }
  for (const bad of ['http://meet.google.com/abc-defg-hij', 'https://meet.google.com/new', 'https://zoom.us/j/1',
    'https://meet.google.com.example.test/abc-defg-hij', `${MEET}/extra`]) {
    assert.equal(meetLinkProblem(bad), MEET_PROBLEM, bad);
  }
  const tutor = member({ tutor_meet_link: MEET });
  const values = { username: 'tutor.a', full_name: 'Tutor A', email: 'a@hub.test', mobile_number: '', permissions: [],
    password: '', meet_link: '' };
  assert.deepEqual(planMemberSave(tutor, { ...values, role: 'TUTOR' }).meetLink, { tutor_meet_link: null }, 'blank removes it');
  assert.equal(planMemberSave(tutor, { ...values, role: 'MENTOR' }).meetLink, null, 'the role change drops it on its own');
  assert.equal(planMemberSave(member({ role: 'MENTOR' }), { ...values, role: 'MENTOR', meet_link: MEET }).meetLink, null);
});

test("Team: a team manager sets a tutor's permanent Meet link with its own PUT, checked first; a refusal shows at the field", async () => {
  let refuse = false;
  serve({
    [`GET ${MEMBER_URL}`]: member(),
    'GET /api/team/permissions/': [],
    [`PUT ${MEET_LINK_URL}`]: (entry) => (refuse
      ? fail(400, { error: 'INVALID_MEET_LINK', message: 'The API refused this link.', fields: ['tutor_meet_link'] })
      : ok(member({ tutor_meet_link: entry.data.tutor_meet_link ? MEET : null }))),
  });
  await open('/team/t-a', MANAGER);
  assert.ok(meetInput(), 'a tutor has the field');
  assert.equal(meetInput().value, '');
  assert.match(bodyText(), /permanent room for their Demo and Diagnostic bookings/);
  const form = meetInput().closest('form');

  await typeInto(meetInput(), 'https://zoom.us/j/1');
  await submit(form);
  assert.ok(bodyText().includes(MEET_PROBLEM), 'the field says what is expected');
  assert.equal(calls('PUT', MEET_LINK_URL).length, 0, 'an unrelated link is not sent');

  await typeInto(meetInput(), 'meet.google.com/abc-defg-hij');
  await submit(form);
  assert.deepEqual(calls('PUT', MEET_LINK_URL).map((entry) => entry.data), [{ tutor_meet_link: 'meet.google.com/abc-defg-hij' }]);
  assert.equal(globalThis.__bookingsApi.calls.filter((entry) => entry.method === 'PATCH').length, 0, 'never through the details PATCH');
  assert.equal(meetInput().value, MEET, 'the link as the API stored it');
  assert.match(bodyText(), /Changes saved\./);

  await typeInto(meetInput(), '');
  await submit(form);
  assert.deepEqual(calls('PUT', MEET_LINK_URL).at(-1).data, { tutor_meet_link: null }, 'blank removes it');

  refuse = true;
  await typeInto(meetInput(), MEET);
  await submit(form);
  assert.ok(meetInput().getAttribute('aria-invalid'), 'the field is marked');
  assert.match(bodyText(), /The API refused this link\./);
});

test('Team: no Meet link field for another role, or for a directory reader', async () => {
  serve({ [`GET ${MEMBER_URL}`]: member({ role: 'MENTOR' }), 'GET /api/team/permissions/': [] });
  const page = await open('/team/t-a', MANAGER);
  assert.ok(!meetInput(), 'a mentor has none');
  await page.unmount();
  // A directory reader (accounts.view_team) is sent no Meet link at all, so is offered none.
  const { tutor_meet_link: _hidden, permissions: _p, ...readable } = member({ tutor_meet_link: MEET });
  serve({ [`GET ${MEMBER_URL}`]: readable });
  await open('/team/t-a', { id: 'reader', role: 'MENTOR', permissions: ['accounts.view_team'] });
  assert.match(bodyText(), /Tutor A/);
  assert.ok(!meetInput());
  assert.ok(!bodyText().includes('meet.google.com'));
});

test("Bookings sheet: the booking's Meet link, or that none is configured; a team manager sets it and the sheet reads it again", async () => {
  let saved = false;
  serve({
    [`GET ${DIAGNOSTIC_LIST}`]: list([ALI]),
    [`GET ${at(ALI)}`]: () => ok(detail(ALI, { tutor_meet_link: saved ? MEET : null })),
    [`PUT ${MEET_LINK_URL}`]: () => {
      saved = true;
      return ok(member({ tutor_meet_link: MEET }));
    },
  });
  await open(`/bookings?type=DIAGNOSTIC&booking=${ALI.id}`, MANAGER);
  assert.match(clean(topDialog().textContent), /Meet linkMeet link not configured/);
  await click(button('Set Meet link', topDialog()));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /^Set Meet link.*Tutor A's permanent Google Meet link\..*other bookings the tutor has not started yet use it\. Started and past bookings keep the link they had\./);
  const input = dialog.querySelector('#booking-meet-link');
  const form = document.getElementById('booking-meet-link-form');

  await submit(form);
  assert.match(clean(topDialog().textContent), /Enter the tutor's Google Meet link\./, 'a link is required here');
  await typeInto(input, 'https://zoom.us/j/1');
  await submit(form);
  assert.ok(clean(topDialog().textContent).includes(MEET_PROBLEM));
  assert.equal(calls('PUT', MEET_LINK_URL).length, 0, 'nothing is sent until it is a Google Meet link');

  await typeInto(input, MEET);
  await submit(form);
  assert.deepEqual(calls('PUT', MEET_LINK_URL).map((entry) => entry.data), [{ tutor_meet_link: MEET }]);
  assert.equal(calls('GET', at(ALI)).length, 2, 'the booking is read again');
  const sheet = topDialog();
  assert.match(clean(sheet.textContent), /Meet linkmeet\.google\.com\/abc-defg-hij/);
  assert.deepEqual(anchors(sheet), [[MEET, '_blank', 'noopener noreferrer']]);
  assert.ok(button('Change Meet link', sheet));
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url.startsWith('/api/bde/')), "never a BDE's route");
});

test("Bookings sheet: the API's refusal is shown in the dialog; nobody but a team manager is offered the change", async () => {
  serve({
    [`GET ${DIAGNOSTIC_LIST}`]: list([ALI]),
    [`GET ${at(ALI)}`]: detail(ALI, { tutor_meet_link: MEET }),
    [`PUT ${MEET_LINK_URL}`]: () => fail(403, { detail: 'You do not have permission to perform this action.' }),
  });
  let page = await open(`/bookings?type=DIAGNOSTIC&booking=${ALI.id}`, MANAGER);
  await click(button('Change Meet link', topDialog()));
  assert.equal(topDialog().querySelector('#booking-meet-link').value, MEET, 'the current link to edit');
  await submit(document.getElementById('booking-meet-link-form'));
  assert.match(clean(topDialog().textContent), /You do not have permission to perform this action\./);
  await page.unmount();

  // Without accounts.manage_team the link is shown, never offered for change.
  page = await open(`/bookings?type=DIAGNOSTIC&booking=${ALI.id}`, ADMIN);
  assert.deepEqual(anchors(topDialog()), [[MEET, '_blank', 'noopener noreferrer']]);
  assert.ok(!button('Change Meet link') && !button('Set Meet link'));
  await page.unmount();

  // A booking its tutor has started keeps its room (backend set_tutor_meet_link): shown, not changed from here.
  const started = { ...ALI, activity_state: 'IN_PROGRESS', started_at: '2026-11-01T04:32:00+00:00' };
  serve({ [`GET ${DIAGNOSTIC_LIST}`]: list([started]),
    [`GET ${at(ALI)}`]: detail(started, { tutor_meet_link: MEET, started_by: { id: 't-a', full_name: 'Tutor A' } }) });
  page = await open(`/bookings?type=DIAGNOSTIC&booking=${ALI.id}`, MANAGER);
  assert.match(clean(topDialog().textContent), /meet\.google\.com\/abc-defg-hij/);
  assert.match(clean(topDialog().textContent), /StartedStarted 1 Nov 2026, 10:02 AM IST by Tutor A/);
  assert.ok(!button('Change Meet link') && !button('Set Meet link'), 'no change offered once started');
  await page.unmount();

  // A booking whose slot has ended keeps its link: shown, not changed from here.
  const ended = { ...ALI, slot: { ...ALI.slot, started: true, ended: true } };
  serve({ [`GET ${DIAGNOSTIC_LIST}`]: list([ended]), [`GET ${at(ALI)}`]: detail(ended, { tutor_meet_link: MEET }) });
  page = await open(`/bookings?type=DIAGNOSTIC&booking=${ALI.id}&when=past`, MANAGER);
  assert.match(clean(topDialog().textContent), /meet\.google\.com\/abc-defg-hij/);
  assert.ok(!button('Change Meet link'));
  await page.unmount();

  // A booking with no tutor has no Meet link to show.
  serve({ [`GET ${LIST}`]: list([RIYA]), [`GET ${at(RIYA)}`]: detail(RIYA) });
  await open(`/bookings?booking=${RIYA.id}`, MANAGER);
  assert.ok(!clean(topDialog().textContent).includes('Meet link'));
  assert.equal(calls('PUT', MEET_LINK_URL).length, 1, 'only the refused attempt');
});

test("BDE: each booking shows who teaches it and its Meet link to read, or that none is set; nothing changes either", async () => {
  const withLink = { ...BDE_BOOKED, tutor: { full_name: 'Tutor A' }, tutor_meet_link: MEET };
  const noLink = { ...BDE_BOOKED, id: 'b-3', date: '2026-11-02', tutor: { full_name: 'Tutor B' }, tutor_meet_link: null };
  const noTutor = { ...BDE_BOOKED, id: 'b-4', date: '2026-11-03', tutor: null, tutor_meet_link: null };
  const cancelled = { ...BDE_CANCELLED, tutor: null, tutor_meet_link: null };
  serve({ [`GET ${ENQUIRY_URL}`]: enquiry([withLink, noLink, noTutor, cancelled]) });
  await open('/enquiries/lead-1?tab=bookings', BDE);
  assert.deepEqual([...document.querySelectorAll('th')].map((th) => clean(th.textContent)),
    ['When (IST)', 'Type', 'Status', 'Tutor', 'Booked on', 'Actions']);
  const [first, second, third, fourth] = bookingRows();
  assert.match(first, /Tutor Ameet\.google\.com\/abc-defg-hij/);
  assert.match(second, /Tutor BMeet link not configured/);
  assert.match(third, /Not assigned yet/);
  assert.match(fourth, /Cancelled—/);
  assert.deepEqual(anchors(document.querySelector('tbody')), [[MEET, '_blank', 'noopener noreferrer']]);
  assert.ok(![...document.querySelectorAll('button')].some((element) => /meet/i.test(clean(element.textContent))),
    'no way to change a Meet link');
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET' && entry.url.startsWith('/api/bde/')),
    "only the BDE's own reads");
});

test('My Bookings: the Meet link to open, in the list and the sheet; none configured says whom to ask', async () => {
  const withLink = { ...MY_RIYA, tutor_meet_link: MEET };
  const noLink = { ...MY_RIYA, id: 'b-sam', student_name: 'Sam', tutor_meet_link: null };
  serve({
    [`GET ${MINE}`]: mine([withLink, noLink, { ...MY_ALI, tutor_meet_link: MEET }]),
    [`GET ${myAt(withLink)}`]: myDetail(withLink),
    [`GET ${myAt(noLink)}`]: myDetail(noLink),
    [`GET ${myAt(MY_ALI)}`]: myDetail({ ...MY_ALI, tutor_meet_link: MEET }),
  });
  let page = await open(`/my-bookings?${opened(withLink)}`, TUTOR);
  const [riya, sam, ali] = rows();
  assert.deepEqual(anchors(riya), [[MEET, '_blank', 'noopener noreferrer']]);
  assert.equal(riya.querySelector('a[href]').getAttribute('aria-label'), "Open the Meet link for Riya's booking");
  assert.match(clean(sam.textContent), /Not configured/);
  assert.equal(ali.querySelectorAll('a[href]').length, 0, 'a cancelled booking has no class to join');
  assert.match(clean(topDialog().textContent), /Meet linkmeet\.google\.com\/abc-defg-hij/);
  assert.deepEqual(anchors(topDialog()), [[MEET, '_blank', 'noopener noreferrer']]);
  await page.unmount();

  page = await open(`/my-bookings?${opened(noLink)}`, TUTOR);
  assert.match(clean(topDialog().textContent), /Meet link not configured.*Ask an administrator to add your link\./);
  await page.unmount();
  await open(`/my-bookings?${opened(MY_ALI)}`, TUTOR);
  assert.ok(!clean(topDialog().textContent).includes('Meet link'), 'nothing to join on a cancelled booking');
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET'), 'only reads');
});

test('Activity feed: a Meet link change says how it changed and how many bookings took it, never the link', async () => {
  const entry = (action, context, changes = {}) => ({ action, context, changes });
  assert.equal(actionLabel('user.meet_link_update'), 'Meet link updated');
  assert.equal(describeActivity(entry('user.meet_link_update', { change: 'added', live_bookings_updated: 0 })),
    "Set the tutor's Google Meet link");
  assert.equal(describeActivity(entry('user.meet_link_update', { change: 'changed', live_bookings_updated: 2 })),
    "Changed the tutor's Google Meet link; 2 bookings not yet ended now use it");
  assert.equal(describeActivity(entry('user.meet_link_update', { change: 'added', live_bookings_updated: 1 })),
    "Set the tutor's Google Meet link; 1 booking not yet ended now uses it");
  assert.equal(describeActivity(entry('user.meet_link_update', { change: 'removed', live_bookings_updated: 3 })),
    "Removed the tutor's Google Meet link");
  assert.equal(describeActivity(entry('user.role_change', { meet_link_removed: true }, { role: { old: 'TUTOR', new: 'MENTOR' } })),
    'Changed role from Tutor to Mentor; their Meet link was removed');
});

// ------------------------------------------------------------ activity feed
test('Activity feed: tutor changes on bookings are labelled and described, naming nobody', async () => {
  const entry = (action, context) => ({ action, context, changes: {} });
  assert.equal(actionLabel('booking.assign_tutor'), 'Tutor assigned');
  assert.equal(actionLabel('booking.unassign_tutor'), 'Tutor unassigned');
  assert.equal(describeActivity(entry('booking.assign_tutor', { booking_type: 'DEMO', old_tutor_id: null, new_tutor_id: 't-1' })),
    'Assigned a tutor to a demo booking');
  assert.equal(describeActivity(entry('booking.assign_tutor', { booking_type: 'DIAGNOSTIC', old_tutor_id: 't-1', new_tutor_id: 't-2' })),
    'Reassigned the tutor of a diagnostic booking');
  assert.equal(describeActivity(entry('booking.unassign_tutor', { booking_type: 'DEMO', old_tutor_id: 't-2', new_tutor_id: null })),
    'Unassigned the tutor from a demo booking');
  assert.equal(describeActivity(entry('booking.unassign_tutor', {})), 'Unassigned the tutor from a booking');
  // Cancellations by their reason code (P3); entries from before keep the text they were given.
  assert.equal(describeActivity(entry('booking.cancel', { booking_type: 'DEMO', reason_code: 'NO_SHOW' })), 'Cancelled the booking — No-show');
  assert.equal(describeActivity(entry('booking.cancel', { booking_type: 'DEMO', reason: 'Cancelled in the Django admin.' })),
    'Cancelled the booking — Cancelled in the Django admin.');
  assert.equal(actionLabel('booking.reschedule'), 'Booking rescheduled');
  assert.equal(describeActivity(entry('booking.reschedule', { booking_type: 'DEMO', reason_code: 'PARENT_REQUEST', tutor_id: 't-1',
    tutor_carried_over: true })), 'Rescheduled a demo booking — Parent asked to move; the tutor carried over');
  assert.equal(describeActivity(entry('booking.reschedule', { booking_type: 'DIAGNOSTIC', reason_code: 'OTHER', tutor_id: 't-1',
    tutor_carried_over: false })), 'Rescheduled a diagnostic booking — Other; the tutor was not free, so it needs one');
  // Reports (P6): ids, the version and field names only, never a report's text.
  assert.equal(actionLabel('booking.complete'), 'Booking completed');
  assert.equal(actionLabel('report.submit'), 'Report submitted');
  assert.equal(actionLabel('report.edit'), 'Report edited');
  assert.equal(describeActivity(entry('booking.complete', { booking_type: 'DEMO', report_id: 'r-1' })),
    'Completed a demo booking with its report');
  assert.equal(describeActivity(entry('report.submit', { booking_type: 'DIAGNOSTIC', version: 1 })),
    'Submitted the report on a diagnostic booking');
  assert.equal(describeActivity(entry('report.edit', { booking_type: 'DIAGNOSTIC', version: 3,
    changed_fields: ['score', 'teacher_remarks', 'grade_snapshot'] })),
    "Edited the report on a diagnostic booking, now version 3 — Score, Teacher's remarks, Grade");
  assert.equal(describeActivity(entry('report.edit', {})), 'Edited the report on a booking');
  // The action filter offers every label: only actions something logs today.
  for (const later of ['conversion.stage', 'conversion.enrol']) {
    assert.ok(!(later in ACTION_LABELS), `${later} is labelled once something logs it`);
  }
  // Leads are logged since lead management (backend bookings.lead_intake, bookings.ownership).
  assert.equal(actionLabel('lead.create'), 'Lead added');
  assert.equal(actionLabel('lead.assign_owner'), 'Lead assigned');
  assert.equal(describeActivity(entry('lead.create', { source: 'WEBSITE', via: 'lead_form' })), 'Received a lead from the website');
  assert.equal(describeActivity(entry('lead.create', { source: 'PHONE_CALL', via: 'admin_leads' })), 'Added a lead (phone call)');
  assert.equal(describeActivity(entry('lead.assign_owner', { previous_owner_id: null, owner_id: 'bde-1' })), 'Assigned a lead to a BDE');
  assert.equal(describeActivity(entry('lead.assign_owner', { previous_owner_id: 'bde-1', owner_id: 'bde-2' })),
    'Reassigned a lead to another BDE');
  // A lead's student time zone, set or corrected (backend bookings.student_timezones): the old zone and the new,
  // labelled apart from a student profile's timezone in the action filter.
  const zone = (old, now) => ({ action: 'lead.update_student_timezone', entity_type: 'lead', context: { via: 'bde_workspace' },
    changes: { student_timezone: { old, new: now } } });
  assert.equal(actionLabel('lead.update_student_timezone'), 'Student timezone changed');
  assert.notEqual(ACTION_LABELS['lead.update_student_timezone'], ACTION_LABELS['student.update_timezone']);
  assert.equal(describeActivity(zone(null, 'Asia/Dubai')), "Changed the student's timezone from — to Asia/Dubai");
  assert.equal(describeActivity(zone('Asia/Dubai', 'America/New_York')),
    "Changed the student's timezone from Asia/Dubai to America/New_York");
  assert.equal(describeActivity(zone('America/New_York', null)), "Changed the student's timezone from America/New_York to —");
  assert.equal(describeActivity(entry('lead.update_student_timezone', { via: 'admin_leads' })), "Changed the student's timezone");
});

// ------------------------------------------------ parent communication (Phase 3.1)
// A booking's communication as GET /api/communications/bookings/<type>/<id>/ answers it (backend communications.overview),
// read-only: administrators see every booking's (accounts.view_all_communications), a BDE their own leads'.
const COMMS_ADMIN = { ...ADMIN, id: 'comms-admin', permissions: [...ADMIN.permissions, 'accounts.view_all_communications'] };
const BDE_COMMS = { ...BDE, id: 'bde-comms', permissions: [...BDE.permissions, 'accounts.view_own_lead_communications'] };
const BDE_ONE = { id: 'bde-1', full_name: 'Bde One' };
const commsUrl = (booking) => `/api/communications/bookings/${booking.booking_type.toLowerCase()}/${booking.id}/`;
const commTask = (step, step_label, extra = {}) => ({ id: `task-${step}`, step, step_label, status: 'OPEN', status_label: 'Open',
  resolution: '', resolution_label: '', owner_role: 'BDE', owner: BDE_ONE, active_from: '2026-10-28T09:00:00+00:00', due_at: null,
  expires_at: '2026-10-31T14:00:00+00:00', overdue: false, resolved_at: null, resolved_by: null, ...extra });
const commMessage = (step, step_label, extra = {}) => ({ id: `msg-${step}`, step, step_label, status: 'PENDING', status_label: 'Pending',
  channel: '', channel_label: '', provider: '', recipient_phone: '+971501234567', text: '', waiting_for: [], scheduled_for: null,
  send_before: '2026-10-31T14:00:00+00:00', queued_at: null, sent_at: null, delivered_at: null, read_at: null, failed_at: null,
  cancelled_at: null, attempt_count: 0, next_attempt_at: null, failure_code: '', failure_reason: '', problem: null, cancel_reason: null,
  created_by: null, created_at: '2026-10-28T09:00:00+00:00', attempts: [], events: [], ...extra });
const metaReport = (status, status_label, at) => ({ status, status_label, provider_status: status.toLowerCase(), occurred_at: at,
  received_at: at, error_code: '', error_message: '' });
const communication = (booking, extra = {}) => ({
  booking: { id: booking.id, booking_type: booking.booking_type, status: 'BOOKED', status_label: 'Booked', slot: RIYA.slot,
    student_name: 'Riya', parent_name: 'Asha Nair', phone: '+971 501234567', owner_bde: BDE_ONE, tutor: null },
  timezone: 'Asia/Kolkata', planned: true,
  parent_confirmation: { status: 'CONFIRMED', label: 'Confirmed', at: '2026-10-29T10:30:00+00:00', by: BDE_ONE, reason: null },
  tasks: [
    commTask('ACKNOWLEDGEMENT', 'Initial acknowledgement', { status: 'DONE', status_label: 'Done', resolution: 'ACCEPTED',
      resolution_label: 'Accepted by the provider (queued, not yet sent)', resolved_at: '2026-10-28T09:01:00+00:00' }),
    commTask('CONFIRMATION_REQUEST', 'Confirmation request', { status: 'MISSED', status_label: 'Missed', resolved_at: '2026-10-31T14:00:00+00:00' }),
    commTask('PARENT_CONFIRMATION', 'Parent confirmation', { due_at: '2026-10-31T14:00:00+00:00', overdue: true }),
    commTask('PRE_ACTIVITY_CALL', 'Pre-activity call', { active_from: '2026-10-31T13:45:00+00:00', due_at: '2026-10-31T14:00:00+00:00',
      expires_at: '2026-10-31T15:00:00+00:00' }),
    commTask('AFTER_ACTIVITY', 'After-activity message', { active_from: null, expires_at: null }),
  ],
  messages: [
    commMessage('ACKNOWLEDGEMENT', 'Initial acknowledgement', { status: 'READ', status_label: 'Read', channel: 'WHATSAPP',
      channel_label: 'WhatsApp', provider: 'meta', text: 'Hi, your Demo class on *Sat, 31 Oct 2026 at 7:30 PM IST* is booked.',
      attempt_count: 1,
      queued_at: '2026-10-28T09:01:00+00:00', sent_at: '2026-10-28T09:02:00+00:00', delivered_at: '2026-10-28T09:03:00+00:00',
      read_at: '2026-10-28T09:10:00+00:00',
      attempts: [{ number: 1, outcome: 'ACCEPTED', outcome_label: 'Accepted by the provider', channel: 'WHATSAPP', provider: 'meta',
        started_at: '2026-10-28T09:01:00+00:00', finished_at: '2026-10-28T09:01:00+00:00', error_code: '', error_message: '',
        retryable: false, triggered_by: null }],
      events: [metaReport('SENT', 'Sent', '2026-10-28T09:02:00+00:00'), metaReport('DELIVERED', 'Delivered', '2026-10-28T09:03:00+00:00'),
        metaReport('READ', 'Read', '2026-10-28T09:10:00+00:00')] }),
    commMessage('CONFIRMATION_REQUEST', 'Confirmation request', { status: 'FAILED', status_label: 'Failed', channel: 'WHATSAPP',
      channel_label: 'WhatsApp', provider: 'meta', queued_at: '2026-10-29T08:00:00+00:00', failed_at: '2026-10-29T08:01:00+00:00',
      failure_code: '131026', failure_reason: 'Permanent delivery failure: Message undeliverable', attempt_count: 1,
      problem: { code: 'DELIVERY_FAILED', label: 'Accepted, then not delivered' }, created_by: BDE_ONE }),
    commMessage('PARENT_CONFIRMATION', 'Parent confirmation', { status: 'WAITING', status_label: 'Waiting',
      waiting_for: [{ code: 'TUTOR_ASSIGNED', label: 'Tutor assigned' }, { code: 'MEET_LINK', label: 'Tutor Meet link' }] }),
  ],
  actions: { request_confirmation: false, record_confirmation: true },
  ...extra,
});
const communicationCard = () => [...document.querySelectorAll('[role="dialog"] section')]
  .find((section) => clean(section.querySelector('h3')?.textContent) === 'Communication');
const listItems = (list) => [...list.children].map((item) => clean(item.textContent));

test("Communication: an administrator reads the booking's communication in its sheet, read-only, every moment in IST", async () => {
  serve({ [`GET ${LIST}`]: list([RIYA]), [`GET ${at(RIYA)}`]: detail(RIYA), [`GET ${commsUrl(RIYA)}`]: communication(RIYA) });
  await open(`/bookings?booking=${RIYA.id}`, COMMS_ADMIN);
  assert.equal(calls('GET', commsUrl(RIYA)).length, 1);
  const card = communicationCard();
  assert.ok(card, 'a Communication card after the Booking card');
  const titles = [...topDialog().querySelectorAll('section h3')].map((title) => clean(title.textContent));
  assert.equal(titles[titles.indexOf('Booking') + 1], 'Communication');
  // Three parts, nothing more: the parent's confirmation, the five steps and the messages.
  assert.deepEqual([...card.querySelectorAll('h4')].map((title) => clean(title.textContent)),
    ['Parent confirmation', 'Communication steps', 'Message history']);
  assert.match(clean(card.textContent), /Parent confirmationRecord answerStatusConfirmedRecorded29 Oct 2026, 4:00 PM IST · by Bde One/);

  // Each step by its status and its moment -- the call too: a task, with nothing to record on it.
  const [steps, messages] = card.querySelectorAll('ol');
  assert.deepEqual(listItems(steps), [
    'Initial acknowledgementDoneSent · 28 Oct 2026, 2:31 PM IST',
    'Confirmation requestMissedTime ran out 31 Oct 2026, 7:30 PM IST',
    'Confirmed messageOverdueDue 31 Oct 2026, 7:30 PM IST',
    'Pre-activity BDE callOpenDue 31 Oct 2026, 7:30 PM IST',
    'After-activity messageOpenAfter the class',
  ]);
  // Each message by its status and when it got there; why one failed, inline.
  assert.deepEqual(listItems(messages), [
    'Initial acknowledgementRead28 Oct 2026, 2:40 PM ISTShow details',
    'Confirmation requestFailed29 Oct 2026, 1:31 PM ISTPermanent delivery failure: Message undeliverable (131026)Show details',
    'Confirmed messageWaitingWaiting for: Tutor assigned, Tutor Meet link',
  ]);

  // On request: the text as it went and each moment it went through.
  await click(button('Show the details of the initial acknowledgement', card));
  // WhatsApp's bold, as the preview shows it -- never the template's ** markers.
  assert.ok(clean(messages.children[0].textContent).includes('Hi, your Demo class on *Sat, 31 Oct 2026 at 7:30 PM IST* is booked.'
    + 'Sent to WhatsApp28 Oct 2026, 2:31 PM IST'
    + 'Sent28 Oct 2026, 2:32 PM ISTDelivered28 Oct 2026, 2:33 PM ISTRead28 Oct 2026, 2:40 PM ISTAttempts1'));
  await click(button('Show the details of the confirmation request', card));
  assert.ok(clean(messages.children[1].textContent).includes('Sent to WhatsApp29 Oct 2026, 1:30 PM IST'
    + 'Failed29 Oct 2026, 1:31 PM ISTAttempts1Requested byBde One'));
  // Nothing to press but the details and what the API offers: the answer may be recorded, nothing is to be asked.
  assert.deepEqual([...card.querySelectorAll('button')].map((element) => clean(element.textContent))
    .filter((label) => !/^(Show|Hide) details$/.test(label)), ['Record answer']);
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET'), 'nothing but reads');
});

test('Communication: no card, and no request for one, without accounts.view_all_communications', async () => {
  serve({ [`GET ${LIST}`]: list([RIYA]), [`GET ${at(RIYA)}`]: detail(RIYA), [`GET ${commsUrl(RIYA)}`]: communication(RIYA) });
  await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  assert.match(clean(topDialog().textContent), /Delhi Private School/, 'the sheet is open');
  assert.ok(!communicationCard());
  assert.equal(calls('GET', commsUrl(RIYA)).length, 0);
});

test('Communication: a booking made before it began says so; one that cannot be read says why, and Try again reads it again', async () => {
  let failing = true;
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA),
    [`GET ${commsUrl(RIYA)}`]: () => (failing ? fail(500, {}) : ok(communication(RIYA, { planned: false, tasks: [], messages: [] }))),
  });
  await open(`/bookings?booking=${RIYA.id}`, COMMS_ADMIN);
  assert.match(clean(communicationCard().textContent), /Could not load this booking's communication\.Try again/);
  failing = false;
  await click(button('Try again', communicationCard()));
  assert.equal(calls('GET', commsUrl(RIYA)).length, 2);
  assert.match(clean(communicationCard().textContent),
    /ConfirmedRecorded.*No messages were planned for this booking: it was made before parent communication began\./);
});

test("BDE: each booking shows the parent's answer and opens its communication in a side sheet", async () => {
  serve({
    [`GET ${ENQUIRY_URL}`]: enquiry([{ ...BDE_BOOKED, parent_confirmation: 'CONFIRMED' }, { ...BDE_CANCELLED, parent_confirmation: 'AWAITING' }]),
    [`GET ${commsUrl(BDE_BOOKED)}`]: communication(BDE_BOOKED),
  });
  const page = await open('/enquiries/lead-1?tab=bookings', BDE_COMMS);
  assert.ok([...document.querySelectorAll('thead th')].some((cell) => clean(cell.textContent) === 'Confirmation'));
  assert.match(bookingRows()[0], /Confirmed/);
  // Never confirmed before it was cancelled: said as it is, nothing to follow up (no warning).
  const awaiting = [...document.querySelectorAll('tbody tr')][1].querySelectorAll('[data-slot="badge"]');
  const badge = [...awaiting].find((element) => clean(element.textContent) === 'Awaiting confirmation');
  assert.equal(badge?.getAttribute('data-variant'), 'outline');

  await click(button('Communication for the demo class on Sat, 31 Oct · 7:30 PM IST'));
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { tab: 'bookings', booking: BDE_BOOKED.id, booking_type: 'DEMO' });
  assert.equal(calls('GET', commsUrl(BDE_BOOKED)).length, 1);
  const sheet = clean(topDialog().textContent);
  // The booking in the header, the parent's answer first, then the workflow beside the messages.
  for (const part of ['CommunicationRiya', 'Demo class', 'Sat, 31 Oct · 7:30 PM IST', 'Booked', 'Booking ID B-1',
    'Parent confirmationConfirmedRecorded 29 Oct 2026, 4:00 PM IST by Bde One', 'Pre-activity BDE callPendingDue 31 Oct 2026, 7:30 PM IST',
    'Waiting for: Tutor assigned, Tutor Meet link']) {
    assert.ok(sheet.includes(part), `the sheet shows ${part}`);
  }
  assert.ok(button('Record parent answer', topDialog()) && !button('Request confirmation', topDialog()), 'only what the API offers');
  // Each step's state on the timeline -- a failed message beats the step it missed -- and the first open step is the current one.
  const [timeline] = topDialog().querySelectorAll('ol');
  assert.deepEqual(listItems(timeline), [
    'Initial acknowledgementSentSent · 28 Oct 2026, 2:31 PM ISTRead · 28 Oct 2026, 2:40 PM IST',
    'Confirmation requestFailedTime ran out 31 Oct 2026, 7:30 PM ISTMessage failed · 29 Oct 2026, 1:31 PM IST',
    'Current stepConfirmed messageOverdueDue 31 Oct 2026, 7:30 PM ISTWaiting for: Tutor assigned, Tutor Meet link',
    'Pre-activity BDE callPendingDue 31 Oct 2026, 7:30 PM IST',
    'After-activity messageScheduledAfter the class',
  ]);
  assert.equal(timeline.querySelector('[aria-current="step"]'), timeline.children[2]);
  // Messages first, the failed one saying so in its row; the call and the tasks a tab away.
  assert.deepEqual([...topDialog().querySelectorAll('[role="tab"]')].map((element) => clean(element.textContent)),
    ['Messages3', 'Call Outcomes', 'Task Details5']);
  const failedRow = listItems(topDialog().querySelectorAll('ol')[1])[1];
  assert.match(failedRow, /^Confirmation requestFailedPermanent delivery failure: Message undeliverable \(131026\)WhatsApp · 29 Oct 2026, 1:31 PM IST/);
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url.startsWith('/api/bookings/')), "the administrators' routes are never called");
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET'), 'nothing but reads');

  await keyDown(topDialog(), 'Escape');
  assert.ok(!topDialog(), 'the sheet closed');
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { tab: 'bookings' }, 'back on the Bookings tab');
});

test('BDE: the pre-activity call reminds from 15 minutes before the start, then reads Done, with nothing to record on it', async () => {
  const at = (minutes) => new Date(Date.now() + minutes * 60000).toISOString();
  const withCall = (booking, call) => {
    const data = communication(booking);
    return { ...data, tasks: data.tasks.map((task) => (task.step === 'PRE_ACTIVITY_CALL' ? { ...task, ...call } : task)) };
  };
  const diagnostic = { ...BDE_BOOKED, id: 'b-3', booking_type: 'DIAGNOSTIC' };
  const cases = [
    // 15 minutes before, for a Demo and a Diagnostic alike.
    [BDE_BOOKED, { active_from: at(0), due_at: at(15) }, 'Pre-activity BDE callPendingCall parent – Demo starts in 15 minutes.'],
    [diagnostic, { active_from: at(-14), due_at: at(1) }, 'Pre-activity BDE callPendingCall parent – Diagnostic starts in 1 minute.'],
    // Not yet: its time only.
    [BDE_BOOKED, { active_from: at(5), due_at: at(20) }, /^Pre-activity BDE callScheduledDue \d{1,2} \w{3} \d{4}, .+ IST$/],
    // Done at the start, by the backend: never Missed, never Overdue.
    [BDE_BOOKED, { active_from: at(-30), due_at: at(-15), status: 'DONE', status_label: 'Done', resolution: 'REMINDED',
      resolution_label: 'Reminder complete', resolved_at: '2026-10-31T14:00:00+00:00' },
    'Pre-activity BDE callCompletedReminder complete · 31 Oct 2026, 7:30 PM IST'],
  ];
  for (const [booking, call, line] of cases) {
    serve({ [`GET ${ENQUIRY_URL}`]: enquiry([booking]), [`GET ${commsUrl(booking)}`]: withCall(booking, call) });
    const page = await open(`/enquiries/lead-1?booking=${booking.id}&booking_type=${booking.booking_type}`, BDE_COMMS);
    const [steps] = topDialog().querySelectorAll('ol');
    if (line instanceof RegExp) assert.match(listItems(steps)[3], line);
    else assert.equal(listItems(steps)[3], line);
    assert.equal(steps.querySelectorAll('button').length, 0, 'nothing to act on in the steps');
    await page.unmount();
  }
});

test('BDE: no Confirmation column, Communication or request for one without accounts.view_own_lead_communications', async () => {
  serve({
    [`GET ${ENQUIRY_URL}`]: enquiry([{ ...BDE_BOOKED, parent_confirmation: null }]),
    [`GET ${commsUrl(BDE_BOOKED)}`]: communication(BDE_BOOKED),
  });
  await open(`/enquiries/lead-1?booking=${BDE_BOOKED.id}&booking_type=DEMO`, BDE);
  assert.ok(![...document.querySelectorAll('thead th')].some((cell) => clean(cell.textContent) === 'Confirmation'));
  assert.ok(!button('Communication for the demo class on Sat, 31 Oct · 7:30 PM IST'));
  assert.ok(!topDialog(), 'no sheet, even with a booking in the URL');
  assert.equal(calls('GET', commsUrl(BDE_BOOKED)).length, 0);
});

test("BDE: a booking that is not one of their leads' is answered as not found", async () => {
  serve({
    [`GET ${ENQUIRY_URL}`]: enquiry([{ ...BDE_BOOKED, parent_confirmation: 'AWAITING' }]),
    [`GET /api/communications/bookings/demo/b-other/`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such booking.' }),
  });
  await open('/enquiries/lead-1?booking=b-other&booking_type=DEMO', BDE_COMMS);
  assert.match(clean(topDialog().textContent), /No communication found for this booking\./);
});

test("History: the parent's answer to the confirmation request, with why they did not confirm", async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA),
    [`GET ${at(RIYA, 'history/')}`]: { booking_id: RIYA.id, timezone: 'Asia/Kolkata',
      chain: [{ id: RIYA.id, status: 'CANCELLED', slot: RIYA.slot, current: true }],
      events: [
        { id: 'p1', booking_id: RIYA.id, kind: 'PARENT_CONFIRMED', kind_label: 'Parent confirmed', at: '2026-10-29T10:30:00+00:00',
          actor: BDE_ONE, details: {} },
        { id: 'p2', booking_id: RIYA.id, kind: 'PARENT_NOT_CONFIRMED', kind_label: 'Parent did not confirm', at: '2026-10-30T10:30:00+00:00',
          actor: BDE_ONE, details: { reason: { code: 'NO_RESPONSE', label: 'No response' } } },
      ] },
  });
  await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  await click(button('Show history', topDialog()));
  const items = [...topDialog().querySelectorAll('[aria-label="History"] li')].map((li) => clean(li.textContent));
  assert.match(items[0], /^Parent confirmed.* · by Bde One$/);
  assert.match(items[1], /^Parent did not confirm — No response.* · by Bde One$/);
});

// ------------------------------------------------ the parent's confirmation (Phase 3.2)
// Asking the parent to confirm and recording their answer, where the API's `actions` offer them.
const AWAITING = { parent_confirmation: { status: 'AWAITING', label: 'Awaiting confirmation', at: null, by: null, reason: null } };
const askable = (booking, extra = {}) => communication(booking, { ...AWAITING,
  actions: { request_confirmation: true, record_confirmation: true }, ...extra });
const previewUrl = (booking) => `${commsUrl(booking)}preview/`;
const requestUrl = (booking) => `${commsUrl(booking)}confirmation-request/`;
const answerUrl = (booking) => `${commsUrl(booking)}parent-confirmation/`;
const READY_PREVIEW = { step: 'CONFIRMATION_REQUEST', step_label: 'Confirmation request', ready: true,
  text: "Hi Sir/Ma'am,\n\nYour child's Demo class is scheduled for *Sat, 31 Oct 2026 at 7:30 PM IST*.\n\n*Bde One*",
  requirements: [{ code: 'BOOKING_ACTIVE', label: 'Booking still upcoming and not started', met: true }, { code: 'BDE_CONTACT', label: "BDE's name and mobile number", met: true }] };
const ASKED = commMessage('CONFIRMATION_REQUEST', 'Confirmation request', { created_by: BDE_ONE });
const cardButton = (label) => button(label, communicationCard());
const openSheet = (user = COMMS_ADMIN) => open(`/bookings?booking=${RIYA.id}`, user);

test('Confirmation: the request is shown exactly as it goes, then added; the card, the booking and the list are read again', async () => {
  const asked = askable(RIYA, { messages: [...communication(RIYA).messages, ASKED],
    actions: { request_confirmation: false, record_confirmation: true } });
  let requested = false;
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA),
    [`GET ${commsUrl(RIYA)}`]: () => ok(requested ? asked : askable(RIYA)),
    [`GET ${previewUrl(RIYA)}`]: READY_PREVIEW,
    [`POST ${requestUrl(RIYA)}`]: () => {
      requested = true;
      return ok({ ...asked, created: true });
    },
  });
  await openSheet();
  await click(cardButton('Request confirmation'));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /^Request confirmation.*Riya · Demo class · Sat, 31 Oct · 7:30 PM IST/);
  assert.deepEqual(calls('GET', previewUrl(RIYA)).map((entry) => entry.params), [{ step: 'CONFIRMATION_REQUEST' }]);
  assert.equal(dialog.querySelector('[aria-label="Message preview"]').textContent, READY_PREVIEW.text, 'exactly as it goes');
  const reads = { detail: calls('GET', at(RIYA)).length, list: calls('GET', LIST).length };

  await click(button('Request confirmation', dialog));
  assert.equal(calls('POST', requestUrl(RIYA)).length, 1);
  assert.ok(!topDialog().textContent.includes('The parent receives this on WhatsApp'), 'the dialog closed');
  const card = communicationCard();
  assert.match(clean(card.querySelector('[role="status"]').textContent), /^Confirmation request added\. It is sent to the parent on WhatsApp\.$/);
  assert.ok(!cardButton('Request confirmation'), 'nothing more to ask');
  assert.equal(listItems(card.querySelectorAll('ol')[1]).at(-1), 'Confirmation requestReady to send');
  assert.ok(calls('GET', at(RIYA)).length > reads.detail && calls('GET', LIST).length > reads.list,
    'the booking and the list are read again');
});

test('Confirmation: asked again, it says the request was already added', async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA),
    [`GET ${commsUrl(RIYA)}`]: askable(RIYA),
    [`GET ${previewUrl(RIYA)}`]: READY_PREVIEW,
    [`POST ${requestUrl(RIYA)}`]: () => ok({ ...askable(RIYA, { messages: [ASKED] }), created: false }),
  });
  await openSheet();
  await click(cardButton('Request confirmation'));
  await click(button('Request confirmation', topDialog()));
  assert.match(clean(communicationCard().querySelector('[role="status"]').textContent),
    /^A confirmation request was already added for this booking\.$/);
});

test('Confirmation: while the preview loads; a message that lacks something says what and cannot be requested', async () => {
  const later = deferred();
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA),
    [`GET ${commsUrl(RIYA)}`]: askable(RIYA),
    [`GET ${previewUrl(RIYA)}`]: () => later.promise,
  });
  await openSheet();
  await click(cardButton('Request confirmation'));
  assert.ok(topDialog().querySelector('[aria-busy="true"]'), 'the preview is loading');
  assert.ok(button('Request confirmation', topDialog()).disabled);
  await act(async () => later.resolve({ status: 200, data: { ...READY_PREVIEW, ready: false, text: null,
    requirements: [{ code: 'BOOKING_ACTIVE', label: 'Booking still upcoming and not started', met: true },
      { code: 'CENTRAL_CONTACT', label: 'Central contact (this lead has no BDE)', met: false }] } }));
  await settle();
  assert.match(clean(topDialog().textContent),
    /This message cannot be sent yet\. It still needs: Central contact \(this lead has no BDE\)\./);
  assert.ok(button('Request confirmation', topDialog()).disabled, 'nothing to request');
  assert.equal(globalThis.__bookingsApi.calls.filter((entry) => entry.method === 'POST').length, 0);
});

test("Confirmation: the API's refusal is shown in the dialog, with what is missing; a preview that fails can be tried again", async () => {
  let previews = 0;
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA),
    [`GET ${commsUrl(RIYA)}`]: askable(RIYA),
    [`GET ${previewUrl(RIYA)}`]: () => (previews++ === 0 ? fail(500, {}) : ok(READY_PREVIEW)),
    [`POST ${requestUrl(RIYA)}`]: () => fail(409, { error: 'MESSAGE_BLOCKED',
      message: 'This message cannot be sent yet: some of its details are missing.', missing: [{ code: 'CENTRAL_CONTACT', label: 'Central contact (this lead has no BDE)' }] }),
  });
  await openSheet();
  await click(cardButton('Request confirmation'));
  assert.match(clean(topDialog().textContent), /Could not prepare the message\.Try again/);
  await click(button('Try again', topDialog()));
  assert.ok(topDialog().querySelector('[aria-label="Message preview"]'), 'read again');
  await click(button('Request confirmation', topDialog()));
  assert.match(clean(topDialog().textContent),
    /This message cannot be sent yet: some of its details are missing\. Missing: Central contact \(this lead has no BDE\)\./);
  assert.ok(!communicationCard().querySelector('[role="status"]'), 'nothing was added');
});

test("Parent's answer: Confirmed is recorded as it is; Not confirmed needs a reason and the cancellation agreed to", async () => {
  const answers = [];
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA),
    [`GET ${commsUrl(RIYA)}`]: askable(RIYA),
    [`POST ${answerUrl(RIYA)}`]: (entry) => {
      answers.push(entry.data);
      return ok({ ...askable(RIYA), changed: true });
    },
  });
  await openSheet();
  await click(cardButton('Record answer'));
  let dialog = topDialog();
  assert.match(clean(dialog.textContent), /^Record parent's answer.*Riya · Demo class · Sat, 31 Oct · 7:30 PM IST/);
  assert.ok(button('Record answer', dialog).disabled, 'nothing chosen yet');
  await click(radio('Confirmed', dialog));
  await click(button('Record answer', dialog));
  assert.deepEqual(answers, [{ outcome: 'CONFIRMED' }]);
  assert.match(clean(communicationCard().querySelector('[role="status"]').textContent), /^Recorded that the parent confirmed\.$/);

  await click(cardButton('Record answer'));
  dialog = topDialog();
  assert.ok(!choice('Why not?', dialog) && !dialog.querySelector('input[type="checkbox"]'), 'a fresh dialog');
  await click(radio('Not confirmed', dialog));
  const confirm = () => button('Record and cancel booking', topDialog());
  assert.ok(confirm().disabled, 'a reason first');
  await click(radio('No response', topDialog()));
  assert.ok(confirm().disabled, 'and the cancellation agreed to');
  const agree = choice('Cancel Riya', topDialog());
  assert.match(clean(agree.textContent), /^Cancel Riya's demo class on Sat, 31 Oct · 7:30 PM IST\. Not confirmed always cancels the booking\.$/);
  await click(agree.querySelector('input[type="checkbox"]'));
  assert.ok(!confirm().disabled);
  await click(confirm());
  assert.deepEqual(answers.at(-1), { outcome: 'NOT_CONFIRMED', reason: 'NO_RESPONSE', confirm_cancellation: true });
  assert.match(clean(communicationCard().querySelector('[role="status"]').textContent),
    /^Recorded that the parent did not confirm\. The booking is cancelled\.$/);
});

test("Parent's answer: the API's refusal is shown in the dialog, which stays open", async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA),
    [`GET ${commsUrl(RIYA)}`]: askable(RIYA),
    // SLOT_STARTED is the scheduled time passing (backend PastStartNotConfirmable); BOOKING_STARTED is the tutor's Start.
    [`POST ${answerUrl(RIYA)}`]: () => fail(409, { error: 'SLOT_STARTED',
      message: "This booking's scheduled time has passed, so the parent's answer can no longer be recorded." }),
  });
  await openSheet();
  await click(cardButton('Record answer'));
  await click(radio('Confirmed', topDialog()));
  await click(button('Record answer', topDialog()));
  assert.match(clean(topDialog().textContent), /This booking's scheduled time has passed, so the parent's answer can no longer be recorded\./);
  assert.ok(!communicationCard().querySelector('[role="status"]'));
});

test('Confirmation: nothing to ask or record unless the API offers it', async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA),
    [`GET ${commsUrl(RIYA)}`]: askable(RIYA, { actions: { request_confirmation: false, record_confirmation: false } }),
  });
  await openSheet();
  assert.ok(!cardButton('Request confirmation') && !cardButton('Record answer'));
});

test("BDE: asks the parent to confirm and records the answer in the communication sheet; the enquiry is read again", async () => {
  let answered = false;
  serve({
    [`GET ${ENQUIRY_URL}`]: () => ok(enquiry([{ ...BDE_BOOKED, parent_confirmation: answered ? 'CONFIRMED' : 'AWAITING' }])),
    [`GET ${commsUrl(BDE_BOOKED)}`]: askable(BDE_BOOKED),
    [`GET ${previewUrl(BDE_BOOKED)}`]: READY_PREVIEW,
    [`POST ${requestUrl(BDE_BOOKED)}`]: () => ok({ ...askable(BDE_BOOKED, { messages: [ASKED],
      actions: { request_confirmation: false, record_confirmation: true } }), created: true }),
    [`POST ${answerUrl(BDE_BOOKED)}`]: () => {
      answered = true;
      return ok({ ...communication(BDE_BOOKED), changed: true });
    },
  });
  await open(`/enquiries/lead-1?booking=${BDE_BOOKED.id}&booking_type=DEMO`, BDE_COMMS);
  const inSheet = (label) => button(label, topDialog());
  await click(inSheet('Request confirmation'));
  await click(inSheet('Request confirmation'));
  assert.equal(calls('POST', requestUrl(BDE_BOOKED)).length, 1);
  assert.match(clean(topDialog().textContent), /Confirmation request added\. It is sent to the parent on WhatsApp\./);
  await click(inSheet('Record parent answer'));
  await click(radio('Confirmed', topDialog()));
  await click(inSheet('Record answer'));
  assert.equal(calls('POST', answerUrl(BDE_BOOKED)).length, 1);
  assert.equal(calls('GET', ENQUIRY_URL).length, 3, 'the enquiry is read again after each action');
  assert.match(bookingRows()[0], /Confirmed/);
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url.startsWith('/api/bookings/')), "the administrators' routes are never called");
});

test("Activity feed: the parent's answer is labelled and described by its codes, naming nobody", () => {
  const entry = (context) => ({ action: 'booking.parent_confirmation', context, changes: {} });
  assert.equal(actionLabel('booking.parent_confirmation'), 'Parent confirmation recorded');
  assert.equal(describeActivity(entry({ booking_type: 'DEMO', outcome: 'CONFIRMED', reason_code: null })),
    "Recorded the parent's confirmation of a demo booking");
  assert.equal(describeActivity(entry({ booking_type: 'DIAGNOSTIC', outcome: 'NOT_CONFIRMED', reason_code: 'TIME_NOT_SUITABLE' })),
    "Recorded that the parent did not confirm a diagnostic booking — Time doesn't suit");
  assert.equal(describeActivity(entry({ outcome: 'NOT_CONFIRMED' })), 'Recorded that the parent did not confirm a booking');
});

test('Activity feed: a confirmation request is labelled and described by its type, naming nobody', () => {
  const entry = (context) => ({ action: 'booking.confirmation_request', context, changes: {} });
  assert.equal(actionLabel('booking.confirmation_request'), 'Confirmation requested');
  assert.equal(describeActivity(entry({ booking_type: 'DIAGNOSTIC', lead_id: 'lead-1', message_id: 'msg-1' })),
    'Asked the parent to confirm a diagnostic booking');
  assert.equal(describeActivity(entry({})), 'Asked the parent to confirm a booking');
});

// ------------------------------------------- Demo invitations (Diagnostic -> Demo)
// The API decides who may send one, and when (backend bookings.demo_invites): the page shows Send Demo
// Invitation where actions.demo_invite says so, and asks for the link only when its menu opens.
const INVITE = { id: 'inv-1', url: 'https://plus.eduport.app/demo-invite#TokenFromTheApi', status: 'ACTIVE',
  created_at: '2026-11-02T06:00:00+00:00', expires_at: '2026-11-09T06:00:00+00:00', created_by: { id: 'admin', full_name: 'Admin One' } };
const INVITE_TEXT = "Book your child's demo class with Eduport Plus. Just pick a date and time:";
const ALI_DONE = { ...ALI, id: 'b-ali-done', status: 'COMPLETED', slot: { ...ALI.slot, started: true, ended: true },
  activity_state: 'COMPLETED', started_at: '2026-11-01T04:31:00+00:00', ...reportFields({ has_report: true, report_version: 1 }) };
const aliReport = { id: 'r-ali', booking_id: ALI_DONE.id, booking_type: 'DIAGNOSTIC', version: 1, student_name: 'Ali', grade: '9',
  tutor_name: 'Tutor A', submitted_at: '2026-11-01T05:20:00+00:00', updated_at: '2026-11-01T05:20:00+00:00',
  fields: { score: 18, max_score: 25, performance_level: 'GOOD', strength_areas: ['Fractions'], skills_to_strengthen: ['Word problems'],
    teacher_remarks: 'Works carefully.', suggested_plan: 'Two sessions a week.' } };
const INVITABLE = { cancel: false, no_show: false, reschedule: false, demo_invite: true };
const inviteUrl = at(ALI_DONE, 'demo-invite/');
const menuItems = () => [...document.querySelectorAll('[role="menuitem"]')];
const menuItem = (label) => menuItems().find((item) => clean(item.textContent) === label);

async function openMenu(trigger) {
  trigger.focus();
  await keyDown(trigger, 'Enter');
}

/** A browser whose clipboard records what is written to it (or refuses); removed afterwards. */
async function withClipboard(run, refuse = false) {
  const written = [];
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text) => {
    if (refuse) throw new Error('blocked');
    written.push(text);
  } } });
  try {
    await run(written);
  } finally {
    delete navigator.clipboard;
  }
}

function serveInvitable(post) {
  serve({
    [`GET ${DIAGNOSTIC_LIST}`]: list([ALI_DONE]),
    [`GET ${at(ALI_DONE)}`]: detail(ALI_DONE, { actions: INVITABLE }),
    [`GET ${at(ALI_DONE, 'report/')}`]: aliReport,
    [`POST ${inviteUrl}`]: post,
  });
}

test('Demo invitation: a Diagnostic whose report is in offers it; the menu copies, sends to the parent and previews one link', async () => {
  await withClipboard(async (written) => {
    let pendingAnswer = null;
    serveInvitable(() => (pendingAnswer ? pendingAnswer.promise : ok({ invite: INVITE, created: true })));
    await open(`/bookings?type=DIAGNOSTIC&booking=${ALI_DONE.id}`, ADMIN);
    const trigger = button('Send Demo Invitation', topDialog());
    assert.ok(trigger, 'the Booking section offers it');
    assert.equal(calls('POST', inviteUrl).length, 0, 'opening the booking issues nothing');

    await openMenu(trigger);
    assert.equal(calls('POST', inviteUrl).length, 1, 'the link is asked for when the menu opens');
    assert.deepEqual(menuItems().map((item) => clean(item.textContent)), ['Copy Link', 'Send to the parent on WhatsApp', 'Preview Link']);
    assert.match(bodyText(), /Link valid until 9 Nov 2026/);
    assert.equal(menuItem('Send to the parent on WhatsApp').getAttribute('href'),
      `https://wa.me/971501234567?text=${encodeURIComponent(`${INVITE_TEXT} ${INVITE.url}`)}`);
    assert.equal(menuItem('Preview Link').getAttribute('href'), INVITE.url);
    assert.equal(menuItem('Preview Link').getAttribute('target'), '_blank');

    await click(menuItem('Copy Link'));
    assert.deepEqual(written, [INVITE.url]);
    assert.ok(button('Copied', topDialog()), 'the button says it was copied');
    assert.match(clean(topDialog().querySelector('[role="status"]')?.textContent), /Invitation link copied\./);

    // Every open asks again -- the link may have been used meanwhile -- and offers nothing until the API answers:
    // then the same active link, until it expires.
    pendingAnswer = deferred();
    await openMenu(button('Copied', topDialog()) ?? button('Send Demo Invitation', topDialog()));
    assert.equal(calls('POST', inviteUrl).length, 2);
    assert.ok(menuItems().some((item) => /Preparing the link/.test(item.textContent)), 'preparing again');
    assert.ok(!menuItem('Copy Link') && !menuItem('Preview Link'), "the earlier open's link is not offered meanwhile");
    pendingAnswer.resolve(ok({ invite: INVITE, created: false }));
    await settle();
    assert.equal(menuItem('Preview Link').getAttribute('href'), INVITE.url);
    assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url.startsWith('/api/bde/')), "a BDE's routes are never called");
  });
});

test('Demo invitation: the link is prepared, a refusal is shown in the menu, and the booking is read again once it closes', async () => {
  const answer = deferred();
  serveInvitable(() => answer.promise);
  await open(`/bookings?type=DIAGNOSTIC&booking=${ALI_DONE.id}`, ADMIN);
  await openMenu(button('Send Demo Invitation', topDialog()));
  const preparing = menuItems().find((item) => /Preparing the link/.test(item.textContent));
  assert.ok(preparing, 'preparing the link');
  assert.equal(preparing.getAttribute('aria-disabled'), 'true');
  assert.ok(!menuItem('Copy Link'), 'nothing to pass on yet');

  answer.resolve(fail(409, { error: 'DEMO_ALREADY_BOOKED', message: 'This student already has a Demo booked or completed.' }));
  await settle();
  assert.match(clean(document.querySelector('[role="alert"]')?.textContent), /already has a Demo booked or completed/);
  assert.ok(!menuItem('Try again') && !menuItem('Copy Link'), 'a refusal that asking again will not change');
  const reads = calls('GET', at(ALI_DONE)).length;
  await keyDown(document.querySelector('[role="menu"]'), 'Escape');
  assert.equal(calls('GET', at(ALI_DONE)).length, reads + 1, 'the booking is read again');
});

test('Demo invitation: a failure that may pass offers Try again, and the copy falls back to a selected link', async () => {
  let attempts = 0;
  serveInvitable(() => {
    attempts += 1;
    return attempts === 1 ? fail(503, { error: 'CAPACITY_CHECK_UNAVAILABLE', message: 'Could not check this slot right now.' })
      : ok({ invite: INVITE, created: false });
  });
  await withClipboard(async (written) => {
    await open(`/bookings?type=DIAGNOSTIC&booking=${ALI_DONE.id}`, ADMIN);
    await openMenu(button('Send Demo Invitation', topDialog()));
    assert.match(clean(document.querySelector('[role="alert"]')?.textContent), /Could not check this slot right now\./);
    await click(menuItem('Try again'));
    assert.equal(attempts, 2);
    assert.ok(menuItem('Copy Link'), 'the link, once it came');
    await click(menuItem('Copy Link'));
    assert.deepEqual(written, []);
    assert.match(bodyText(), /Copying is blocked here, so the link is selected/);
    assert.ok(bodyText().includes(INVITE.url), 'the link is shown to copy by hand');
  }, true);
});

test('Demo invitation: nothing to send unless the API offers it', async () => {
  serve({
    [`GET ${DIAGNOSTIC_LIST}`]: list([ALI_DONE]),
    [`GET ${at(ALI_DONE)}`]: detail(ALI_DONE, { actions: { ...INVITABLE, demo_invite: false } }),
    [`GET ${at(ALI_DONE, 'report/')}`]: aliReport,
  });
  await open(`/bookings?type=DIAGNOSTIC&booking=${ALI_DONE.id}`, ADMIN);
  assert.ok(topDialog() && clean(topDialog().textContent).includes('Ali'));
  assert.ok(!button('Send Demo Invitation', topDialog()));
});

test('Demo invitation: a Demo booked with one says so, who sent it, the Diagnostic it came from, and its timeline', async () => {
  const INVITED = { ...RIYA, id: 'b-invited' };
  serve({
    [`GET ${LIST}`]: list([INVITED]),
    [`GET ${at(INVITED)}`]: detail(INVITED, { channel: 'BDE_HANDOFF', referral_status: null,
      created_by: { id: 'bde-1', full_name: 'Bde One' }, invited_from: { id: ALI_DONE.id, status: 'COMPLETED', slot: ALI.slot } }),
    [`GET ${at(INVITED, 'history/')}`]: { booking_id: INVITED.id, timezone: 'Asia/Kolkata',
      chain: [{ id: INVITED.id, status: 'BOOKED', slot: INVITED.slot, current: true }],
      events: [{ id: 'e1', booking_id: INVITED.id, kind: 'CREATED', kind_label: 'Created', at: '2026-11-02T09:00:00+00:00',
        actor: null, details: { slot: INVITED.slot, seat: 1, via: 'demo_invite', invite_id: 'inv-1' } }] },
  });
  await open(`/bookings?booking=${INVITED.id}`, ADMIN);
  const text = clean(topDialog().textContent);
  assert.match(text, /Came inDemo invitation/);
  assert.match(text, /Invited byBde One/);
  assert.match(text, /From DiagnosticSun, 1 Nov · 10:00 AM IST/);
  assert.ok(!text.includes('Credited BDE'));
  await click(button('Show history', topDialog()));
  const items = [...topDialog().querySelectorAll('[aria-label="History"] li')].map((li) => clean(li.textContent));
  assert.match(items[0], /^Booked with a Demo invitation for Sat, 31 Oct · 7:30 PM IST.* · by the invitation page$/);
});

const BDE_DIAGNOSTIC = { id: 'b-diag', booking_type: 'DIAGNOSTIC', date: '2026-10-29', time: '10:00', starts_at: '2026-10-29T04:30:00+00:00',
  status: 'COMPLETED', ended: true, activity_state: 'COMPLETED', started_at: '2026-10-29T04:31:00+00:00',
  booked_at: '2026-10-27T09:00:00+00:00', cancelled_at: null, actions: { cancel: false, no_show: false, demo_invite: true } };
const BDE_INVITE_URL = `/api/bde/bookings/diagnostic/${BDE_DIAGNOSTIC.id}/demo-invite/`;

test("BDE: a Diagnostic of their own lead offers Send Demo Invitation through the BDE's route, to this parent's WhatsApp", async () => {
  serve({
    [`GET ${ENQUIRY_URL}`]: enquiry([{ ...BDE_BOOKED, actions: { cancel: true, no_show: false, demo_invite: false } }, BDE_DIAGNOSTIC]),
    [`POST ${BDE_INVITE_URL}`]: () => ok({ invite: { ...INVITE, created_by: { id: 'bde', full_name: 'Bde' } }, created: true }),
  });
  await open('/enquiries/lead-1?tab=bookings', BDE);
  const [demoRow, diagnosticRow] = [...document.querySelectorAll('tbody tr')];
  assert.ok(!button('Send Demo Invitation', demoRow), 'never from a Demo');
  await openMenu(button('Send Demo Invitation', diagnosticRow));
  assert.equal(calls('POST', BDE_INVITE_URL).length, 1);
  assert.equal(menuItem('Send to the parent on WhatsApp').getAttribute('href'),
    `https://wa.me/971501234567?text=${encodeURIComponent(`${INVITE_TEXT} ${INVITE.url}`)}`);
  assert.equal(menuItem('Preview Link').getAttribute('href'), INVITE.url);
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url.startsWith('/api/bookings/')), "the administrators' routes are never called");
});

test('BDE: a refused invitation reads the enquiry again once the menu closes', async () => {
  serve({
    [`GET ${ENQUIRY_URL}`]: enquiry([BDE_DIAGNOSTIC]),
    [`POST ${BDE_INVITE_URL}`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such booking.' }),
  });
  await open('/enquiries/lead-1?tab=bookings', BDE);
  await openMenu(button('Send Demo Invitation'));
  assert.match(clean(document.querySelector('[role="alert"]')?.textContent), /No such booking\./);
  await keyDown(document.querySelector('[role="menu"]'), 'Escape');
  assert.equal(calls('GET', ENQUIRY_URL).length, 2);
});

test('Activity feed: Demo invitations and the Demos they book are labelled and described, naming nobody', () => {
  assert.equal(actionLabel('demo_invite.issue'), 'Demo invitation issued');
  assert.equal(actionLabel('demo_invite.revoke'), 'Demo invitation revoked');
  const entry = (action, context) => ({ action, context, changes: {} });
  assert.equal(describeActivity(entry('demo_invite.issue', { diagnostic_booking_id: 'b-1', replaced_invite_id: null })),
    'Issued a Demo invitation link');
  assert.equal(describeActivity(entry('demo_invite.issue', { replaced_invite_id: 'inv-0' })),
    'Issued a new Demo invitation link (the last one had expired)');
  assert.equal(describeActivity(entry('demo_invite.revoke', {})), 'Revoked a Demo invitation link');
  assert.equal(describeActivity(entry('booking.create', { booking_type: 'DEMO', via: 'demo_invite', referral_status: null })),
    'Booked a demo slot with a Demo invitation');
  assert.equal(describeActivity(entry('booking.create', { booking_type: 'DEMO', via: 'public_booking', referral_status: 'ATTRIBUTED' })),
    'Booked a demo slot through a BDE link');
});

// ------------------------------------------------------------------ Re-Demos
// The API decides who may ask and schedule, and when (backend bookings.redemos); the Hub shows each
// action where the API's actions say so, shows the reason back before asking, and books a Re-Demo
// only from the administrators' schedule dialog -- nothing is ever sent to the parent to book.
const REASON = 'The parent wants a slower pace.';
const IRA_SHEET = detail(IRA, { activity_state: 'COMPLETED', started_at: STARTED_AT,
  actions: { cancel: false, no_show: false, reschedule: false, demo_invite: false, request_redemo: true },
  redemo_request: null, redemo_from: null });
const REDEMO = { id: 'rd-1', status: 'AWAITING_SCHEDULING', status_label: 'Awaiting scheduling',
  requested_at: '2026-11-01T06:00:00+00:00', requested_by: { id: 'bde', full_name: 'Bde One' }, reason: REASON,
  student_name: 'Ira', grade: 'Class 8', parent_name: 'Asha Nair', phone: '+971 501234567', owner_bde: { id: 'bde', full_name: 'Bde One' },
  original: { id: IRA.id, status: 'REDEMO_REQUIRED', slot: IRA.slot, tutor: TUTOR_A, tutor_meet_link: null,
    activity_state: 'COMPLETED', has_report: true, report_version: 2 },
  booking: null, tutor: null };
const REDEMO_DETAIL = { ...REDEMO, number: 1, timezone: 'Asia/Kolkata',
  lead: { id: 'lead-ira', phone_dial_code: '+971', phone_number: '501234567', school_name: 'Delhi Private School',
    syllabus: 'CBSE', country: 'United Arab Emirates', source: 'BOOKING_PAGE', owner_bde: { id: 'bde', full_name: 'Bde One' } },
  original_report: { id: 'r-ira', version: 2, submitted_at: '2026-10-31T15:10:00+00:00', submitted_by: TUTOR_A,
    updated_at: '2026-10-31T16:20:00+00:00' },
  admin_remarks: '', remarks_updated_at: null, remarks_updated_by: null,
  bookings: [], chain: [{ id: 'rd-1', status: 'AWAITING_SCHEDULING', status_label: 'Awaiting scheduling',
    requested_at: REDEMO.requested_at, original: REDEMO.original, booking: null, current: true }],
  actions: { schedule: true, edit_remarks: true } };
const REDO_SLOT = { date: '2026-11-01', time: '10:00', starts_at: '2026-11-01T04:30:00+00:00', ends_at: '2026-11-01T05:30:00+00:00',
  started: false, ended: false };
const SCHEDULED = { id: 'b-redo', status: 'BOOKED', slot: REDO_SLOT, tutor: { id: 't-c', full_name: 'Tutor C' },
  tutor_meet_link: MEET, activity_state: 'UPCOMING', has_report: false, report_version: null };
const REDEMOS = '/api/bookings/redemos/';
const redemoAt = (rest = '') => `${REDEMOS}${REDEMO.id}/${rest}`;
// The original Demo's tutor (Tutor A) is free, but never eligible for its Re-Demo (backend REDEMO_ORIGINAL_TUTOR).
const ORIGINAL_REASON = 'Taught the Demo being repeated, so cannot teach its Re-Demo.';
const TUTORS = { redemo_id: REDEMO.id, timezone: 'Asia/Kolkata', schedulable: true, refusal: null, tutors: [
  { id: 't-a', full_name: 'Tutor A', email: 'a@hub.test', status: 'AVAILABLE', free_slots: 9, tutor_meet_link: null,
    original: true, eligible: false, reason: { code: 'REDEMO_ORIGINAL_TUTOR', message: ORIGINAL_REASON } },
  { id: 't-b', full_name: 'Tutor B', email: 'b@hub.test', status: 'UNAVAILABLE', free_slots: 0, tutor_meet_link: null,
    original: false, eligible: true, reason: { code: 'TUTOR_UNAVAILABLE', message: 'No free Demo slot in the booking window.' } },
  { id: 't-c', full_name: 'Tutor C', email: 'c@hub.test', status: 'AVAILABLE', free_slots: 1, reason: null,
    tutor_meet_link: MEET, original: false, eligible: true },
] };
const openSlot = (time, extra = {}) => ({ time, starts_at: `2026-11-01T${time}:00+05:30`, ends_at: `2026-11-01T${time}:00+05:30`,
  status: 'AVAILABLE', seats_left: 3, bookable: true, unavailable_reason: null, lead_conflict: null, tutor_free: true,
  tutor_reason: null, ...extra });
const SLOTS = { redemo_id: REDEMO.id, timezone: 'Asia/Kolkata', schedulable: true, refusal: null,
  tutor: { id: 't-c', full_name: 'Tutor C', tutor_meet_link: MEET },
  dates: [{ date: '2026-11-01', slots: [openSlot('10:00'), openSlot('19:30', { bookable: false, unavailable_reason: 'TUTOR_BUSY',
    tutor_free: false, tutor_reason: { code: 'BOOKING_CONFLICT', message: 'Teaching another booking then.' } })] }] };
const tutorRadios = (dialog) => [...dialog.querySelectorAll('input[name="redemo-tutor"]')].map((input) => {
  const label = input.closest('label');
  return [clean(label.querySelector('.font-medium').textContent),
    [...label.querySelectorAll('[data-slot="badge"]')].map((badge) => clean(badge.textContent)).join(' '), input.disabled];
});

async function typeText(element, value) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  await act(async () => {
    setter.call(element, value);
    element.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
}

test('Re-Demo: a completed Demo offers Request Re-Demo; the reason is required and shown back before anything is sent', async () => {
  serve({
    [`GET ${LIST}`]: list([IRA]),
    [`GET ${at(IRA)}`]: IRA_SHEET,
    [`GET ${at(IRA, 'report/')}`]: iraReport,
    [`POST ${at(IRA, 'redemo/')}`]: () => ok(REDEMO_DETAIL),
  });
  await open(`/bookings?booking=${IRA.id}`, ADMIN);
  await click(button('Request Re-Demo', topDialog()));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /Request Re-Demo.*Ira · Demo/);
  assert.equal(button('Review request', dialog).disabled, true, 'no reason, nothing to review');
  const notice = 'The tutor assigned to the Re-Demo will see this reason.';
  assert.equal(clean(dialog.querySelector('[role="note"]').textContent), notice, 'whoever writes the reason is told who reads it');
  await typeText(dialog.querySelector('textarea'), '   ');
  assert.equal(button('Review request', dialog).disabled, true, 'blank is no reason');
  await typeText(dialog.querySelector('textarea'), `  ${REASON}  `);
  await click(button('Review request', dialog));
  assert.match(clean(topDialog().textContent), new RegExp(`Confirm the Re-Demo request.*Reason${REASON}.*Re-Demo required straight away`));
  assert.equal(clean(topDialog().querySelector('[role="note"]').textContent), notice, 'and told again before confirming');
  assert.equal(calls('POST', at(IRA, 'redemo/')).length, 0, 'nothing is sent before the confirmation');
  await click(button('Request Re-Demo', topDialog()));
  assert.deepEqual(calls('POST', at(IRA, 'redemo/')).map((entry) => entry.data), [{ reason: REASON }]);
  assert.match(bodyText(), /Asked for a Re-Demo of Ira's demo\. It is now Re-Demo required; schedule it in the Re-Demo requests tab\./);
});

test("Re-Demo: a refusal is shown in the dialog; no Request Re-Demo unless the API offers it", async () => {
  serve({
    [`GET ${LIST}`]: list([IRA]),
    [`GET ${at(IRA)}`]: IRA_SHEET,
    [`GET ${at(IRA, 'report/')}`]: iraReport,
    [`POST ${at(IRA, 'redemo/')}`]: () => fail(409, { error: 'REDEMO_ALREADY_REQUESTED',
      message: 'A Re-Demo has already been requested for this Demo.' }),
  });
  await open(`/bookings?booking=${IRA.id}`, ADMIN);
  await click(button('Request Re-Demo', topDialog()));
  await typeText(topDialog().querySelector('textarea'), REASON);
  await click(button('Review request', topDialog()));
  await click(button('Request Re-Demo', topDialog()));
  assert.match(clean(topDialog().textContent), /A Re-Demo has already been requested for this Demo\./);
  await mounted.pop().unmount();

  serve({
    [`GET ${LIST}`]: list([IRA]),
    [`GET ${at(IRA)}`]: { ...IRA_SHEET, actions: { ...IRA_SHEET.actions, request_redemo: false } },
    [`GET ${at(IRA, 'report/')}`]: iraReport,
  });
  await open(`/bookings?booking=${IRA.id}`, ADMIN);
  assert.ok(clean(topDialog().textContent).includes('Ira'));
  assert.ok(!button('Request Re-Demo', topDialog()));
});

test('Re-Demo: a Demo sent for one says so, keeps its report, and opens its request in the Re-Demo tab', async () => {
  serve({
    [`GET ${LIST}`]: list([{ ...IRA, status: 'REDEMO_REQUIRED' }]),
    [`GET ${at(IRA)}`]: { ...IRA_SHEET, status: 'REDEMO_REQUIRED', actions: { ...IRA_SHEET.actions, request_redemo: false },
      redemo_request: { id: REDEMO.id, status: 'AWAITING_SCHEDULING', status_label: 'Awaiting scheduling',
        requested_at: REDEMO.requested_at, requested_by: REDEMO.requested_by } },
    [`GET ${at(IRA, 'report/')}`]: iraReport,
    [`GET ${REDEMOS}`]: list([REDEMO]),
    [`GET ${redemoAt()}`]: REDEMO_DETAIL,
  });
  const page = await open(`/bookings?when=past&booking=${IRA.id}`, ADMIN);
  const text = clean(topDialog().textContent);
  assert.match(text, /Re-Demo required/);
  assert.match(text, /Re-DemoOpen requestStatusAwaiting schedulingRequested byBde One/);
  assert.equal(calls('GET', at(IRA, 'report/')).length, 1, 'its report is still read');
  await click(button('Open request', topDialog()));
  assert.equal(page.location().pathname, '/bookings/demo');
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { tab: 'redemo', redemo: REDEMO.id });
});

test('Re-Demo tab: the requests, newest first; search and status reach the API; one opens with its reason and no link', async () => {
  serve({
    [`GET ${REDEMOS}`]: list([REDEMO]),
    [`GET ${redemoAt()}`]: REDEMO_DETAIL,
  });
  const page = await open('/bookings?type=REDEMO', ADMIN);
  assert.equal(page.location().pathname, '/bookings/demo', "the former Re-Demo tab's link lands on Demo's");
  assert.deepEqual([...document.querySelectorAll('[role="tab"]')].map((element) => [clean(element.textContent),
    element.getAttribute('aria-selected')]), [['Bookings', 'false'], ['Re-Demo requests', 'true']]);
  assert.equal(calls('GET', LIST).length, 0, 'the booking list is not read on the Re-Demo tab');
  const [first] = rows();
  assert.match(clean(first.textContent), /Ira.*Class 8 · BDE: Bde One.*Awaiting scheduling/);
  await choose('Filter by Re-Demo status', 'Re-Demo scheduled');
  assert.equal(calls('GET', REDEMOS).at(-1).params.status, 'SCHEDULED');
  const search = document.querySelector('[aria-label="Search Re-Demo requests"]');
  await typeInto(search, 'Ira');
  await submit(search.closest('form'));
  assert.deepEqual(calls('GET', REDEMOS).at(-1).params, { page: 1, page_size: 25, q: 'Ira', status: 'SCHEDULED' });

  await click(button('View the Re-Demo request for Ira'));
  const text = clean(topDialog().textContent);
  assert.match(text, new RegExp(`Reason${REASON}`));
  assert.match(text, /Re-Demo 1Schedule Re-DemoNot scheduled yet\. Choose the tutor, date and time; the BDE then tells the parent\./);
  assert.match(text, /Original Demo.*Tutor: Tutor A · Report: Submitted · version 2/);
  assert.ok(!/invitation|demo-invite/i.test(text), 'no parent invitation anywhere');
  // Opening the original Demo leaves the Re-Demo tab for Demo's bookings, with that booking open.
  await click(button('Open the original Demo', topDialog()));
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { when: 'all', booking: IRA.id });
});

test("Re-Demo tab: scheduling picks the tutor, then a time they are free, shows their Meet link and books it with the remarks", async () => {
  serve({
    [`GET ${REDEMOS}`]: list([REDEMO]),
    [`GET ${redemoAt()}`]: REDEMO_DETAIL,
    [`GET ${redemoAt('tutors/')}`]: TUTORS,
    [`GET ${redemoAt('slots/')}`]: SLOTS,
    [`POST ${redemoAt('schedule/')}`]: () => ok({ ...REDEMO_DETAIL, status: 'SCHEDULED', status_label: 'Re-Demo scheduled',
      tutor: SCHEDULED.tutor, booking: SCHEDULED, bookings: [SCHEDULED], admin_remarks: 'Go slower.',
      actions: { schedule: false, edit_remarks: true }, booking_id: SCHEDULED.id }),
  });
  await open(`/bookings?type=REDEMO&redemo=${REDEMO.id}`, ADMIN);
  await click(button('Schedule Re-Demo', topDialog()));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /Schedule the Re-Demo.*Ira · Re-Demo of the Demo on Sat, 31 Oct · 7:30 PM IST/);
  // The original Demo's tutor stays listed but disabled, and says why; the others are offered as they are free.
  assert.deepEqual(tutorRadios(dialog), [['Tutor A', 'Original tutor · Not eligible', true], ['Tutor B', 'Unavailable', true],
    ['Tutor C', 'Available', false]]);
  assert.match(clean(dialog.textContent),
    new RegExp(`Tutor AOriginal tutor · Not eligible${ORIGINAL_REASON.replace('.', '\\.')}.*No free Demo slot in the booking window\\..*1 free Demo slot`));
  const original = dialog.querySelector('input[value="t-a"]').closest('label');
  assert.equal(original.getAttribute('aria-disabled'), 'true');
  assert.match(original.className, /cursor-not-allowed/);
  assert.ok(!dialog.querySelector('[role="alert"]'), 'another tutor can teach it');
  assert.equal(calls('GET', redemoAt('slots/')).length, 0, 'no slots until a tutor is chosen');
  assert.equal(button('Schedule Re-Demo', dialog).disabled, true);

  await click(dialog.querySelector('input[value="t-c"]'));
  assert.deepEqual(calls('GET', redemoAt('slots/')).map((entry) => entry.params), [{ tutor_id: 't-c' }]);
  const text = clean(topDialog().textContent);
  assert.match(text, /Date and time \(IST\)Sun, 1 Nov\(1\)Times10:00 AM3 seats left7:30 PMTeaching another booking then\./);
  assert.match(text, /Meet link: meet\.google\.com\/abc-defg-hij/);
  assert.equal(dialog.querySelector('input[name="redemo-time"][value="19:30"]').disabled, true, 'not a time the tutor is busy');
  assert.equal(button('Schedule Re-Demo', dialog).disabled, true, 'no time yet');
  await click(dialog.querySelector('input[name="redemo-time"][value="10:00"]'));
  await typeText(dialog.querySelector('#redemo-remarks'), ' Go slower. ');
  assert.match(clean(topDialog().textContent),
    /Books the Re-Demo with Tutor C on Sun, 1 Nov · 10:00 AM IST\. Nothing is sent to the parent: the BDE tells them the time\./);
  const reads = calls('GET', redemoAt()).length;
  await click(button('Schedule Re-Demo', dialog));
  assert.deepEqual(calls('POST', redemoAt('schedule/')).map((entry) => entry.data),
    [{ tutor_id: 't-c', date: '2026-11-01', time: '10:00', remarks: 'Go slower.' }]);
  assert.match(bodyText(), /Ira's Re-Demo is booked with Tutor C on Sun, 1 Nov · 10:00 AM IST\. The BDE tells the parent\./);
  assert.ok(calls('GET', redemoAt()).length > reads, 'the request is read again');
});

test('Re-Demo tab: with no tutor but the original one free, scheduling says why and cannot go ahead', async () => {
  const onlyOriginal = { ...TUTORS, tutors: TUTORS.tutors.map((option) => (option.id === 't-c'
    ? { ...option, status: 'UNAVAILABLE', free_slots: 0, reason: { code: 'TUTOR_UNAVAILABLE', message: 'No free Demo slot in the booking window.' } }
    : option)) };
  serve({
    [`GET ${REDEMOS}`]: list([REDEMO]),
    [`GET ${redemoAt()}`]: REDEMO_DETAIL,
    [`GET ${redemoAt('tutors/')}`]: onlyOriginal,
  });
  await open(`/bookings?type=REDEMO&redemo=${REDEMO.id}`, ADMIN);
  await click(button('Schedule Re-Demo', topDialog()));
  const dialog = topDialog();
  assert.match(clean(dialog.querySelector('[role="alert"]').textContent),
    /^No other tutor can teach this Re-Demo: the tutor who taught the Demo being repeated is not eligible/);
  assert.deepEqual(tutorRadios(dialog).map(([name, , disabled]) => [name, disabled]), [['Tutor A', true], ['Tutor B', true], ['Tutor C', true]]);
  assert.equal(button('Schedule Re-Demo', dialog).disabled, true);
  assert.equal(calls('GET', redemoAt('slots/')).length, 0);
  assert.equal(calls('POST', redemoAt('schedule/')).length, 0, 'nothing can be booked');
});

test('Re-Demo tab: a refused schedule is shown and the slots read again; one already scheduled is not offered', async () => {
  serve({
    [`GET ${REDEMOS}`]: list([REDEMO]),
    [`GET ${redemoAt()}`]: REDEMO_DETAIL,
    [`GET ${redemoAt('tutors/')}`]: TUTORS,
    [`GET ${redemoAt('slots/')}`]: SLOTS,
    [`POST ${redemoAt('schedule/')}`]: () => fail(409, { error: 'TUTOR_UNAVAILABLE', message: 'This tutor is not free then.',
      conflict: { code: 'BOOKING_CONFLICT', message: 'Teaching another booking then.' } }),
  });
  await open(`/bookings?type=REDEMO&redemo=${REDEMO.id}`, ADMIN);
  await click(button('Schedule Re-Demo', topDialog()));
  await click(topDialog().querySelector('input[value="t-c"]'));
  await click(topDialog().querySelector('input[name="redemo-time"][value="10:00"]'));
  await click(button('Schedule Re-Demo', topDialog()));
  assert.match(clean(topDialog().textContent), /This tutor is not free then\. Teaching another booking then\./);
  assert.equal(calls('GET', redemoAt('slots/')).length, 2, 'the slots are read again');
  await mounted.pop().unmount();

  serve({
    [`GET ${REDEMOS}`]: list([REDEMO]),
    [`GET ${redemoAt()}`]: REDEMO_DETAIL,
    [`GET ${redemoAt('tutors/')}`]: { ...TUTORS, schedulable: false,
      refusal: { code: 'REDEMO_SCHEDULED', message: 'The Re-Demo is already scheduled. Change its booking instead.' } },
  });
  await open(`/bookings?type=REDEMO&redemo=${REDEMO.id}`, ADMIN);
  await click(button('Schedule Re-Demo', topDialog()));
  assert.match(clean(topDialog().textContent), /The Re-Demo is already scheduled\. Change its booking instead\./);
  assert.equal(button('Schedule Re-Demo', topDialog()).disabled, true);
});

test('Re-Demo tab: a scheduled one shows its booking, tutor and Meet link, and opens the booking', async () => {
  serve({
    [`GET ${REDEMOS}`]: list([{ ...REDEMO, status: 'SCHEDULED', tutor: SCHEDULED.tutor, booking: SCHEDULED }]),
    [`GET ${redemoAt()}`]: { ...REDEMO_DETAIL, status: 'SCHEDULED', status_label: 'Re-Demo scheduled', tutor: SCHEDULED.tutor,
      booking: SCHEDULED, bookings: [SCHEDULED], actions: { schedule: false, edit_remarks: true } },
  });
  const page = await open('/bookings?type=REDEMO', ADMIN);
  assert.match(clean(rows()[0].textContent), /Re-Demo scheduled.*Tutor C.*Sun, 1 Nov10:00 AM/);
  await click(button('View the Re-Demo request for Ira'));
  const text = clean(topDialog().textContent);
  assert.match(text, /Re-Demo 1BookingSun, 1 Nov · 10:00 AM IST.*Tutor: Tutor C · Report: Not submitted yet.*Meet linkmeet\.google\.com\/abc-defg-hij/);
  assert.ok(!button('Schedule Re-Demo', topDialog()), 'scheduled once; changed from its booking');
  await click(button('Open the Re-Demo booking', topDialog()));
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { when: 'all', booking: SCHEDULED.id });
});

test('Re-Demo tab: remarks for the tutor are saved with their own PUT; without accounts.assign_booking_tutor nothing changes', async () => {
  serve({
    [`GET ${REDEMOS}`]: list([REDEMO]),
    [`GET ${redemoAt()}`]: REDEMO_DETAIL,
    [`PUT ${redemoAt('remarks/')}`]: (entry) => ok({ ...REDEMO_DETAIL, admin_remarks: entry.data.remarks,
      remarks_updated_at: '2026-11-01T07:00:00+00:00', remarks_updated_by: { id: 'admin', full_name: 'Admin One' }, changed: true }),
  });
  await open(`/bookings?type=REDEMO&redemo=${REDEMO.id}`, ADMIN);
  const remarks = topDialog().querySelector('[aria-label="Remarks for the tutor"]');
  assert.match(clean(topDialog().textContent), /Shown to the Re-Demo tutor, not the BDE\./);
  assert.equal(button('Save remarks', topDialog()).disabled, true, 'nothing changed yet');
  await typeText(remarks, 'Prefers mornings.');
  await click(button('Save remarks', topDialog()));
  assert.deepEqual(calls('PUT', redemoAt('remarks/')).map((entry) => entry.data), [{ remarks: 'Prefers mornings.' }]);
  assert.match(clean(topDialog().textContent), /Remarks saved\..*|Last saved .* by Admin One/);
  await mounted.pop().unmount();

  serve({
    [`GET ${REDEMOS}`]: list([REDEMO]),
    [`GET ${redemoAt()}`]: { ...REDEMO_DETAIL, admin_remarks: 'Prefers mornings.', actions: { schedule: false, edit_remarks: false } },
  });
  await open(`/bookings?type=REDEMO&redemo=${REDEMO.id}`, VIEWER);
  assert.match(clean(topDialog().textContent), /Remarks for the tutorPrefers mornings\./);
  assert.match(clean(topDialog().textContent), /Not scheduled yet: an administrator chooses the tutor, date and time\./);
  assert.ok(!button('Schedule Re-Demo', topDialog()) && !button('Save remarks', topDialog()));
  assert.ok(!topDialog().querySelector('textarea'));
});

test('Re-Demo tab: an error, then Try again; none yet says so', async () => {
  let attempts = 0;
  serve({ [`GET ${REDEMOS}`]: () => (++attempts === 1 ? fail(500, { message: 'Server error' }) : ok(list([]))) });
  await open('/bookings?type=REDEMO', ADMIN);
  assert.match(bodyText(), /Server error/);
  await click(button('Try again'));
  assert.match(bodyText(), /No Re-Demo requests yet/);
});

test('Re-Demo: the booking it scheduled is marked Re-Demo, names the Demo it teaches again, and its timeline says so', async () => {
  const REDO = { ...RIYA, id: 'b-redo', tutor: { id: 't-c', full_name: 'Tutor C' }, redemo_for_id: REDEMO.id };
  serve({
    [`GET ${LIST}`]: list([REDO, { ...RIYA, id: 'b-other', student_name: 'Sara', redemo_for_id: null }]),
    [`GET ${at(REDO)}`]: detail(REDO, { channel: 'BDE_HANDOFF', referral_status: null, created_by: { id: 'admin', full_name: 'Admin One' },
      invited_from: null, redemo_request: null,
      redemo_from: { id: REDEMO.id, status: 'SCHEDULED', status_label: 'Re-Demo scheduled',
        original: { id: IRA.id, status: 'REDEMO_REQUIRED', slot: IRA.slot } } }),
    [`GET ${at(REDO, 'history/')}`]: { booking_id: REDO.id, timezone: 'Asia/Kolkata',
      chain: [{ id: REDO.id, status: 'BOOKED', slot: REDO.slot, current: true }],
      events: [
        { id: 'e1', booking_id: REDO.id, kind: 'CREATED', kind_label: 'Created', at: '2026-11-02T09:00:00+00:00',
          actor: { id: 'admin', full_name: 'Admin One' }, details: { slot: REDO.slot, seat: 1, via: 'redemo', redemo_request_id: REDEMO.id } },
        { id: 'e2', booking_id: REDO.id, kind: 'TUTOR_ASSIGNED', kind_label: 'Tutor assigned', at: '2026-11-02T09:00:00+00:00',
          actor: { id: 'admin', full_name: 'Admin One' }, details: { old_tutor: null, new_tutor: { id: 't-c', full_name: 'Tutor C' }, via: 'redemo' } },
      ] },
  });
  await open(`/bookings?booking=${REDO.id}`, ADMIN);
  const [redo, other] = rows();
  assert.match(clean(redo.textContent), /RiyaClass 8Re-Demo/);
  assert.ok(!clean(other.textContent).includes('Re-Demo'), 'an ordinary Demo is not marked');
  const text = clean(topDialog().textContent);
  assert.match(text, /^RiyaSat, 31 Oct · 7:30 PM IST · Class 8Demo classRe-Demo/);
  assert.match(text, /Came inRe-Demo, scheduled by an administrator/);
  assert.match(text, /Scheduled byAdmin One/);
  assert.match(text, /Re-Demo ofSat, 31 Oct · 7:30 PM IST/);
  assert.match(text, /Re-Demo requestRe-Demo scheduled/);
  assert.ok(!/From Diagnostic|Credited BDE|Invited by/.test(text));
  await click(button('Show history', topDialog()));
  const items = [...topDialog().querySelectorAll('[aria-label="History"] li')].map((li) => clean(li.textContent));
  assert.match(items[0], /^Re-Demo scheduled for Sat, 31 Oct · 7:30 PM IST.* · by Admin One$/);
  assert.match(items[1], /^Tutor C assigned for the Re-Demo.* · by Admin One$/);
});

const BDE_DONE_DEMO = { ...BDE_BOOKED, id: 'b-done', status: 'COMPLETED', ended: true, activity_state: 'COMPLETED',
  started_at: '2026-10-31T14:02:00+00:00', redemo: null, redemo_from: null,
  actions: { cancel: false, no_show: false, demo_invite: false, request_redemo: true } };
const BDE_REDEMO = { id: 'rd-1', status: 'AWAITING_SCHEDULING', status_label: 'Awaiting scheduling', requested_at: REDEMO.requested_at,
  requested_by: { full_name: 'Bde One' }, reason: REASON, tutor: null, booking: null };
const BDE_REDEMO_URL = `/api/bde/bookings/demo/${BDE_DONE_DEMO.id}/redemo/`;

test("BDE: a completed Demo of their own lead is sent for a Re-Demo through the BDE's route; the row then says where it stands", async () => {
  serve({
    [`GET ${ENQUIRY_URL}`]: enquiry([BDE_DONE_DEMO]),
    [`POST ${BDE_REDEMO_URL}`]: () => ok(enquiry([{ ...BDE_DONE_DEMO, status: 'REDEMO_REQUIRED', redemo: BDE_REDEMO,
      actions: { ...BDE_DONE_DEMO.actions, request_redemo: false } }])),
  });
  await open('/enquiries/lead-1?tab=bookings', BDE);
  await click(button(`Request a Re-Demo of the demo on ${clean(rows()[0].querySelector('td').textContent)}`));
  await typeText(topDialog().querySelector('textarea'), REASON);
  await click(button('Review request', topDialog()));
  assert.match(clean(topDialog().textContent), new RegExp(`Reason${REASON}`));
  await click(button('Request Re-Demo', topDialog()));
  assert.deepEqual(calls('POST', BDE_REDEMO_URL).map((entry) => entry.data), [{ reason: REASON }]);
  const row = clean(rows()[0].textContent);
  assert.match(row, /Re-Demo required.*Re-Demo:Awaiting scheduling/);
  assert.ok(!button('Request Re-Demo'), 'asked for once');
  assert.match(bodyText(), /An administrator schedules it; then tell the parent the date and time shown here\./);
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url.startsWith('/api/bookings/')), "the administrators' routes are never called");
});

test('BDE: once scheduled, the row says when and with whom -- no invitation to send -- and the Re-Demo is marked', async () => {
  const redo = { ...BDE_BOOKED, id: 'b-redo', date: '2026-11-01', time: '10:00', starts_at: '2026-11-01T04:30:00+00:00',
    tutor: { full_name: 'Tutor C' }, tutor_meet_link: MEET, redemo: null, redemo_from: { id: 'rd-1', demo_booking_id: 'b-done' },
    actions: { cancel: true, no_show: false, demo_invite: false, request_redemo: false } };
  const done = { ...BDE_DONE_DEMO, status: 'REDEMO_REQUIRED', actions: { ...BDE_DONE_DEMO.actions, request_redemo: false },
    redemo: { ...BDE_REDEMO, status: 'SCHEDULED', status_label: 'Re-Demo scheduled', tutor: { full_name: 'Tutor C' },
      booking: { id: 'b-redo', booking_type: 'DEMO', date: '2026-11-01', time: '10:00', starts_at: '2026-11-01T04:30:00+00:00' } } };
  serve({ [`GET ${ENQUIRY_URL}`]: enquiry([redo, done]) });
  await open('/enquiries/lead-1?tab=bookings', BDE);
  const [first, second] = rows().map((element) => clean(element.textContent));
  assert.match(first, /^Sun, 1 Nov · 10:00 AM ISTDemo classUpcomingRe-DemoTutor C/);
  assert.match(second, /Re-Demo:Re-Demo scheduledSun, 1 Nov · 10:00 AM IST with Tutor C/);
  assert.ok(!button('Send Re-Demo Invitation') && !/invitation/i.test(bodyText()), 'nothing to send the parent');
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET'), 'only reads');
});

test('Activity feed: Re-Demo requests, remarks and scheduling are labelled and described, naming nobody', () => {
  const entry = (action, context) => ({ action, context, changes: {} });
  assert.equal(actionLabel('redemo.request'), 'Re-Demo requested');
  assert.equal(actionLabel('redemo.remarks'), 'Re-Demo remarks updated');
  assert.equal(describeActivity(entry('redemo.request', { booking_id: 'b-1' })), 'Asked for a completed Demo to be taught again');
  assert.equal(describeActivity(entry('redemo.remarks', { cleared: false })), "Updated the Re-Demo's remarks");
  assert.equal(describeActivity(entry('redemo.remarks', { cleared: true })), "Cleared the Re-Demo's remarks");
  assert.equal(describeActivity(entry('booking.create', { booking_type: 'DEMO', via: 'redemo', referral_status: null })),
    'Scheduled a Re-Demo');
});

// ------------------------------------------------------------------ the tutor's Re-Demos
// A Re-Demo reaches its tutor as one (backend bookings.tutor_bookings, `redemo`): marked, with why it is
// taught again, the administrators' remarks and the Demo it follows -- and started and reported on as any Demo.
const MY_REDO = { ...MY_RIYA, id: 'b-redo', slot: mySlot('2026-11-01', '10:00'), tutor_meet_link: MEET,
  redemo: { number: 2, reason: REASON, admin_remarks: 'Go slower with fractions.',
    original: { slot: mySlot('2026-10-28', '19:30'), tutor: { full_name: 'Orla Menon' } } } };

test("My Bookings: a Re-Demo is marked as one, and its sheet says why, the admin's remarks and the Demo it follows", async () => {
  serve({ [`GET ${MINE}`]: mine([MY_RIYA, MY_REDO]), [`GET ${myAt(MY_REDO)}`]: myDetail(MY_REDO), [`GET ${myAt(MY_RIYA)}`]: myDetail(MY_RIYA) });
  const page = await open(`/my-bookings?${opened(MY_REDO)}`, TUTOR);
  const [riya, redo] = rows().map((element) => clean(element.textContent));
  assert.match(riya, /^Sat, 31 Oct7:30 PMDemo classRiya/);
  assert.match(redo, /^Sun, 1 Nov10:00 AMRe-Demo 2Riya/);
  const text = clean(topDialog().textContent);
  assert.match(text, /^RiyaSun, 1 Nov · 10:00 AM IST · Class 8Re-Demo 2/);
  assert.match(text, /TypeRe-DemoWhenSun, 1 Nov · 10:00 AM IST/);
  assert.match(text, /Meet linkmeet\.google\.com\/abc-defg-hij/);
  // The reason and the admin's remarks, each labelled with where it comes from.
  assert.match(text, new RegExp(`Re-Demo 2Request reason${REASON}From the Re-Demo request \\(BDE / parent\\)` +
    'Admin remarksGo slower with fractions\\.From the administrator who scheduled it' +
    'Follows the DemoWed, 28 Oct · 7:30 PM ISTTaught by Orla Menon'));
  assert.ok(!/Requested by|Bde One|Admin One/.test(text), 'never who asked or who scheduled it');
  // Its report is the Demo report flow, as for any Demo.
  assert.match(text, /ReportReportYou can write the report once you start the class\./);
  // The sheet is the Re-Demo the URL names, read from the tutor's own API and nothing else.
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { booking: MY_REDO.id, booking_type: 'DEMO' });
  assert.equal(calls('GET', myAt(MY_REDO)).length, 1);
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET' && entry.url.startsWith(MINE)),
    "only the tutor's own bookings are read");
  await mounted.pop().unmount();

  serve({ [`GET ${MINE}`]: mine([MY_REDO]), [`GET ${myAt(MY_REDO)}`]: myDetail({ ...MY_REDO, redemo: { ...MY_REDO.redemo,
    number: 1, admin_remarks: '' } }) });
  await open(`/my-bookings?${opened(MY_REDO)}`, TUTOR);
  // A first Re-Demo is "Re-Demo", unnumbered; with no remarks the tutor is told there are none.
  assert.match(clean(topDialog().textContent), /^RiyaSun, 1 Nov · 10:00 AM IST · Class 8Re-Demo(?! \d)/);
  assert.match(clean(topDialog().textContent), /Admin remarksNo remarksFrom the administrator who scheduled it/);
  await mounted.pop().unmount();

  serve({ [`GET ${MINE}`]: mine([MY_RIYA]), [`GET ${myAt(MY_RIYA)}`]: myDetail(MY_RIYA) });
  await open(`/my-bookings?${opened(MY_RIYA)}`, TUTOR);
  assert.ok(!/Follows the Demo|Re-Demo|Request reason/.test(clean(topDialog().textContent)), 'an ordinary Demo has no Re-Demo section');
});

test('Communication: a Re-Demo says its parent is contacted by the BDE, with nothing to send', async () => {
  const REDO = { ...RIYA, id: 'b-redo', redemo_for_id: 'rd-1' };
  serve({
    [`GET ${LIST}`]: list([REDO]),
    [`GET ${at(REDO)}`]: detail(REDO, { channel: 'BDE_HANDOFF', referral_status: null,
      created_by: { id: 'admin', full_name: 'Admin One' }, invited_from: null, redemo_request: null,
      redemo_from: { id: 'rd-1', status: 'SCHEDULED', status_label: 'Re-Demo scheduled',
        original: { id: IRA.id, status: 'REDEMO_REQUIRED', slot: IRA.slot } } }),
    [`GET ${commsUrl(REDO)}`]: communication(REDO, { planned: false, redemo: true, tasks: [], messages: [],
      parent_confirmation: { status: 'AWAITING', label: 'Awaiting confirmation', at: null, by: null, reason: null },
      actions: { request_confirmation: false, record_confirmation: true } }),
  });
  await open(`/bookings?booking=${REDO.id}`, COMMS_ADMIN);
  const card = clean(communicationCard().textContent);
  assert.match(card, /No messages are sent for a Re-Demo: the BDE contacts the parent directly with its date, time and tutor\./);
  assert.ok(!card.includes('made before parent communication began'));
  // The BDE or Admin may still record what the parent said on the phone; nothing is offered to send.
  assert.ok(button('Record answer', communicationCard()));
  assert.ok(!button('Request confirmation', communicationCard()), 'nothing to send the parent');
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET'), 'only reads');
});

// ------------------------------------------------------------------ BDE follow-ups
const FOLLOW_UPS = '/api/bde/follow-ups/';
const FOLLOW_UP_BDE = { id: 'bde', role: 'BDE', permissions: [
  'accounts.record_parent_confirmation', 'accounts.send_lead_communications', 'accounts.share_booking_report',
  'accounts.view_own_enquiries', 'accounts.view_own_lead_communications', 'accounts.view_own_lead_reports'] };
const NO_ACTIONS = { record_outcome: false, request_confirmation: false, record_answer: false };
const FOLLOW_UP_TYPES = { NEW_ENQUIRY_CALL: 'Call new enquiry', PARENT_CONFIRMATION: 'Parent confirmation',
  PRE_ACTIVITY_CALL: 'Pre-activity call', TUTOR_REPORT: 'Share tutor report', REDEMO_CONFIRMATION: 'Re-Demo confirmation' };
const FU_KIRAN = { id: 'e-kiran', parent_name: 'Ravi Menon', student_name: 'Kiran', grade: 'Class 7', phone: '+91 9876543210',
  phone_dial_code: '+91', phone_number: '9876543210' };
const FU_DONA = { id: 'e-dona', parent_name: 'Asha Nair', student_name: 'Dona', grade: 'Class 8', phone: '+971 501234567',
  phone_dial_code: '+971', phone_number: '501234567' };
const followUpBooking = (id, booking_type, date, extra = {}) => ({ id, booking_type, date, time: '19:30',
  starts_at: `${date}T14:00:00+00:00`, status: 'BOOKED', activity_state: 'UPCOMING', redemo: false, ...extra });
const followUp = (type, id, fields = {}) => ({ id, type, type_label: FOLLOW_UP_TYPES[type], state: 'DUE_TODAY',
  state_label: 'Due today', due_at: '2026-11-07T14:00:00+00:00', opens_at: null, request: null, booking: null,
  enquiry: FU_DONA, actions: NO_ACTIONS, ...fields });
const FU_NEW_CALL = followUp('NEW_ENQUIRY_CALL', 'f-call', { enquiry: FU_KIRAN, due_at: '2026-11-07T16:30:00+00:00' });
const FU_CONFIRM = followUp('PARENT_CONFIRMATION', 'b-dona', { booking: followUpBooking('b-dona', 'DEMO', '2026-11-07'),
  actions: { ...NO_ACTIONS, request_confirmation: true, record_answer: true } });
const FU_PRE_CALL = followUp('PRE_ACTIVITY_CALL', 't-call', { booking: followUpBooking('b-ali', 'DIAGNOSTIC', '2026-11-07'),
  actions: { ...NO_ACTIONS, record_outcome: true } });
const FU_REPORT = followUp('TUTOR_REPORT', 'r-done', { state: 'PENDING', state_label: 'Pending',
  due_at: '2026-11-08T14:40:00+00:00',
  booking: followUpBooking('b-done', 'DEMO', '2026-11-06', { status: 'COMPLETED', activity_state: 'COMPLETED' }) });
const FU_REDEMO = followUp('REDEMO_CONFIRMATION', 'b-redo', { state: 'PENDING', state_label: 'Pending',
  due_at: '2026-11-09T14:00:00+00:00', booking: followUpBooking('b-redo', 'DEMO', '2026-11-09', { redemo: true }),
  actions: { ...NO_ACTIONS, record_answer: true } });

test('Follow-ups: reminders only, each with what does it; the call is recorded here and the list read again', async () => {
  let remaining = [FU_NEW_CALL, FU_CONFIRM, FU_PRE_CALL, FU_REPORT, FU_REDEMO];
  const count = (state) => remaining.filter((row) => row.state === state).length;
  serve({
    [`GET ${FOLLOW_UPS}`]: () => ok({ results: remaining, count: remaining.length, page: 1, page_size: 25,
      timezone: 'Asia/Kolkata', summary: { total: remaining.length, today: count('DUE_TODAY'), upcoming: count('PENDING') } }),
    ['POST /api/communications/bookings/diagnostic/b-ali/call-outcome/']: () => {
      remaining = remaining.filter((item) => item !== FU_PRE_CALL);
      return ok({});
    },
  });
  await open('/follow-ups', FOLLOW_UP_BDE);
  // Nothing is ever overdue: a reminder leaves once its time is up.
  assert.deepEqual([...document.querySelectorAll('[role="tab"]')].map((element) => clean(element.textContent)),
    ['All open5', 'Due today3', 'Upcoming2']);
  assert.deepEqual(rows().map((row) => clean(row.querySelector('td').textContent)), [
    'Call new enquiryDue todayCall the parent and guide them to book a Demo or Diagnostic.',
    'Parent confirmationDue todayAsk the parent to confirm, then record their answer.',
    'Pre-activity callDue todayCall the parent before the class starts.',
    'Share tutor reportPendingReview the report and share it with the parent.',
    'Re-Demo confirmationPendingTell the parent the Re-Demo’s date and time, then record their answer.',
  ]);
  const [call, confirm, preCall, report, redemo] = rows();
  assert.match(clean(call.textContent), /KiranRavi Menon\+91 9876543210No booking yet/);
  assert.match(clean(redemo.textContent), /Demo classRe-DemoMon, 9 Nov · 7:30 PM IST/);
  // A new enquiry opens its own page, and a report its tutor feedback, where it is sent; nothing is recorded here.
  assert.equal(call.querySelector('a[aria-label="Open Kiran’s enquiry"]').getAttribute('href'), '/enquiries/e-kiran');
  assert.equal(report.querySelector('a[aria-label="Open Dona’s tutor report to share it"]').getAttribute('href'),
    '/enquiries/e-dona?tab=feedback');
  assert.deepEqual([...call.querySelectorAll('button')].length + [...report.querySelectorAll('button')].length, 0);
  assert.ok(button('Request confirmation', confirm) && button('Record answer', confirm));
  assert.ok(button('Record outcome', preCall));
  assert.ok(button('Record answer', redemo) && !button('Request confirmation', redemo), 'a Re-Demo is confirmed by hand');
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.method !== 'GET'), 'nothing is written by looking');

  // A Re-Demo's answer is recorded in the dialog the communication sheet uses.
  await click(button('Record answer', redemo));
  assert.match(clean(topDialog().textContent), /Record parent's answerDona · Demo class · Mon, 9 Nov · 7:30 PM IST/);
  await click(button('Cancel', topDialog()));

  // The call before a class: how it went, picked from the list, kept on its booking's communication.
  await click(button('Record outcome', preCall));
  assert.deepEqual([...topDialog().querySelectorAll('label')].map((element) => clean(element.textContent)),
    ['Called', 'Messaged', 'No answer']);
  await click(radio('No answer', topDialog()));
  await click(button('Record outcome', topDialog()));
  assert.deepEqual(calls('POST', '/api/communications/bookings/diagnostic/b-ali/call-outcome/').map((entry) => entry.data),
    [{ outcome: 'NO_ANSWER' }]);
  assert.match(bodyText(), /Recorded “No answer” for the call to Asha Nair\./);
  assert.equal(calls('GET', FOLLOW_UPS).length, 2, 'the list and its counts are read again');
  assert.deepEqual(rows().map((row) => clean(row.querySelector('td span').textContent)),
    ['Call new enquiryDue today', 'Parent confirmationDue today', 'Share tutor reportPending', 'Re-Demo confirmationPending']);
});

// ------------------------------------------------------- BDE Demo and Diagnostic Bookings: filters
const BDE_LISTS = { id: 'bde-lists', role: 'BDE', permissions: ['accounts.view_own_enquiries', 'accounts.view_own_lead_communications'] };
const BDE_DEMO_LIST = '/api/bde/bookings/demo/';
const BDE_DIAGNOSTIC_LIST = '/api/bde/bookings/diagnostic/';
const bdeListOf = (booking_type) => ({ count: 1, page: 1, page_size: 25, timezone: 'Asia/Kolkata', results: [{
  id: `b-${booking_type.toLowerCase()}`, booking_type, date: '2026-11-10', time: '19:30', starts_at: '2026-11-10T14:00:00+00:00',
  status: 'BOOKED', activity_state: 'UPCOMING', started_at: null, booked_at: '2026-11-01T10:00:00+05:30', tutor: null,
  parent_confirmation: 'AWAITING', redemo: false,
  enquiry: { id: 'lead-1', parent_name: 'Asha Nair', student_name: 'Riya', grade: 'Class 8' } }] });
const lastParams = (url) => calls('GET', url).at(-1).params;
const pressed = () => [...document.querySelectorAll('[aria-pressed="true"]')].map((element) => clean(element.textContent));
const searchBox = () => document.querySelector('input[aria-label="Search bookings"]');
const LIST_STATUSES = ['BOOKED', 'COMPLETED', 'REDEMO_REQUIRED', 'RESCHEDULED', 'CANCELLED'].map((value) => ({ value }));

/** The options of the Radix Select labelled `label`, read with it open, then closed again. */
async function optionsOf(label) {
  const trigger = document.querySelector(`[aria-label="${label}"]`);
  trigger.focus();
  await keyDown(trigger, 'Enter');
  const options = [...document.querySelectorAll('[role="option"]')].map((element) => clean(element.textContent));
  await keyDown(document.activeElement, 'Escape');
  return options;
}

test('BDE booking filters: Today, This Week (Monday to Sunday) and This Month are Indian dates, whatever the device says', () => {
  const at = (iso) => new Date(iso);
  // 01:30 IST on Monday 9 Nov is still Sunday 8 Nov in UTC: India's date decides.
  assert.equal(indianToday(at('2026-11-08T20:00:00Z')), '2026-11-09');
  assert.deepEqual(classDateSpan('today', at('2026-11-08T20:00:00Z')), { from: '2026-11-09', to: '2026-11-09' });
  assert.deepEqual(classDateSpan('week', at('2026-11-08T20:00:00Z')), { from: '2026-11-09', to: '2026-11-15' });
  // A Sunday closes its week; a week and a month run across a new year and a leap day.
  assert.deepEqual(classDateSpan('week', at('2026-11-08T10:00:00Z')), { from: '2026-11-02', to: '2026-11-08' });
  assert.deepEqual(classDateSpan('week', at('2027-01-01T06:00:00Z')), { from: '2026-12-28', to: '2027-01-03' });
  assert.deepEqual(classDateSpan('month', at('2028-02-10T06:00:00Z')), { from: '2028-02-01', to: '2028-02-29' });
  // 23:59 IST on 31 Dec is December; midnight IST (18:30 UTC) is January.
  assert.deepEqual(classDateSpan('month', at('2026-12-31T18:29:00Z')), { from: '2026-12-01', to: '2026-12-31' });
  assert.deepEqual(classDateSpan('month', at('2026-12-31T18:30:00Z')), { from: '2027-01-01', to: '2027-01-31' });
  assert.equal(classDateSpan('all', at('2026-11-08T10:00:00Z')), null);
  assert.equal(classDateSpan('custom', at('2026-11-08T10:00:00Z')), null);
});

test('BDE booking filters: read from the URL, unknown values dropped, a link from before the presets kept as Custom', () => {
  const read = (query) => readBdeBookingFilters(new URLSearchParams(query), LIST_STATUSES, new Date('2026-11-08T10:00:00Z'));
  const defaults = { page: 1, q: '', status: '', when: 'upcoming', dates: 'all', from: '', to: '', filtered: false };
  assert.deepEqual(read(''), defaults);
  assert.deepEqual(read('dates=week&status=BOOKED&when=past&q=Riya&page=3'),
    { page: 3, q: 'Riya', status: 'BOOKED', when: 'past', dates: 'week', from: '2026-11-02', to: '2026-11-08', filtered: true });
  // A preset's own span wins over stray dates; Custom has its own; only from/to is Custom; Custom without them is All Time.
  assert.deepEqual([read('dates=month&from=2026-01-01').from, read('dates=month&from=2026-01-01').to], ['2026-11-01', '2026-11-30']);
  assert.deepEqual(read('dates=custom&from=2026-11-01&to=2026-11-15'),
    { ...defaults, dates: 'custom', from: '2026-11-01', to: '2026-11-15', filtered: true });
  assert.equal(read('from=2026-11-01&to=2026-11-15').dates, 'custom');
  assert.deepEqual(read('dates=custom'), defaults);
  assert.deepEqual(read('dates=yesterday&status=LOST&when=soon&from=2026-1-1'), defaults);
  assert.deepEqual(read('when=all'), { ...defaults, when: 'all', filtered: true });
  // What the API is asked: All Schedules asks for neither; All Time for no dates.
  assert.deepEqual(bdeBookingParams(read(''), 25), { page: 1, page_size: 25, when: 'upcoming' });
  assert.deepEqual(bdeBookingParams(read('dates=today&when=all&status=CANCELLED'), 25),
    { page: 1, page_size: 25, status: 'CANCELLED', from: '2026-11-08', to: '2026-11-08' });
});

test('BDE Demo Bookings: class date presets and the other filters combine, each change on page 1; Clear all filters puts them back', async () => {
  serve({ [`GET ${BDE_DEMO_LIST}`]: bdeListOf('DEMO') });
  const page = await open('/demo-bookings?page=2', BDE_LISTS);
  assert.deepEqual(lastParams(BDE_DEMO_LIST), { page: 2, page_size: 25, when: 'upcoming' });
  assert.deepEqual(pressed(), ['All Time']);
  assert.match(bodyText(), /Class dateTodayThis WeekThis MonthAll TimeCustomClasses on any date/);
  assert.ok(!button('Clear all filters'), 'nothing to clear at the defaults');
  // The table and its View are as before.
  assert.equal(rows().length, 1);
  assert.ok(document.querySelector('a[aria-label="View Riya\'s booking on Tue, 10 Nov · 7:30 PM IST"]'));

  const month = classDateSpan('month', new Date());
  await click(button('This Month'));
  assert.equal(page.location().search, '?dates=month');
  assert.deepEqual(lastParams(BDE_DEMO_LIST), { page: 1, page_size: 25, when: 'upcoming', ...month });
  assert.deepEqual(pressed(), ['This Month']);
  assert.ok(bodyText().includes(`Classes on ${rangeLabel(month.from, month.to)} (IST)`));

  await choose('Filter by booking status', 'Booked');
  await choose('Filter by schedule', 'Past');
  assert.deepEqual(lastParams(BDE_DEMO_LIST), { page: 1, page_size: 25, status: 'BOOKED', when: 'past', ...month });
  await choose('Filter by schedule', 'All Schedules');
  await typeInto(searchBox(), 'Riya');
  await submit(searchBox().closest('form'));
  assert.deepEqual(lastParams(BDE_DEMO_LIST), { page: 1, page_size: 25, q: 'Riya', status: 'BOOKED', ...month });
  assert.equal(page.location().search, '?dates=month&status=BOOKED&when=all&q=Riya');
  assert.deepEqual(await optionsOf('Filter by booking status'),
    ['All statuses', 'Booked', 'Completed', 'Re-Demo required', 'Rescheduled', 'Cancelled']);

  await click(button('Clear all filters'));
  assert.equal(page.location().search, '');
  assert.deepEqual(lastParams(BDE_DEMO_LIST), { page: 1, page_size: 25, when: 'upcoming' });
  assert.deepEqual(pressed(), ['All Time']);
  assert.equal(searchBox().value, '');
  assert.ok(!button('Clear all filters'));
});

test('BDE Diagnostic Bookings: the same filters -- a Custom range from the URL or picked on the calendar, and Today', async () => {
  serve({ [`GET ${BDE_DIAGNOSTIC_LIST}`]: bdeListOf('DIAGNOSTIC') });
  const page = await open('/diagnostic-bookings?dates=custom&from=2026-11-01&to=2026-11-15', BDE_LISTS);
  assert.deepEqual(lastParams(BDE_DIAGNOSTIC_LIST),
    { page: 1, page_size: 25, when: 'upcoming', from: '2026-11-01', to: '2026-11-15' });
  assert.deepEqual(pressed(), ['Custom']);
  assert.ok(bodyText().includes('Classes on 1 Nov 2026 – 15 Nov 2026 (IST)'));
  assert.ok(button('Clear all filters'));
  // A Re-Demo is only ever a Demo's.
  assert.deepEqual(await optionsOf('Filter by booking status'), ['All statuses', 'Booked', 'Completed', 'Rescheduled', 'Cancelled']);
  assert.deepEqual(await optionsOf('Filter by schedule'), ['Upcoming', 'Past', 'All Schedules']);

  const today = classDateSpan('today', new Date());
  await click(button('Today'));
  assert.equal(page.location().search, '?dates=today');
  assert.deepEqual(lastParams(BDE_DIAGNOSTIC_LIST), { page: 1, page_size: 25, when: 'upcoming', ...today });

  // Custom: two clicks on the calendar, in either order, make the range -- here the last day first.
  const month = today.from.slice(0, 8);
  await click(button('Custom'));
  const calendar = () => document.querySelector('[role="dialog"]');
  assert.match(clean(calendar().textContent), /Pick the first day\./);
  // Its weeks run Monday to Sunday, as This Week does.
  assert.deepEqual([...calendar().querySelectorAll('thead th')].map((th) => th.textContent),
    ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']);
  await click(calendar().querySelector(`td[data-day="${month}12"] button`));
  assert.match(clean(calendar().textContent), /Now pick the last day\./);
  assert.equal(calls('GET', BDE_DIAGNOSTIC_LIST).length, 2, 'nothing is asked for before the range is whole');
  await click(calendar().querySelector(`td[data-day="${month}10"] button`));
  assert.equal(page.location().search, `?dates=custom&from=${month}10&to=${month}12`);
  assert.deepEqual(lastParams(BDE_DIAGNOSTIC_LIST),
    { page: 1, page_size: 25, when: 'upcoming', from: `${month}10`, to: `${month}12` });
  assert.deepEqual(pressed(), ['Custom']);
  assert.ok(!calendar(), 'the calendar closes once the range is picked');
});

// ------------------------------------------------------- Student Time (Student Local Time)
// Beside each booking's Indian time, the student's own: the booking's real UTC
// instant (starts_at) read in the zone the student's lead keeps
// (student_timezone, backend bookings.student_timezones) -- never the slot's
// date and time strings, nor the responses' `timezone` (India's). Every
// instant below is the very IST date and time it is booked at.
const SUN_8_NOV_0730 = '2026-11-08T02:00:00+00:00'; // Sun 8 Nov, 7:30 AM IST -- 6:00 AM in Dubai
const SAT_7_NOV_0730 = '2026-11-07T02:00:00+00:00'; // Sat 7 Nov, 7:30 AM IST -- 9:00 PM on Fri 6 Nov in New York (EST)
const SAT_7_NOV_1930 = '2026-11-07T14:00:00+00:00'; // Sat 7 Nov, 7:30 PM IST
const MON_9_NOV_1930 = '2026-11-09T14:00:00+00:00'; // Mon 9 Nov, 7:30 PM IST
const TUE_10_NOV_1000 = '2026-11-10T04:30:00+00:00'; // Tue 10 Nov, 10:00 AM IST

const fieldsShown = () => Object.fromEntries([...document.querySelectorAll('dt')]
  .map((dt) => [clean(dt.textContent), clean(dt.nextElementSibling?.textContent)]));
const headings = () => [...document.querySelectorAll('th')].map((th) => clean(th.textContent));
/** Each row's cell under the header `header`, as read. */
const column = (header) => {
  const index = headings().indexOf(header);
  assert.ok(index >= 0, `a ${header} column`);
  return rows().map((row) => clean(row.querySelectorAll('td')[index].textContent));
};
/** Lay the page out as a phone (390px wide) while `fn` runs: ResponsiveList shows cards. */
async function onAPhone(fn) {
  const wide = window.innerWidth;
  Object.defineProperty(window, 'innerWidth', { value: 390, configurable: true, writable: true });
  try {
    await fn();
  } finally {
    Object.defineProperty(window, 'innerWidth', { value: wide, configurable: true, writable: true });
  }
}

test('Student Time: a booking at its student\'s own time, from its instant and their zone; India\'s clock adds nothing', () => {
  assert.deepEqual(studentTime(SUN_8_NOV_0730, 'Asia/Dubai'),
    { time: '6:00 AM', day: 'Sun, 8 Nov', otherDay: false, place: 'UAE', label: '6:00 AM UAE' });
  assert.equal(studentTimeState(SUN_8_NOV_0730, 'Asia/Dubai'), 'different');
  // Across midnight: Saturday morning in India is Friday evening in New York, which says the day.
  assert.deepEqual(studentTime(SAT_7_NOV_0730, 'America/New_York'),
    { time: '9:00 PM', day: 'Fri, 6 Nov', otherDay: true, place: 'New York', label: 'Fri, 6 Nov · 9:00 PM New York' });
  assert.equal(studentTime(new Date(SAT_7_NOV_0730), 'America/New_York').label, 'Fri, 6 Nov · 9:00 PM New York', 'a Date too');
  // India's zone, its old name (a browser may send it) and Sri Lanka read India's clock: the same, never a zone name compared.
  for (const zone of ['Asia/Kolkata', 'Asia/Calcutta', 'Asia/Colombo']) {
    assert.equal(studentTime(SAT_7_NOV_1930, zone), null, zone);
    assert.equal(studentTimeState(SAT_7_NOV_1930, zone), 'same', zone);
  }
});

test('Student Time: daylight saving is the zone\'s own at the instant -- London and Sydney, summer and winter', () => {
  // 7:30 PM IST: British Summer Time in July, Greenwich Mean Time in November.
  assert.equal(studentTime('2026-07-07T14:00:00+00:00', 'Europe/London').label, '3:00 PM UK');
  assert.equal(studentTime(SAT_7_NOV_1930, 'Europe/London').label, '2:00 PM UK');
  // Sydney is past midnight either way: AEDT (UTC+11) in November, AEST (UTC+10) in July -- midnight itself.
  assert.deepEqual(studentTime(SAT_7_NOV_1930, 'Australia/Sydney'),
    { time: '1:00 AM', day: 'Sun, 8 Nov', otherDay: true, place: 'Sydney', label: 'Sun, 8 Nov · 1:00 AM Sydney' });
  assert.deepEqual(studentTime('2026-07-07T14:00:00+00:00', 'Australia/Sydney'),
    { time: '12:00 AM', day: 'Wed, 8 Jul', otherDay: true, place: 'Sydney', label: 'Wed, 8 Jul · 12:00 AM Sydney' });
  // New York either side of its change on 1 November: EDT, then EST.
  assert.equal(studentTime('2026-10-31T14:00:00+00:00', 'America/New_York').label, '10:00 AM New York');
  assert.equal(studentTime('2026-11-01T14:00:00+00:00', 'America/New_York').label, '9:00 AM New York');
});

test('Student Time: no zone, a zone nobody knows, or no instant -- nothing to show, and nothing thrown', () => {
  for (const zone of [null, undefined, '', 'Not/AZone', 'Asia/Atlantis', 42]) {
    assert.equal(studentTime(SUN_8_NOV_0730, zone), null, String(zone));
    assert.equal(studentTimeState(SUN_8_NOV_0730, zone), 'unknown', String(zone));
  }
  // A saved zone this browser's own zone data does not know (the server's may be newer) is still the lead's:
  // shown as it is, and a correction opens on it rather than on Not set.
  for (const zone of [null, undefined, '', 42]) assert.equal(savedTimezoneLabel(zone), 'Not set', String(zone));
  for (const zone of ['Not/AZone', 'Asia/Atlantis']) {
    assert.equal(savedTimezoneLabel(zone), zone);
    assert.equal(listedTimezone(zone), zone);
  }
  for (const instant of [null, undefined, '', 'not a date', new Date(NaN)]) {
    assert.equal(studentTime(instant, 'Asia/Dubai'), null, String(instant));
    assert.equal(studentTimeState(instant, 'Asia/Dubai'), 'unknown', String(instant));
  }
  assert.equal(studentTimezoneLabel(null), '');
});

test('Student Time: where a zone is -- the curated names, an IANA city, an offset where a zone names no place', () => {
  const label = (zone) => studentTimezoneLabel(zone, new Date(SAT_7_NOV_1930));
  assert.deepEqual(['Asia/Dubai', 'Europe/London', 'Asia/Riyadh', 'Asia/Colombo', 'Asia/Dhaka'].map(label),
    ['UAE', 'UK', 'KSA', 'Sri Lanka', 'Bangladesh']);
  // Where the curated short label is an abbreviation (ET, AEST, SGT, IST), its place.
  assert.deepEqual(['America/New_York', 'America/Los_Angeles', 'Australia/Sydney', 'Australia/Perth', 'Asia/Singapore',
    'Asia/Kolkata'].map(label), ['New York', 'Los Angeles', 'Sydney', 'Perth', 'Singapore', 'India']);
  // A listed zone under an older name a browser may give is that zone, on every engine alike (a table, never
  // the engine's own resolution: Chrome resolves Asia/Kolkata to Asia/Calcutta, Safari keeps the name it is given).
  assert.deepEqual(['Asia/Calcutta', 'US/Eastern', 'Asia/Katmandu', 'Australia/NSW', 'GB', 'Singapore'].map(label),
    ['India', 'New York', 'Nepal', 'Sydney', 'UK', 'Singapore']);
  assert.deepEqual(['Asia/Calcutta', 'Asia/Katmandu', 'US/Pacific', 'Australia/West', 'Europe/Belfast', 'Asia/Dubai',
    'Europe/Berlin', '', null].map(listedTimezone),
  ['Asia/Kolkata', 'Asia/Kathmandu', 'America/Los_Angeles', 'Australia/Perth', 'Europe/London', 'Asia/Dubai',
    'Europe/Berlin', '', '']);
  assert.equal(savedTimezoneLabel('Asia/Katmandu'), 'Nepal (Asia/Katmandu)');
  assert.deepEqual(['Europe/Berlin', 'America/Argentina/Buenos_Aires', 'Asia/Ho_Chi_Minh'].map(label),
    ['Berlin', 'Buenos Aires', 'Ho Chi Minh']);
  assert.deepEqual(['Etc/GMT+5', 'Etc/GMT-4'].map(label), ['GMT-5', 'GMT+4']);
  assert.equal(studentTime(SAT_7_NOV_1930, 'Etc/GMT+5').label, '9:00 AM GMT-5');
  assert.equal(studentTime(SAT_7_NOV_1930, 'Europe/Berlin').label, '3:00 PM Berlin');
  // The zone a lead keeps, as its details show it.
  assert.equal(savedTimezoneLabel('Asia/Dubai'), 'United Arab Emirates (Asia/Dubai)');
  assert.equal(savedTimezoneLabel('Asia/Calcutta'), 'India (Asia/Calcutta)');
  assert.equal(savedTimezoneLabel('Europe/Berlin'), 'Europe/Berlin');
  // `place` is the Student Time's alone: what the session and exam selects offer, and their short labels, are as they were.
  assert.deepEqual(TIMEZONE_OPTIONS.map(({ value, label: name, short }) => `${value}|${name}|${short}`), [
    'Asia/Kolkata|India|IST', 'Asia/Dubai|United Arab Emirates|UAE', 'Asia/Qatar|Qatar|Qatar', 'Asia/Riyadh|Saudi Arabia|KSA',
    'Asia/Kuwait|Kuwait|Kuwait', 'Asia/Bahrain|Bahrain|Bahrain', 'Asia/Muscat|Oman|Oman', 'Asia/Singapore|Singapore|SGT',
    'Europe/London|United Kingdom|UK', 'America/New_York|US — Eastern|ET', 'America/Chicago|US — Central|CT',
    'America/Denver|US — Mountain|MT', 'America/Los_Angeles|US — Pacific|PT', 'Australia/Sydney|Australia — Sydney|AEST',
    'Australia/Perth|Australia — Perth|AWST', 'Asia/Colombo|Sri Lanka|Sri Lanka', 'Asia/Kathmandu|Nepal|Nepal',
    'Asia/Dhaka|Bangladesh|Bangladesh']);
});

test('Student Time: a list shows its column only while one of its bookings reads differently; the correction routes', () => {
  const row = (starts_at, student_timezone) => ({ starts_at, student_timezone });
  const shows = (list) => showsStudentTime(list, (entry) => entry.starts_at, (entry) => entry.student_timezone);
  assert.equal(shows([]), false);
  assert.equal(shows(undefined), false);
  assert.equal(shows([row(SAT_7_NOV_1930, 'Asia/Kolkata'), row(SAT_7_NOV_1930, null), row(SAT_7_NOV_1930, 'Not/AZone')]), false);
  assert.equal(shows([row(SAT_7_NOV_1930, 'Asia/Calcutta'), row(SUN_8_NOV_0730, 'Asia/Dubai')]), true);
  assert.equal(enquiryTimezoneUrl('lead-1'), '/api/bde/enquiries/lead-1/student-timezone/');
  assert.equal(leadTimezoneUrl('lead-1'), '/api/leads/lead-1/student-timezone/');
});

// The administrators' rows (backend coordination.booking_row): the slot nested, the student's zone beside it.
const zonedSlot = (id, booking_type, date, time, starts_at) => ({ id, booking_type, date, time, starts_at,
  ends_at: new Date(Date.parse(starts_at) + 3_600_000).toISOString(), started: false, ended: false });
const ZARA = { ...RIYA, id: 'b-zara', student_name: 'Zara', student_timezone: 'Asia/Dubai',
  slot: zonedSlot('s-zara', 'DEMO', '2026-11-08', '07:30', SUN_8_NOV_0730) };
const NOAH = { ...RIYA, id: 'b-noah', student_name: 'Noah', student_timezone: 'America/New_York',
  slot: zonedSlot('s-noah', 'DEMO', '2026-11-07', '07:30', SAT_7_NOV_0730) };
const ISHA = { ...RIYA, id: 'b-isha', student_name: 'Isha', student_timezone: 'Asia/Calcutta',
  slot: zonedSlot('s-isha', 'DEMO', '2026-11-09', '19:30', MON_9_NOV_1930) };
const OMAR = { ...RIYA, id: 'b-omar', student_name: 'Omar', student_timezone: null,
  slot: zonedSlot('s-omar', 'DEMO', '2026-11-10', '10:00', TUE_10_NOV_1000) };
// A zone this browser does not know must not take the page down: Intl would throw on it.
const UNKNOWN_ZONE = { ...OMAR, id: 'b-unknown', student_name: 'Uma', student_timezone: 'Not/AZone' };

test('Student Time: the administrators\' Demo bookings show each student\'s own time; Same as IST, or a dash while unknown', async () => {
  serve({ [`GET ${LIST}`]: list([ZARA, NOAH, ISHA, OMAR, UNKNOWN_ZONE]) });
  let page = await open('/bookings/demo', ADMIN);
  assert.deepEqual(headings(), ['Date & Time', 'Student Time', 'Student', 'Parent', 'Tutor', 'Status', 'Report', 'Actions']);
  assert.deepEqual(column('Student Time'), ['6:00 AM UAE', 'Fri, 6 Nov · 9:00 PM New York', 'Same as IST', '—', '—']);
  // The Indian time is as it was, in its own cell.
  assert.deepEqual(column('Date & Time'), ['Sun, 8 Nov7:30 AM IST', 'Sat, 7 Nov7:30 AM IST', 'Mon, 9 Nov7:30 PM IST',
    'Tue, 10 Nov10:00 AM IST', 'Tue, 10 Nov10:00 AM IST']);
  await page.unmount();

  // Nobody whose clock reads differently from India's: no column at all.
  serve({ [`GET ${LIST}`]: list([ISHA, OMAR, UNKNOWN_ZONE]) });
  page = await open('/bookings/demo', ADMIN);
  assert.deepEqual(headings(), ['Date & Time', 'Student', 'Parent', 'Tutor', 'Status', 'Report', 'Actions']);
  assert.equal(rows().length, 3);
  await page.unmount();

  // On a phone each booking is a card: Student Time is one of its fields.
  serve({ [`GET ${LIST}`]: list([ZARA, ISHA]) });
  await onAPhone(async () => {
    await open('/bookings/demo', ADMIN);
    const cards = [...document.querySelectorAll('[aria-label="Demo classes"] > li')].map((card) => clean(card.textContent));
    assert.equal(cards.length, 2);
    assert.match(cards[0], /Date & TimeSun, 8 Nov · 7:30 AM ISTStudent Time6:00 AM UAETutor/);
    assert.match(cards[1], /Date & TimeMon, 9 Nov · 7:30 PM ISTStudent TimeSame as ISTTutor/);
  });
});

// The BDE's rows (backend enquiries.booking_list_row): flat, the enquiry beside them.
const bdeZoned = (id, date, time, starts_at, student_timezone, student_name) => ({ id, booking_type: 'DEMO', date, time, starts_at,
  student_timezone, status: 'BOOKED', activity_state: 'UPCOMING', started_at: null, booked_at: '2026-11-01T10:00:00+05:30',
  tutor: null, parent_confirmation: 'AWAITING', redemo: false,
  enquiry: { id: `lead-${id}`, parent_name: 'Asha Nair', student_name, grade: 'Class 8' } });

test('Student Time: a BDE\'s Demo Bookings show each student\'s own time beside the Indian one; View keeps its name', async () => {
  serve({ [`GET ${BDE_DEMO_LIST}`]: { count: 3, page: 1, page_size: 25, timezone: 'Asia/Kolkata', results: [
    bdeZoned('b-zara', '2026-11-08', '07:30', SUN_8_NOV_0730, 'Asia/Dubai', 'Zara'),
    bdeZoned('b-noah', '2026-11-07', '07:30', SAT_7_NOV_0730, 'America/New_York', 'Noah'),
    bdeZoned('b-isha', '2026-11-09', '19:30', MON_9_NOV_1930, 'Asia/Kolkata', 'Isha'),
  ] } });
  let page = await open('/demo-bookings', BDE_LISTS);
  assert.deepEqual(headings(), ['Date & Time', 'Student Time', 'Student', 'Parent', 'Tutor', 'Status', 'Confirmation', 'Open']);
  assert.deepEqual(column('Student Time'), ['6:00 AM UAE', 'Fri, 6 Nov · 9:00 PM New York', 'Same as IST']);
  assert.ok(document.querySelector('a[aria-label="View Zara\'s booking on Sun, 8 Nov · 7:30 AM IST"]'));
  await page.unmount();

  // A list without a zone known: as before.
  serve({ [`GET ${BDE_DEMO_LIST}`]: bdeListOf('DEMO') });
  page = await open('/demo-bookings', BDE_LISTS);
  assert.deepEqual(headings(), ['Date & Time', 'Student', 'Parent', 'Tutor', 'Status', 'Confirmation', 'Open']);
});

test('Student Time: an enquiry\'s Bookings tab gives it a column of its own; the When cell is the slot alone', async () => {
  const zoned = (booking) => ({ ...booking, student_timezone: 'America/New_York' });
  serve({ [`GET ${ENQUIRY_URL}`]: { ...enquiry([zoned(BDE_BOOKED), zoned(BDE_CANCELLED)]), student_timezone: 'America/New_York' } });
  const page = await open('/enquiries/lead-1?tab=bookings', BDE);
  assert.deepEqual(headings(), ['When (IST)', 'Student Time', 'Type', 'Status', 'Tutor', 'Booked on', 'Actions']);
  // 7:30 PM IST on 31 October is 10:00 AM in New York (EDT); 10:00 AM IST on 29 October, half past midnight there.
  assert.deepEqual(column('Student Time'), ['10:00 AM New York', '12:30 AM New York']);
  assert.equal(clean(rows()[0].querySelector('td').textContent), 'Sat, 31 Oct · 7:30 PM IST');
  assert.ok(button('Cancel the demo class on Sat, 31 Oct · 7:30 PM IST'), 'the actions keep their names');
  await page.unmount();

  await onAPhone(async () => {
    await open('/enquiries/lead-1?tab=bookings', BDE);
    const cards = [...document.querySelectorAll('[aria-label="Bookings"] > li')].map((card) => clean(card.textContent));
    assert.match(cards[0], /^Sat, 31 Oct · 7:30 PM IST.*Student Time10:00 AM New YorkTutor/);
    assert.match(cards[1], /Student Time12:30 AM New YorkTutor/);
  });
});

// The tutor's own rows (backend tutor_bookings.booking_row): the slot nested, the student's zone beside the child.
const myZoned = (booking, id, student_name, date, time, starts_at, student_timezone) => ({ ...booking, id, student_name,
  student_timezone, slot: { date, time, starts_at, ends_at: new Date(Date.parse(starts_at) + 3_600_000).toISOString(),
    started: false, ended: false } });
const MY_ZARA = myZoned(MY_RIYA, 'b-zara', 'Zara', '2026-11-08', '07:30', SUN_8_NOV_0730, 'Asia/Dubai');
const MY_NOAH = myZoned(MY_RIYA, 'b-noah', 'Noah', '2026-11-07', '07:30', SAT_7_NOV_0730, 'America/New_York');
const MY_ISHA = myZoned(MY_RIYA, 'b-isha', 'Isha', '2026-11-09', '19:30', MON_9_NOV_1930, 'Asia/Kolkata');
const MY_OMAR = myZoned(MY_RIYA, 'b-omar', 'Omar', '2026-11-10', '10:00', TUE_10_NOV_1000, null);

test('Student Time: a tutor\'s Demo Bookings show each student\'s own time, in the table and on a phone\'s cards', async () => {
  serve({ [`GET ${MINE}`]: mine([MY_ZARA, MY_NOAH, MY_ISHA, MY_OMAR]) });
  let page = await open('/my-bookings/demo', TUTOR);
  assert.deepEqual(headings(), ['Date & Time (IST)', 'Student Time', 'Student', 'Class', 'Status', 'Feedback', 'Meeting', 'Actions']);
  assert.deepEqual(column('Student Time'), ['6:00 AM UAE', 'Fri, 6 Nov · 9:00 PM New York', 'Same as IST', '—']);
  assert.deepEqual(column('Date & Time (IST)'), ['Sun, 8 Nov7:30 AM IST', 'Sat, 7 Nov7:30 AM IST', 'Mon, 9 Nov7:30 PM IST',
    'Tue, 10 Nov10:00 AM IST']);
  await page.unmount();

  serve({ [`GET ${MINE}`]: mine([MY_ISHA, MY_OMAR]) });
  page = await open('/my-bookings/demo', TUTOR);
  assert.ok(!headings().includes('Student Time'), 'nobody whose clock reads differently: no column');
  await page.unmount();

  serve({ [`GET ${MINE}`]: mine([MY_NOAH, MY_OMAR]) });
  await onAPhone(async () => {
    await open('/my-bookings/demo', TUTOR);
    const cards = [...document.querySelectorAll('[aria-label="Demo Bookings"] > li')].map((card) => clean(card.textContent));
    assert.match(cards[0], /Date & TimeSat, 7 Nov · 7:30 AM ISTStudent TimeFri, 6 Nov · 9:00 PM New York/);
    assert.match(cards[1], /Date & TimeTue, 10 Nov · 10:00 AM ISTStudent Time—/);
  });
});

test('Student Time: a tutor\'s booking says it under its slot and in its Bookings tab; the zone is theirs to read, never to change', async () => {
  // The booking page's own words from when it was booked (details.display_time) are never what is shown.
  // Its enquiry's next booking is this child's too: read in the booking's own zone.
  const noah = { ...MY_NOAH, timezone: 'Asia/Kolkata', details: { display_time: '04:00 pm - 05:00 pm' },
    enquiry: { source_label: 'Booking page', status: 'DEMO_BOOKED', status_label: 'Demo booked', created_at: '2026-11-01T05:00:00+00:00',
      next_booking: { id: MY_NOAH.id, booking_type: 'DEMO', date: '2026-11-07', time: '07:30', starts_at: SAT_7_NOV_0730 }, bookings: [] } };
  serve({ [`GET ${myAt(MY_NOAH)}`]: noah });
  let page = await open(`/my-bookings/demo/${MY_NOAH.id}`, { ...TUTOR, permissions: [...TUTOR.permissions, 'accounts.change_student_timezone'] });
  assert.match(bodyText(), /Sat, 7 Nov · 7:30 AM IST\s*Student Time: Fri, 6 Nov · 9:00 PM New York/);
  assert.equal(fieldsShown()['Student timezone'], 'US — Eastern (America/New_York)');
  assert.equal(fieldsShown().Country, 'United Arab Emirates');
  assert.equal(fieldsShown()['Next booking'], 'Sat, 7 Nov · 7:30 AM ISTStudent Time: Fri, 6 Nov · 9:00 PM New York');
  assert.ok(!button('Change student timezone') && !button('Change'), 'a tutor reads the zone; only its BDE or an administrator corrects it');
  assert.ok(!bodyText().includes('04:00 pm'), 'never the booking page\'s own words');
  await mouseDown(tab('Bookings'));
  assert.deepEqual(headings(), ['Date & Time (IST)', 'Student Time', 'Booking Type', 'Status', 'Meeting', 'Action']);
  assert.deepEqual(column('Student Time'), ['Fri, 6 Nov · 9:00 PM New York']);
  await page.unmount();

  // India's clock: nothing added, the zone named all the same.
  serve({ [`GET ${myAt(MY_ISHA)}`]: { ...MY_ISHA, timezone: 'Asia/Kolkata' } });
  page = await open(`/my-bookings/demo/${MY_ISHA.id}`, TUTOR);
  assert.match(bodyText(), /Mon, 9 Nov · 7:30 PM IST/);
  assert.ok(!bodyText().includes('Student Time:'));
  assert.equal(fieldsShown()['Student timezone'], 'India (Asia/Kolkata)');
  await mouseDown(tab('Bookings'));
  assert.ok(!headings().includes('Student Time'));
});

test("Student Time: a BDE's communication sheet heads its booking with the student's own time beside the Indian one", async () => {
  // RIYA's slot, as the communication API gives it: Sat 31 Oct, 7:30 PM IST -- 6:00 PM in Dubai.
  const dubai = { ...BDE_BOOKED, parent_confirmation: 'CONFIRMED', student_timezone: 'Asia/Dubai' };
  serve({
    [`GET ${ENQUIRY_URL}`]: { ...enquiry([dubai]), student_timezone: 'Asia/Dubai' },
    [`GET ${commsUrl(BDE_BOOKED)}`]: communication(BDE_BOOKED),
  });
  const page = await open('/enquiries/lead-1?tab=bookings', BDE_COMMS);
  await click(button('Communication for the demo class on Sat, 31 Oct · 7:30 PM IST'));
  assert.match(clean(topDialog().textContent), /Sat, 31 Oct · 7:30 PM ISTStudent Time: 6:00 PM UAEBooked/);
  await page.unmount();

  // A student on India's clock: the header is the Indian time alone.
  serve({
    [`GET ${ENQUIRY_URL}`]: { ...enquiry([{ ...dubai, student_timezone: 'Asia/Calcutta' }]), student_timezone: 'Asia/Calcutta' },
    [`GET ${commsUrl(BDE_BOOKED)}`]: communication(BDE_BOOKED),
  });
  await open('/enquiries/lead-1?tab=bookings', BDE_COMMS);
  await click(button('Communication for the demo class on Sat, 31 Oct · 7:30 PM IST'));
  assert.ok(!clean(topDialog().textContent).includes('Student Time'));
});

// ------------------------------------------------------------------ run
let failed = 0;
for (const { name, fn } of tests) {
  globalThis.__bookingsApi = { calls: [], handler: () => fail(404, { message: 'No handler' }) };
  try {
    await fn();
    console.log(`  ✓ ${name}`);
  } catch (error) {
    failed += 1;
    console.log(`  ✗ ${name}\n    ${String(error.stack || error).split('\n').slice(0, 6).join('\n    ')}`);
  } finally {
    while (mounted.length) await mounted.pop().unmount();
    await settle(2);
  }
}
console.error = quiet;
console.log(`${tests.length - failed}/${tests.length} booking page tests passed.`);
window.close();
process.exit(failed ? 1 : 0);
