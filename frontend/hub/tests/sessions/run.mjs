// Normal Session lifecycle tests: where a class stands (Upcoming, In Progress,
// Notes Due, Not Started, Completed, No-show / Not Conducted, Cancelled), what
// its tutor's notes may do (nothing without a Start; once it has ended they
// complete it, however late -- no deadline, no approval), and what an administrator or the student's
// mentor may record or correct -- in the Hub's Sessions page and Learn's
// sessions list, rendered for real in jsdom (harness.jsx) with the API stood
// in for (api-stub.js). The backend decides; these check what is offered.
//
//   npm run test:sessions
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

// ------------------------------------------------------------------ bundle
const bundle = path.join(tmpdir(), `hub-sessions-${process.pid}.mjs`);
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
      // One React for the Hub and the Learn components alike.
      for (const dep of ['react', 'react-dom', 'react-router-dom']) build.onResolve({ filter: new RegExp('^' + dep + '(/.*)?$') }, (args) => ({ path: require.resolve(args.path, { paths: [hubDir] }) }));
      build.onResolve({ filter: /lib\/api$/ }, (args) => (args.importer.includes('/frontend/') ? { path: path.join(here, 'api-stub.js') } : undefined));
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

const { mount, act, hub, learn } = await import(pathToFileURL(bundle).href);

// ------------------------------------------------------------------ helpers
const tests = [];
let cleanup;
const test = (name, fn) => tests.push({ name, fn });
const settle = async () => { for (let i = 0; i < 6; i++) await act(async () => new Promise((resolve) => setTimeout(resolve, 0))); };
const click = async (el) => { assert.ok(el, 'nothing to click'); await act(async () => el.click()); await settle(); };
const text = () => document.body.textContent.replace(/\s+/g, ' ');
const buttons = (label) => [...document.querySelectorAll('button')].filter((el) => el.textContent.trim() === label);
const open = async (kind, props) => { cleanup = await mount(kind, props); await settle(); };
const serve = (routes) => {
  globalThis.__sessionsApi = {
    calls: [],
    handler: async (entry) => {
      const answer = routes[`${entry.method} ${entry.url}`];
      if (answer === undefined) return { data: {} };
      return { data: typeof answer === 'function' ? answer(entry) : answer };
    },
  };
};
const calls = (method, url) => globalThis.__sessionsApi.calls.filter((entry) => entry.method === method && entry.url === url);
const type = async (el, value) => {
  const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
  await act(async () => el.dispatchEvent(new window.Event('input', { bubbles: true })));
  await settle();
};
// The row's actions menu: [{ label, disabled, title }] as offered.
const rowActions = async () => {
  await click(document.querySelector('button[aria-label="Row actions"]'));
  const menu = document.querySelector('.legacy-ui.animate-fadeIn');
  assert.ok(menu, 'the row actions open');
  return [...menu.querySelectorAll('button')].map((el) => ({ label: el.textContent.trim(), disabled: el.disabled, title: el.title, el }));
};
const tab = async (label) => click(buttons(label)[0]);

