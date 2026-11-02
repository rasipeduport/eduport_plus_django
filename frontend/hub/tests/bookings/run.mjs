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
      build.onResolve({ filter: /lib\/api$/ }, (args) => (args.importer.startsWith(src) ? { path: path.join(here, 'api-stub.js') } : undefined));
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

const { mount, act, canOpenPage, homePage, ACTION_LABELS, actionLabel, describeActivity } = await import(pathToFileURL(bundle).href);

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
const RIYA = { id: 'b-riya', booking_type: 'DEMO', status: 'BOOKED', slot: slot('s-1', 'DEMO', '2026-10-31', '19:30'),
  student_name: 'Riya', grade: 'Class 8', parent_name: 'Asha Nair', phone: '+971 501234567', tutor: null, bde: null,
  booked_at: '2026-10-28T09:00:00+00:00' };
const ALI = { id: 'b-ali', booking_type: 'DIAGNOSTIC', status: 'BOOKED', slot: slot('s-2', 'DIAGNOSTIC', '2026-11-01', '10:00'),
  student_name: 'Ali', grade: 'Class 9', parent_name: 'Sara Khan', phone: '+91 9800000002',
  tutor: { id: 't-a', full_name: 'Tutor A' }, bde: { id: 'bde-1', full_name: 'Bde One' }, booked_at: '2026-10-28T10:00:00+00:00' };
const ARUN = { id: 'b-arun', booking_type: 'DEMO', status: 'BOOKED', slot: slot('s-3', 'DEMO', '2026-11-01', '19:30'),
  student_name: 'Arun', grade: 'Class 7', parent_name: 'Meena Raj', phone: '+971 509999999',
  tutor: { id: 't-b', full_name: 'Tutor B' }, bde: null, booked_at: '2026-10-28T11:00:00+00:00' };

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

