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
  // Today's agenda (BDE Hub redesign, Phase 3): the bookings on today's Indian date, here the day of that demo.
  agenda: { date: NEXT_DEMO.date, total: 1, rows: [{ ...NEXT_DEMO, status: 'BOOKED', activity_state: 'UPCOMING',
    tutor: { full_name: 'Tutor A' }, enquiry: { id: ENQUIRY_ID, parent_name: 'Asha Nair', student_name: 'Riya', grade: 'Class 8' } }] },
  recent_enquiries: [ENQUIRY_ROW] } };
const BDE_ENQUIRIES = { status: 200, body: { results: [ENQUIRY_ROW], count: 1, page: 1, page_size: 25 } };
// Their Demo and Diagnostic Bookings (BDE Hub redesign, Phase 5): that demo, and no diagnostic test.
const BDE_DEMO_BOOKINGS = { status: 200, body: { count: 1, page: 1, page_size: 25, timezone: 'Asia/Kolkata', results: [{
  ...NEXT_DEMO, status: 'BOOKED', activity_state: 'UPCOMING', started_at: null, booked_at: '2026-10-27T09:00:00+05:30',
  tutor: { full_name: 'Tutor A' }, parent_confirmation: 'AWAITING', redemo: false,
  enquiry: { id: ENQUIRY_ID, parent_name: 'Asha Nair', student_name: 'Riya', grade: 'Class 8' } }] } };
const BDE_DIAGNOSTIC_BOOKINGS = { status: 200, body: { count: 0, page: 1, page_size: 25, timezone: 'Asia/Kolkata', results: [] } };
// Their follow-ups and activity (BDE Hub redesign, Phase 6): asking that demo's parent to confirm, and its booking.
const BDE_FOLLOW_UPS = { status: 200, body: { count: 1, page: 1, page_size: 25, timezone: 'Asia/Kolkata',
  summary: { total: 1, overdue: 0, today: 1, upcoming: 0 }, results: [{
    id: '3e5f7a9b-1c2d-4e3f-8a9b-0c1d2e3f4a5b', step: 'CONFIRMATION_REQUEST', step_label: 'Confirmation request',
    active_from: null, due_at: '2026-10-30T09:00:00+00:00', expires_at: null, overdue: false,
    booking: { ...NEXT_DEMO, status: 'BOOKED', activity_state: 'UPCOMING' },
    enquiry: { id: ENQUIRY_ID, parent_name: 'Asha Nair', student_name: 'Riya', grade: 'Class 8', phone: '+971 501234567',
      phone_dial_code: '+971', phone_number: '501234567' } }] } };
const BDE_ACTIVITY = { status: 200, body: { count: 1, page: 1, page_size: 30, timezone: 'Asia/Kolkata', results: [{
  id: '4f6a8b0c-2d3e-4f5a-9b0c-1d2e3f4a5b6c', kind: 'CREATED', kind_label: 'Created', at: '2026-10-27T09:00:00+05:30',
  by_you: false, detail: { origin: 'public_booking' }, booking: NEXT_DEMO,
  enquiry: { id: ENQUIRY_ID, parent_name: 'Asha Nair', student_name: 'Riya', grade: 'Class 8' } }] } };
const BDE_ENQUIRY = { status: 200, body: { ...ENQUIRY_ROW, phone_dial_code: '+971', phone_number: '501234567',
  school_name: 'Delhi Private School', syllabus: 'CBSE', country: 'United Arab Emirates', created_at: '2026-10-27T09:00:00+05:30',
  timezone: 'Asia/Kolkata', bookings: [{ ...NEXT_DEMO, status: 'BOOKED', ended: false, booked_at: '2026-10-27T09:00:00+05:30', cancelled_at: null,
    // Who teaches it and its Google Meet link, to read (Phase 1: the tutor's name and the booking's copy of their link).
    tutor: { full_name: 'Tutor A' }, tutor_meet_link: 'https://meet.google.com/abc-defg-hij',
    // What the API offers the owner BDE (P3, Q22): cancel it; No-show once its slot starts.
    actions: { cancel: true, no_show: false },
    // The parent's answer to the confirmation request (Phase 3.1), for whoever may see the lead's communication.
    parent_confirmation: 'AWAITING' }] } };