// ---------------------------------------------------------------- fixtures
const HOUR = 3600 * 1000;
const at = (offset) => new Date(Date.now() + offset).toISOString();
const TUTOR_PROFILE = { id: 't-a', full_name: 'Tutor A', email: 'a@hub.test' };
const session = (extra = {}) => {
  const start = extra.startIn ?? HOUR;
  const { startIn: _s, ...rest } = extra;
  const end = start + HOUR;
  return {
    id: 's-1', student_id: 'stu-1', title: 'Algebra', status: 'scheduled', series_id: null, class_number: null,
    start_time: at(start), end_time: at(end), start_opens_at: at(start - 5 * 60 * 1000),
    students: { student_code: 'EDP1', full_name: 'Riya', mentor_profile: null, avatar_url: null },
    tutor: 't-a', tutor_profile: TUTOR_PROFILE, tutor_meet_link: 'https://meet.google.com/aaa-aaaa-aaa',
    started_at: null, started_by_profile: null, completed_at: null, completed_by_profile: null, duration_hours: 1,
    recording_link: null, notes_link: null, homework_link: null, content_files: {}, homework: null, rating: null,
    outcome_reason: null, outcome_note: null, outcome_kind: null,
    consumes_credit: true,
    ...rest,
  };
};
const started = (startIn, extra = {}) => session({ startIn, started_at: at(startIn), started_by_profile: TUTOR_PROFILE, ...extra });
const ADMIN = {
  id: 'admin', role: 'ADMIN',
  permissions: ['accounts.view_all_sessions', 'accounts.manage_session', 'accounts.create_session', 'accounts.cancel_session',
    'accounts.correct_session_outcome'],
};
const MENTOR = {
  id: 'm-1', role: 'MENTOR',
  permissions: ['accounts.view_mentored_sessions', 'accounts.manage_session', 'accounts.create_session', 'accounts.cancel_session'],
};
const TUTOR = { id: 't-a', role: 'TUTOR', permissions: ['accounts.view_tutored_sessions', 'accounts.edit_session_notes'] };
const sessionsApi = (rows, extra = {}) => serve({ 'GET /api/students/': [], 'GET /api/sessions/': { sessions: rows }, ...extra });

// The states every class can be in, as the backend's ClassStateTests has them.
const CASES = [
  ['upcoming', session({ startIn: 24 * HOUR })],
  ['upcoming', session({ startIn: -10 * 60 * 1000 })],  // under way, nobody started it yet
  ['in_progress', started(-10 * 60 * 1000)],
  ['notes_due', started(-3 * HOUR)],
  ['notes_due', started(-5 * HOUR, { status: 'attended' })],
  ['not_started', session({ startIn: -7 * HOUR })],
  ['not_started', session({ startIn: -9 * HOUR, status: 'attended' })],  // staff attendance is operational only
  ['completed', started(-11 * HOUR, { status: 'attended', completed_at: at(-9 * HOUR) })],
  ['not_conducted', session({ startIn: -13 * HOUR, status: 'not_conducted', outcome_reason: 'STUDENT_NO_SHOW', outcome_kind: 'no_show' })],
  ['cancelled', session({ startIn: 48 * HOUR, status: 'cancelled' })],
];

// -------------------------------------------------------------------- tests
test('Hub and Learn put every class in the same one state, as the backend does', () => {
  const now = new Date();
  for (const [expected, row] of CASES) {
    assert.equal(hub.classState(row, now), expected, JSON.stringify(row));
    assert.equal(learn.sessionState(row, now), expected, JSON.stringify(row));
  }
});

test("The tutor's notes: none without a Start, complete once it ended however late, edits once completed", () => {
  const now = new Date();
  assert.equal(hub.notesMode(session({ startIn: 24 * HOUR }), now), 'not_started');
  assert.equal(hub.notesMode(session({ startIn: -7 * HOUR }), now), 'not_started');
  assert.equal(hub.notesMode(session({ startIn: -7 * HOUR, status: 'attended' }), now), 'not_started');
  assert.equal(hub.notesMode(started(-10 * 60 * 1000), now), 'wait');
  assert.equal(hub.notesMode(started(-3 * HOUR), now), 'complete');
  // No deadline: days or weeks later they still complete it.
  assert.equal(hub.notesMode(started(-50 * HOUR), now), 'complete');
  assert.equal(hub.notesMode(started(-30 * 24 * HOUR), now), 'complete');
  assert.equal(hub.notesMode(started(-3 * HOUR, { status: 'attended', completed_at: at(-HOUR) }), now), 'save');
  assert.equal(hub.notesMode(session({ status: 'cancelled' }), now), null);
  assert.equal(hub.notesMode(session({ startIn: -5 * HOUR, status: 'not_conducted' }), now), null);
  // Exactly at its end, and long after.
  const due = started(-3 * HOUR);
  assert.equal(hub.notesMode(due, new Date(due.end_time)), 'complete');
  assert.equal(hub.notesMode(due, new Date(new Date(due.end_time).getTime() + 60 * 24 * HOUR)), 'complete');
  for (const gone of ['notesDueBy', 'lateNotesPending', 'notesOverdue']) assert.equal(hub[gone], undefined, gone);
});

