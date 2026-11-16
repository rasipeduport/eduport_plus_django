// Report building block tests: lib/reports (the report form's fields, its
// validation against the API's own rules and words, the request it sends, the
// API's refusals, where a booking stands with its report, the report and PDF
// URLs) and the components the tutor's form and the Admin's report view are
// built from -- the character counter, the Textarea, the item list, the
// read-only report and the PDF download -- and the tutor's report page
// (src/pages/TutorReportPage.jsx): both forms, the confirm before the first
// submit, edits and their versions, the preview, the API's refusals and the
// unsaved-changes guard -- in jsdom, the API answered per test by api-stub.js.
//
//   npm run test:reports
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
const bundle = path.join(tmpdir(), `hub-reports-${process.pid}.mjs`);
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
    'import.meta.env': JSON.stringify({ MODE: 'test', DEV: true, PROD: false }),
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

// A download is an object URL a link is clicked on: both recorded, nothing navigates.
const saved = [];
const revoked = [];
let objectUrls = 0;
URL.createObjectURL = () => `blob:test/${objectUrls++}`;
URL.revokeObjectURL = (url) => revoked.push(url);
window.HTMLAnchorElement.prototype.click = function click() {
  saved.push({ href: this.href, name: this.download });
};

const { render, mountPage, act, h, Fragment, ItemListHost, CharCounter, PdfDownloadButton, ReportFieldsView, Textarea, reports, confirmLeave } = await import(pathToFileURL(bundle).href);

// ------------------------------------------------------------------ helpers
const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();

async function settle(rounds = 6) {
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
const keyDown = (element, key) => fire(element, new window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));

async function typeInto(input, value) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
  await settle(2);
}

async function paste(input, text) {
  const event = new window.Event('paste', { bubbles: true, cancelable: true });
  Object.defineProperty(event, 'clipboardData', { value: { getData: () => text } });
  await fire(input, event);
  return event.defaultPrevented;
}

function button(label, root = document.body) {
  return [...root.querySelectorAll('button')].find(
    (element) => clean(element.textContent) === label || element.getAttribute('aria-label') === label
  );
}

const rowsOf = (root) => [...root.querySelectorAll('input')];