// The reports on it (P9, design F.4): one submitted Demo report, at its second version, as the owner BDE's list answers it.
const REPORTED_DEMO_ID = 'e3c1a7b9-2d4f-4b6a-8c5e-9f0a1b2c3d4e';
const BDE_REPORTS = { status: 200, body: { timezone: 'Asia/Kolkata', count: 1, results: [{
  booking: { id: REPORTED_DEMO_ID, booking_type: 'DEMO', date: '2026-10-26', time: '19:30', starts_at: '2026-10-26T14:00:00+00:00',
    status: 'COMPLETED', completed_at: '2026-10-26T15:10:00+00:00' },
  report: { id: 'f4d2b8c0-3e5a-4c7b-9d6f-0a1b2c3d4e5f', booking_id: REPORTED_DEMO_ID, booking_type: 'DEMO', version: 2,
    fields: { assessment_review: 'Quick with mental arithmetic.', class_observation_review: 'Asked good questions.',
      suggested_strategy: 'Start with the algebra track.' },
    student_name: 'Riya', grade: 'Class 8', tutor_name: 'Tutor A', submitted_at: '2026-10-26T15:10:00+00:00',
    updated_at: '2026-10-27T09:00:00+05:30' } }] } };
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

// Booking management (Phase 3, on the Phase 2 API), laid over the same
// recorded answers: accounts.view_all_bookings and accounts.assign_booking_tutor,
// which the administrator's role group carries and a superuser holds (D1).
// Each type is its own list since the Diagnostic/Demo split: they are served
// the Demo list the page opens on (one booking with no tutor yet, one
// assigned), an empty Diagnostic list and one Demo booking in full, on fixed
// dates, so nothing shown moves with the clock.
const VIEW_ALL_BOOKINGS = 'accounts.view_all_bookings';
const ASSIGN_BOOKING_TUTOR = 'accounts.assign_booking_tutor';
const BOOKING_ID = '7c0b6a52-3e1d-4f8a-9b2c-5d4e3f2a1b0c';
const BOOKINGS_PATH = '/api/bookings/demo/';
const DIAGNOSTIC_BOOKINGS_PATH = '/api/bookings/diagnostic/';
const BOOKING_PATH = `${BOOKINGS_PATH}${BOOKING_ID}/`;
const bookingSlot = (id, booking_type, date, time, starts_at, ends_at) => ({ id, booking_type, date, time, starts_at, ends_at,
  started: false, ended: false });
const UNASSIGNED_BOOKING = { id: BOOKING_ID, booking_type: 'DEMO', status: 'BOOKED',
  slot: bookingSlot('1f2e3d4c-5b6a-4978-8a9b-0c1d2e3f4a5b', 'DEMO', '2026-10-31', '19:30', '2026-10-31T14:00:00+00:00', '2026-10-31T15:00:00+00:00'),
  student_name: 'Riya', grade: 'Class 8', parent_name: 'Asha Nair', phone: '+971 501234567', tutor: null, bde: null,
  booked_at: '2026-10-28T09:00:00+00:00' };
const ASSIGNED_BOOKING = { id: '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d', booking_type: 'DEMO', status: 'BOOKED',
  slot: bookingSlot('2a3b4c5d-6e7f-4809-9a1b-2c3d4e5f6a7b', 'DEMO', '2026-11-01', '10:00', '2026-11-01T04:30:00+00:00', '2026-11-01T05:30:00+00:00'),
  student_name: 'Ali', grade: 'Class 9', parent_name: 'Sara Khan', phone: '+91 9800000002',
  tutor: { id: '3c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f', full_name: 'Tutor A' }, bde: null, booked_at: '2026-10-28T10:00:00+00:00' };
const BOOKINGS_LIST = { status: 200, body: { results: [UNASSIGNED_BOOKING, ASSIGNED_BOOKING], count: 2, page: 1, page_size: 25,
  timezone: 'Asia/Kolkata' } };
const BOOKING_DETAIL = { status: 200, body: { ...UNASSIGNED_BOOKING, timezone: 'Asia/Kolkata', seat: 1,
  lead: { id: '4d5e6f7a-8b9c-4d0e-9f1a-2b3c4d5e6f7a', phone_dial_code: '+971', phone_number: '501234567',
    school_name: 'Delhi Private School', syllabus: 'CBSE', country: 'United Arab Emirates', source: 'BOOKING_PAGE', owner_bde: null },
  referral_status: 'NO_REF', tutor_assigned_at: null, tutor_assigned_by: null, tutor_meet_link: null, tutor_changeable: true,
  tutor_change_refusal: null,
  cancelled_at: null, cancelled_by: null, cancel_reason: '', cancel_reason_code: '', rescheduled_at: null, rescheduled_by: null,
  reschedule_reason: '', reschedule_reason_code: '', rescheduled_from: null, rescheduled_to: null,
  // What the API offers an administrator for this booking (P3): cancel and move it; No-show once its slot starts.
  actions: { cancel: true, no_show: false, reschedule: true } } };