test('Outcomes and cancelling: recorded once ended without a completion; cancelled only until the end', () => {
  const now = new Date();
  assert.ok(hub.mayRecordOutcome(session({ startIn: -7 * HOUR }), now));
  assert.ok(hub.mayRecordOutcome(started(-3 * HOUR), now));
  assert.ok(!hub.mayRecordOutcome(session({ startIn: -10 * 60 * 1000 }), now), 'not before the end');
  assert.ok(!hub.mayRecordOutcome(started(-3 * HOUR, { status: 'attended', completed_at: at(-HOUR) }), now));
  assert.ok(!hub.mayRecordOutcome(started(-3 * HOUR, { status: 'attended', homework: { id: 'h-1', status: 'assigned' } }), now));
  assert.ok(hub.mayCancel(session({ startIn: -10 * 60 * 1000 }), now), 'under way it may still be cancelled');
  assert.ok(!hub.mayCancel(session({ startIn: -2 * HOUR }), now), 'never once it has ended');
});

test('Learn tells the student what happened, never the staff reason', () => {
  const now = new Date();
  const label = (row) => learn.sessionBadge(row, now).label;
  assert.equal(label(session({ startIn: 24 * HOUR })), 'Scheduled');
  assert.equal(label(started(-10 * 60 * 1000)), 'In progress');
  assert.equal(label(started(-3 * HOUR)), 'Notes pending');
  assert.equal(label(session({ startIn: -7 * HOUR })), 'Awaiting update');
  assert.equal(label(session({ startIn: -7 * HOUR, status: 'attended' })), 'Attended');
  assert.equal(label(started(-11 * HOUR, { status: 'attended', completed_at: at(-9 * HOUR) })), 'Attended');
  assert.equal(label(session({ startIn: -13 * HOUR, status: 'not_conducted', outcome_kind: 'no_show' })), 'Missed');
  assert.equal(label(session({ startIn: -13 * HOUR, status: 'not_conducted', outcome_kind: 'not_conducted' })), 'Not held');
});

test('Sessions page: the tabs follow where each class stands, Needs Action counted beside its tab', async () => {
  sessionsApi(CASES.map(([, row], i) => ({ ...row, id: `s-${i}`, title: `Class ${i}` })));
  await open('sessions', { user: ADMIN });
  for (const label of ['Upcoming', 'Needs Action', 'Completed', 'No-show / Not Conducted', 'Cancelled']) {
    assert.equal(buttons(label).length, 1, label);
  }
  const titles = () => [...document.querySelectorAll('tbody tr')].map((tr) => tr.querySelector('td').textContent.trim());
  assert.deepEqual(titles().sort(), ['Class 0', 'Class 1', 'Class 2']);
  assert.ok(text().includes('Not started yet'), 'a class under way that nobody started says so');
  await tab('Needs Action');
  assert.deepEqual(titles().sort(), ['Class 3', 'Class 4', 'Class 5', 'Class 6']);
  assert.ok(document.querySelector('[aria-label="4 need action"]'), 'Needs Action counts its classes');
  assert.ok(text().includes('Nobody started this class'));
  assert.ok(text().includes("Awaiting the tutor's notes"));
  await tab('Completed');
  assert.deepEqual(titles(), ['Class 7']);
  await tab('No-show / Not Conducted');
  assert.deepEqual(titles(), ['Class 8']);
  assert.ok(text().includes('No-show') && text().includes('Student no-show'));
  await tab('Cancelled');
  assert.deepEqual(titles(), ['Class 9']);
});