test('loading, then the Demo bookings with assigned and unassigned ones told apart; Diagnostic is its own tab', async () => {
  const answer = deferred();
  serve({ [`GET ${LIST}`]: () => answer.promise, [`GET ${DIAGNOSTIC_LIST}`]: list([ALI]) });
  const page = await open('/bookings', ADMIN);
  assert.ok(document.querySelector('[data-slot="skeleton"]'), 'a loading skeleton while the list loads');
  assert.deepEqual(calls('GET', LIST)[0].params, { page: 1, page_size: 25, when: 'upcoming' });

  answer.resolve({ status: 200, data: list([RIYA, ARUN]) });
  await settle();
  assert.ok(!document.querySelector('[data-slot="skeleton"]'), 'the skeleton is gone');
  assert.deepEqual([...document.querySelectorAll('[role="tab"]')].map((element) => [clean(element.textContent),
    element.getAttribute('aria-selected')]), [['Demo', 'true'], ['Diagnostic', 'false']], 'a tab per type, Demo first');
  assert.deepEqual([...document.querySelectorAll('th')].map((th) => clean(th.textContent)),
    ['When (IST)', 'Student', 'Parent', 'Tutor', 'Status', 'Report', 'Actions'], 'one type per tab, so no type column; a report column (P8)');
  const [riya, arun] = rows();
  assert.match(clean(riya.textContent), /Sat, 31 Oct.*7:30 PM.*Riya.*Class 8.*Asha Nair.*Unassigned.*Upcoming/);
  assert.match(clean(arun.textContent), /Arun.*Tutor B.*Upcoming/);
  assert.ok(!arun.textContent.includes('Unassigned'));
  assert.ok(button('Assign', riya) && !button('Change', riya), 'an unassigned booking offers Assign');
  assert.ok(button('Change', arun) && !button('Assign', arun), 'an assigned booking offers Change');
  assert.match(bodyText(), /Showing 1–2 of 2/);

  await mouseDown(tab('Diagnostic'));
  assert.deepEqual(calls('GET', DIAGNOSTIC_LIST).map((entry) => entry.params), [{ page: 1, page_size: 25, when: 'upcoming' }]);
  assert.equal(new URLSearchParams(page.location().search).get('type'), 'DIAGNOSTIC');
  assert.deepEqual(rows().map((row) => clean(row.querySelector('td:nth-child(2) p').textContent)), ['Ali']);
  assert.ok(!globalThis.__bookingsApi.calls.some((entry) => entry.url === '/api/bookings/'), 'no combined list is asked for');
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
  const page = await open('/bookings', ADMIN);
  assert.match(clean(rows()[0].textContent), /^No upcoming demo bookings\.$/);
  assert.match(bodyText(), /No results/);
  await mouseDown(tab('Diagnostic'));
  assert.match(clean(rows()[0].textContent), /^No upcoming diagnostic bookings\.$/);
  await page.unmount();
  globalThis.__bookingsApi.calls = [];
  await open('/bookings?status=CANCELLED', ADMIN);
  assert.match(clean(rows()[0].textContent), /^No bookings match these filters\.$/);
  assert.equal(calls('GET', LIST)[0].params.status, 'CANCELLED');
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
  serve({ [`GET ${LIST}`]: list([RIYA]) });
  const page = await open('/bookings?page=2&from=2026-10-30&to=2026-11-02', ADMIN);
  assert.deepEqual(calls('GET', LIST).at(-1).params,
    { page: 2, page_size: 25, from: '2026-10-30', to: '2026-11-02', when: 'upcoming' });
  assert.match(bodyText(), /30 Oct 2026 – 2 Nov 2026/);

  await typeInto(document.querySelector('[aria-label="Search bookings"]'), 'riya');
  await submit(document.querySelector('[aria-label="Search bookings"]').closest('form'));
  assert.deepEqual(calls('GET', LIST).at(-1).params,
    { page: 1, page_size: 25, q: 'riya', from: '2026-10-30', to: '2026-11-02', when: 'upcoming' });

  // The other tab keeps the filters, and is a list of its own: the type is its URL, never a filter.
  await mouseDown(tab('Diagnostic'));
  assert.deepEqual(calls('GET', DIAGNOSTIC_LIST).at(-1).params,
    { page: 1, page_size: 25, q: 'riya', from: '2026-10-30', to: '2026-11-02', when: 'upcoming' });
  await choose('Filter by status', 'Cancelled');
  assert.equal(calls('GET', DIAGNOSTIC_LIST).at(-1).params.status, 'CANCELLED');
  await choose('Filter by status', 'Completed');
  assert.equal(calls('GET', DIAGNOSTIC_LIST).at(-1).params.status, 'COMPLETED');
  await choose('Filter by tutor assignment', 'Needs a tutor');
  assert.equal(calls('GET', DIAGNOSTIC_LIST).at(-1).params.assigned, 'false');
  await choose('Filter by when', 'All dates');
  const last = calls('GET', DIAGNOSTIC_LIST).at(-1).params;
  assert.equal('when' in last, false, '"All dates" sends no when filter');
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)),
    { q: 'riya', from: '2026-10-30', to: '2026-11-02', type: 'DIAGNOSTIC', status: 'COMPLETED', assigned: 'false', when: 'all' });

  await click(button('Clear'));
  assert.deepEqual(calls('GET', DIAGNOSTIC_LIST).at(-1).params, { page: 1, page_size: 25, when: 'upcoming' });
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { type: 'DIAGNOSTIC' });
  await mouseDown(tab('Demo'));
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), {}, 'Demo is the default tab');
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
  const page = await open('/bookings?type=DIAGNOSTIC', ADMIN);
  await click(button('View', rows()[0]));
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { type: 'DIAGNOSTIC', booking: ALI.id });
  assert.equal(calls('GET', '/api/bookings/diagnostic/b-ali/').length, 1);
  const sheet = topDialog();
  const text = clean(sheet.textContent);
  for (const shown of ['Ali', 'Tutor A', 'Assigned by', 'Admin One', 'Delhi Private School', 'Sara Khan', '+91 9800000002',
    "Through a BDE's link", 'Bde One', 'Diagnostic test']) {
    assert.ok(text.includes(shown), `the sheet shows ${shown}`);
  }
  assert.ok(button('Change tutor', sheet) && button('Unassign', sheet));

  // The other tab is the other type's list: the open booking closes, and the page starts again at 1.
  await mouseDown(tab('Demo'));
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), {});
  assert.ok(!topDialog(), 'the sheet closed');
});