function withBookings(answers) {
  const me = answers['/api/auth/me/'];
  const permissions = [...me.body.user.permissions, ASSIGN_BOOKING_TUTOR, VIEW_ALL_BOOKINGS].sort();
  return {
    ...answers,
    '/api/auth/me/': { ...me, body: { ...me.body, user: { ...me.body.user, permissions } } },
    [BOOKINGS_PATH]: BOOKINGS_LIST,
    [DIAGNOSTIC_BOOKINGS_PATH]: { status: 200, body: { ...BOOKINGS_LIST.body, results: [], count: 0 } },
    [BOOKING_PATH]: BOOKING_DETAIL,
  };
}

// My Bookings for tutors (Phase 4, on the tutor bookings API), laid over the
// same recorded answers: accounts.view_assigned_bookings, which the tutor's
// role group carries and a superuser holds (D1) -- the Hub still opens the
// page for the TUTOR role only. The tutors are served their own bookings (one
// upcoming, one cancelled) and one in full, on fixed dates; a superuser, who
// teaches none, is served the empty list the API answers. A booking is opened
// by its type and its id (?booking=<id>&booking_type=DEMO).
const VIEW_ASSIGNED_BOOKINGS = 'accounts.view_assigned_bookings';
const MY_BOOKING_ID = '6b5a4c3d-2e1f-4a0b-9c8d-7e6f5a4b3c2d';
const MY_BOOKINGS_PATH = '/api/tutor/bookings/';
const MY_BOOKING_PATH = `${MY_BOOKINGS_PATH}demo/${MY_BOOKING_ID}/`;
const mySlot = (date, time, starts_at, ends_at) => ({ date, time, starts_at, ends_at, started: false, ended: false });
// Each with the Google Meet room it is taught in (Phase 1): the booking's copy of the tutor's link, or null.
const MY_BOOKING = { id: MY_BOOKING_ID, booking_type: 'DEMO', status: 'BOOKED',
  slot: mySlot('2026-10-31', '19:30', '2026-10-31T14:00:00+00:00', '2026-10-31T15:00:00+00:00'),
  student_name: 'Riya', grade: 'Class 8', syllabus: 'CBSE', school_name: 'Delhi Private School', country: 'United Arab Emirates',
  tutor_meet_link: 'https://meet.google.com/abc-defg-hij' };
const MY_CANCELLED_BOOKING = { id: '8d7c6b5a-4e3f-4a2b-9c1d-0e9f8a7b6c5d', booking_type: 'DIAGNOSTIC', status: 'CANCELLED',
  slot: mySlot('2026-11-01', '10:00', '2026-11-01T04:30:00+00:00', '2026-11-01T05:30:00+00:00'),
  student_name: 'Ali', grade: 'Class 9', syllabus: 'IGCSE', school_name: 'Al Noor School', country: 'India', tutor_meet_link: null };
const myBookings = (results) => ({ status: 200, body: { results, count: results.length, page: 1, page_size: 25,
  timezone: 'Asia/Kolkata' } });
const NO_SUCH_BOOKING = { status: 404, body: { error: 'NOT_FOUND', message: 'No such booking.' } };
function withAssignedBookings(answers, own = []) {
  const me = answers['/api/auth/me/'];
  const permissions = [...me.body.user.permissions, VIEW_ASSIGNED_BOOKINGS].sort();
  const detail = own.find((booking) => booking.id === MY_BOOKING_ID);
  return {
    ...answers,
    '/api/auth/me/': { ...me, body: { ...me.body, user: { ...me.body.user, permissions } } },
    [MY_BOOKINGS_PATH]: myBookings(own),
    [MY_BOOKING_PATH]: detail ? { status: 200, body: { ...detail, timezone: 'Asia/Kolkata' } } : NO_SUCH_BOOKING,
  };
}
const OWN_BOOKINGS = [MY_BOOKING, MY_CANCELLED_BOOKING];

// Parent communication (Phase 3.1, on the read-only communication API), laid
// over the same recorded answers: what accounts.0017 grants the administrator's
// role group -- every booking's communication, sending, the parent's answer,
// the templates -- and the BDE's -- their own leads' -- and a superuser all of
// it (D1). The administrators are served the open booking's communication; it
// is read in the booking's sheet, so only its call shows here.
const VIEW_ALL_COMMUNICATIONS = 'accounts.view_all_communications';
const VIEW_OWN_LEAD_COMMUNICATIONS = 'accounts.view_own_lead_communications';
const SEND_LEAD_COMMUNICATIONS = 'accounts.send_lead_communications';
const RECORD_PARENT_CONFIRMATION = 'accounts.record_parent_confirmation';
const ADMIN_COMMUNICATIONS = ['accounts.manage_message_templates', RECORD_PARENT_CONFIRMATION, SEND_LEAD_COMMUNICATIONS,
  VIEW_ALL_COMMUNICATIONS];
