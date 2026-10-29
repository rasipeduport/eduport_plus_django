// Booking page tests: the real Bookings page (src/pages/BookingsPage.jsx) in
// jsdom, its API answered per test by api-stub.js, driven as an administrator
// would -- filters, paging, the detail sheet, and assigning, reassigning and
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

const { mount, act, canOpenPage, homePage } = await import(pathToFileURL(bundle).href);

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
const LIST = '/api/bookings/';
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

test('loading, then every booking with assigned and unassigned ones told apart', async () => {
  const answer = deferred();
  serve({ [`GET ${LIST}`]: () => answer.promise });
  await open('/bookings', ADMIN);
  assert.ok(document.querySelector('[data-slot="skeleton"]'), 'a loading skeleton while the list loads');
  assert.deepEqual(calls('GET', LIST)[0].params, { page: 1, page_size: 25, when: 'upcoming' });

  answer.resolve({ status: 200, data: list([RIYA, ALI]) });
  await settle();
  assert.ok(!document.querySelector('[data-slot="skeleton"]'), 'the skeleton is gone');
  const [riya, ali] = rows();
  assert.match(clean(riya.textContent), /Sat, 31 Oct.*7:30 PM.*Demo class.*Riya.*Class 8.*Asha Nair.*Unassigned.*Upcoming/);
  assert.match(clean(ali.textContent), /Diagnostic test.*Ali.*Tutor A.*Upcoming/);
  assert.ok(!ali.textContent.includes('Unassigned'));
  assert.ok(button('Assign', riya) && !button('Change', riya), 'an unassigned booking offers Assign');
  assert.ok(button('Change', ali) && !button('Assign', ali), 'an assigned booking offers Change');
  assert.match(bodyText(), /Showing 1–2 of 2/);
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
  serve({ [`GET ${LIST}`]: list([]) });
  const page = await open('/bookings', ADMIN);
  assert.match(clean(rows()[0].textContent), /^No upcoming bookings\.$/);
  assert.match(bodyText(), /No results/);
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

  await mouseDown([...document.querySelectorAll('[role="tab"]')].find((tab) => clean(tab.textContent) === 'Demo'));
  assert.equal(calls('GET', LIST).at(-1).params.type, 'DEMO');
  await choose('Filter by status', 'Cancelled');
  assert.equal(calls('GET', LIST).at(-1).params.status, 'CANCELLED');
  await choose('Filter by tutor assignment', 'Needs a tutor');
  assert.equal(calls('GET', LIST).at(-1).params.assigned, 'false');
  await choose('Filter by when', 'All dates');
  const last = calls('GET', LIST).at(-1).params;
  assert.equal('when' in last, false, '"All dates" sends no when filter');
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)),
    { q: 'riya', from: '2026-10-30', to: '2026-11-02', type: 'DEMO', status: 'CANCELLED', assigned: 'false', when: 'all' });

  await click(button('Clear'));
  assert.deepEqual(calls('GET', LIST).at(-1).params, { page: 1, page_size: 25, type: 'DEMO', when: 'upcoming' });
});

test('an unknown filter value in the URL is dropped, never sent', async () => {
  serve({ [`GET ${LIST}`]: list([RIYA]) });
  await open('/bookings?type=TRIAL&status=done&assigned=maybe&when=tomorrow&from=31-10-2026', ADMIN);
  assert.deepEqual(calls('GET', LIST)[0].params, { page: 1, page_size: 25, when: 'upcoming' });
});

test('View opens the booking in full in the side sheet', async () => {
  serve({ [`GET ${LIST}`]: list([RIYA, ALI]), [`GET /api/bookings/${ALI.id}/`]: detail(ALI) });
  const page = await open('/bookings', ADMIN);
  await click(button('View', rows()[1]));
  assert.equal(new URLSearchParams(page.location().search).get('booking'), ALI.id);
  const sheet = topDialog();
  const text = clean(sheet.textContent);
  for (const shown of ['Ali', 'Tutor A', 'Assigned by', 'Admin One', 'Delhi Private School', 'Sara Khan', '+91 9800000002',
    "Through a BDE's link", 'Bde One', 'Diagnostic test']) {
    assert.ok(text.includes(shown), `the sheet shows ${shown}`);
  }
  assert.ok(button('Change tutor', sheet) && button('Unassign', sheet));
});