test('a booking opened under the other type is not found', async () => {
  serve({ [`GET ${LIST}`]: list([RIYA]) });
  await open(`/bookings?booking=${ALI.id}`, ADMIN);
  assert.equal(calls('GET', `/api/bookings/demo/${ALI.id}/`).length, 1, 'asked for as a Demo booking, the tab it was opened on');
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
    ['Seat 1: Arun (Completed)', 'Seat 1: Arun (Completed), 7:30 PM – 8:30 PM: open the booking', '/bookings?type=DEMO&booking=b-arun'],
    ['Seat 2: Riya', 'Seat 2: Riya, 7:30 PM – 8:30 PM: open the booking', '/bookings?type=DEMO&booking=b-riya'],
  ], 'one link per seat, in seat order, named by the child and the slot');
  const bookingsCell = evening.querySelector('td:nth-child(2)');
  assert.ok(clean(bookingsCell.textContent).startsWith('2 / 3') && bookingsCell.querySelectorAll('a').length === 2,
    'the seats are listed under the count, in the Bookings column');

  await click(links[1]);
  assert.equal(page.location().pathname, '/bookings');
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { type: 'DEMO', booking: RIYA.id });
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
      tutor_change_refusal: { code: 'SLOT_STARTED', message: 'This booking has already started, so its tutor cannot be changed.' },
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
      refusal: { code: 'SLOT_STARTED', message: 'This booking has already started, so it can no longer be moved.' } },
  });
  await click(button('Cancel', topDialog()));
  await click(button('Reschedule', topDialog()));
  assert.match(clean(topDialog().textContent), /This booking has already started, so it can no longer be moved\./);
  assert.ok(button('Move booking', topDialog()).disabled);
});