const BOOKING_COMMUNICATION_PATH = `/api/communications/bookings/demo/${BOOKING_ID}/`;
const BOOKING_COMMUNICATION = { status: 200, body: { timezone: 'Asia/Kolkata', planned: true,
  booking: { id: BOOKING_ID, booking_type: 'DEMO', status: 'BOOKED', status_label: 'Booked', slot: UNASSIGNED_BOOKING.slot,
    student_name: 'Riya', parent_name: 'Asha Nair', phone: '+971 501234567', owner_bde: null, tutor: null },
  parent_confirmation: { status: 'AWAITING', label: 'Awaiting confirmation', at: null, by: null, reason: null },
  tasks: [{ id: '5e6f7a8b-9c0d-4e1f-8a2b-3c4d5e6f7a8b', step: 'ACKNOWLEDGEMENT', step_label: 'Initial acknowledgement',
    status: 'OPEN', status_label: 'Open', resolution: '', resolution_label: '', owner_role: 'ADMIN', owner: null,
    active_from: '2026-10-28T09:00:00+00:00', due_at: '2026-10-28T12:00:00+00:00', expires_at: '2026-10-31T14:00:00+00:00',
    overdue: false, resolved_at: null, resolved_by: null }],
  messages: [],
  actions: { request_confirmation: true, record_confirmation: true } } };
function withCommunications(answers, permissions) {
  const me = answers['/api/auth/me/'];
  return {
    ...answers,
    '/api/auth/me/': { ...me, body: { ...me.body, user: { ...me.body.user, permissions: [...me.body.user.permissions, ...permissions].sort() } } },
    [BOOKING_COMMUNICATION_PATH]: BOOKING_COMMUNICATION,
  };
}
const SUPERUSER_COMMUNICATIONS = [...ADMIN_COMMUNICATIONS, VIEW_OWN_LEAD_COMMUNICATIONS];

// Lead management (accounts.0018, on the Leads API), laid over the same
// recorded answers: accounts.view_all_leads, accounts.add_lead and
// accounts.assign_lead_owner, which the administrator's role group carries
// and a superuser holds (D1). They are served two leads -- one from the
// website that nobody owns yet, one a BDE owns -- the BDE accounts to assign
// to, and the first lead in full, on fixed dates.
const LEAD_PERMISSIONS = ['accounts.add_lead', 'accounts.assign_lead_owner', 'accounts.view_all_leads'];
const LEAD_ID = '2c4e6a8b-0d1f-4a3b-8c5d-7e9f0a1b2c3d';
const LEAD_BDE_ID = '8f7e6d5c-4b3a-4291-8f0e-1d2c3b4a5f6e';
const LEADS_PATH = '/api/leads/';
const WEBSITE_LEAD = { id: LEAD_ID, parent_name: 'Meera Menon', phone: '+91 9876543210', student_name: 'Kavya', grade: 'Class 7',
  source: 'WEBSITE', source_label: 'Website', status: 'NEW', status_label: 'New', next_booking: null, added_at: null,
  owner: null, created_at: '2026-11-06T09:00:00+05:30' };
const OWNED_LEAD = { ...ENQUIRY_ROW, owner: { id: LEAD_BDE_ID, full_name: 'Bde One' }, created_at: '2026-10-27T09:00:00+05:30' };
const LEADS_LIST = { status: 200, body: { results: [WEBSITE_LEAD, OWNED_LEAD], count: 2, page: 1, page_size: 25 } };
const LEAD_BDES = { status: 200, body: { results: [{ id: LEAD_BDE_ID, full_name: 'Bde One', assignable: true }] } };
const LEAD_DETAIL = { status: 200, body: { ...WEBSITE_LEAD, phone_dial_code: '+91', phone_number: '9876543210',
  parent_email: 'meera@example.com', school_name: 'Kendriya Vidyalaya', syllabus: 'CBSE', country: 'India',
  timezone: 'Asia/Kolkata', bookings: [], added_by: null, source_details: { utm_source: 'instagram' } } };