test('the tutor list: every active tutor, Available or Unavailable with the reason; an unavailable one cannot be picked', async () => {
  serve({ [`GET ${LIST}`]: list([RIYA]), [`GET /api/bookings/${RIYA.id}/tutors/`]: tutors(RIYA) });
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
  assert.equal(calls('PUT', `/api/bookings/${RIYA.id}/tutor/`).length, 0);
});

test('assigning a tutor: PUT, then the list and the open booking are read again', async () => {
  const assigned = detail({ ...RIYA, tutor: { id: 't-b', full_name: 'Tutor B' } });
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET /api/bookings/${RIYA.id}/`]: detail(RIYA),
    [`GET /api/bookings/${RIYA.id}/tutors/`]: tutors(RIYA),
    [`PUT /api/bookings/${RIYA.id}/tutor/`]: () => ok({ ...assigned, changed: true }),
  });
  await open(`/bookings?booking=${RIYA.id}`, ADMIN);
  await click(button('Assign tutor', topDialog()));
  const dialog = topDialog();
  await click(dialog.querySelectorAll('input[type="radio"]')[1]);
  await click(button('Assign', dialog));
  assert.deepEqual(calls('PUT', `/api/bookings/${RIYA.id}/tutor/`).map((entry) => entry.data), [{ tutor_id: 't-b' }]);
  assert.match(bodyText(), /Tutor B now teaches Riya's demo class\./);
  assert.equal(calls('GET', LIST).length, 2, 'the list is read again');
  assert.equal(calls('GET', `/api/bookings/${RIYA.id}/`).length, 2, 'the open booking is read again');
  assert.ok(!bodyText().includes('Assign tutor Riya'), 'the dialog closed');
});

test('reassigning: the current tutor is marked and cannot be "reassigned" to themselves', async () => {
  serve({
    [`GET ${LIST}`]: list([ALI]),
    [`GET /api/bookings/${ALI.id}/tutors/`]: tutors(ALI, 't-c'),
    [`PUT /api/bookings/${ALI.id}/tutor/`]: () => ok({ ...detail({ ...ALI, tutor: { id: 't-b', full_name: 'Tutor B' } }), changed: true }),
  });
  await open('/bookings', ADMIN);
  await click(button('Change', rows()[0]));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /^Change tutor/);
  assert.deepEqual(tutorOptions(dialog)[2], ['Tutor C', 'Current Available', null]);
  const [, other, current] = [...dialog.querySelectorAll('input[type="radio"]')];
  await click(current);
  assert.ok(button('Reassign', dialog).disabled, 'the current tutor again changes nothing');
  await click(other);
  await click(button('Reassign', dialog));
  assert.deepEqual(calls('PUT', `/api/bookings/${ALI.id}/tutor/`).map((entry) => entry.data), [{ tutor_id: 't-b' }]);
  assert.match(bodyText(), /Tutor B now teaches Ali's diagnostic test\./);
});

test('unassigning: confirmed first, then DELETE and a fresh list', async () => {
  const unassigned = detail({ ...ALI, tutor: null });
  serve({
    [`GET ${LIST}`]: list([ALI]),
    [`GET /api/bookings/${ALI.id}/`]: detail(ALI),
    [`DELETE /api/bookings/${ALI.id}/tutor/`]: () => ok({ ...unassigned, changed: true }),
  });
  await open(`/bookings?booking=${ALI.id}`, ADMIN);
  await click(button('Unassign', topDialog()));
  const confirm = topDialog();
  assert.match(clean(confirm.textContent), /Tutor A will no longer teach Ali's booking/);
  assert.equal(calls('DELETE', `/api/bookings/${ALI.id}/tutor/`).length, 0, 'nothing is sent before confirming');
  await click(button('Unassign', confirm));
  assert.equal(calls('DELETE', `/api/bookings/${ALI.id}/tutor/`).length, 1);
  assert.match(bodyText(), /Unassigned the tutor from Ali's booking\./);
  assert.equal(calls('GET', LIST).length, 2);
});

test('a conflict the API finds at assignment time is shown, and the tutor list read again', async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET /api/bookings/${RIYA.id}/tutors/`]: tutors(RIYA),
    [`PUT /api/bookings/${RIYA.id}/tutor/`]: () => fail(409, {
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
  assert.equal(calls('GET', `/api/bookings/${RIYA.id}/tutors/`).length, 2, 'what is free is read again');
  assert.ok(button('Assign', dialog).disabled, 'the choice is cleared');
  assert.ok(!bodyText().includes('now teaches'));
});

test("a booking whose tutor can no longer change says why, and offers no assignment", async () => {
  serve({
    [`GET ${LIST}`]: list([RIYA]),
    [`GET /api/bookings/${RIYA.id}/tutors/`]: tutors(RIYA, null, {
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
  serve({ [`GET ${LIST}`]: list([RIYA, ALI]), [`GET /api/bookings/${ALI.id}/`]: detail(ALI) });
  await open(`/bookings?booking=${ALI.id}`, VIEWER);
  for (const label of ['Assign', 'Change', 'Assign tutor', 'Change tutor', 'Unassign']) {
    assert.ok(!button(label), `no ${label} button`);
  }
  assert.ok(clean(topDialog().textContent).includes('Tutor A'), 'the booking still shows its tutor');
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

const tab = (name) => [...document.querySelectorAll('[role="tab"]')].find((element) => clean(element.textContent) === name);
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
  serve({ [`GET ${MINE}`]: mine([MY_RIYA]), [`GET ${MINE}${MY_RIYA.id}/`]: myDetail(MY_RIYA) });
  await open(`/my-bookings?booking=${MY_RIYA.id}`, TUTOR);
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
  serve({ [`GET ${MINE}`]: mine([MY_RIYA, MY_ALI]), [`GET ${MINE}${MY_ALI.id}/`]: myDetail(MY_ALI) });
  const page = await open('/my-bookings', TUTOR);
  await click(button('View the booking for Ali'));
  assert.equal(new URLSearchParams(page.location().search).get('booking'), MY_ALI.id);
  assert.equal(calls('GET', `${MINE}${MY_ALI.id}/`).length, 1);
  const text = clean(topDialog().textContent);
  assert.match(text, /^Ali.*Sun, 1 Nov · 10:00 AM IST · Class 9.*Diagnostic test.*Cancelled/);
  assert.match(text, /This booking was cancelled\. There is no class to teach\./);
  assert.match(text,
    /BookingTypeDiagnostic testWhenSun, 1 Nov · 10:00 AM ISTStatusCancelled.*StudentNameAliClassClass 9SyllabusIGCSESchoolAl Noor SchoolCountryIndia/);
});

test('My Bookings: a booking no longer assigned to the tutor is not found', async () => {
  serve({
    [`GET ${MINE}`]: mine([]),
    [`GET ${MINE}b-gone/`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such booking.' }),
  });
  await open('/my-bookings?booking=b-gone', TUTOR);
  assert.match(clean(topDialog().textContent), /Booking not found.*It may no longer be assigned to you/);
});

test('My Bookings: nothing but the child and the slot is rendered, whatever else the API sends', async () => {
  const leaky = { ...MY_RIYA, ...PRIVATE };
  serve({ [`GET ${MINE}`]: mine([leaky]), [`GET ${MINE}${MY_RIYA.id}/`]: myDetail(leaky) });
  await open(`/my-bookings?booking=${MY_RIYA.id}`, TUTOR);
  const text = bodyText();
  assert.ok(text.includes('Delhi Private School') && clean(topDialog().textContent).includes('United Arab Emirates'),
    'the booking itself is shown, in the list and the sheet');
  for (const value of PRIVATE_TEXT) {
    assert.ok(!text.includes(value), `${value} is not rendered`);
  }
  assert.ok(!document.querySelector('a[href^="tel:"], a[href*="wa.me"], a[href^="mailto:"]'), 'no contact links');
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