test('Cancel: a reason from the list, No-show only once the slot has started; then a fresh list', async () => {
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
    'No-showAvailable once the slot has started.', 'Parent asked to cancel', 'Duplicate booking', 'Booked by mistake', 'Other',
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

test('Cancel: No-show once the slot has started, and a refusal shown as it comes', async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET ${at(RIYA)}`]: detail(RIYA, { actions: { cancel: true, no_show: true, reschedule: false } }),
    [`POST ${at(RIYA, 'cancel/')}`]: () => fail(409, { error: 'NO_SHOW_BEFORE_START',
      message: 'A booking can be marked No-show only once its slot has started.' }),
  });
  await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  assert.ok(!button('Reschedule', topDialog()), 'a started booking is not moved');
  await click(button('Cancel booking', topDialog()));
  assert.ok(!radio('No-show').disabled);
  await click(radio('No-show'));
  await click(button('Cancel booking', topDialog()));
  assert.deepEqual(calls('POST', at(RIYA, 'cancel/')).map((entry) => entry.data), [{ reason: 'NO_SHOW' }]);
  assert.match(clean(topDialog().textContent), /A booking can be marked No-show only once its slot has started\./);
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
  status: 'BOOKED', ended: false, booked_at: '2026-10-28T09:00:00+00:00', cancelled_at: null, actions: { cancel: true, no_show: false } };
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
  await open('/enquiries/lead-1', BDE);
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
  await open('/enquiries/lead-1', BDE);
  await click(button('Cancel the demo class on Sat, 31 Oct · 7:30 PM IST'));
  await click(radio('Other', topDialog()));
  await click(button('Cancel booking', topDialog()));
  assert.match(clean(topDialog().textContent), /No such booking\./);
  assert.ok(!/Cancelled Riya's/.test(bodyText()));
});

test('BDE: no Cancel unless the API offers it', async () => {
  serve({ [`GET ${ENQUIRY_URL}`]: enquiry([{ ...BDE_BOOKED, actions: { cancel: false, no_show: false } }, { ...BDE_BOOKED, id: 'b-3', actions: undefined }]) });
  await open('/enquiries/lead-1', BDE);
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
const DEV = { ...RIYA, id: 'b-dev', student_name: 'Dev', slot: OVER, tutor: TUTOR_A, ...reportFields({ report_due: true }) };
const NOOR = { ...RIYA, id: 'b-noor', student_name: 'Noor', slot: OVER, tutor: null, ...reportFields({ report_due: true }) };
const SAM = { ...RIYA, id: 'b-sam', student_name: 'Sam', slot: { ...RIYA.slot, started: true }, tutor: TUTOR_A, ...reportFields() };
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
  assert.deepEqual(cells.map((cell) => clean(cell.textContent)), ['Report v2', 'Report due', 'Report due', '—', '—']);
  assert.deepEqual(cells.map((cell) => cell.querySelector('[data-slot="badge"]')?.dataset.variant ?? null),
    ['success', 'warning', 'warning', null, null]);
});

test('reports: Filter by report reaches the API and the URL with search and every other filter; Report due looks at past slots', async () => {
  serve({ [`GET ${LIST}`]: list([IRA]) });
  const page = await open('/bookings', ADMIN);
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
  await choose('Filter by status', 'Booked');
  await choose('Filter by tutor assignment', 'Tutor assigned');
  assert.deepEqual(params(), { page: 1, page_size: 25, q: 'Dev', status: 'BOOKED', assigned: 'true', report: 'due', when: 'past' });
  await choose('Filter by when', 'All dates');
  assert.deepEqual(params(), { page: 1, page_size: 25, q: 'Dev', status: 'BOOKED', assigned: 'true', report: 'due' });
  // Back to Upcoming: no report is due there, so Report due goes rather than empty the list.
  await choose('Filter by when', 'Upcoming');
  assert.deepEqual(params(), { page: 1, page_size: 25, q: 'Dev', status: 'BOOKED', assigned: 'true', when: 'upcoming' });
  assert.equal(query().report, undefined);

  await choose('Filter by report', 'Report due');
  await click(button('Clear'));
  assert.deepEqual(params(), { page: 1, page_size: 25, when: 'upcoming' });
  assert.deepEqual(query(), {});
  await page.unmount();

  // A link to the reports due shows them, whatever it says of Upcoming; an unknown value is dropped.
  for (const [link, sent] of [
    ['/bookings?report=due', { page: 1, page_size: 25, report: 'due', when: 'past' }],
    ['/bookings?report=due&when=upcoming', { page: 1, page_size: 25, report: 'due', when: 'past' }],
    ['/bookings?report=due&when=all', { page: 1, page_size: 25, report: 'due' }],
    ['/bookings?report=overdue', { page: 1, page_size: 25, when: 'upcoming' }],
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

test('reports: a booking without its report says why -- due (with or without a tutor), in progress, upcoming; none for a cancelled one', async () => {
  for (const [booking, says] of [
    [DEV, 'Report due. The class is over and the tutor has not written the report yet.'],
    [NOOR, 'Report due. The class is over, and no tutor is assigned to write the report.'],
    [SAM, 'The class has started. The tutor can write the report now.'],
    [SOON, 'The tutor can write the report once the class starts.'],
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
// sends a report outside the Hub; nothing here records a send.
const BDE_REPORTS = { ...BDE, permissions: [...BDE.permissions, 'accounts.view_own_lead_reports'] };
const REPORTS_URL = '/api/bde/enquiries/lead-1/reports/';
const DONE = { status: 'COMPLETED', ended: true, cancelled_at: null, actions: { cancel: false, no_show: false } };
const DONE_DEMO = { ...BDE_BOOKED, ...DONE, id: 'b-7' };
const DONE_DIAGNOSTIC = { ...BDE_CANCELLED, ...DONE, id: 'b-8' };
const DONE_DEMO_PDF = `/api/bde/bookings/demo/${DONE_DEMO.id}/report/pdf/`;
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
  await open('/enquiries/lead-1', BDE_REPORTS);
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
  await open('/enquiries/lead-1', BDE_REPORTS);
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
  await open('/enquiries/lead-1', BDE_REPORTS);
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
  await open('/enquiries/lead-1', BDE_REPORTS);
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
    serve({ ...leadWithReports(DEMO_REPORT), [`GET ${DONE_DEMO_PDF}`]: pdfAnswer('Demo-Report-Riya-2026-10-31.pdf') });
    await open('/enquiries/lead-1', BDE_REPORTS);
    assert.match(bodyText(), /Share PDF hands the PDF to WhatsApp or another app on this device\. Pick the parent’s chat there\./);
    // The PDF arrived after the browser stopped counting the tap: kept, and the next tap shares it at once.
    await click(button('Share the demo class report PDF'));
    assert.match(clean(reportItems()[0].textContent), /The PDF is ready\. Tap Share PDF again to share it\./);
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
  assert.ok(onlyReads(), 'nothing about a share is recorded');
});

// ------------------------------------------------------------ My Bookings (tutors)
const MINE = '/api/tutor/bookings/';
const VIEW_ASSIGNED = 'accounts.view_assigned_bookings';
const TUTOR = { id: 'tutor', role: 'TUTOR', permissions: [VIEW_ASSIGNED, 'accounts.view_staff_dashboard'] };

// The tutor API's rows (backend bookings.tutor_bookings): the slot, without its id, and the child.
const mySlot = (date, time) => ({ date, time, starts_at: `${date}T14:00:00+00:00`, ends_at: `${date}T15:00:00+00:00`,
  started: false, ended: false });
const MY_RIYA = { id: 'b-riya', booking_type: 'DEMO', status: 'BOOKED', slot: mySlot('2026-10-31', '19:30'),
  student_name: 'Riya', grade: 'Class 8', syllabus: 'CBSE', school_name: 'Delhi Private School', country: 'United Arab Emirates' };
const MY_ALI = { id: 'b-ali', booking_type: 'DIAGNOSTIC', status: 'CANCELLED', slot: mySlot('2026-11-01', '10:00'),
  student_name: 'Ali', grade: 'Class 9', syllabus: 'IGCSE', school_name: 'Al Noor School', country: 'India' };
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
    ['When (IST)', 'Type', 'Student', 'Syllabus', 'School', 'Country', 'Status', 'Actions']);
  const [riya, ali] = rows();
  assert.match(clean(riya.textContent),
    /^Sat, 31 Oct7:30 PMDemo classRiyaClass 8CBSEDelhi Private SchoolUnited Arab EmiratesUpcomingView$/);
  assert.match(clean(ali.textContent), /^Sun, 1 Nov10:00 AMDiagnostic testAliClass 9IGCSEAl Noor SchoolIndiaCancelledView$/);
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
// and the slot's started / ended, as the tutor's rows carry them (backend bookings.tutor_bookings).
const reportOf = (row, slot, report) => ({ ...row, slot: { ...row.slot, ...slot }, has_report: false, report_version: null,
  report_due: false, ...report });
const MY_UPCOMING = reportOf(MY_RIYA, {}, {});
const MY_RUNNING = reportOf({ ...MY_RIYA, id: 'b-sam', student_name: 'Sam' }, { started: true }, {});
const MY_DUE = reportOf({ ...MY_RIYA, id: 'b-dev', booking_type: 'DIAGNOSTIC', student_name: 'Dev' }, { started: true, ended: true },
  { report_due: true });
const MY_DONE = reportOf({ ...MY_RIYA, id: 'b-ira', status: 'COMPLETED', student_name: 'Ira' }, { started: true, ended: true },
  { has_report: true, report_version: 2 });
const MY_CANCELLED = reportOf(MY_ALI, { started: true, ended: true }, {});

/** The report links in ``root``: [label, where it goes]. */
const reportLinks = (root) => [...root.querySelectorAll('a')].map((link) => [clean(link.textContent), link.getAttribute('href')]);

test('My Bookings: each booking says where it stands with its report, and offers Write report or Edit report', async () => {
  serve({ [`GET ${MINE}`]: mine([MY_UPCOMING, MY_RUNNING, MY_DUE, MY_DONE, MY_CANCELLED]) });
  await open('/my-bookings', TUTOR);
  const status = (row) => clean(row.querySelectorAll('td')[6].textContent);
  const actions = (row) => row.querySelectorAll('td')[7];
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
  // Report due is the API's word: a booked booking whose slot is over without it stays In progress.
  serve({ [`GET ${MINE}`]: mine([reportOf(MY_RIYA, { started: true, ended: true }, {})]) });
  await click(button('Refresh'));
  assert.equal(status(rows()[0]), 'In progress');
  assert.ok(globalThis.__bookingsApi.calls.every((entry) => entry.method === 'GET'), 'only reads');
});

test("My Bookings: the sheet's Report section -- what the report waits for, or its version, its PDF and Edit report", async () => {
  const cases = [
    [MY_UPCOMING, 'You can write the report once the class starts.', [], false],
    [MY_RUNNING, 'The class has started. You can write the report now.', [['Write report', '/my-bookings/demo/b-sam/report']], false],
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
  for (const later of ['conversion.stage', 'conversion.enrol', 'lead.assign_owner']) {
    assert.ok(!(later in ACTION_LABELS), `${later} is labelled once something logs it`);
  }
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