function withLeads(answers) {
  const me = answers['/api/auth/me/'];
  const permissions = [...new Set([...me.body.user.permissions, ...LEAD_PERMISSIONS])].sort();
  return {
    ...answers,
    '/api/auth/me/': { ...me, body: { ...me.body, user: { ...me.body.user, permissions } } },
    [LEADS_PATH]: LEADS_LIST,
    [`${LEADS_PATH}bdes/`]: LEAD_BDES,
    [`${LEADS_PATH}${LEAD_ID}/`]: LEAD_DETAIL,
  };
}

const CALLERS = {
  admin: { answers: withLeads(withCommunications(withBookings(withBookingSlots(fixtures.callers.admin)), ADMIN_COMMUNICATIONS)) },
  superuser: { answers: withLeads(withCommunications(withAssignedBookings(withBookings(withBookingSlots(asSuperuserAfterEnquiries(
    asSuperuserAfterBookingLinks(fixtures.callers.superuser))))), SUPERUSER_COMMUNICATIONS)) },
  su_mentor: { answers: withLeads(withCommunications(withAssignedBookings(withBookings(withBookingSlots(asSuperuserAfterEnquiries(
    asSuperuserAfterBookingLinks(fixtures.callers.su_mentor))))), SUPERUSER_COMMUNICATIONS)) },
  mentor_a: { answers: fixtures.callers.mentor_a },
  tutor_a: { answers: withAssignedBookings(fixtures.callers.tutor_a, OWN_BOOKINGS) },
  tutor_b: { answers: withAssignedBookings(fixtures.callers.tutor_b) },
  parent_a: { answers: fixtures.callers.parent_a },
  unknown: { answers: fixtures.callers.unknown },
  bde: {
    answers: { ...fixtures.callers.unknown, [BOOKING_LINKS_PATH]: BDE_LINKS, [BDE_DASHBOARD_PATH]: BDE_DASHBOARD,
      [ENQUIRIES_PATH]: BDE_ENQUIRIES, [ENQUIRY_PATH]: BDE_ENQUIRY, [`${ENQUIRY_PATH}reports/`]: BDE_REPORTS,
      '/api/bde/bookings/demo/': BDE_DEMO_BOOKINGS, '/api/bde/bookings/diagnostic/': BDE_DIAGNOSTIC_BOOKINGS,
      '/api/bde/follow-ups/': BDE_FOLLOW_UPS, '/api/bde/activity/': BDE_ACTIVITY },
    // With the workflow permissions the BDE role group carries since accounts.0015 (P2).
    me: fakeMe('BDE', [ADD_ENQUIRY, 'accounts.cancel_booking', 'accounts.create_demo_booking', 'accounts.manage_own_conversion',
      RECORD_PARENT_CONFIRMATION, SEND_LEAD_COMMUNICATIONS, 'accounts.share_booking_report', VIEW_OWN_BOOKING_LINKS,
      VIEW_OWN_ENQUIRIES, VIEW_OWN_LEAD_COMMUNICATIONS, 'accounts.view_own_lead_reports']),
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
  '/bookings', `/bookings?booking=${BOOKING_ID}`, '/my-bookings', `/my-bookings?booking=${MY_BOOKING_ID}&booking_type=DEMO`,
  `/my-bookings/demo/${MY_BOOKING_ID}/report`, '/leads', `/leads/${LEAD_ID}`,
  // The BDE workspace's pages beyond My Enquiries (BDE Hub redesign, Phase 2).
  '/demo-bookings', '/diagnostic-bookings', '/follow-ups', '/sales', '/plans',
];
const labelOf = { ...Object.fromEntries(Object.entries(ids).map(([name, id]) => [id, name])), [ENQUIRY_ID]: 'enquiry_a',
  [BOOKING_ID]: 'booking_a', [MY_BOOKING_ID]: 'my_booking_a', [LEAD_ID]: 'lead_a', [LEAD_BDE_ID]: 'lead_bde' };
const symbolic = (value) => JSON.parse(JSON.stringify(value).replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g, (id) => `{${labelOf[id] || 'id'}}`));
// Activity rows name the moment the fixture world was recorded ("26 Oct, 12:27 PM");
// a re-recorded fixtures.json moves it, so it never counts as a difference.
// The staff dashboard's week button names the current week ("Oct 23 – Oct 29"),
// which moves with the clock the tests run on: neither is a difference.
const timeless = (value) => JSON.parse(JSON.stringify(value ?? null)
  .replace(/\d{1,2} [A-Z][a-z]{2}, \d{1,2}:\d{2} [AP]M\b/g, '{time}')
  .replace(/\b[A-Z][a-z]{2} \d{1,2} – [A-Z][a-z]{2} \d{1,2}\b/g, '{week}'));

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