test('Tutor: Submit Notes stays shut until someone started the class and it has ended', async () => {
  for (const [row, title, path] of [
    [session({ startIn: 24 * HOUR }), 'Opens once the class has been started and has ended', '/sessions'],
    [session({ startIn: -7 * HOUR }), 'Nobody started this class, so it takes no notes', '/sessions?tab=needs_action'],
    [started(-10 * 60 * 1000), 'Opens when the class ends at', '/sessions'],
  ]) {
    sessionsApi([row]);
    await open('sessions', { user: TUTOR, path });
    const [item] = await rowActions();
    assert.equal(item.label, 'Submit Notes');
    assert.ok(item.disabled, title);
    assert.ok(item.title.startsWith(title), item.title);
    await cleanup(); cleanup = null;
  }
});

test("Tutor: the notes complete the class, hours or days after it ended -- never for approval", async () => {
  const due = started(-3 * HOUR);
  sessionsApi([due], { 'PUT /api/sessions/': { success: true, completed: true } });
  await open('sessions', { user: TUTOR, path: '/sessions?tab=needs_action' });
  let [item] = await rowActions();
  assert.equal(item.label, 'Submit Notes');
  await click(item.el);
  assert.ok(buttons('Submit & Complete').length === 1, text());
  await cleanup(); cleanup = null;

  const late = started(-50 * HOUR, { id: 's-late' });
  sessionsApi([late], { 'PUT /api/sessions/': { success: true, completed: true } });
  await open('sessions', { user: TUTOR, path: '/sessions?tab=needs_action' });
  assert.ok(text().includes("Awaiting the tutor's notes"), text());
  assert.ok(!text().includes('overdue') && !text().includes('Late notes'), text());
  [item] = await rowActions();
  assert.equal(item.label, 'Submit Notes');
  await click(item.el);
  assert.equal(buttons('Submit & Complete').length, 1);
  assert.ok(!text().includes('approve'), text());
});

test('Staff: an ended class nobody started offers Record Outcome, never Cancel; one still to come the reverse', async () => {
  sessionsApi([session({ startIn: -7 * HOUR })]);
  await open('sessions', { user: MENTOR, path: '/sessions?tab=needs_action' });
  let labels = (await rowActions()).map((item) => item.label);
  assert.deepEqual(labels, ['Mark Attended', 'Reschedule', 'Record Outcome', 'Edit Resource Links']);
  await cleanup(); cleanup = null;

  sessionsApi([session({ startIn: 24 * HOUR })]);
  await open('sessions', { user: MENTOR });
  labels = (await rowActions()).map((item) => item.label);
  assert.ok(labels.includes('Cancel Session') && !labels.includes('Record Outcome'), labels.join(', '));
});

test('Record Outcome: a reason from the list, Other only with its note, posted as chosen', async () => {
  const row = session({ startIn: -7 * HOUR });
  sessionsApi([row], { [`POST /api/sessions/${row.id}/outcome/`]: { success: true, session: { ...row, status: 'not_conducted' } } });
  await open('sessions', { user: MENTOR, path: '/sessions?tab=needs_action' });
  const item = (await rowActions()).find((entry) => entry.label === 'Record Outcome');
  await click(item.el);
  const confirm = () => buttons('Record outcome').at(-1);
  assert.ok(confirm().disabled, 'nothing chosen yet');
  await click(document.querySelector('input[value="OTHER"]'));
  assert.ok(confirm().disabled, 'Other needs its note');
  await type(document.querySelector('#session-outcome-note'), 'Power cut at the student’s home');
  assert.ok(!confirm().disabled);
  await click(confirm());
  assert.deepEqual(calls('POST', `/api/sessions/${row.id}/outcome/`).map((c) => c.data), [{ reason: 'OTHER', note: 'Power cut at the student’s home' }]);
});