async function typeText(element, value) {
  const proto = element instanceof window.HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  await act(async () => {
    setter.call(element, value);
    element.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
  await settle(2);
}

const topDialog = () => [...document.querySelectorAll('[role="dialog"]')].at(-1);

/** Pick ``option`` from the Radix Select labelled ``label``, as the keyboard would. */
async function choose(label, option) {
  const trigger = document.querySelector(`[aria-label="${label}"]`);
  assert.ok(trigger, `no select labelled ${label}`);
  trigger.focus();
  await keyDown(trigger, 'Enter');
  const item = [...document.querySelectorAll('[role="option"]')].find((element) => clean(element.textContent) === option);
  assert.ok(item, `no option ${option} in ${label}`);
  await click(item);
}

/** A read-only report's details as [label, value] (a "Changed" mark left out), its headings, and its paragraphs. */
const details = (root) => [...root.querySelectorAll('dl > div')].map((row) =>
  [row.querySelector('dt').textContent, row.querySelector('dd').firstChild?.textContent ?? '']);
const headings = (root) => [...root.querySelectorAll('h4')].map((heading) => heading.firstChild.textContent);
const paragraphs = (root) => [...root.querySelectorAll('section p')].map((p) => p.textContent);

const mounted = [];
async function show(element) {
  const page = await render(element);
  mounted.push(page);
  return page;
}

// ------------------------------------------------------------------ the API
const ok = (data, headers = {}) => Promise.resolve({ status: 200, data, headers });
const fail = (status, data) => Promise.reject(Object.assign(new Error(`HTTP ${status}`), { response: { status, data } }));
const blobOf = (body) => new Blob([JSON.stringify(body)], { type: 'application/json' });

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const calls = (method, url) => globalThis.__reportsApi.calls.filter(
  (entry) => (!method || entry.method === method) && (!url || entry.url === url));

/** Answers keyed "METHOD url"; a value is the body, a function is called with the request. */
function serve(table) {
  globalThis.__reportsApi.handler = (entry) => {
    const answer = table[`${entry.method} ${entry.url}`];
    if (answer === undefined) return fail(404, { error: 'NOT_FOUND', message: `No answer for ${entry.method} ${entry.url}` });
    return typeof answer === 'function' ? answer(entry) : ok(answer);
  };
}

// ------------------------------------------------------------------ fixtures
const DIAGNOSTIC_INPUT = {
  score: '18', max_score: '25', performance_level: 'GOOD',
  strength_areas: ['  Fractions ', '', 'Place value'], skills_to_strengthen: ['Word problems'],
  teacher_remarks: 'Works carefully.\r\nChecks each step.  ', suggested_plan: 'The plan is:\n30 Days Foundation Plan',
};
const DEMO_INPUT = {
  assessment_review: 'Scored 9 out of 12.', class_observation_review: 'Attentive.', suggested_strategy: 'Timed practice.',
};

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

// ------------------------------------------------------------- lib/reports
test('the fields, limits and labels are the API\'s', () => {
  assert.deepEqual(reports.REPORT_FIELDS.DIAGNOSTIC, ['score', 'max_score', 'performance_level', 'strength_areas',
    'skills_to_strengthen', 'teacher_remarks', 'suggested_plan']);
  assert.deepEqual(reports.REPORT_FIELDS.DEMO, ['assessment_review', 'class_observation_review', 'suggested_strategy']);
  assert.deepEqual([reports.MAX_ITEMS, reports.ITEM_CHARS, reports.MAX_SCORE], [15, 120, 1000]);
  assert.deepEqual(['teacher_remarks', 'suggested_plan', 'assessment_review', 'class_observation_review', 'suggested_strategy']
    .map(reports.textLimit), [2000, 1000, 1200, 1200, 1200]);
  assert.deepEqual(reports.PERFORMANCE_LEVELS.map((level) => level.value), ['EXCELLENT', 'GOOD', 'AVERAGE', 'BELOW_AVERAGE']);
  assert.equal(reports.performanceLevelLabel('BELOW_AVERAGE'), 'Below Average');
  assert.equal(reports.REPORT_SUBJECT, 'Mathematics');
  assert.equal(reports.DIAGNOSTIC_ASSESSMENT_TYPE, 'Diagnostic Test');
  assert.throws(() => reports.emptyReportForm('WEBINAR'), /Unknown report type/);
});

test('a blank form, a saved report as a form, and the request a form sends', () => {
  assert.deepEqual(reports.emptyReportForm('DIAGNOSTIC'), {
    score: '', max_score: '', performance_level: '', strength_areas: [''], skills_to_strengthen: [''],
    teacher_remarks: '', suggested_plan: '',
  });
  assert.deepEqual(reports.emptyReportForm('DEMO'), { assessment_review: '', class_observation_review: '', suggested_strategy: '' });

  const saved = { score: 18, max_score: 25, performance_level: 'GOOD', strength_areas: ['Fractions'], skills_to_strengthen: [],
    teacher_remarks: 'Careful.', suggested_plan: 'Plan.' };
  const form = reports.reportForm('DIAGNOSTIC', saved);
  assert.deepEqual(form, { ...saved, score: '18', max_score: '25', skills_to_strengthen: [''] });
  form.strength_areas.push('Ratios');
  assert.deepEqual(saved.strength_areas, ['Fractions'], 'the form is a copy');

  // Trimmed text with "\n" line breaks, blank rows dropped, whole numbers as numbers -- and never a system field.
  assert.deepEqual(reports.reportPayload('DIAGNOSTIC', DIAGNOSTIC_INPUT), {
    score: 18, max_score: 25, performance_level: 'GOOD', strength_areas: ['Fractions', 'Place value'],
    skills_to_strengthen: ['Word problems'], teacher_remarks: 'Works carefully.\nChecks each step.',
    suggested_plan: 'The plan is:\n30 Days Foundation Plan',
  });
  assert.deepEqual(reports.reportPayload('DIAGNOSTIC', { ...DIAGNOSTIC_INPUT, score: '1.5', student_name: 'X' }).score, '1.5');
  assert.ok(!('student_name' in reports.reportPayload('DIAGNOSTIC', { ...DIAGNOSTIC_INPUT, student_name: 'X' })));
  assert.deepEqual(reports.reportPayload('DEMO', { ...DEMO_INPUT, assessment_review: '  Scored 9 out of 12.  ' }), DEMO_INPUT);

  // Changed only when the request would be.
  assert.equal(reports.reportChanged('DEMO', DEMO_INPUT, { ...DEMO_INPUT, suggested_strategy: 'Timed practice. ' }), false);
  assert.equal(reports.reportChanged('DEMO', DEMO_INPUT, { ...DEMO_INPUT, suggested_strategy: 'Untimed practice.' }), true);
  assert.equal(reports.reportChanged('DIAGNOSTIC', DIAGNOSTIC_INPUT, { ...DIAGNOSTIC_INPUT, strength_areas: ['Fractions', 'Place value', ''] }), false);
});

test('validation finds what the API would refuse, in the API\'s words', () => {
  const valid = (type, values) => assert.deepEqual(reports.validateReport(type, values), {});
  const problem = (type, values, field, message) => assert.equal(reports.validateReport(type, values)[field], message, field);

  valid('DIAGNOSTIC', DIAGNOSTIC_INPUT);
  valid('DEMO', DEMO_INPUT);
  assert.deepEqual(reports.validateReport('DIAGNOSTIC', reports.emptyReportForm('DIAGNOSTIC')), {
    score: 'This field is required.', max_score: 'This field is required.', performance_level: 'This field is required.',
    strength_areas: 'List 1 to 15 items.', skills_to_strengthen: 'List 1 to 15 items.',
    teacher_remarks: 'This field is required.', suggested_plan: 'This field is required.',
  });
  assert.deepEqual(Object.keys(reports.validateReport('DEMO', reports.emptyReportForm('DEMO'))),
    ['assessment_review', 'class_observation_review', 'suggested_strategy']);

  // Scores: whole numbers, 0 to 1000 (the maximum at least 1), and never above the maximum.
  const D = DIAGNOSTIC_INPUT;
  for (const score of ['1.5', '-1', 'ten', '1e2']) problem('DIAGNOSTIC', { ...D, score }, 'score', 'Enter a whole number.');
  problem('DIAGNOSTIC', { ...D, max_score: '0' }, 'max_score', 'Enter a number from 1 to 1000.');
  problem('DIAGNOSTIC', { ...D, max_score: '1001' }, 'max_score', 'Enter a number from 1 to 1000.');
  problem('DIAGNOSTIC', { ...D, score: '26' }, 'score', 'The score cannot be more than the maximum score.');
  valid('DIAGNOSTIC', { ...D, score: '0' });
  valid('DIAGNOSTIC', { ...D, score: '25' });
  problem('DIAGNOSTIC', { ...D, performance_level: 'GREAT' }, 'performance_level', 'Choose a performance level.');

  // Lists: 1 to 15 one-line items of at most 120 characters; blank rows do not count.
  problem('DIAGNOSTIC', { ...D, strength_areas: ['', '  '] }, 'strength_areas', 'List 1 to 15 items.');
  problem('DIAGNOSTIC', { ...D, strength_areas: Array.from({ length: 16 }, (_, i) => `Item ${i}`) }, 'strength_areas', 'List 1 to 15 items.');
  valid('DIAGNOSTIC', { ...D, strength_areas: Array.from({ length: 15 }, (_, i) => `Item ${i}`) });
  problem('DIAGNOSTIC', { ...D, skills_to_strengthen: ['x'.repeat(121)] }, 'skills_to_strengthen', 'Each item holds at most 120 characters.');
  valid('DIAGNOSTIC', { ...D, skills_to_strengthen: ['x'.repeat(120)] });
  assert.deepEqual(reports.itemProblems(['ok', '', 'x'.repeat(121), 'two\nlines']),
    [null, null, 'Each item holds at most 120 characters.', 'Each item is one line.']);

  // Text: required, and counted as the API counts -- an emoji or a line break is one character.
  problem('DIAGNOSTIC', { ...D, teacher_remarks: '   \n ' }, 'teacher_remarks', 'This field is required.');
  problem('DIAGNOSTIC', { ...D, teacher_remarks: 'x'.repeat(2001) }, 'teacher_remarks', 'Use at most 2000 characters.');
  valid('DIAGNOSTIC', { ...D, teacher_remarks: '😀'.repeat(2000) });
  valid('DIAGNOSTIC', { ...D, suggested_plan: 'a\r\n'.repeat(500) });
  problem('DEMO', { ...DEMO_INPUT, suggested_strategy: 'x'.repeat(1201) }, 'suggested_strategy', 'Use at most 1200 characters.');
  assert.equal(reports.charCount('😀\r\n'), 2);
});

test('the API\'s refusals keep a message for each field', () => {
  const error = (status, data) => ({ response: { status, data } });
  assert.deepEqual(reports.reportError(error(400, { error: 'VALIDATION_ERROR', message: 'Check the report.',
    fields: { score: ['Enter a whole number.', 'second'], status: ['This field cannot be set.'], non_field_errors: ['Send an object.'] } })), {
    status: 400, code: 'VALIDATION_ERROR', message: 'Check the report.', version: null,
    fields: { score: 'Enter a whole number.', status: 'This field cannot be set.', non_field_errors: 'Send an object.' },
  });
  assert.deepEqual(reports.reportError(error(409, { error: 'REPORT_EXISTS', message: 'It exists.', version: 2 })), {
    status: 409, code: 'REPORT_EXISTS', message: 'It exists.', version: 2, fields: {},
  });
  assert.equal(reports.reportError(error(409, { error: 'REPORT_VERSION_CONFLICT', version: 3 })).version, 3);
  assert.equal(reports.reportError(error(403, { detail: 'You do not have permission to perform this action.' })).message,
    'You do not have permission to perform this action.');
  assert.equal(reports.reportError(error(500, {}), 'Could not save the report.').message, 'Could not save the report.');
  assert.equal(reports.reportError(new Error('Network Error')).message, 'Could not reach the server. Check your connection and try again.');
});

test('where a booking stands with its report, and what its tutor is offered', () => {
  // Where it stands as a class is the API's activity_state, and Write report follows the tutor's own start
  // (started_at) -- never the slot's clock, which says nothing of a start.
  const STARTED = '2026-11-01T14:02:00+00:00';
  const booking = (status, slot = {}, report = {}) => ({ status, slot: { started: false, ended: false, ...slot },
    activity_state: status === 'BOOKED' ? 'UPCOMING' : status, started_at: null, has_report: false, report_version: null,
    report_due: false, ...report });
  const state = (b) => [reports.reportState(b).label, reports.reportState(b).variant];
  const actions = (b) => reports.reportActions(b);

  const upcoming = booking('BOOKED');
  const ready = booking('BOOKED', {}, { activity_state: 'READY' });
  const late = booking('BOOKED', { started: true }, { activity_state: 'LATE' });
  const running = booking('BOOKED', { started: true }, { activity_state: 'IN_PROGRESS', started_at: STARTED });
  const due = booking('BOOKED', { started: true, ended: true }, { activity_state: 'IN_PROGRESS', started_at: STARTED, report_due: true });
  const missed = booking('BOOKED', { started: true, ended: true }, { activity_state: 'NOT_STARTED' });
  const done = booking('COMPLETED', { started: true, ended: true }, { started_at: STARTED, has_report: true, report_version: 2 });
  assert.deepEqual(state(upcoming), ['Upcoming', 'success']);
  assert.deepEqual(state(ready), ['Ready to start', 'success']);
  assert.deepEqual(state(late), ['Not started yet', 'warning']);
  assert.deepEqual(state(running), ['In progress', 'info']);
  assert.deepEqual(state(due), ['Report due', 'warning']);
  assert.deepEqual(state(missed), ['Not started', 'warning']);
  assert.deepEqual(state(done), ['Completed', 'secondary']);
  assert.deepEqual(state(booking('CANCELLED', { started: true })), ['Cancelled', 'outline']);
  assert.deepEqual(state(booking('RESCHEDULED')), ['Rescheduled', 'outline']);
  assert.deepEqual(reports.reportState(missed).key, 'not_started');
  // Due is the API's word (report_due), never worked out here: a started booking whose slot is over stays In progress.
  assert.equal(reports.reportState({ ...due, report_due: false }).label, 'In progress');

  assert.deepEqual(actions(upcoming), { write: false, edit: false, pdf: false });
  assert.deepEqual(actions(ready), { write: false, edit: false, pdf: false });
  assert.deepEqual(actions(late), { write: false, edit: false, pdf: false }, 'the scheduled time alone opens no report');
  assert.deepEqual(actions(missed), { write: false, edit: false, pdf: false });
  assert.deepEqual(actions(running), { write: true, edit: false, pdf: false });
  assert.deepEqual(actions(due), { write: true, edit: false, pdf: false });
  assert.deepEqual(actions(done), { write: false, edit: true, pdf: true });
  // A booking completed before Start existed has no recorded start: completed and editable all the same.
  const legacy = { ...done, started_at: null };
  assert.deepEqual(state(legacy), ['Completed', 'secondary']);
  assert.deepEqual(actions(legacy), { write: false, edit: true, pdf: true });
  assert.deepEqual(reports.reportBadge(legacy), { label: 'Report v2', variant: 'success' });
  assert.deepEqual(actions(booking('CANCELLED', { started: true, ended: true })), { write: false, edit: false, pdf: false });

  assert.deepEqual(reports.reportBadge(done), { label: 'Report v2', variant: 'success' });
  assert.deepEqual(reports.reportBadge(due), { label: 'Report due', variant: 'warning' });
  assert.equal(reports.reportBadge(running), null);
});

test('the report and PDF URLs, for the tutor and the Admin', () => {
  assert.equal(reports.tutorReportUrl('DIAGNOSTIC', 'b-1'), '/api/tutor/bookings/diagnostic/b-1/report/');
  assert.equal(reports.tutorReportPreviewUrl('DEMO', 'b-2'), '/api/tutor/bookings/demo/b-2/report/preview/');
  assert.equal(reports.bookingReportUrl('DEMO', 'b-2'), '/api/bookings/demo/b-2/report/');
  // The lead's owner BDE (P9): the reports on one of their enquiries, and each one's current PDF.
  assert.equal(reports.bdeReportsUrl('lead-1'), '/api/bde/enquiries/lead-1/reports/');
  assert.equal(reports.bdeReportPdfUrl('DIAGNOSTIC', 'b-1'), '/api/bde/bookings/diagnostic/b-1/report/pdf/');
  assert.throws(() => reports.bdeReportPdfUrl('WEBINAR', 'b-1'), /Unknown booking type/);
  const tutorReport = reports.tutorReportUrl('DIAGNOSTIC', 'b-1');
  assert.equal(reports.reportPdfUrl(tutorReport), '/api/tutor/bookings/diagnostic/b-1/report/pdf/');
  assert.equal(reports.reportPdfUrl(tutorReport, 2), '/api/tutor/bookings/diagnostic/b-1/report/revisions/2/pdf/');
  assert.equal(reports.reportPdfUrl(reports.bookingReportUrl('DEMO', 'b-2'), 1), '/api/bookings/demo/b-2/report/revisions/1/pdf/');
  assert.throws(() => reports.tutorReportUrl('WEBINAR', 'b-1'), /Unknown booking type/);
  // The tutor's report page, and the name a PDF is saved under when the server's cannot be read.
  assert.equal(reports.tutorReportPagePath('DIAGNOSTIC', 'b-1'), '/my-bookings/diagnostic/b-1/report');
  assert.equal(reports.tutorReportPagePath('DEMO', 'b-2'), '/my-bookings/demo/b-2/report');
  assert.throws(() => reports.tutorReportPagePath('WEBINAR', 'b-1'), /Unknown booking type/);
  assert.equal(reports.reportPdfFallbackName('DIAGNOSTIC'), 'Diagnostic-Report.pdf');
  assert.equal(reports.reportPdfFallbackName('DEMO', 3), 'Demo-Report-v3.pdf');
});

test("the message Send via WhatsApp fills in, as approved (A11): the BDE attaches the PDF", () => {
  assert.equal(reports.reportWhatsAppMessage('DIAGNOSTIC', 'Asha Nair', 'Riya'),
    "Hello Asha Nair, please find Riya's Diagnostic Test report from Eduport Plus attached.");
  assert.equal(reports.reportWhatsAppMessage('DEMO', 'Asha Nair', 'Riya'),
    "Hello Asha Nair, please find Riya's Demo Class report from Eduport Plus attached.");
  assert.equal(reports.reportWhatsAppMessage('DEMO', '', 'Riya'), "Hello, please find Riya's Demo Class report from Eduport Plus attached.");
  // Without the Web Share API (as in jsdom) no file can be shared, so Share PDF is not offered.
  assert.equal(reports.canSharePdf(), false);
});

test('the file name a Content-Disposition header gives', () => {
  const name = reports.filenameFromDisposition;
  assert.equal(name('attachment; filename="Diagnostic-Report-Riya-2026-11-01-v2.pdf"'), 'Diagnostic-Report-Riya-2026-11-01-v2.pdf');
  assert.equal(name('attachment; filename=Demo-Report-Ali-2026-11-01.pdf'), 'Demo-Report-Ali-2026-11-01.pdf');
  assert.equal(name("attachment; filename*=UTF-8''R%C3%ADya.pdf; filename=\"Riya.pdf\""), 'Ríya.pdf');
  assert.equal(name('attachment'), null);
  assert.equal(name(undefined), null);
});

test('a refused PDF download is said in plain words, read from the blob it came as', async () => {
  const refusal = (status, body) => reports.reportPdfError({ response: { status, data: blobOf(body) } });
  assert.equal(await refusal(403, { detail: 'Authentication credentials were not provided.' }),
    'Your session has ended. Sign in again to download the PDF.');
  assert.equal(await refusal(403, { detail: 'You do not have permission to perform this action.' }),
    'You do not have access to this report.');
  assert.equal(await refusal(404, { error: 'NO_VERSION' }), 'That version of the report does not exist.');
  assert.equal(await refusal(404, { error: 'NO_REPORT' }), 'This booking has no report yet.');
  assert.equal(await refusal(404, { error: 'NOT_FOUND' }), 'This booking is not available to you any more.');
  assert.equal(await refusal(429, { detail: 'Request was throttled. Expected available in 42 seconds.' }),
    'Too many downloads in a short time. Try again in 42 seconds.');
  assert.equal(await refusal(429, {}), 'Too many downloads in a short time. Try again in a minute.');
  assert.equal(await refusal(500, {}), 'The PDF could not be made. Try again.');
  assert.equal(await reports.reportPdfError({ response: { status: 404, data: { error: 'NO_REPORT' } } }), 'This booking has no report yet.');
  assert.equal(await reports.reportPdfError(new Error('Network Error')), 'Could not reach the server. Check your connection and try again.');
});

// --------------------------------------------------------------- components
test('the character counter counts as the API does, amber near the limit and red past it', async () => {
  const { container } = await show(h(Fragment, null,
    h(CharCounter, { id: 'a', value: 'x'.repeat(10), max: 100 }),
    h(CharCounter, { id: 'b', value: 'x'.repeat(95), max: 100 }),
    h(CharCounter, { id: 'c', value: 'x'.repeat(101), max: 100 }),
    h(CharCounter, { id: 'd', value: '😀\r\n', max: 100 })));
  const [a, b, c, d] = ['a', 'b', 'c', 'd'].map((id) => container.querySelector(`#${id}`));
  assert.equal(clean(a.textContent), '10/100 characters');
  assert.ok(!a.className.includes('text-warning') && !a.className.includes('text-destructive'));
  assert.ok(b.className.includes('text-warning'));
  assert.ok(c.className.includes('text-destructive'));
  assert.equal(clean(d.textContent), '2/100 characters');
});

test('the Textarea is a styled textarea that keeps its props', async () => {
  const { container } = await show(h(Textarea, { id: 'remarks', maxLength: 2000, 'aria-invalid': 'true', rows: 6, defaultValue: 'Hello' }));
  const area = container.querySelector('textarea');
  assert.equal(area.getAttribute('data-slot'), 'textarea');
  assert.deepEqual([area.id, area.maxLength, area.getAttribute('aria-invalid'), area.rows, area.value],
    ['remarks', 2000, 'true', 6, 'Hello']);
});

test('the item list: typing, adding, removing, Enter for the next item, pasting lines, and the 15-item cap', async () => {
  const changes = [];
  const { container } = await show(
    h(ItemListHost, { id: 'strengths', label: 'Strength areas', initial: [''], onItems: (items) => changes.push(items) })
  );
  const inputs = () => rowsOf(container);
  assert.equal(inputs().length, 1);
  assert.equal(inputs()[0].getAttribute('aria-label'), 'Strength areas 1');
  assert.equal(inputs()[0].maxLength, 120);
  assert.ok(button('Remove Strength areas 1', container).disabled, 'a lone empty row cannot be removed');

  await typeInto(inputs()[0], 'Fractions');
  assert.deepEqual(changes.at(-1), ['Fractions']);

  await click(button('Add item', container));
  assert.deepEqual(changes.at(-1), ['Fractions', '']);
  assert.ok(document.activeElement === inputs()[1], 'the new row has the focus');

  await typeInto(inputs()[1], 'Ratios');
  const enter = new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
  await fire(inputs()[1], enter);
  assert.ok(enter.defaultPrevented, 'Enter never submits the form');
  assert.deepEqual(changes.at(-1), ['Fractions', 'Ratios', '']);
  assert.ok(document.activeElement === inputs()[2], 'the next row has the focus');

  assert.equal(await paste(inputs()[2], 'Place value\n\nDecimals\r\nShapes'), true);
  assert.deepEqual(changes.at(-1), ['Fractions', 'Ratios', 'Place value', 'Decimals', 'Shapes']);
  assert.equal(await paste(inputs()[0], 'one line only'), false, 'a single line pastes as typed');

  await click(button('Remove Strength areas 2', container));
  assert.deepEqual(changes.at(-1), ['Fractions', 'Place value', 'Decimals', 'Shapes']);

  // At the cap: no more rows, by button or by Enter, and pasted lines that would not fit stay as typed.
  const full = await show(h(ItemListHost, { id: 'full', label: 'Skills', initial: Array.from({ length: 15 }, (_, i) => `Skill ${i}`) }));
  const add = button('Up to 15 items', full.container);
  assert.ok(add && add.disabled);
  await keyDown(rowsOf(full.container)[14], 'Enter');
  assert.equal(rowsOf(full.container).length, 15);
  assert.equal(await paste(rowsOf(full.container)[0], 'a\nb'), false);
});

test('the item list marks a row that breaks a rule, and every row when the list does', async () => {
  const long = 'x'.repeat(121);
  const { container } = await show(h(ItemListHost, { id: 'skills', label: 'Skills', initial: ['Fine', long] }));
  const [fine, tooLong] = rowsOf(container);
  assert.equal(fine.getAttribute('aria-invalid'), null);
  assert.equal(tooLong.getAttribute('aria-invalid'), 'true');
  const hint = container.querySelector(`#${tooLong.getAttribute('aria-describedby')}`);
  assert.deepEqual([...hint.children].map((part) => clean(part.textContent)),
    ['Each item holds at most 120 characters.', '121/120 characters']);

  const blank = await show(h(ItemListHost, { id: 'none', label: 'Skills', initial: [''], invalid: true }));
  assert.equal(rowsOf(blank.container)[0].getAttribute('aria-invalid'), 'true');
});

test('a report read-only, as its PDF prints it, with what a version changed marked', async () => {
  const diagnostic = {
    student_name: 'Riya Menon', grade: '8', tutor_name: 'Tutor Anu',
    fields: { score: 18, max_score: 25, performance_level: 'GOOD', strength_areas: ['Fractions', 'Place value'],
      skills_to_strengthen: ['Word problems'], teacher_remarks: 'Line one.\nLine two.', suggested_plan: 'Weekly drills.' },
  };
  const { container } = await show(
    h(ReportFieldsView, { type: 'DIAGNOSTIC', report: diagnostic, changedFields: ['teacher_remarks', 'tutor_name_snapshot'] })
  );
  assert.deepEqual(details(container), [['Student Name', 'Riya Menon'], ['Grade', '8'], ['Subject', 'Mathematics'],
    ['Assessment Type', 'Diagnostic Test'], ['Tutor Name', 'Tutor Anu']]);
  assert.deepEqual(headings(container), ['Summary', 'Strength Areas', 'Skills to Strengthen', 'Teacher’s Remarks', 'Suggested Plan']);
  assert.deepEqual(paragraphs(container), ['Score: 18/25', 'Performance Level: Good', 'Line one.\nLine two.', 'Weekly drills.']);
  assert.deepEqual([...container.querySelectorAll('li')].map((li) => li.textContent), ['Fractions', 'Place value', 'Word problems']);
  const remarks = [...container.querySelectorAll('p')].find((p) => p.textContent.startsWith('Line one.'));
  assert.ok(remarks.className.includes('whitespace-pre-line'), 'the tutor\'s line breaks show');
  // What this version changed: the tutor's name and the remarks, nothing else.
  const marked = [...container.querySelectorAll('[data-slot="badge"]')].map((badge) =>
    badge.closest('dd') ? badge.closest('dd').previousElementSibling.textContent : badge.closest('h4').firstChild.textContent);
  assert.deepEqual(marked, ['Tutor Name', 'Teacher’s Remarks']);
  assert.ok(marked.every((_, i) => clean(container.querySelectorAll('[data-slot="badge"]')[i].textContent) === 'Changed'));

  const demo = await show(h(ReportFieldsView, { type: 'DEMO', report: { student_name: 'Ali', grade: '9', tutor_name: 'Tutor Binu',
    fields: { assessment_review: 'Scored 9 out of 12.', class_observation_review: '', suggested_strategy: 'Timed practice.' } } }));
  assert.deepEqual(details(demo.container).map(([label]) => label), ['Student Name', 'Grade', 'Subject', 'Tutor Name']);
  assert.deepEqual(headings(demo.container), ['Assessment Review', 'Class Observation Review', 'Suggested Strategy']);
  assert.deepEqual(paragraphs(demo.container), ['Scored 9 out of 12.', '—', 'Timed practice.']);
  assert.equal(demo.container.querySelectorAll('[data-slot="badge"]').length, 0);
});

test('a PDF download is saved under the server\'s name, as a blob, one at a time', async () => {
  const url = '/api/tutor/bookings/diagnostic/b-1/report/revisions/2/pdf/';
  const pending = deferred();
  globalThis.__reportsApi.handler = () => pending.promise;
  const { container } = await show(h(PdfDownloadButton, { url, fallbackName: 'Diagnostic-Report.pdf' }));
  const start = saved.length;

  await click(button('Download PDF', container));
  const busy = button('Downloading…', container);
  assert.ok(busy && busy.disabled, 'busy while it downloads');
  await click(busy);
  assert.equal(calls().length, 1, 'a second click starts nothing');
  assert.deepEqual(calls()[0], { method: 'GET', url, params: null, data: null, responseType: 'blob' });

  await act(async () => pending.resolve({ status: 200, data: new Blob(['%PDF-1.7']),
    headers: { 'content-disposition': 'attachment; filename="Diagnostic-Report-Riya-2026-11-01-v2.pdf"' } }));
  await settle();
  assert.deepEqual(saved.slice(start).map((entry) => entry.name), ['Diagnostic-Report-Riya-2026-11-01-v2.pdf']);
  assert.ok(button('Download PDF', container) && !button('Download PDF', container).disabled);
  assert.equal(container.querySelector('[role="alert"]'), null);

  // A header the browser does not let the page read: the fallback name.
  globalThis.__reportsApi.handler = () => ok(new Blob(['%PDF-1.7']), {});
  await click(button('Download PDF', container));
  assert.equal(saved.at(-1).name, 'Diagnostic-Report.pdf');
});

test('a refused PDF download says why under the button, and the next try clears it', async () => {
  const { container } = await show(h(PdfDownloadButton, { url: '/api/bookings/demo/b-2/report/pdf/' }, 'Current PDF'));
  const start = saved.length;
  globalThis.__reportsApi.handler = () => fail(429, blobOf({ detail: 'Request was throttled. Expected available in 30 seconds.' }));
  await click(button('Current PDF', container));
  assert.equal(clean(container.querySelector('[role="alert"]').textContent), 'Too many downloads in a short time. Try again in 30 seconds.');

  globalThis.__reportsApi.handler = () => fail(404, blobOf({ error: 'NO_VERSION', message: 'This report has no such version.' }));
  await click(button('Current PDF', container));
  assert.equal(clean(container.querySelector('[role="alert"]').textContent), 'That version of the report does not exist.');
  assert.equal(saved.length, start, 'nothing saved');

  globalThis.__reportsApi.handler = () => ok(new Blob(['%PDF-1.7']), { 'content-disposition': 'attachment; filename="Demo-Report-Ali-2026-11-01.pdf"' });
  await click(button('Current PDF', container));
  assert.equal(container.querySelector('[role="alert"]'), null);
  assert.equal(saved.at(-1).name, 'Demo-Report-Ali-2026-11-01.pdf');
});


// ------------------------------------------------------------ the report page
const TUTOR = { id: 'tutor-anu', role: 'TUTOR', full_name: 'Tutor Anu', email: 'anu@bookings.test',
  permissions: ['accounts.submit_booking_report', 'accounts.view_assigned_bookings'] };
const slotOf = (started, ended) => ({ date: '2026-11-01', time: '19:30', starts_at: '2026-11-01T14:00:00+00:00',
  ends_at: '2026-11-01T15:00:00+00:00', started, ended });
// One assigned booking as the tutor API answers it (backend bookings.tutor_bookings): the child and the slot only,
// started by its tutor unless a test says otherwise -- a report follows the tutor's own Start.
const STARTED = { activity_state: 'IN_PROGRESS', started_at: '2026-11-01T14:02:00+00:00', start_opens_at: '2026-11-01T13:55:00+00:00',
  actions: { start: false }, start_refusal: { code: 'BOOKING_STARTED', message: 'This booking has already started.' } };
const NOT_STARTED = { started_at: null, actions: { start: false } };
const assigned = (id, type, extra = {}) => ({ id, booking_type: type, status: 'BOOKED', slot: slotOf(true, false),
  student_name: 'Riya', grade: 'Class 8', syllabus: 'CBSE', school_name: 'Delhi Private School',
  country: 'United Arab Emirates', has_report: false, report_version: null, report_due: false, timezone: 'Asia/Kolkata',
  ...STARTED, ...extra });
const DIAG = assigned('b-1', 'DIAGNOSTIC');
const DEMO_DUE = assigned('b-3', 'DEMO', { slot: slotOf(true, true), report_due: true });
const DEMO_DONE = assigned('b-2', 'DEMO', { status: 'COMPLETED', slot: slotOf(true, true), has_report: true, report_version: 2,
  activity_state: 'COMPLETED', start_refusal: { code: 'BOOKING_COMPLETED', message: 'This booking is already completed.' } });
const tutorAt = (booking, rest = '') => `/api/tutor/bookings/${booking.booking_type.toLowerCase()}/${booking.id}/${rest}`;
const pageOf = (booking) => `/my-bookings/${booking.booking_type.toLowerCase()}/${booking.id}/report`;
const NO_REPORT = () => fail(404, { error: 'NO_REPORT', message: 'This booking has no report yet.' });
// What the administrators' API carries and the tutor's never sends: were it ever to arrive, none of it shows.
const LEAK = { parent_name: 'Asha Nair', phone: '+971 501234567', bde: { id: 'bde-1', full_name: 'Bde One' },
  lead: { id: 'lead-1', phone_number: '501234567', owner_bde: { full_name: 'Bde Two' } } };
const LEAKED_TEXT = ['Asha Nair', '501234567', '+971', 'Bde One', 'Bde Two'];

const DIAG_FIELDS = { score: 18, max_score: 25, performance_level: 'GOOD', strength_areas: ['Fractions', 'Place value'],
  skills_to_strengthen: ['Word problems'], teacher_remarks: 'Works carefully.\nChecks each step.',
  suggested_plan: 'The plan is:\n30 Days Foundation Plan' };
const DEMO_V1 = { assessment_review: 'Scored 9 out of 12.', class_observation_review: 'Attentive.', suggested_strategy: 'Timed practice.' };
const DEMO_V2 = { ...DEMO_V1, suggested_strategy: 'Timed practice, twice a week.' };
const DEMO_V3 = { ...DEMO_V2, class_observation_review: 'Attentive and quick.' };
const savedReport = (booking, version, fields) => ({ id: `r-${booking.id}`, booking_id: booking.id, booking_type: booking.booking_type,
  version, fields, student_name: 'Riya', grade: '8', tutor_name: 'Tutor Anu', submitted_at: '2026-11-01T15:10:00+00:00',
  updated_at: `2026-11-01T15:1${version}:00+00:00` });
const revision = (version, fields, changed) => ({ version, changed_fields: changed, edited_at: `2026-11-01T15:1${version}:00+00:00`,
  edited_by: { id: 'tutor-anu', name: 'Tutor Anu' }, fields, student_name: 'Riya', grade: '8', tutor_name: 'Tutor Anu' });
const revisions = (rows) => ({ results: rows, count: rows.length, version: rows.at(-1).version });
const completed = (booking) => ({ id: booking.id, booking_type: booking.booking_type, status: 'COMPLETED', completed_at: '2026-11-01T15:10:00+00:00' });

const field = (name) => document.getElementById(reports.reportFieldId(name));
const errorOf = (name) => clean(document.getElementById(`${reports.reportFieldId(name)}-error`)?.textContent ?? '');
const form = () => document.getElementById('report-form');
const submitForm = () => fire(form(), new window.Event('submit', { bubbles: true, cancelable: true }));
const notice = () => clean(document.querySelector('[role="status"], [role="alert"]')?.textContent ?? '');
const pageText = () => clean(document.body.textContent);

async function openPage(path) {
  const page = await mountPage(path, TUTOR);
  mounted.push(page);
  await settle();
  return page;
}

async function fillDiagnostic(values = DIAG_FIELDS) {
  await typeText(field('score'), String(values.score));
  await typeText(field('max_score'), String(values.max_score));
  await choose('Performance level', reports.performanceLevelLabel(values.performance_level));
  for (const name of ['strength_areas', 'skills_to_strengthen']) {
    for (const [index, item] of values[name].entries()) {
      if (index) await click(button('Add item', field(name)));
      await typeText(rowsOf(field(name))[index], item);
    }
  }
  await typeText(field('teacher_remarks'), values.teacher_remarks);
  await typeText(field('suggested_plan'), values.suggested_plan);
}

async function fillDemo(values = DEMO_V1) {
  for (const [name, value] of Object.entries(values)) await typeText(field(name), value);
}

test('the report page: a first Diagnostic report -- its printed details filled in, every field, confirmed, then version 1', async () => {
  serve({
    [`GET ${tutorAt(DIAG)}`]: { ...DIAG, ...LEAK },
    [`GET ${tutorAt(DIAG, 'report/')}`]: NO_REPORT,
    [`POST ${tutorAt(DIAG, 'report/')}`]: (entry) => ok({ report: savedReport(DIAG, 1, entry.data), booking: completed(DIAG) }),
    [`GET ${tutorAt(DIAG, 'report/revisions/')}`]: revisions([revision(1, DIAG_FIELDS, reports.REPORT_FIELDS.DIAGNOSTIC)]),
  });
  await openPage(pageOf(DIAG));
  assert.equal(clean(document.querySelector('h1').textContent), 'Diagnostic results');
  for (const part of ['Student nameRiya', 'ClassClass 8', 'SubjectMathematics', 'Assessment typeDiagnostic Test', 'Tutor nameTutor Anu']) {
    assert.ok(pageText().includes(part), `missing ${part}`);
  }
  for (const value of LEAKED_TEXT) assert.ok(!pageText().includes(value), `${value} is not rendered`);
  assert.equal(clean(document.querySelector('[data-slot="badge"][data-variant="info"]')?.textContent), 'In progress');
  assert.ok(!pageText().includes('Saved results'), 'no saved report yet');

  await fillDiagnostic();
  assert.ok(pageText().includes('Unsaved changes'));
  await submitForm();
  // First the confirm step; nothing sent yet.
  assert.match(clean(topDialog().textContent), /Submit results\?Below is the report as it will print\. Submitting completes this booking\. You can still edit it later/);
  assert.equal(calls('POST').length, 0);
  await click(button('Submit results', topDialog()));
  assert.equal(calls('POST').length, 1);
  assert.deepEqual(calls('POST')[0].data, DIAG_FIELDS, 'exactly the fields the tutor writes, never a printed one');

  assert.match(notice(), /Results submitted\. The booking is now completed, and you can still edit the results\./);
  assert.equal(clean(document.querySelector('[data-slot="badge"][data-variant="secondary"]')?.textContent), 'Completed');
  assert.ok(button('Save changes').disabled, 'nothing to save until something changes');
  assert.ok(pageText().includes('Version 1 is the current one.'));
  assert.match(pageText(), /Version 1 · currentSaved .* by Tutor AnuFirst version/);
  assert.ok(!globalThis.__reportsApi.calls.some((entry) => entry.url.startsWith('/api/bookings/')), "the administrators' API is never called");
});

test('the report page: a booking without a report is never asked for one -- no 404 for the browser to log', async () => {
  globalThis.__reportsApi.calls = [];
  serve({ [`GET ${tutorAt(DIAG)}`]: DIAG, [`GET ${tutorAt(DIAG, 'report/')}`]: NO_REPORT });
  let page = await openPage(pageOf(DIAG));
  assert.equal(calls('GET', tutorAt(DIAG, 'report/')).length, 0, 'has_report is false: nothing to read');
  assert.ok(form(), 'the form for a first report');
  assert.equal(field('teacher_remarks').value, '');
  await page.unmount();

  // Should a NO_REPORT come all the same, it reads as no report yet -- not as a failure or a missing booking.
  globalThis.__reportsApi.calls = [];
  serve({ [`GET ${tutorAt(DEMO_DONE)}`]: DEMO_DONE, [`GET ${tutorAt(DEMO_DONE, 'report/')}`]: NO_REPORT });
  page = await openPage(pageOf(DEMO_DONE));
  assert.equal(calls('GET', tutorAt(DEMO_DONE, 'report/')).length, 1, 'has_report is true: read');
  for (const text of ['Could not load this report.', 'Booking not found', 'Try again']) {
    assert.ok(!pageText().includes(text), `no "${text}"`);
  }
  assert.ok(!pageText().includes('Saved feedback'));
  await page.unmount();
});

test('the report page: a first Demo report has its own three fields, no score and no assessment type', async () => {
  serve({
    [`GET ${tutorAt(DEMO_DUE)}`]: DEMO_DUE,
    [`GET ${tutorAt(DEMO_DUE, 'report/')}`]: NO_REPORT,
    [`POST ${tutorAt(DEMO_DUE, 'report/')}`]: (entry) => ok({ report: savedReport(DEMO_DUE, 1, entry.data), booking: completed(DEMO_DUE) }),
    [`GET ${tutorAt(DEMO_DUE, 'report/revisions/')}`]: revisions([revision(1, DEMO_V1, reports.REPORT_FIELDS.DEMO)]),
  });
  await openPage(pageOf(DEMO_DUE));
  assert.equal(clean(document.querySelector('h1').textContent), 'Demo feedback');
  assert.ok(pageText().includes('Report due'));
  assert.equal(field('score'), null);
  assert.ok(!pageText().includes('Assessment type'));
  assert.deepEqual(['assessment_review', 'class_observation_review', 'suggested_strategy'].map((name) => field(name)?.maxLength),
    [1200, 1200, 1200]);
  await fillDemo();
  await submitForm();
  await click(button('Submit feedback', topDialog()));
  assert.deepEqual(calls('POST', tutorAt(DEMO_DUE, 'report/'))[0].data, DEMO_V1);
  assert.ok(pageText().includes('Version 1 is the current one.'));
});

test('the report page: nothing is sent while a field breaks a rule -- each problem on its field, the first focused', async () => {
  serve({
    [`GET ${tutorAt(DIAG)}`]: DIAG,
    [`GET ${tutorAt(DIAG, 'report/')}`]: NO_REPORT,
    [`POST ${tutorAt(DIAG, 'report/')}`]: () => fail(400, { error: 'VALIDATION_ERROR', message: 'Check the report.',
      fields: { teacher_remarks: ['Use at most 2000 characters.'] } }),
  });
  await openPage(pageOf(DIAG));
  assert.equal(clean(document.getElementById('report-teacher-remarks-count').textContent), '0/2000 characters');
  assert.deepEqual([field('teacher_remarks').maxLength, field('suggested_plan').maxLength], [2000, 1000]);

  await submitForm();
  assert.equal(calls('POST').length, 0, 'nothing sent');
  assert.equal(topDialog(), undefined, 'no confirm step');
  assert.match(notice(), /Some fields need attention\. They are marked below\./);
  assert.deepEqual(['score', 'max_score', 'performance_level', 'strength_areas', 'skills_to_strengthen', 'teacher_remarks',
    'suggested_plan'].map(errorOf), ['This field is required.', 'This field is required.', 'This field is required.',
    'List 1 to 15 items.', 'List 1 to 15 items.', 'This field is required.', 'This field is required.']);
  assert.equal(document.activeElement?.id, field('score').id, 'the first problem has the focus');
  assert.equal(field('score').getAttribute('aria-invalid'), 'true');

  await fillDiagnostic({ ...DIAG_FIELDS, score: 30 });
  assert.equal(errorOf('score'), 'The score cannot be more than the maximum score.');
  await typeText(field('score'), '1.5');
  assert.equal(errorOf('score'), 'Enter a whole number.');
  await typeText(field('score'), '18');
  assert.equal(errorOf('score'), '');

  // What only the API knows, shown on its field; typing there clears it.
  await submitForm();
  await click(button('Submit results', topDialog()));
  assert.equal(errorOf('teacher_remarks'), 'Use at most 2000 characters.');
  assert.equal(document.activeElement?.id, field('teacher_remarks').id, 'the refused field has the focus');
  await typeText(field('teacher_remarks'), 'Shorter remarks.');
  assert.equal(errorOf('teacher_remarks'), '');
});

test('the report page: an edit loads the saved report, saves a new version, and every version shows with its PDF', async () => {
  let history = [revision(1, DEMO_V1, reports.REPORT_FIELDS.DEMO), revision(2, DEMO_V2, ['suggested_strategy'])];
  serve({
    [`GET ${tutorAt(DEMO_DONE)}`]: DEMO_DONE,
    [`GET ${tutorAt(DEMO_DONE, 'report/')}`]: savedReport(DEMO_DONE, 2, DEMO_V2),
    [`GET ${tutorAt(DEMO_DONE, 'report/revisions/')}`]: () => ok(revisions(history)),
    [`PUT ${tutorAt(DEMO_DONE, 'report/')}`]: (entry) => {
      history = [...history, revision(3, DEMO_V3, ['class_observation_review'])];
      const { version: _version, ...fields } = entry.data;
      return ok({ report: savedReport(DEMO_DONE, 3, fields), booking: completed(DEMO_DONE), changed: true });
    },
    [`GET ${tutorAt(DEMO_DONE, 'report/revisions/1/pdf/')}`]: () => ok(new Blob(['%PDF-1.7']),
      { 'content-disposition': 'attachment; filename="Demo-Report-Riya-2026-11-01-v1.pdf"' }),
    [`GET ${tutorAt(DEMO_DONE, 'report/pdf/')}`]: () => ok(new Blob(['%PDF-1.7']),
      { 'content-disposition': 'attachment; filename="Demo-Report-Riya-2026-11-01.pdf"' }),
  });
  await openPage(pageOf(DEMO_DONE));
  assert.equal(field('suggested_strategy').value, DEMO_V2.suggested_strategy, 'the saved report is in the form');
  assert.ok(button('Save changes').disabled);
  assert.ok(!pageText().includes('Unsaved changes'));
  const versionRows = () => [...document.querySelectorAll('ol > li')].map((li) => clean(li.querySelector('div').textContent));
  assert.deepEqual(versionRows().map((row) => row.replace(/Saved .* by Tutor Anu/, '')),
    ['Version 2 · currentChanged: Suggested strategyShowPDF', 'Version 1First versionShowPDF']);

  // An earlier version, as it was saved, and its own PDF.
  await click(button('Show version 1'));
  assert.ok(pageText().includes(DEMO_V1.suggested_strategy));
  await click(button('PDF of version 1'));
  const pdf = calls('GET', tutorAt(DEMO_DONE, 'report/revisions/1/pdf/'));
  assert.equal(pdf.length, 1);
  assert.equal(pdf[0].responseType, 'blob');
  assert.equal(saved.at(-1).name, 'Demo-Report-Riya-2026-11-01-v1.pdf');

  // An edit: no confirm step, the version it was made from, and the next version.
  await typeText(field('class_observation_review'), DEMO_V3.class_observation_review);
  assert.ok(pageText().includes('Unsaved changes'));
  await submitForm();
  assert.equal(topDialog(), undefined, 'editing needs no confirm');
  assert.deepEqual(calls('PUT')[0].data, { version: 2, ...DEMO_V3 });
  assert.match(notice(), /Changes saved as version 3\./);
  assert.ok(button('Save changes').disabled);
  assert.equal(calls('GET', tutorAt(DEMO_DONE, 'report/revisions/')).length, 2, 'the versions are read again');
  assert.equal(versionRows()[0].replace(/Saved .* by Tutor Anu/, ''), 'Version 3 · currentChanged: Class observation reviewShowPDF');
  assert.equal(versionRows().length, 3, 'earlier versions are kept');

  await click(button('Download PDF'));
  assert.equal(saved.at(-1).name, 'Demo-Report-Riya-2026-11-01.pdf');
});

test('the report page: Preview PDF shows the unsaved form as its PDF from the preview route, and saves nothing', async () => {
  let answer = () => ok(new Blob(['%PDF-1.7']), { 'content-disposition': 'inline; filename="Diagnostic-Report-Riya-2026-11-01-preview.pdf"' });
  serve({
    [`GET ${tutorAt(DIAG)}`]: DIAG,
    [`GET ${tutorAt(DIAG, 'report/')}`]: NO_REPORT,
    [`POST ${tutorAt(DIAG, 'report/preview/')}`]: (entry) => answer(entry),
  });
  await openPage(pageOf(DIAG));
  await click(button('Preview PDF'));
  assert.equal(calls('POST').length, 0, 'an incomplete form is not previewed');
  assert.match(notice(), /Some fields need attention/);

  await fillDiagnostic();
  await click(button('Preview PDF'));
  const [request] = calls('POST', tutorAt(DIAG, 'report/preview/'));
  assert.deepEqual([request.data, request.responseType], [DIAG_FIELDS, 'blob']);
  assert.equal(calls('POST', tutorAt(DIAG, 'report/')).length, 0, 'nothing submitted');
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /Report previewThis is how the report will print\. Nothing has been saved\./);
  const frame = dialog.querySelector('iframe');
  assert.match(frame.getAttribute('src'), /^blob:test\//);
  assert.equal(dialog.querySelector('a').getAttribute('href'), frame.getAttribute('src'));
  const url = frame.getAttribute('src');
  await click(button('Close', dialog));
  assert.ok(revoked.includes(url), 'the preview is freed once closed');
  assert.ok(pageText().includes('Unsaved changes'), 'the form is still unsaved');

  // Refused as a save would be: on the field, or in plain words.
  answer = () => fail(400, blobOf({ error: 'VALIDATION_ERROR', fields: { suggested_plan: ['Use at most 1000 characters.'] } }));
  await click(button('Preview PDF'));
  assert.equal(errorOf('suggested_plan'), 'Use at most 1000 characters.');
  answer = () => fail(429, blobOf({ detail: 'Request was throttled. Expected available in 20 seconds.' }));
  await click(button('Preview PDF'));
  assert.match(notice(), /Too many downloads in a short time\. Try again in 20 seconds\./);
});

test('the report page: unsaved changes -- memory only; reload or close warns; Cancel and Back ask before discarding', async () => {
  const stored = [];
  const setItem = window.Storage.prototype.setItem;
  window.Storage.prototype.setItem = function record(key, value) {
    stored.push(key);
    return setItem.call(this, key, value);
  };
  try {
    serve({ [`GET ${tutorAt(DIAG)}`]: DIAG, [`GET ${tutorAt(DIAG, 'report/')}`]: NO_REPORT });
    const leaving = () => {
      const event = new window.Event('beforeunload', { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    let page = await openPage(pageOf(DIAG));
    assert.equal(leaving(), false, 'nothing to lose yet');
    await click(button('Cancel'));
    assert.equal(page.location().pathname, '/my-bookings/diagnostic/b-1', 'a clean form leaves at once');
    assert.equal(page.location().search, '?tab=feedback', 'back to the booking, on its feedback');
    await page.unmount();

    page = await openPage(pageOf(DIAG));
    await typeText(field('teacher_remarks'), 'Half-written remarks.');
    assert.equal(leaving(), true, 'reload or close warns');
    await click(button('Cancel'));
    assert.match(clean(topDialog().textContent), /Discard your changes\?Your changes to this report have not been saved\./);
    await click(button('Keep editing', topDialog()));
    assert.equal(page.location().pathname, pageOf(DIAG));
    assert.equal(field('teacher_remarks').value, 'Half-written remarks.');
    await click(button('Back to booking'));
    await click(button('Discard changes', topDialog()));
    assert.equal(page.location().pathname, '/my-bookings/diagnostic/b-1');
    assert.equal(leaving(), false, 'no warning once the page is gone');
    assert.deepEqual(stored, [], 'nothing typed is kept in browser storage');
    assert.equal(window.localStorage.length + window.sessionStorage.length, 0);
  } finally {
    window.Storage.prototype.setItem = setItem;
  }
});

test('the report page: unsaved changes -- a link to another page of the Hub asks first, then goes where it pointed', async () => {
  serve({ [`GET ${tutorAt(DIAG)}`]: DIAG, [`GET ${tutorAt(DIAG, 'report/')}`]: NO_REPORT });
  // Links as the sidebar and the breadcrumbs render them; a click that gets past the page is counted (and
  // stopped there: jsdom cannot navigate).
  const link = (href, attributes = {}) => {
    const anchor = document.createElement('a');
    anchor.href = href;
    for (const [name, value] of Object.entries(attributes)) anchor.setAttribute(name, value);
    document.body.appendChild(anchor);
    return anchor;
  };
  const passed = [];
  const count = (event) => {
    if (event.target.tagName !== 'A') return;
    passed.push(event.target.getAttribute('href'));
    event.preventDefault();
  };
  document.addEventListener('click', count);
  try {
    const page = await openPage(pageOf(DIAG));
    const sidebar = link('/my-bookings?from=sidebar');
    await click(sidebar);
    assert.deepEqual(passed, ['/my-bookings?from=sidebar'], 'a clean form lets a link through');
    passed.length = 0;

    await typeText(field('teacher_remarks'), 'Half-written remarks.');
    await click(sidebar);
    assert.deepEqual(passed, [], 'held before the router hears of it');
    assert.match(clean(topDialog().textContent), /Discard your changes\?Your changes to this report have not been saved\./);
    await click(button('Keep editing', topDialog()));
    assert.equal(page.location().pathname, pageOf(DIAG));
    assert.equal(field('teacher_remarks').value, 'Half-written remarks.');

    // A new tab or window, or a download, leaves nothing behind.
    await click(link('/my-bookings?tab', { target: '_blank' }));
    await click(link('/files/report.pdf', { download: '' }));
    await fire(sidebar, new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ctrlKey: true }));
    assert.deepEqual(passed, ['/my-bookings?tab', '/files/report.pdf', '/my-bookings?from=sidebar']);
    assert.equal(topDialog(), undefined);

    await click(sidebar);
    await click(button('Discard changes', topDialog()));
    assert.equal(`${page.location().pathname}${page.location().search}`, '/my-bookings?from=sidebar');
  } finally {
    document.removeEventListener('click', count);
    for (const anchor of document.querySelectorAll('body > a')) anchor.remove();
  }
});

test('the report page: unsaved changes -- logging out asks first; with nothing to lose it logs out at once', async () => {
  serve({ [`GET ${tutorAt(DIAG)}`]: DIAG });
  let loggedOut = 0;
  const logout = () => {
    loggedOut += 1;
  };
  const leave = async () => {
    await act(async () => confirmLeave(logout));
    await settle();
  };
  const page = await openPage(pageOf(DIAG));
  await leave();
  assert.equal(loggedOut, 1, 'a clean form: at once');

  await typeText(field('teacher_remarks'), 'Half-written remarks.');
  await leave();
  assert.equal(loggedOut, 1, 'held');
  assert.match(clean(topDialog().textContent), /Discard your changes\?Your changes to this report have not been saved\./);
  await click(button('Keep editing', topDialog()));
  assert.equal(loggedOut, 1, 'still signed in');
  assert.equal(field('teacher_remarks').value, 'Half-written remarks.');
  await leave();
  await click(button('Discard changes', topDialog()));
  assert.equal(loggedOut, 2, 'then logs out');

  await page.unmount();
  await leave();
  assert.equal(loggedOut, 3, 'no page holding the way out: at once');
});

test("the report page: unsaved changes -- the browser's Back and Forward ask first, and the page stays where it was", async () => {
  serve({ [`GET ${tutorAt(DIAG)}`]: DIAG, [`GET ${tutorAt(DIAG, 'report/')}`]: NO_REPORT });
  // The entries as App.jsx's BrowserRouter numbers them (history.state.idx), the report page between My Bookings
  // and a later page. The router's listener is added after installLeaveGuard's, as main.jsx has it: at the window,
  // listeners run in the order they were added (Chrome does not run capturing ones first there).
  const heard = [];
  const router = (event) => heard.push(event.state?.idx);
  window.addEventListener('popstate', router);
  const travel = async (step) => {
    step();
    await settle(12);
  };
  try {
    window.history.replaceState({ idx: 0 }, '', '/my-bookings');
    window.history.pushState({ idx: 1 }, '', pageOf(DIAG));
    window.history.pushState({ idx: 2 }, '', '/my-bookings?later');
    await travel(() => window.history.back());
    heard.length = 0;
    await openPage(pageOf(DIAG));
    await travel(() => window.history.back());
    assert.deepEqual(heard, [0], 'a clean form lets Back through');
    await travel(() => window.history.forward());
    heard.length = 0;

    await typeText(field('teacher_remarks'), 'Half-written remarks.');
    for (const [step, label] of [[() => window.history.back(), 'Back'], [() => window.history.forward(), 'Forward']]) {
      await travel(step);
      assert.deepEqual(heard, [], `${label}: the router never hears of it`);
      assert.deepEqual([window.history.state?.idx, window.location.pathname], [1, pageOf(DIAG)], `${label}: still here`);
      assert.match(clean(topDialog().textContent), /Discard your changes\?/);
      await click(button('Keep editing', topDialog()));
      assert.equal(field('teacher_remarks').value, 'Half-written remarks.');
    }

    await travel(() => window.history.back());
    await click(button('Discard changes', topDialog()));
    await settle(12);
    assert.deepEqual(heard, [0], 'then the step back reaches the router');
    assert.equal(window.location.pathname, '/my-bookings');
    // The page is still on screen here, as it can be for a moment in the browser: the text went at Discard.
    assert.equal(field('teacher_remarks').value, '', 'discarded at once');
    assert.ok(!pageText().includes('Unsaved changes'));
  } finally {
    window.removeEventListener('popstate', router);
    window.history.replaceState(null, '', '/');
  }
});

test('the report page: unsaved changes -- discarding clears the form at once, so leaving and coming straight back shows none of it', async () => {
  serve({ [`GET ${tutorAt(DIAG)}`]: DIAG });
  const page = await openPage(pageOf(DIAG));
  // A link to this same page: after Discard the page stays on screen, as it does in the browser when Back or
  // Forward comes before the next page has rendered -- the case where the discarded text used to come back.
  const again = document.createElement('a');
  again.href = `${pageOf(DIAG)}?again=1`;
  again.addEventListener('click', (event) => event.preventDefault()); // jsdom cannot navigate; the router would
  document.body.appendChild(again);
  try {
    await typeText(field('teacher_remarks'), 'Half-written remarks.');
    await submitForm();
    assert.match(notice(), /Some fields need attention/);
    await click(again);
    await click(button('Discard changes', topDialog()));
    assert.equal(`${page.location().pathname}${page.location().search}`, `${pageOf(DIAG)}?again=1`, 'left as the link said');
    assert.equal(field('teacher_remarks').value, '', 'the discarded text is gone');
    assert.ok(!pageText().includes('Unsaved changes'), 'nothing unsaved');
    assert.equal(notice(), '', 'nor the earlier notice');
    assert.ok(!pageText().includes('This field is required.'), 'nor its marks on the empty form');
    await click(again);
    assert.equal(topDialog(), undefined, 'a clean form lets the next link through');
  } finally {
    again.remove();
  }
});

test('the report page: refusals -- submitted elsewhere, saved elsewhere, no longer assigned, busy, cancelled', async () => {
  // Submitted in another tab: the saved report becomes the one edited, and the typed text stays.
  let report = NO_REPORT;
  serve({
    [`GET ${tutorAt(DIAG)}`]: DIAG,
    [`GET ${tutorAt(DIAG, 'report/')}`]: () => (typeof report === 'function' ? report() : ok(report)),
    [`POST ${tutorAt(DIAG, 'report/')}`]: () => {
      report = savedReport(DIAG, 1, { ...DIAG_FIELDS, teacher_remarks: 'From the other tab.' });
      return fail(409, { error: 'REPORT_EXISTS', message: 'This booking already has its report.', version: 1 });
    },
  });
  let page = await openPage(pageOf(DIAG));
  await fillDiagnostic();
  await submitForm();
  await click(button('Submit results', topDialog()));
  assert.match(notice(), /This report was already submitted \(version 1\)\. Your text is still below: review it and save it as an edit\./);
  assert.equal(field('teacher_remarks').value, DIAG_FIELDS.teacher_remarks);
  assert.ok(button('Save changes') && !button('Save changes').disabled, 'saved as an edit from here');
  await page.unmount();

  // Saved elsewhere since this page loaded: reloading replaces the form, after asking.
  let latest = savedReport(DEMO_DONE, 2, DEMO_V2);
  let put = () => fail(409, { error: 'REPORT_VERSION_CONFLICT', message: 'The report has changed.', version: 3 });
  serve({
    [`GET ${tutorAt(DEMO_DONE)}`]: DEMO_DONE,
    [`GET ${tutorAt(DEMO_DONE, 'report/')}`]: () => ok(latest),
    [`GET ${tutorAt(DEMO_DONE, 'report/revisions/')}`]: revisions([revision(1, DEMO_V1, []), revision(2, DEMO_V2, [])]),
    [`PUT ${tutorAt(DEMO_DONE, 'report/')}`]: () => put(),
  });
  page = await openPage(pageOf(DEMO_DONE));
  await typeText(field('suggested_strategy'), 'Mine.');
  latest = savedReport(DEMO_DONE, 3, DEMO_V3);
  await submitForm();
  assert.match(notice(), /saved somewhere else and is now version 3\. Reload to see that version/);
  await click(button('Reload the latest version'));
  await click(button('Reload', topDialog()));
  assert.equal(field('class_observation_review').value, DEMO_V3.class_observation_review, 'the latest version is in the form');
  assert.ok(button('Save changes').disabled);

  // Busy: said, and the form stays for another try. No longer assigned: the form closes.
  await typeText(field('suggested_strategy'), 'Mine again.');
  put = () => fail(503, { error: 'REPORT_BUSY', message: 'Busy.' });
  await submitForm();
  assert.match(notice(), /being saved somewhere else right now\. Try again in a moment\./);
  assert.ok(!document.querySelector('#report-form fieldset').disabled);
  put = () => fail(404, { error: 'NOT_FOUND', message: 'No such booking.' });
  await submitForm();
  assert.match(notice(), /no longer assigned to you, so the report cannot be saved\./);
  assert.ok(document.querySelector('#report-form fieldset').disabled);
  await page.unmount();

  // Cancelled meanwhile: said, and the booking read again.
  globalThis.__reportsApi.calls = [];
  let booking = DIAG;
  serve({
    [`GET ${tutorAt(DIAG)}`]: () => ok(booking),
    [`GET ${tutorAt(DIAG, 'report/')}`]: NO_REPORT,
    [`POST ${tutorAt(DIAG, 'report/')}`]: () => {
      booking = { ...DIAG, status: 'CANCELLED' };
      return fail(409, { error: 'BOOKING_CANCELLED', message: 'Cancelled.' });
    },
  });
  await openPage(pageOf(DIAG));
  await fillDiagnostic();
  await submitForm();
  await click(button('Submit results', topDialog()));
  assert.match(notice(), /This booking was cancelled, so the report cannot be saved\./);
  assert.equal(calls('GET', tutorAt(DIAG)).length, 2);
  assert.ok(pageText().includes('This booking was cancelled, so there is no report to write.'));
  assert.equal(form(), null);
});

test('the report page: a booking not started yet offers Start, confirmed first; once started the form opens', async () => {
  const ready = assigned('b-9', 'DEMO', { slot: slotOf(false, false), activity_state: 'READY', ...NOT_STARTED,
    actions: { start: true }, start_refusal: null });
  serve({
    [`GET ${tutorAt(ready)}`]: ready,
    [`POST ${tutorAt(ready, 'start/')}`]: () => ok({ booking: { ...ready, ...STARTED }, changed: true }),
  });
  const page = await openPage(pageOf(ready));
  assert.ok(pageText().includes('Start the class to write its report.'));
  assert.equal(form(), null, 'no form before the start');
  await click(button('Start Demo for Riya'));
  assert.match(clean(topDialog().textContent), /^Start Demo\?.*It cannot be undone\./);
  await click(button('Start Demo', topDialog()));
  assert.equal(calls('POST', tutorAt(ready, 'start/')).length, 1);
  assert.ok(form(), 'the form for a first report, once started');
  assert.equal(button('Start Demo for Riya'), undefined);
  assert.equal(calls('POST', tutorAt(ready, 'report/')).length, 0, 'starting writes no report');
  await page.unmount();
});

test('the report page: a booking not assigned, a mistyped link, a class not started, a cancelled booking, a load error', async () => {
  serve({
    [`GET ${tutorAt(DIAG)}`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such booking.' }),
    [`GET ${tutorAt(DIAG, 'report/')}`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such booking.' }),
  });
  let page = await openPage(pageOf(DIAG));
  assert.match(pageText(), /Booking not found.*It may no longer be assigned to you/);
  await click(button('Go to Diagnostic Bookings'));
  assert.equal(page.location().pathname, '/my-bookings/diagnostic');
  await page.unmount();

  globalThis.__reportsApi.calls = [];
  page = await openPage('/my-bookings/webinar/b-1/report');
  assert.match(pageText(), /Booking not found/);
  assert.equal(globalThis.__reportsApi.calls.length, 0, 'a link naming no booking type asks the API nothing');
  await page.unmount();

  for (const [booking, says] of [
    [assigned('b-4', 'DEMO', { slot: slotOf(false, false), activity_state: 'UPCOMING', ...NOT_STARTED,
      start_refusal: { code: 'START_TOO_EARLY', message: 'A booking can be started from 5 minutes before its scheduled time.' } }),
    'You can write the report once you start the class.'],
    // Its scheduled time has passed, or its slot is over, with no start: still no form.
    [assigned('b-7', 'DEMO', { activity_state: 'LATE', ...NOT_STARTED }),
      'The scheduled time has passed. Start the class to write its report.'],
    [assigned('b-8', 'DEMO', { slot: slotOf(true, true), activity_state: 'NOT_STARTED', ...NOT_STARTED }),
      'The slot ended without the class being started, so no report can be written.'],
    [assigned('b-5', 'DIAGNOSTIC', { status: 'CANCELLED' }), 'This booking was cancelled, so there is no report to write.'],
    [assigned('b-6', 'DEMO', { status: 'RESCHEDULED' }), 'This booking was moved to another slot. Write the report on the new booking.'],
  ]) {
    serve({ [`GET ${tutorAt(booking)}`]: booking, [`GET ${tutorAt(booking, 'report/')}`]: NO_REPORT });
    page = await openPage(pageOf(booking));
    assert.ok(pageText().includes(says), says);
    assert.equal(form(), null, 'no form');
    assert.equal(button('Preview PDF'), undefined);
    await page.unmount();
  }

  let attempts = 0;
  serve({
    [`GET ${tutorAt(DIAG)}`]: () => (attempts++ === 0 ? fail(500, { message: 'The server had a problem.' }) : ok(DIAG)),
    [`GET ${tutorAt(DIAG, 'report/')}`]: NO_REPORT,
  });
  await openPage(pageOf(DIAG));
  assert.match(pageText(), /The server had a problem\./);
  await click(button('Try again'));
  assert.ok(form(), 'loaded on the second try');
});

// ------------------------------------------------------------------ run
// TEST_ONLY=<words> runs only the tests whose names hold them.
const only = process.env.TEST_ONLY;
let failed = 0;
for (const { name, fn } of tests.filter((entry) => !only || entry.name.includes(only))) {
  globalThis.__reportsApi = { calls: [], handler: () => fail(404, { message: 'No handler' }) };
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
const ran = only ? tests.filter((entry) => entry.name.includes(only)).length : tests.length;
console.log(`${ran - failed}/${ran} report tests passed.`);
window.close();
process.exit(failed ? 1 : 0);
