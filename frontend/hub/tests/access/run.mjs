// Hub access tests: what every kind of caller is offered on every page,
// compared with the recorded baseline.
//
//   npm run test:access                    compare with baseline.json (+ approved-changes.json)
//   ACCESS_RECORD=1 npm run test:access    re-record baseline.json from the current Hub
//
// baseline.json was recorded from the Hub as it stood before navigation and
// page decisions moved from roles to permissions (commit 3d56003). Any
// difference must be listed, with the decision that approved it, in
// approved-changes.json. fixtures.json holds the real API's answers for each
// caller, recorded from the backend's authorization-matrix world (commit
// f7c6528); the script that recorded them is not in the repository.
import { readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';
import { JSDOM, VirtualConsole } from 'jsdom';

const here = path.dirname(fileURLToPath(import.meta.url));
const hub = path.resolve(here, '../..');
const src = path.join(hub, 'src');
const BASELINE = path.join(here, 'baseline.json');
const APPROVED = path.join(here, 'approved-changes.json');
const fixtures = JSON.parse(readFileSync(path.join(here, 'fixtures.json'), 'utf8'));

// ------------------------------------------------------------------ bundle
const bundle = path.join(tmpdir(), `hub-access-${process.pid}.mjs`);
await esbuild.build({
  entryPoints: [path.join(here, 'scenarios.jsx')],
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

const { describeAt } = await import(pathToFileURL(bundle).href);

// --------------------------------------------------------------- scenarios
const ids = fixtures.ids;
const fakeMe = (role, permissions = []) => ({ user: { id: `id-${role}`, username: role.toLowerCase(), email: `${role.toLowerCase()}@matrix.test`, full_name: role, role,
  is_superuser: false, must_change_password: false, permissions, groups: [] }, must_change_password: false, csrf_token: 'stub' });

// BDE booking links (DEVT-5934), laid over the recorded answers, which predate
// it -- the same answers the backend authorization matrix records. A superuser
// holds accounts.view_own_booking_links (D1) and is told it is not a BDE, but
// the Hub opens the page only for the BDE role; the BDE holds it and is served
// its own two links.
const VIEW_OWN_BOOKING_LINKS = 'accounts.view_own_booking_links';
const BOOKING_LINKS_PATH = '/api/bde/booking-links/';
function asSuperuserAfterBookingLinks(answers) {
  const me = answers['/api/auth/me/'];
  const permissions = [...me.body.user.permissions, VIEW_OWN_BOOKING_LINKS].sort();
  return {
    ...answers,
    '/api/auth/me/': { ...me, body: { ...me.body, user: { ...me.body.user, permissions } } },
    [BOOKING_LINKS_PATH]: { status: 403, body: { error: 'NOT_A_BDE', message: 'Booking links belong to BDE accounts, and this account is not one.' } },
  };
}
const BDE_LINKS = { status: 200, body: { links: [
  { booking_type: 'DEMO', url: 'https://plus.eduport.app/demo?ref=DemoToken-0123456789ab', created_at: '2026-10-27T09:00:00+05:30' },
  { booking_type: 'DIAGNOSTIC', url: 'https://plus.eduport.app/exam?ref=DiagToken-0123456789ab', created_at: '2026-10-27T09:00:00+05:30' },
] } };

// Booking slot management (DEVT-5973), laid over the same recorded answers:
// accounts.manage_booking_slots, which the administrator's role group carries
// and a superuser holds (D1), and one date's slots as the API serves them. The
// page is opened at that fixed date, so nothing it shows moves with the clock.
const MANAGE_BOOKING_SLOTS = 'accounts.manage_booking_slots';
const SLOTS_DATE = '2026-10-29';
const SLOTS_PATH = `/api/booking-slots/demo/${SLOTS_DATE}/`;
const slotRow = (time, end_time, booked, open_status, closedBy = null) => ({ time, end_time, scheduled: true, booked, capacity: 3,
  status: closedBy ? 'Fully Booked' : open_status, open_status, closed: Boolean(closedBy),
  closed_at: closedBy ? '2026-10-28T09:30:00+00:00' : null, closed_by: closedBy, close_reason: closedBy ? 'Teacher training' : '' });
const SLOTS_DAY = { status: 200, body: { booking_type: 'DEMO', date: SLOTS_DATE, timezone: 'Asia/Kolkata', slot_minutes: 60, capacity: 3,
  parent_state: 'open', window: { first: '2026-10-29', last: '2026-11-04' }, editable: true, slots: [
    slotRow('07:30', '08:30', 0, 'Available'),
    slotRow('08:30', '09:30', 1, 'Filling Fast'),
    slotRow('09:30', '10:30', 2, 'Only a Few Left'),
    slotRow('10:30', '11:30', 3, 'Fully Booked'),
    slotRow('11:30', '12:30', 1, 'Filling Fast', 'ADMIN'),
  ] } };
function withBookingSlots(answers) {
  const me = answers['/api/auth/me/'];
  const permissions = [...me.body.user.permissions, MANAGE_BOOKING_SLOTS].sort();
  return {
    ...answers,
    '/api/auth/me/': { ...me, body: { ...me.body, user: { ...me.body.user, permissions } } },
    [SLOTS_PATH]: SLOTS_DAY,
  };
}

// BDE portal phase 1 (dashboard and My Enquiries), laid over the same
// recorded answers: accounts.view_own_enquiries and accounts.add_enquiry,
// which the BDE's role group carries and a superuser holds (D1) -- the Hub
// still opens the enquiry pages for the BDE role only, and gives a superuser
// the staff dashboard. The BDE is served its own dashboard and one enquiry,
// on fixed dates, so nothing shown moves with the clock.
const VIEW_OWN_ENQUIRIES = 'accounts.view_own_enquiries';
const ADD_ENQUIRY = 'accounts.add_enquiry';
const ENQUIRY_ID = '5d1f0c2e-8a47-4c3b-9e61-2f7a9b0c4d18';
const BDE_DASHBOARD_PATH = '/api/bde/dashboard/';
const ENQUIRIES_PATH = '/api/bde/enquiries/';
const ENQUIRY_PATH = `${ENQUIRIES_PATH}${ENQUIRY_ID}/`;
const NEXT_DEMO = { id: '0b8e4a91-3c2d-4f5e-8a7b-6c9d0e1f2a3b', booking_type: 'DEMO', date: '2026-10-30', time: '19:30',
  starts_at: '2026-10-30T14:00:00+00:00' };
const ENQUIRY_ROW = { id: ENQUIRY_ID, parent_name: 'Asha Nair', phone: '+971 501234567', student_name: 'Riya', grade: 'Class 8',
  source: 'DEMO_LINK', source_label: 'Demo link', status: 'BOOKED', status_label: 'Demo booked', next_booking: NEXT_DEMO,
  added_at: '2026-10-27T09:00:00+05:30' };
const BDE_DASHBOARD = { status: 200, body: { timezone: 'Asia/Kolkata', enquiries: { total: 1, last_7_days: 1 },
  bookings: { DEMO: { total: 1, upcoming: 1 }, DIAGNOSTIC: { total: 0, upcoming: 0 } },
  upcoming: { total: 1, rows: [{ ...NEXT_DEMO, enquiry: { id: ENQUIRY_ID, parent_name: 'Asha Nair', student_name: 'Riya', grade: 'Class 8' } }] },
  recent_enquiries: [ENQUIRY_ROW] } };
const BDE_ENQUIRIES = { status: 200, body: { results: [ENQUIRY_ROW], count: 1, page: 1, page_size: 25 } };
const BDE_ENQUIRY = { status: 200, body: { ...ENQUIRY_ROW, phone_dial_code: '+971', phone_number: '501234567',
  school_name: 'Delhi Private School', syllabus: 'CBSE', country: 'United Arab Emirates', created_at: '2026-10-27T09:00:00+05:30',
  timezone: 'Asia/Kolkata', bookings: [{ ...NEXT_DEMO, status: 'BOOKED', ended: false, booked_at: '2026-10-27T09:00:00+05:30', cancelled_at: null }] } };
const NOT_A_BDE = { status: 403, body: { error: 'NOT_A_BDE', message: 'Enquiries belong to BDE accounts, and this account is not one.' } };
function asSuperuserAfterEnquiries(answers) {
  const me = answers['/api/auth/me/'];
  const permissions = [...me.body.user.permissions, ADD_ENQUIRY, VIEW_OWN_ENQUIRIES].sort();
  return {
    ...answers,
    '/api/auth/me/': { ...me, body: { ...me.body, user: { ...me.body.user, permissions } } },
    [BDE_DASHBOARD_PATH]: NOT_A_BDE,
    [ENQUIRIES_PATH]: NOT_A_BDE,
    [ENQUIRY_PATH]: NOT_A_BDE,
  };
}

const CALLERS = {
  admin: { answers: withBookingSlots(fixtures.callers.admin) },
  superuser: { answers: withBookingSlots(asSuperuserAfterEnquiries(asSuperuserAfterBookingLinks(fixtures.callers.superuser))) },
  su_mentor: { answers: withBookingSlots(asSuperuserAfterEnquiries(asSuperuserAfterBookingLinks(fixtures.callers.su_mentor))) },
  mentor_a: { answers: fixtures.callers.mentor_a },
  tutor_a: { answers: fixtures.callers.tutor_a },
  tutor_b: { answers: fixtures.callers.tutor_b },
  parent_a: { answers: fixtures.callers.parent_a },
  unknown: { answers: fixtures.callers.unknown },
  bde: {
    answers: { ...fixtures.callers.unknown, [BOOKING_LINKS_PATH]: BDE_LINKS, [BDE_DASHBOARD_PATH]: BDE_DASHBOARD,
      [ENQUIRIES_PATH]: BDE_ENQUIRIES, [ENQUIRY_PATH]: BDE_ENQUIRY },
    me: fakeMe('BDE', [ADD_ENQUIRY, VIEW_OWN_BOOKING_LINKS, VIEW_OWN_ENQUIRIES]),
  },
  sales_tl: { answers: fixtures.callers.unknown, me: fakeMe('SALES_TL') },
};
const a = ids.stu_a;
const PATHS = [
  '/dashboard', '/students', `/students/${a}`, `/students/${a}?tab=sessions`, `/students/${a}?tab=exams`,
  `/students/${a}?tab=homework`, `/students/${a}?tab=documents`, `/students/${a}?tab=activity`, `/students/${a}?tab=notes`,
  `/students/${ids.stu_b}`, '/sessions', `/sessions?student_id=${a}`, '/exams', `/exams?student_id=${a}`, '/homework',
  '/invitations', '/activity', '/team', `/team/${ids.mentor_c}`, `/team/${ids.mentor_c}?tab=activity`, '/booking-links',
  `/booking-slots?type=demo&date=${SLOTS_DATE}`, '/enquiries', `/enquiries/${ENQUIRY_ID}`, '/admins', '/nowhere',
];
const labelOf = { ...Object.fromEntries(Object.entries(ids).map(([name, id]) => [id, name])), [ENQUIRY_ID]: 'enquiry_a' };
const symbolic = (value) => JSON.parse(JSON.stringify(value).replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g, (id) => `{${labelOf[id] || 'id'}}`));
// Activity rows name the moment the fixture world was recorded ("26 Oct, 12:27 PM");
// a re-recorded fixtures.json moves it, so it never counts as a difference.
const timeless = (value) => JSON.parse(JSON.stringify(value ?? null).replace(/\d{1,2} [A-Z][a-z]{2}, \d{1,2}:\d{2} [AP]M\b/g, '{time}'));

const results = {};
for (const [caller, setup] of Object.entries(CALLERS)) {
  for (const at of PATHS) {
    results[`${symbolic(at)} @ ${caller}`] = timeless(symbolic(await describeAt(at, setup)));
  }
}
console.error = quiet;

// ----------------------------------------------------------------- compare
if (process.env.ACCESS_RECORD) {
  writeFileSync(BASELINE, `${JSON.stringify({ results }, null, 1)}\n`);
  console.log(`Recorded ${Object.keys(results).length} results to ${path.relative(hub, BASELINE)}.`);
  window.close();
  process.exit(0);
}
const baseline = JSON.parse(readFileSync(BASELINE, 'utf8')).results;
let approved = {};
try { approved = JSON.parse(readFileSync(APPROVED, 'utf8')).changes || {}; } catch { /* none yet */ }
const expected = Object.fromEntries(Object.entries(baseline).map(([key, result]) => [key, timeless(result)]));
for (const [key, change] of Object.entries(approved)) expected[key] = timeless(change.result);
const keys = [...new Set([...Object.keys(expected), ...Object.keys(results)])].sort();
const differences = keys.filter((key) => JSON.stringify(expected[key]) !== JSON.stringify(results[key]));
if (process.env.ACCESS_REPORT) {
  writeFileSync(process.env.ACCESS_REPORT, `${JSON.stringify(Object.fromEntries(differences.map((key) => [key, { expected: expected[key], actual: results[key] }])), null, 1)}\n`);
}
for (const key of differences) {
  console.log(`DIFF ${key}`);
  for (const field of new Set([...Object.keys(expected[key] || {}), ...Object.keys(results[key] || {})])) {
    const before = JSON.stringify((expected[key] || {})[field]);
    const after = JSON.stringify((results[key] || {})[field]);
    if (before !== after) console.log(`  ${field}: ${before}\n  ${' '.repeat(field.length)}  -> ${after}`);
  }
}
console.log(`${keys.length - differences.length}/${keys.length} access results match the baseline and its approved changes.`);
window.close();
process.exit(differences.length ? 1 : 0);
