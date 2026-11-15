// Join Meet tests: every place a class or a chapter exam is joined, in the
// Hub and in Learn, rendered for real in jsdom (harness.jsx) with the API
// stood in for (api-stub.js). A class joins the Meet room of the tutor it is
// assigned to (`tutor_meet_link`), a chapter exam the room of the mentor it is
// assigned to (`mentor_meet_link`); the student's own link is never opened,
// even when a payload still carries one, and a missing room is said plainly.
//
//   npm run test:meet-links
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';
import { JSDOM, VirtualConsole } from 'jsdom';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const hub = path.resolve(here, '../..');
const src = path.join(hub, 'src');

// ------------------------------------------------------------------ bundle
const bundle = path.join(tmpdir(), `hub-meet-links-${process.pid}.mjs`);
const libsBundle = path.join(tmpdir(), `hub-meet-links-libs-${process.pid}.mjs`);
const build = (entryPoints, outfile) => esbuild.build({
  entryPoints,
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
      // One React for the Hub and the Learn components alike.
      for (const dep of ['react', 'react-dom', 'react-router-dom']) build.onResolve({ filter: new RegExp('^' + dep + '(/.*)?$') }, (args) => ({ path: require.resolve(args.path, { paths: [hub] }) }));
      build.onResolve({ filter: /lib\/api$/ }, (args) => (args.importer.includes('/frontend/') ? { path: path.join(here, 'api-stub.js') } : undefined));
      build.onResolve({ filter: /^@\// }, (args) => build.resolve(`./${args.path.slice(2)}`, { resolveDir: src, kind: args.kind }));
    },
  }],
});
await build([path.join(here, 'harness.jsx')], bundle);
await build([path.join(src, 'lib/meet-rooms.js')], libsBundle);

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
  'cancelAnimationFrame', 'localStorage', 'sessionStorage', 'MutationObserver', 'DOMRect',
  // Learn's buttons (framer-motion) hand jsdom an AbortSignal: it must be jsdom's own.
  'AbortController', 'AbortSignal']) {
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

const { mount, act } = await import(pathToFileURL(bundle).href);
const rooms = await import(pathToFileURL(libsBundle).href);

// ------------------------------------------------------------------ helpers
const tests = [];
let cleanup;
const test = (name, fn) => tests.push({ name, fn });
const settle = async () => { for (let i = 0; i < 6; i++) await act(async () => new Promise((resolve) => setTimeout(resolve, 0))); };
const click = async (el) => { assert.ok(el, 'nothing to click'); await act(async () => el.click()); await settle(); };
const text = () => document.body.textContent.replace(/\s+/g, ' ');
const buttons = (label) => [...document.querySelectorAll('button')].filter((el) => el.textContent.trim() === label);
const hrefs = () => [...document.querySelectorAll('a[href]')].map((a) => a.getAttribute('href'));
const open = async (kind, props) => { cleanup = await mount(kind, props); await settle(); };
const serve = (routes) => {
  globalThis.__meetApi = {
    calls: [],
    handler: async (entry) => {
      const answer = routes[`${entry.method} ${entry.url}`];
      if (answer === undefined) return { data: {} };
      return { data: typeof answer === 'function' ? answer(entry) : answer };
    },
  };
};
const calls = (method, url) => globalThis.__meetApi.calls.filter((entry) => entry.method === method && entry.url === url);

// window.open, recorded; the tab Start Session opens before the API answers.
let opened;
let replaced;
const stubWindowOpen = () => {
  opened = [];
  replaced = [];
  window.open = (url, target, features) => {
    opened.push([url, target, features]);
    return { opener: window, closed: false, location: { replace: (to) => replaced.push(to) }, close() { this.closed = true; } };
  };
};

// ---------------------------------------------------------------- fixtures
const TUTOR_LINK = 'https://meet.google.com/aaa-aaaa-aaa';
const MENTOR_LINK = 'https://meet.google.com/mmm-mone-mmm';
const STUDENT_LINK = 'https://meet.google.com/sss-ssss-sss';
const HOUR = 3600 * 1000;
const at = (offset) => new Date(Date.now() + offset).toISOString();

// A class as the Sessions API returns it -- with an old-style student link
// still nested, which nothing may open.
const session = (extra = {}) => {
  const start = extra.startIn ?? HOUR;
  const { startIn: _s, ...rest } = extra;
  return {
    id: 's-1', student_id: 'stu-1', title: 'Algebra', status: 'scheduled', series_id: null, class_number: null,
    start_time: at(start), end_time: at(start + HOUR), start_opens_at: at(start - 5 * 60 * 1000),
    students: { student_code: 'EDP1', full_name: 'Riya', mentor_profile: null, avatar_url: null, meet_link: STUDENT_LINK },
    tutor: 't-a', tutor_profile: { id: 't-a', full_name: 'Tutor A', email: 'a@hub.test' }, tutor_meet_link: TUTOR_LINK,
    started_at: null, started_by_profile: null, completed_at: null, completed_by_profile: null, duration_hours: 1,
    recording_link: null, notes_link: null, homework_link: null, content_files: {}, homework: null, rating: null,
    ...rest,
  };
};
const noLink = (extra = {}) => session({ id: 's-2', tutor: 't-n', tutor_profile: { id: 't-n', full_name: 'Tutor N', email: 'n@hub.test' }, tutor_meet_link: null, ...extra });
const noTutor = (extra = {}) => session({ id: 's-3', tutor: null, tutor_profile: null, tutor_meet_link: null, ...extra });
const exam = (extra = {}) => ({
  id: 'e-1', student_id: 'stu-1', chapter_name: 'Fractions', status: 'scheduled', type: 'chapter',
  start_time: at(2 * HOUR), end_time: at(3 * HOUR), mentor: 'm-1', mentor_profile: { id: 'm-1', full_name: 'Mentor One', email: 'm@hub.test' },
  mentor_meet_link: MENTOR_LINK, students: { full_name: 'Riya', meet_link: STUDENT_LINK }, files: [], file_count: 0, ...extra,
});
const ADMIN = { id: 'admin', role: 'ADMIN', permissions: ['accounts.view_all_sessions', 'accounts.manage_session', 'accounts.create_session', 'accounts.cancel_session'] };
const TUTOR = { id: 't-a', role: 'TUTOR', permissions: ['accounts.view_tutored_sessions', 'accounts.edit_session_notes'] };
const sessionsApi = (rows) => serve({ 'GET /api/students/': [], 'GET /api/sessions/': { sessions: rows } });

// -------------------------------------------------------------------- tests
test('The room helpers read the owner\'s link only: never the student\'s, never a non-https address', () => {
  assert.equal(rooms.classMeetLink(session()), TUTOR_LINK);
  assert.equal(rooms.classMeetLink(noLink()), null);
  assert.equal(rooms.classMeetLink(session({ tutor_meet_link: 'http://meet.google.com/aaa-aaaa-aaa' })), null);
  assert.equal(rooms.classMeetMissing(noLink()), "Tutor's Meet link not set");
  assert.equal(rooms.classMeetMissing(noTutor()), 'No tutor assigned');
  assert.equal(rooms.examMeetLink(exam()), MENTOR_LINK);
  assert.equal(rooms.examMeetLink(exam({ mentor_meet_link: null, tutor_meet_link: TUTOR_LINK })), null, "never a tutor's link");
  assert.equal(rooms.examMeetMissing(exam({ mentor_meet_link: null })), "Mentor's Meet link not set");
  assert.equal(rooms.examMeetMissing(exam({ mentor: null, mentor_profile: null, mentor_meet_link: null })), 'No mentor assigned');
});

test("Sessions table: Join Meet opens the class's tutor room; a missing room is said, never replaced", async () => {
  sessionsApi([session(), noLink(), noTutor()]);
  await open('sessions', { user: ADMIN, path: '/sessions' });
  assert.ok(hrefs().includes(TUTOR_LINK), text());
  assert.ok(!hrefs().includes(STUDENT_LINK));
  assert.ok(text().includes("Tutor's Meet link not set"));
  assert.ok(text().includes('No tutor assigned'));
  assert.equal(hrefs().filter((href) => href.includes('meet.google.com')).length, 1, 'one room for the one class that has one');
});

test("Sessions table: a tutor joins their started class in their own room", async () => {
  sessionsApi([session({ startIn: -10 * 60 * 1000, started_at: at(-10 * 60 * 1000), started_by_profile: { id: 't-a', full_name: 'Tutor A' } })]);
  await open('sessions', { user: TUTOR, path: '/sessions' });
  assert.ok(hrefs().includes(TUTOR_LINK), text());
  assert.ok(!hrefs().includes(STUDENT_LINK));
});

test("Start Session opens the tutor's room once started; without one it says so and opens nothing", async () => {
  stubWindowOpen();
  const due = session({ startIn: 2 * 60 * 1000 });
  serve({ [`POST /api/sessions/${due.id}/start/`]: { success: true, changed: true, session: { ...due, started_at: at(0) } } });
  await open('start', { session: due, asTutor: true });
  await click(buttons('Start Session')[0]);
  assert.ok(text().includes("Google Meet opens in a new tab, in the tutor's room."));
  await click(buttons('Start Session').at(-1));
  assert.equal(calls('POST', `/api/sessions/${due.id}/start/`).length, 1);
  assert.deepEqual(replaced, [TUTOR_LINK]);
  await cleanup(); cleanup = null;

  stubWindowOpen();
  const bare = noLink({ startIn: 2 * 60 * 1000 });
  serve({ [`POST /api/sessions/${bare.id}/start/`]: { success: true, changed: true, session: { ...bare, started_at: at(0) } } });
  await open('start', { session: bare, asTutor: true });
  await click(buttons('Start Session')[0]);
  assert.ok(text().includes('You have no Meet link yet, so Google Meet will not open.'));
  await click(buttons('Start Session').at(-1));
  assert.deepEqual([opened, replaced], [[], []], 'no tab, and never the student\'s room');
  await cleanup(); cleanup = null;

  await open('start', { session: noLink({ startIn: 2 * 60 * 1000 }), asTutor: false });
  await click(buttons('Start Session')[0]);
  assert.ok(text().includes("This class's tutor has no Meet link yet"));
});

test("Upcoming Sessions (admin/mentor dashboard): Join is the tutor's room, or the reason there is none", async () => {
  await open('upcoming', { sessions: [session({ startIn: 60 * 1000 }), noLink({ startIn: 2 * 60 * 1000 })], students: [] });
  assert.ok(hrefs().includes(TUTOR_LINK));
  assert.ok(!hrefs().includes(STUDENT_LINK));
  assert.ok(text().includes("Tutor's Meet link not set"));
});

test("Today's Work (tutor dashboard): a class still to come joins the tutor's room, or says why it cannot", async () => {
  await open('today', { classes: [session({ startIn: 60 * 1000 }), noLink({ startIn: 2 * 60 * 1000 })] });
  assert.ok(hrefs().includes(TUTOR_LINK));
  assert.ok(!hrefs().includes(STUDENT_LINK));
  assert.ok(text().includes("Tutor's Meet link not set"));
});

test("Student profile: no student-level Join; Next Up joins the class in the tutor's room and the exam in the mentor's", async () => {
  const student = { id: 'stu-1', full_name: 'Riya', student_code: 'EDP1', status: 'active', meet_link: STUDENT_LINK };
  await open('header', { student, user: { id: 'admin', role: 'ADMIN', permissions: [] } });
  assert.ok(!text().includes('Join Meet'));
  assert.ok(!hrefs().includes(STUDENT_LINK));
  await cleanup(); cleanup = null;

  await open('overview', { student, user: { id: 'admin', role: 'ADMIN', permissions: [] },
    highlights: { next_session: session(), last_session: null, next_exam: exam() } });
  assert.ok(hrefs().includes(TUTOR_LINK), text());
  assert.ok(hrefs().includes(MENTOR_LINK));
  assert.ok(!hrefs().includes(STUDENT_LINK));
  await cleanup(); cleanup = null;

  await open('overview', { student, user: { id: 'admin', role: 'ADMIN', permissions: [] },
    highlights: { next_session: noLink(), last_session: null, next_exam: exam({ mentor_meet_link: null }) } });
  assert.ok(text().includes("Tutor's Meet link not set"));
  assert.ok(text().includes("Mentor's Meet link not set"));
  assert.ok(!hrefs().some((href) => href.includes('meet.google.com')));
});

test("Learn: the next class card joins the tutor's room, or says it is not available", async () => {
  stubWindowOpen();
  await open('learn-class', { nextSession: session(), meetLink: STUDENT_LINK });
  assert.ok(text().includes('meet.google.com/aaa-aaaa-aaa'));
  assert.ok(!text().includes('sss-ssss-sss'), "a student link handed in is ignored");
  await click(buttons('Join Meeting')[0]);
  assert.deepEqual(opened, [[TUTOR_LINK, '_blank', undefined]]);
  await cleanup(); cleanup = null;

  stubWindowOpen();
  await open('learn-class', { nextSession: noLink() });
  assert.ok(text().includes("Your tutor's Meet link is not available yet."));
  assert.ok(buttons('Join Meeting')[0].disabled);
  await cleanup(); cleanup = null;
  await open('learn-class', { nextSession: noTutor() });
  assert.ok(text().includes('No tutor is assigned to this class yet.'));
});

test("Learn: the next exam card joins the mentor's room, never a tutor's or the student's", async () => {
  stubWindowOpen();
  await open('learn-exam', { exam: exam({ tutor_meet_link: TUTOR_LINK }), meetLink: STUDENT_LINK });
  assert.ok(text().includes('meet.google.com/mmm-mone-mmm'));
  await click(buttons('Join Exam')[0]);
  assert.deepEqual(opened, [[MENTOR_LINK, '_blank', undefined]]);
  await cleanup(); cleanup = null;

  await open('learn-exam', { exam: exam({ mentor_meet_link: null }) });
  assert.ok(text().includes("Your mentor's Meet link is not available yet."));
  assert.ok(buttons('Join Exam')[0].disabled);
});

test("Learn: each scheduled exam in the Exams list joins its own mentor's room", async () => {
  stubWindowOpen();
  await open('learn-exams', { exams: [exam(), exam({ id: 'e-2', chapter_name: 'Decimals', mentor_meet_link: null })], meetLink: STUDENT_LINK });
  await click(buttons('Join Exam')[0]);
  assert.deepEqual(opened, [[MENTOR_LINK, '_blank', undefined]]);
  assert.ok(buttons('Meet link not available')[0].disabled);
  assert.ok(text().includes("Your mentor's Meet link is not available yet."));
});

test("Team: a team manager sets a mentor's Meet link with the same PUT, as mentor_meet_link", async () => {
  const MANAGER = { id: 'admin', role: 'ADMIN', permissions: ['accounts.manage_team', 'accounts.view_team'] };
  const mentor = (link = null) => ({ id: 'm-1', username: 'mentor.one', email: 'm@hub.test', full_name: 'Mentor One', mobile_number: '',
    role: 'MENTOR', is_active: true, deactivated_at: null, created_at: '2026-10-01T09:00:00+00:00', is_superuser: false,
    deactivation_reason: null, must_change_password: false, has_password: true, locked_until: null, last_login: null,
    invited_by: null, permissions: [], tutor_meet_link: null, mentor_meet_link: link });
  serve({
    'GET /api/team/m-1/': mentor(),
    'GET /api/team/permissions/': [],
    'PUT /api/team/m-1/meet-link/': (entry) => mentor(entry.data.mentor_meet_link ? MENTOR_LINK : null),
  });
  await open('team', { user: MANAGER, path: '/team/m-1' });
  const input = document.getElementById('team-member-meet-link');
  assert.ok(input, 'a mentor has the field');
  assert.ok(text().includes("permanent room for their students' chapter exams"));
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, MENTOR_LINK);
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
  await act(async () => input.closest('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })));
  await settle();
  assert.deepEqual(calls('PUT', '/api/team/m-1/meet-link/').map((entry) => entry.data), [{ mentor_meet_link: MENTOR_LINK }]);
  assert.equal(document.getElementById('team-member-meet-link').value, MENTOR_LINK);
});

// ---------------------------------------------------------------------- run
let failures = 0;
for (const { name, fn } of tests) {
  try { await fn(); console.log(`PASS ${name}`); }
  catch (err) { failures++; console.log(`FAIL ${name}: ${err.stack}`); }
  finally { if (cleanup) await cleanup(); cleanup = null; await settle(); }
}
console.error = quiet;
console.log(`${tests.length - failures}/${tests.length} Join Meet tests passed.`);
window.close(); process.exit(failures ? 1 : 0);