test('Staff: no late-notes review -- an ended, started class without its notes offers Record Outcome', async () => {
  const row = started(-50 * HOUR, { notes_link: null });
  sessionsApi([row]);
  await open('sessions', { user: MENTOR, path: '/sessions?tab=needs_action' });
  const labels = (await rowActions()).map((entry) => entry.label);
  assert.ok(labels.includes('Record Outcome') && !labels.includes('Review Late Notes'), labels.join(', '));
  assert.ok(!text().includes('Late notes awaiting approval'), text());
});

test('Correct Outcome: administrators only, always saying why; removing it is a revocation', async () => {
  const row = session({
    startIn: -13 * HOUR, status: 'not_conducted', outcome_reason: 'STUDENT_NO_SHOW', outcome_kind: 'no_show',
    outcome_recorded_at: at(-HOUR), outcome_recorded_by_profile: { id: 'm-1', full_name: 'Mentor One' }, consumes_credit: true,
  });
  sessionsApi([row]);
  await open('sessions', { user: MENTOR, path: '/sessions?tab=not_conducted' });
  let labels = (await rowActions()).map((entry) => entry.label);
  assert.ok(!labels.includes('Correct Outcome') && !labels.includes('Edit Resource Links'), labels.join(', '));
  await cleanup(); cleanup = null;

  sessionsApi([row], { [`POST /api/sessions/${row.id}/outcome/revoke/`]: { success: true, session: { ...row, status: 'scheduled' } } });
  await open('sessions', { user: ADMIN, path: '/sessions?tab=not_conducted' });
  labels = (await rowActions()).map((entry) => entry.label);
  assert.ok(labels.includes('Correct Outcome'), labels.join(', '));
  await click(buttons('Correct Outcome')[0]);
  await click([...document.querySelectorAll('input[name="session-outcome-correction"]')][1]);
  const confirm = () => buttons('Remove outcome').at(-1);
  assert.ok(confirm().disabled, 'a correction always says why');
  await type(document.querySelector('#session-outcome-correction-note'), 'Recorded against the wrong class');
  await click(confirm());
  assert.deepEqual(calls('POST', `/api/sessions/${row.id}/outcome/revoke/`).map((c) => c.data), [{ correction_note: 'Recorded against the wrong class' }]);
});

test('Learn: Upcoming and Past, each class labelled for the student', async () => {
  const rows = [
    session({ id: 'l-0', title: 'Next', startIn: 24 * HOUR }),
    started(-3 * HOUR, { id: 'l-1', title: 'Started' }),
    session({ id: 'l-2', title: 'Unstarted', startIn: -7 * HOUR }),
    session({ id: 'l-3', title: 'Missed one', startIn: -13 * HOUR, status: 'not_conducted', outcome_kind: 'no_show' }),
    session({ id: 'l-4', title: 'Not held one', startIn: -15 * HOUR, status: 'not_conducted', outcome_kind: 'not_conducted' }),
    session({ id: 'l-5', title: 'Called off', startIn: 30 * HOUR, status: 'cancelled' }),
  ];
  serve({});
  await open('learn-sessions', { sessions: rows });
  assert.ok(text().includes('Next') && !text().includes('Unstarted'), text());
  await tab('Past');
  for (const words of ['Notes pending', 'Awaiting update', 'Missed', 'Not held']) assert.ok(text().includes(words), words);
  assert.ok(!text().includes('Called off'));
});

// ---------------------------------------------------------------------- run
let failures = 0;
for (const { name, fn } of tests) {
  try { await fn(); console.log(`PASS ${name}`); }
  catch (err) { failures++; console.log(`FAIL ${name}: ${err.stack}`); }
  finally { if (cleanup) await cleanup(); cleanup = null; await settle(); }
}
console.error = quiet;
console.log(`${tests.length - failures}/${tests.length} session lifecycle tests passed.`);
window.close(); process.exit(failures ? 1 : 0);
