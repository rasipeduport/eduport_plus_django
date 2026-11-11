// Sales Management tests: the real Syllabus & Plans and Global Pricing pages
// (src/pages/SalesSyllabiPage.jsx, SalesSyllabusPage.jsx,
// SalesSyllabusEditorPage.jsx, SalesPricingPage.jsx) in jsdom, their API
// answered per test by api-stub.js -- an administrator listing and filtering
// syllabuses, writing one as a draft with its chapters and plan types,
// previewing its PDF, publishing it only on confirmation, editing a
// published one through a new draft, and changing the global pricing -- and
// the package prices the editor works out, which must equal the API's
// (backend sales.pricing) to the last fil.
//
//   npm run test:sales
//
// Which callers the Hub routes to each page across the whole Hub is the access
// tests' job (tests/access, paths /sales-syllabus and /sales-pricing).
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
const bundle = path.join(tmpdir(), `hub-sales-${process.pid}.mjs`);
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

const harness = await import(pathToFileURL(bundle).href);
const { mount, act, canOpenPage } = harness;

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
const keyDown = (element, key) => fire(element, new window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));

async function typeInto(input, value) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
}

function button(label, root = document.body) {
  return [...root.querySelectorAll('button')].find(
    (element) => clean(element.textContent) === label || element.getAttribute('aria-label') === label
  );
}

const topDialog = () => [...document.querySelectorAll('[role="dialog"]')].at(-1);

/** Pick `option` from the Radix Select labelled `label`, as the keyboard would open it. */
async function choose(label, option) {
  const trigger = document.querySelector(`[aria-label="${label}"]`) ?? document.getElementById(label);
  assert.ok(trigger, `no select labelled ${label}`);
  trigger.focus();
  await keyDown(trigger, 'Enter');
  const item = [...document.querySelectorAll('[role="option"]')].find((element) => clean(element.textContent) === option);
  assert.ok(item, `no option ${option} in ${label}`);
  await click(item);
}

const rows = () => [...document.querySelectorAll('tbody tr')];
const headers = () => [...document.querySelectorAll('th')].map((th) => clean(th.textContent));
const link = (text) => [...document.querySelectorAll('a')].find((a) => clean(a.textContent) === text);

const mounted = [];
async function open(at, user, options) {
  const page = await mount(at, user, options);
  mounted.push(page);
  return page;
}

// ------------------------------------------------------------------ the API
const ok = (data) => Promise.resolve({ status: 200, data });
const fail = (status, data) => Promise.reject(Object.assign(new Error(`HTTP ${status}`), { response: { status, data } }));

/** Answers keyed "METHOD url"; a value is the body, a function is called with the request. */
function serve(table) {
  globalThis.__salesApi.handler = (entry) => {
    const answer = table[`${entry.method} ${entry.url}`];
    if (answer === undefined) return fail(404, { error: 'NOT_FOUND', message: `No answer for ${entry.method} ${entry.url}` });
    return typeof answer === 'function' ? answer(entry) : ok(answer);
  };
}

const calls = (method, url) => globalThis.__salesApi.calls.filter((entry) => entry.method === method && entry.url === url);

// Downloads and previews are object URLs: recorded, nothing navigates.
const saved = [];
let objectUrls = 0;
URL.createObjectURL = () => `blob:test/${objectUrls++}`;
URL.revokeObjectURL = () => {};
window.HTMLAnchorElement.prototype.click = function click() {
  saved.push({ href: this.href, name: this.download });
};

const input = (id) => document.getElementById(id);
const menuItem = (label) => [...document.querySelectorAll('[role="menuitem"]')].find((item) => clean(item.textContent) === label);
async function openMenu(trigger) {
  trigger.focus();
  await keyDown(trigger, 'Enter');
}

// ------------------------------------------------------------------ fixtures
const ADMIN = { id: 'admin', role: 'ADMIN', permissions: ['accounts.manage_sales_pricing', 'accounts.manage_sales_syllabi'] };
const ADMIN_WITHOUT = { id: 'admin-2', role: 'ADMIN', permissions: ['accounts.view_all_leads'] };
const MENTOR = { id: 'mentor', role: 'MENTOR', permissions: ['accounts.view_staff_dashboard'] };
const ROOT_MENTOR = { id: 'root', role: 'MENTOR', is_superuser: true, permissions: ['accounts.manage_sales_pricing', 'accounts.manage_sales_syllabi'] };

const SYLLABI = '/api/sales/syllabi/';
const PRICING_URL = '/api/sales/pricing/';
const ID = '11111111-1111-4111-8111-111111111111';
const COPY_ID = '22222222-2222-4222-8222-222222222222';
const at = (path = '') => `${SYLLABI}${ID}/${path}`;
const ASHA = { id: 'admin', name: 'Asha Admin' };

const PRICING = {
  id: 'p-1', version: 1, currency: 'AED', standard_fee: '45', offer_fee: '35', single_payment_percent: '5',
  single_payment_plan_types: ['REGULAR'], note: 'Current offer', effective_from: '2026-11-09T04:00:00+00:00', created_by: ASHA,
};
const PRICING_ANSWER = { current: PRICING, versions: [{ ...PRICING, effective_until: null }] };

const GRADE_6 = [['Patterns In Mathematics', '4', '2'], ['Lines And Angles', '5', '2'], ['Number Play', '4', '2'],
  ['Data Handling And Presentation', '3', '2'], ['Prime Time', '3', '2'], ['Perimeter And Area', '3', '2'], ['Fractions', '5', '2'],
  ['Playing With Constructions', '4', '2'], ['Symmetry', '2', '1'], ['The Other Side Of Zero', '5', '2']];
const chaptersOf = (rows, prefix) => rows.map(([name, regular, revision], index) => ({
  id: `${prefix}-${index}`, position: index + 1, name, regular_classes: regular, revision_classes: revision, bridge_classes: null,
}));
const PACKAGES = [
  { plan_type: 'REGULAR', title: 'Regular Course Package', classes: '38', fee_per_class: '35', total: '1330', single_payment: { price: '1264', saving: '66' } },
  { plan_type: 'REVISION', title: 'Revision Course (Exam Oriented) Package', classes: '19', fee_per_class: '35', total: '665', single_payment: null },
];

function revision(number, extra = {}) {
  const draft = extra.is_draft ?? false;
  return {
    id: `rev-${number}`, number, is_draft: draft, title: 'Grade 6 CBSE', subtitle: 'Detailed Chapter-Wise 1:1 Learning Plan',
    package_title: 'Grade 6 CBSE – 1:1 Tuition Packages & Fee Details', grade: 6, board: 'CBSE', syllabus_version: 'New Syllabus',
    structure: 'CHAPTER_WISE', plan_types: ['REGULAR', 'REVISION', 'REGULAR_REVISION'],
    inclusions: ['Personalized 1:1 live sessions', 'Structured CBSE aligned learning', 'Dedicated mentor support'],
    chapters: chaptersOf(GRADE_6, `r${number}`), totals: { regular: '38', revision: '19', bridge: '0' }, packages: PACKAGES,
    subtitle_display: 'Detailed Chapter-Wise 1:1 Learning Plan', package_title_display: 'Grade 6 CBSE – 1:1 Tuition Packages & Fee Details',
    created_at: '2026-11-08T04:00:00+00:00', created_by: ASHA, updated_at: `2026-11-09T05:00:0${number}.123456+05:30`, updated_by: ASHA,
    published_at: draft ? null : '2026-11-08T06:00:00+00:00', published_by: draft ? null : ASHA,
    ...extra,
  };
}

function detailOf({ published = null, draft = null, status } = {}) {
  const history = [draft, published].filter(Boolean).map((rev) => ({
    number: rev.number, state: rev.is_draft ? 'DRAFT' : 'PUBLISHED', title: rev.title, created_at: rev.created_at,
    created_by: ASHA, published_at: rev.published_at, published_by: rev.published_by,
  }));
  return {
    id: ID, status: status ?? (published ? 'PUBLISHED' : 'DRAFT'), structure_locked: Boolean(published), reference: null,
    created_at: '2026-11-08T04:00:00+00:00', created_by: ASHA, updated_at: '2026-11-09T05:00:00+00:00', updated_by: ASHA,
    deactivated_at: null, deactivated_by: null, published, draft, history, similar: [], pricing: PRICING,
  };
}

const ROW = {
  id: ID, status: 'PUBLISHED', revision: 1, published_revision: 1, draft_revision: 2, title: 'Grade 6 CBSE', grade: 6, board: 'CBSE',
  syllabus_version: 'New Syllabus', structure: 'CHAPTER_WISE', plan_types: ['REGULAR', 'REVISION', 'REGULAR_REVISION'], chapter_count: 10,
  totals: { regular: '38', revision: '19', bridge: null }, updated_at: '2026-11-09T05:00:00+00:00', updated_by: ASHA,
};
const BRIDGE_ROW = {
  ...ROW, id: COPY_ID, status: 'DRAFT', published_revision: null, draft_revision: 1, title: 'Grade 7 CBSE', grade: 7,
  syllabus_version: '', structure: 'BRIDGE_COURSE', plan_types: ['BRIDGE_COURSE'], chapter_count: 30,
  totals: { regular: null, revision: null, bridge: '30' },
};
const list = (results, count = results.length) => ({ results, count, page: 1, page_size: 25 });

// ------------------------------------------------------------------ the tests
const tests = [];
const test = (name, fn) => tests.push({ name, fn });

test('Prices: the editor prices packages exactly as the API does, rounding only the single payment, to the nearest unit', () => {
  const grade6 = chaptersOf(GRADE_6, 'c');
  assert.deepEqual(harness.packagePrices(['REGULAR_REVISION'], grade6, PRICING), PACKAGES);
  assert.deepEqual(harness.packagePrices(['CHAPTER_PLAN'], grade6, PRICING), []);
  assert.deepEqual(harness.packagePrices(['REVISION'], grade6, PRICING).map((p) => p.title), ['Revision Course (Exam Oriented) Package']);
  // Half classes at a fee with cents: every fil kept, and only the single payment rounded (backend tests_pricing).
  const halves = [{ regular_classes: '1', revision_classes: '19.5', bridge_classes: null }];
  const [revisionCard] = harness.packagePrices(['REVISION'], halves, { ...PRICING, offer_fee: '35.25', single_payment_plan_types: ['REVISION'] });
  assert.equal(revisionCard.total, '687.375');
  assert.deepEqual(revisionCard.single_payment, { price: '653', saving: '34.375' });
  // Grade 9: 2,765 less 5% is 2,626.75 -> 2,627, saving 138; a half rounds up (Grade 6: 1,263.50 -> 1,264, in PACKAGES).
  const grade9 = [{ regular_classes: '79', revision_classes: '41', bridge_classes: null }];
  assert.deepEqual(harness.packagePrices(['REGULAR'], grade9, PRICING)[0].single_payment, { price: '2627', saving: '138' });
  // Nothing rounded on the way: 492.10 less 5% is 467.495 -> 467 (not 467.50 -> 468); 3,995.499375 -> 3,995.
  const fils = [{ regular_classes: '14', revision_classes: '1', bridge_classes: null }];
  assert.deepEqual(harness.packagePrices(['REGULAR'], fils, { ...PRICING, offer_fee: '35.15' })[0].single_payment, { price: '467', saving: '25.1' });
  const quarter = [{ regular_classes: '59.5', revision_classes: '1', bridge_classes: null }, { regular_classes: '59.5', revision_classes: '1', bridge_classes: null }];
  const [quarterCard] = harness.packagePrices(['REGULAR'], quarter, { ...PRICING, offer_fee: '35.25', single_payment_percent: '4.75' });
  assert.deepEqual([quarterCard.classes, quarterCard.total, quarterCard.single_payment], ['119', '4194.75', { price: '3995', saving: '199.75' }]);
  assert.equal(harness.formatAmount('24379.875', 'INR'), 'INR 24,379.875');
  // Whole cents, as the PDF prints them (backend sales.pdf.money).
  assert.deepEqual(['122.5', '1067.5', '35', '0.5'].map((value) => harness.formatAmount(value, 'AED')),
    ['AED 122.50', 'AED 1,067.50', 'AED 35', 'AED 0.50']);
  assert.deepEqual(['1', '1.5', '99.5', '1.25', '100', 'x', ''].map((text) => harness.toHalves(text)), [2n, 3n, 199n, null, null, null, null]);
});

test("Form: a payload carries only its structure's counts; the API's per-row errors land on their fields", () => {
  const form = {
    title: ' Grade 7 CBSE ', subtitle: '', package_title: '', grade: '7', board: 'CBSE', syllabus_version: '', structure: 'BRIDGE_COURSE',
    plan_types: ['REGULAR'], inclusions: ['A', ' '], chapters: [{ key: 'k', id: null, name: 'Ratios', regular_classes: '2', revision_classes: '1', bridge_classes: '1' }],
  };
  assert.deepEqual(harness.payloadOf(form), {
    title: 'Grade 7 CBSE', subtitle: '', package_title: '', grade: 7, board: 'CBSE', syllabus_version: '', structure: 'BRIDGE_COURSE',
    plan_types: ['BRIDGE_COURSE'], inclusions: ['A'], chapters: [{ name: 'Ratios', bridge_classes: '1' }],
  });
  assert.deepEqual(harness.formErrors({ ...form, title: '', chapters: [{ ...form.chapters[0], name: '', bridge_classes: '1.25' }] }), {
    title: 'Enter the title the PDF shows.',
    'chapters.0.name': 'Enter the chapter name.',
    'chapters.0.bridge_classes': 'Use whole or half classes, such as 2 or 1.5.',
  });
  assert.deepEqual(harness.apiFieldErrors({ grade: ['Too high.'], chapters: { 2: { revision_classes: ['Use whole or half classes, such as 2 or 1.5.'] } } }), {
    grade: 'Too high.', 'chapters.2.revision_classes': 'Use whole or half classes, such as 2 or 1.5.',
  });
  assert.deepEqual(harness.apiFieldErrors({ chapters: { non_field_errors: ['This list may not be empty.'] } }), { chapters: 'This list may not be empty.' });
});

test('Syllabus & Plans: every syllabus with its grade, board, version, structure, plans, classes and status; filters go to the API', async () => {
  serve({ [`GET ${SYLLABI}`]: list([ROW, BRIDGE_ROW]) });
  await open('/sales-syllabus?status=PUBLISHED&structure=CHAPTER_WISE&board=CBSE&grade=6&q=grade', ADMIN);
  assert.deepEqual(calls('GET', SYLLABI)[0].params,
    { page: 1, page_size: 25, q: 'grade', status: 'PUBLISHED', structure: 'CHAPTER_WISE', board: 'CBSE', grade: '6' });
  assert.deepEqual(headers(), ['Syllabus', 'Grade', 'Board', 'Version', 'Structure', 'Plan types', 'Classes', 'Status', 'Last updated', 'Actions']);
  const cells = (row) => [...row.querySelectorAll('td')].map((td) => clean(td.textContent));
  assert.deepEqual(cells(rows()[0]).slice(0, 8), ['Grade 6 CBSE10 chapters', 'Grade 6', 'CBSE', 'New Syllabus', 'Chapter-wise',
    'RegularRevisionRegular + Revision', '38 Regular · 19 Revision', 'PublishedDraft r2']);
  assert.deepEqual(cells(rows()[1]).slice(0, 8), ['Grade 7 CBSE30 days', 'Grade 7', 'CBSE', '—', 'Bridge Course', 'Bridge Course',
    '30 classes', 'Draft']);
  assert.ok(link('New syllabus'), 'a new syllabus is a click away');
  assert.ok(link('Global pricing'));
});

test('Syllabus & Plans: deactivating asks first; duplicating opens the copy as a new draft', async () => {
  serve({
    [`GET ${SYLLABI}`]: list([ROW]),
    [`POST ${at('deactivate/')}`]: detailOf({ published: revision(1), status: 'INACTIVE' }),
    [`POST ${at('duplicate/')}`]: { ...detailOf({ draft: revision(1, { is_draft: true }) }), id: COPY_ID },
    [`GET ${SYLLABI}${COPY_ID}/`]: { ...detailOf({ draft: revision(1, { is_draft: true, title: 'Grade 6 CBSE (Copy)' }) }), id: COPY_ID },
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
  });
  const page = await open('/sales-syllabus', ADMIN);
  await openMenu(button('Actions for Grade 6 CBSE'));
  assert.deepEqual([...document.querySelectorAll('[role="menuitem"]')].map((item) => clean(item.textContent)),
    ['View', 'Edit draft', 'Preview PDF', 'Download PDF', 'Publish…', 'Duplicate', 'Deactivate']);
  // While a PDF is being drawn, the page says so and the menus offer no second one.
  globalThis.__salesApi.handler = ((serveFn) => (entry) =>
    entry.url === at('pdf/') ? new Promise(() => {}) : serveFn(entry))(globalThis.__salesApi.handler);
  await click(menuItem('Preview PDF'));
  assert.match(bodyText(), /Drawing the PDF…/);
  await openMenu(button('Actions for Grade 6 CBSE'));
  assert.equal(menuItem('Download PDF').getAttribute('data-disabled'), '');
  await click(menuItem('Deactivate'));
  assert.equal(calls('POST', at('deactivate/')).length, 0, 'nothing is sent before the confirmation');
  assert.match(clean(topDialog().textContent), /Deactivate this syllabus\?.*Nothing is deleted/);
  await click(button('Deactivate', topDialog()));
  assert.equal(calls('POST', at('deactivate/')).length, 1);
  assert.match(bodyText(), /Grade 6 CBSE is inactive: it is hidden from the sales to come\./);

  await openMenu(button('Actions for Grade 6 CBSE'));
  await click(menuItem('Duplicate'));
  assert.equal(page.location().pathname, `/sales-syllabus/${COPY_ID}/edit`);
  assert.equal(input('syllabus-title').value, 'Grade 6 CBSE (Copy)');
  assert.match(bodyText(), /Copied Grade 6 CBSE as a new draft/);
  await settle();
  assert.equal(page.location().state, null, 'the notice is shown once: Back or a reload never shows it again');
});

test('New syllabus: nothing is sent until the form is complete; chapters are added, moved and totalled as they are typed', async () => {
  const created = detailOf({ draft: revision(1, { is_draft: true }) });
  serve({
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
    [`POST ${SYLLABI}`]: created,
    [`GET ${at()}`]: created,
  });
  const page = await open('/sales-syllabus/new', ADMIN);
  await click(button('Save draft'));
  assert.equal(calls('POST', SYLLABI).length, 0);
  assert.match(bodyText(), /Enter the title the PDF shows\..*Choose the grade\..*Enter the chapter name\. Enter the number of classes\./);

  await typeInto(input('syllabus-title'), 'Grade 6 CBSE');
  await choose('syllabus-grade', 'Grade 6');
  await typeInto(input('chapter-0-name'), 'Fractions');
  await typeInto(input('chapter-0-regular_classes'), '5');
  await typeInto(input('chapter-0-revision_classes'), '2');
  await click(button('Add chapter'));
  assert.equal(document.activeElement, input('chapter-1-name'), 'a new row is ready for its name');
  await typeInto(input('chapter-1-name'), 'Symmetry');
  await typeInto(input('chapter-1-regular_classes'), '4');
  await typeInto(input('chapter-1-revision_classes'), '1.5');
  await click(button('Move chapter 2 up'));
  assert.equal(input('chapter-0-name').value, 'Symmetry');
  assert.match(bodyText(), /Total Regular classes: 9·Total Revision classes: 3\.5/);
  assert.doesNotMatch(bodyText(), /Enter the title the PDF shows|Enter the chapter name/, 'a corrected field is no longer flagged');
  // Priced as typed: 9 x AED 35 = 315, less 5% paid at once = 299.25 -> 299.
  assert.match(bodyText(), /Regular Course Package9 Classes.*AED 315.*Single payment: AED 299 \(saves AED 16\)/);
  assert.match(bodyText(), /Revision Course \(Exam Oriented\) Package3\.5 Classes.*AED 122\.50(?!\d)/);

  await click(button('Save draft'));
  const [sent] = calls('POST', SYLLABI);
  assert.deepEqual(sent.data.chapters, [
    { name: 'Symmetry', regular_classes: '4', revision_classes: '1.5' },
    { name: 'Fractions', regular_classes: '5', revision_classes: '2' },
  ]);
  assert.deepEqual([sent.data.title, sent.data.grade, sent.data.board, sent.data.plan_types],
    ['Grade 6 CBSE', 6, 'CBSE', ['REGULAR', 'REVISION', 'REGULAR_REVISION']]);
  assert.equal(page.location().pathname, `/sales-syllabus/${ID}/edit`);
  assert.match(bodyText(), /Saved as a draft\. Preview it, then publish it when it is ready\./);
});

test("New syllabus: the API's refusal of one chapter's count is shown on that chapter", async () => {
  serve({
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
    [`POST ${SYLLABI}`]: () => fail(400, { error: 'VALIDATION_ERROR', message: 'Check the syllabus details.',
      fields: { chapters: { 0: { revision_classes: ['Ensure that there are no more than 1 decimal places.'] } } } }),
  });
  await open('/sales-syllabus/new', ADMIN);
  await typeInto(input('syllabus-title'), 'Grade 6 CBSE');
  await choose('syllabus-grade', 'Grade 6');
  await typeInto(input('chapter-0-name'), 'Fractions');
  await typeInto(input('chapter-0-regular_classes'), '5');
  await typeInto(input('chapter-0-revision_classes'), '2');
  await click(button('Save draft'));
  assert.equal(input('chapter-0-revision_classes').getAttribute('aria-invalid'), 'true');
  assert.match(bodyText(), /Ensure that there are no more than 1 decimal places\./);
});

test('New syllabus: a Bridge Course counts days of classes, is sold as itself, and previews its PDF unsaved', async () => {
  serve({
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
    'POST /api/sales/syllabi/pdf-preview/': { size: 10 },
  });
  await open('/sales-syllabus/new', ADMIN);
  await click(input('syllabus-structure-BRIDGE_COURSE'));
  assert.ok(input('chapter-0-bridge_classes'), 'one count a day');
  assert.equal(input('chapter-0-regular_classes'), null);
  assert.match(bodyText(), /A Bridge Course is sold as the whole course, or by the day: BDEs choose any of its days when quoting/);
  assert.doesNotMatch(bodyText(), /sold as one plan/);
  await typeInto(input('syllabus-title'), 'Grade 7 CBSE');
  await choose('syllabus-grade', 'Grade 7');
  await typeInto(input('chapter-0-name'), 'Ratios');
  await typeInto(input('chapter-0-bridge_classes'), '1');
  assert.match(bodyText(), /Total classes: 1.*Bridge Course Package1 Class.*AED 35/);

  // A stale CSRF token refuses the first try (its body a blob, as a PDF request's is): it is sent once more.
  let previews = 0;
  globalThis.__salesApi.handler = ((serveFn) => (entry) => {
    if (entry.url === '/api/sales/syllabi/pdf-preview/' && previews++ === 0) {
      return fail(403, new Blob([JSON.stringify({ detail: 'CSRF Failed: CSRF token from the X-CSRFToken HTTP header incorrect.' })]));
    }
    return serveFn(entry);
  })(globalThis.__salesApi.handler);
  await click(button('Preview PDF'));
  assert.equal(calls('POST', '/api/sales/syllabi/pdf-preview/').length, 2);
  assert.deepEqual(globalThis.__salesApi.calls.filter((entry) => entry.method !== 'GET').map((entry) => entry.method),
    ['POST', 'CSRF', 'POST'], 'a fresh token is fetched between the two tries');
  assert.deepEqual(calls('CSRF', '')[0].params, { refresh: true });
  const preview = calls('POST', '/api/sales/syllabi/pdf-preview/')[1];
  assert.deepEqual(preview.params, { disposition: 'inline' });
  assert.deepEqual([preview.data.structure, preview.data.plan_types, preview.data.chapters],
    ['BRIDGE_COURSE', ['BRIDGE_COURSE'], [{ name: 'Ratios', bridge_classes: '1' }]]);
  assert.match(clean(topDialog().textContent), /PDF preview/);
  assert.ok(topDialog().querySelector('iframe[src^="blob:test/"]'), 'the PDF shows in the dialog');
});

test("A draft of a published syllabus: saved without touching the published revision, then published only on confirmation", async () => {
  let current = detailOf({ published: revision(1), draft: revision(2, { is_draft: true, title: 'Grade 6 CBSE (2027)' }) });
  serve({
    [`GET ${at()}`]: () => ok(current),
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
    [`PUT ${at('draft/')}`]: (entry) => {
      current = detailOf({ published: revision(1), draft: revision(2, { is_draft: true, title: entry.data.title, updated_at: '2026-11-09T06:00:00.654321+05:30' }) });
      return ok(current);
    },
    [`POST ${at('publish/')}`]: () => ok(detailOf({ published: revision(2, { title: 'Grade 6 CBSE 2027' }) })),
  });
  const page = await open(`/sales-syllabus/${ID}/edit`, ADMIN);
  assert.equal(input('syllabus-title').value, 'Grade 6 CBSE (2027)');
  assert.equal(input('syllabus-structure-BRIDGE_COURSE').disabled, true, 'the structure is fixed once published');
  await typeInto(input('syllabus-title'), 'Grade 6 CBSE 2027');
  await click(button('Save draft'));
  const [put] = calls('PUT', at('draft/'));
  assert.equal(put.data.updated_at, '2026-11-09T05:00:02.123456+05:30', 'the save names the draft it edited');
  assert.match(bodyText(), /Draft revision 2 saved\. The published revision 1 is unchanged\./);

  await click(button('Publish…'));
  assert.equal(calls('POST', at('publish/')).length, 0);
  assert.match(clean(topDialog().textContent), /Publish revision 2\?.*becomes what BDEs sell from\. Revision 1 stays in the history, unchanged\./);
  await click(button('Publish', topDialog()));
  assert.deepEqual(calls('POST', at('publish/'))[0].data, { revision: 2, updated_at: '2026-11-09T06:00:00.654321+05:30' });
  assert.equal(page.location().pathname, `/sales-syllabus/${ID}`);
});

test("Publishing from the editor publishes the draft it shows: one saved again elsewhere is refused, not published", async () => {
  let current = detailOf({ published: revision(1), draft: revision(2, { is_draft: true }) });
  serve({
    [`GET ${at()}`]: () => ok(current),
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
    [`POST ${at('publish/')}`]: () => ok(detailOf({ published: revision(2) })),
  });
  await open(`/sales-syllabus/${ID}/edit`, ADMIN);
  // Someone else saves the draft while this editor shows it.
  current = detailOf({ published: revision(1), draft: revision(2, { is_draft: true, updated_at: '2026-11-09T07:00:00.000001+05:30' }) });
  await click(button('Publish…'));
  assert.match(clean(topDialog().textContent), /This draft was saved again since you opened it/);
  assert.equal(button('Publish', topDialog()).disabled, true);
  assert.equal(calls('POST', at('publish/')).length, 0);
  // The page hears of it: closing the dialog leaves the way to the newer draft in reach.
  await click(button('Cancel', topDialog()));
  assert.ok(button('Reload the latest version'), 'the editor offers to reload the newer draft');
});

test('The editor: a failed pricing load says so and retries; starting a draft someone else started opens theirs', async () => {
  let pricingAnswers = 0;
  serve({
    [`GET ${at()}`]: () => ok(detailOf({ draft: revision(1, { is_draft: true }) })),
    [`GET ${PRICING_URL}`]: () => (pricingAnswers++ === 0 ? fail(500, {}) : ok(PRICING_ANSWER)),
  });
  await open(`/sales-syllabus/${ID}/edit`, ADMIN);
  assert.match(bodyText(), /Could not load the pricing\./);
  assert.doesNotMatch(bodyText(), /No pricing is set up yet/);
  await click(button('Try again'));
  assert.match(bodyText(), /Priced at pricing version 1/);
  assert.equal(calls('PUT', at('draft/')).length, 0, 'retrying the pricing saves nothing');
  await mounted.pop().unmount();

  // Nor does it create anything on a new syllabus's form.
  pricingAnswers = 0;
  serve({ [`GET ${PRICING_URL}`]: () => (pricingAnswers++ === 0 ? fail(500, {}) : ok(PRICING_ANSWER)) });
  await open('/sales-syllabus/new', ADMIN);
  await click(button('Try again'));
  assert.equal(calls('POST', SYLLABI).length, 0);
  assert.doesNotMatch(bodyText(), /Check the highlighted fields/);
  await mounted.pop().unmount();

  serve({
    [`GET ${at()}`]: () => ok(detailOf({ published: revision(1) })),
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
    [`POST ${at('draft/')}`]: () => fail(409, { error: 'DRAFT_EXISTS', message: 'This syllabus already has a draft. Open it to keep editing.' }),
  });
  await open(`/sales-syllabus/${ID}/edit`, ADMIN);
  await click(button('Start a draft'));
  // Meanwhile another administrator started it: the editor opens theirs.
  serve({
    [`GET ${at()}`]: () => ok(detailOf({ published: revision(1), draft: revision(2, { is_draft: true, title: 'Theirs' }) })),
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
    [`POST ${at('draft/')}`]: () => fail(409, { error: 'DRAFT_EXISTS', message: 'This syllabus already has a draft. Open it to keep editing.' }),
  });
  await click(button('Start a draft', topDialog()));
  assert.equal(input('syllabus-title').value, 'Theirs');
});

test('The syllabus pages take the raw layout, like every page built on the design tokens', async () => {
  serve({ [`GET ${at()}`]: detailOf({ published: revision(1) }), [`GET ${PRICING_URL}`]: PRICING_ANSWER, [`GET ${SYLLABI}`]: list([ROW]) });
  for (const path of ['/sales-syllabus', '/sales-syllabus/new', `/sales-syllabus/${ID}`, `/sales-syllabus/${ID}/edit`]) {
    await open(path, ADMIN, { layout: true });
    assert.equal(document.querySelector('.legacy-ui'), null, path);
    await mounted.pop().unmount();
  }
});

test("Activity: a syllabus's entries name the revision; a pricing version's names its figures", () => {
  const entry = (action, extra) => harness.describeActivity({ action, changes: {}, context: {}, ...extra });
  assert.equal(entry('syllabus.publish', { context: { revision: 2 } }), 'Published revision 2');
  assert.equal(entry('syllabus.create', { context: { revision: 1, reference: '9th Plan & Price.pdf' } }),
    'Loaded a syllabus as a draft from 9th Plan & Price.pdf');
  assert.equal(entry('pricing.create_version', {
    changes: { offer_fee: { old: null, new: '35' }, standard_fee: { old: null, new: '45' } }, context: { version: 1, previous_version: null },
  }), 'Pricing v1: offer fee 35 a class');
  // A quote's entries: what is payable at once (whole cents), and why one was cancelled.
  assert.equal(entry('quote.create', { context: { revision: 1, payable_amount: '122.5', currency: 'AED' } }),
    'Issued a quote of revision 1: AED 122.50 payable at once');
  assert.equal(entry('quote.cancel', { context: { reason: 'Parent chose Regular' } }), 'Cancelled the quote: Parent chose Regular');
  assert.deepEqual([harness.actionLabels['quote.create'], harness.actionLabels['quote.cancel']], ['Quote issued', 'Quote cancelled']);
});

test('A draft changed meanwhile is not overwritten: the editor says so and offers the latest version', async () => {
  serve({
    [`GET ${at()}`]: detailOf({ draft: revision(1, { is_draft: true }) }),
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
    [`PUT ${at('draft/')}`]: () => fail(409, { error: 'DRAFT_CHANGED', message: 'This draft was changed or published meanwhile. Reload it to see the latest version.' }),
  });
  await open(`/sales-syllabus/${ID}/edit`, ADMIN);
  await typeInto(input('syllabus-title'), 'Mine');
  await click(button('Save draft'));
  assert.match(bodyText(), /This draft was changed or published meanwhile\..*Reload the latest version/);
  await click(button('Reload the latest version'));
  assert.match(clean(topDialog().textContent), /Reload the latest version\?/);
});

test('A syllabus: its published revision and waiting draft, packages, history; editing a published one starts a draft first', async () => {
  serve({
    [`GET ${at()}`]: detailOf({ published: revision(1), draft: revision(2, { is_draft: true, title: 'Grade 6 CBSE (2027)' }) }),
  });
  await open(`/sales-syllabus/${ID}`, ADMIN);
  assert.match(bodyText(), /Published · revision 1.*Draft · revision 2/);
  assert.match(bodyText(), /Published revision 1/);
  assert.match(bodyText(), /Regular Course Package38 Classes.*AED 1,330.*Single payment: AED 1,264 \(saves AED 66\)/);
  assert.match(bodyText(), /Revision 2Draft.*Revision 1Published/);
  assert.ok(link('Edit draft'));
  await mounted.pop().unmount();

  serve({
    [`GET ${at()}`]: detailOf({ published: revision(1) }),
    [`POST ${at('draft/')}`]: detailOf({ published: revision(1), draft: revision(2, { is_draft: true }) }),
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
  });
  const page = await open(`/sales-syllabus/${ID}`, ADMIN);
  await click(button('Edit'));
  assert.equal(calls('POST', at('draft/')).length, 0);
  assert.match(clean(topDialog().textContent), /The published revision stays as it is — BDEs keep selling it — until you publish the draft\./);
  await click(button('Start a draft', topDialog()));
  assert.equal(calls('POST', at('draft/')).length, 1);
  assert.equal(page.location().pathname, `/sales-syllabus/${ID}/edit`);
});

test('A syllabus: publishing is refused for the whole opening once the draft is seen to have changed, even after the page reloads it', async () => {
  // The page shows r2 as saved at T1; by the time the dialog reads it, someone saved it at T2.
  let reads = 0;
  const t2 = revision(2, { is_draft: true, updated_at: '2026-11-09T07:00:00.000001+05:30', title: 'Theirs' });
  serve({
    [`GET ${at()}`]: () => ok(reads++ === 0 ? detailOf({ published: revision(1), draft: revision(2, { is_draft: true }) })
      : detailOf({ published: revision(1), draft: t2 })),
    [`POST ${at('publish/')}`]: () => ok(detailOf({ published: revision(2) })),
  });
  await open(`/sales-syllabus/${ID}`, ADMIN);
  await click(button('Publish…'));
  assert.equal(reads, 3, 'the dialog read the syllabus, then the page reloaded it behind the dialog');
  assert.match(bodyText(), /Draft · revision 2/);
  assert.match(clean(topDialog().textContent), /This draft was saved again since you opened it/);
  assert.equal(button('Publish', topDialog()).disabled, true, 'still refused although the page now shows the newer draft');
  assert.equal(calls('POST', at('publish/')).length, 0);
  // Reopened, the dialog reads the draft the page now shows: it may be published.
  await click(button('Cancel', topDialog()));
  await click(button('Publish…'));
  assert.equal(button('Publish', topDialog()).disabled, false);
  await mounted.pop().unmount();

  // Published or discarded meanwhile: the dialog says there is nothing to publish and the page reloads.
  reads = 0;
  serve({
    [`GET ${at()}`]: () => ok(reads++ === 0 ? detailOf({ published: revision(1), draft: revision(2, { is_draft: true }) })
      : detailOf({ published: revision(2) })),
  });
  await open(`/sales-syllabus/${ID}`, ADMIN);
  await click(button('Publish…'));
  assert.match(clean(topDialog().textContent), /This syllabus has no draft to publish\./);
  assert.equal(reads, 3, 'the page is read again');
});

test('A syllabus: the publish dialog checks and publishes the draft the page showed when it opened, whatever reloads behind it', async () => {
  const t2 = revision(2, { is_draft: true, updated_at: '2026-11-09T07:00:00.000001+05:30', title: 'Theirs' });
  const waiting = [];
  let reads = 0;
  serve({
    [`GET ${at()}`]: () => {
      reads += 1;
      if (reads === 1) return ok(detailOf({ published: revision(1), draft: revision(2, { is_draft: true }) })); // the page: T1
      if (reads === 2) return ok(detailOf({ published: revision(1), draft: t2 })); // the dialog's read: T2, so stale
      return new Promise((resolve) => waiting.push(resolve)); // the page's reload and the next read wait
    },
    [`POST ${at('publish/')}`]: () => ok(detailOf({ published: revision(2) })),
  });
  await open(`/sales-syllabus/${ID}`, ADMIN);
  await click(button('Publish…'));
  await click(button('Cancel', topDialog()));
  // Reopened while the page's reload is still on its way: the page still shows T1.
  await click(button('Publish…'));
  assert.equal(waiting.length, 2);
  // The reload answers first (the page now shows T2), then the dialog's read: it is checked against T1, as opened.
  await act(async () => waiting[0]({ status: 200, data: detailOf({ published: revision(1), draft: t2 }) }));
  await settle();
  await act(async () => waiting[1]({ status: 200, data: detailOf({ published: revision(1), draft: t2 }) }));
  await settle();
  assert.match(clean(topDialog().textContent), /This draft was saved again since you opened it/);
  assert.equal(button('Publish', topDialog()).disabled, true);
  assert.equal(calls('POST', at('publish/')).length, 0);
});

test('A syllabus: a discard names the draft the page showed when the dialog opened, not one reloaded behind it', async () => {
  const waiting = [];
  let reads = 0;
  serve({
    [`GET ${at()}`]: () => {
      reads += 1;
      if (reads === 1) return ok(detailOf({ published: revision(1), draft: revision(2, { is_draft: true }) }));
      return new Promise((resolve) => waiting.push(resolve));
    },
    [`DELETE ${at('draft/')}`]: () => fail(409, { error: 'DRAFT_CHANGED', message: 'This draft was changed or published meanwhile. Reload it to see the latest version.' }),
  });
  await open(`/sales-syllabus/${ID}`, ADMIN);
  await openMenu(button('More actions'));
  await click(menuItem('Discard draft'));
  await click(button('Discard draft', topDialog()));
  // Refused: the page reloads. Reopened before the reload answers...
  await openMenu(button('More actions'));
  await click(menuItem('Discard draft'));
  // ...the reload lands behind the dialog with the newer draft, and the Admin confirms.
  await act(async () => waiting[0]({ status: 200, data: detailOf({ published: revision(1),
    draft: revision(2, { is_draft: true, updated_at: '2026-11-09T07:00:00.000001+05:30' }) }) }));
  await settle();
  await click(button('Discard draft', topDialog()));
  assert.deepEqual(calls('DELETE', at('draft/')).map((entry) => entry.data.updated_at),
    ['2026-11-09T05:00:02.123456+05:30', '2026-11-09T05:00:02.123456+05:30'], 'both name the draft the page showed');
});

test('Syllabus & Plans: a PDF refusal and an action refusal are both shown, neither hiding the other', async () => {
  serve({
    [`GET ${SYLLABI}`]: list([ROW]),
    [`GET ${at('pdf/')}`]: () => fail(409, { error: 'NO_PRICING', message: 'Set up the global pricing first: the PDF prices every package.' }),
    [`POST ${at('deactivate/')}`]: () => fail(409, { error: 'ALREADY_INACTIVE', message: 'This syllabus is already inactive.' }),
  });
  await open('/sales-syllabus', ADMIN);
  await openMenu(button('Actions for Grade 6 CBSE'));
  await click(menuItem('Preview PDF'));
  await openMenu(button('Actions for Grade 6 CBSE'));
  await click(menuItem('Deactivate'));
  await click(button('Deactivate', topDialog()));
  assert.match(bodyText(), /Set up the global pricing first/);
  assert.match(bodyText(), /Grade 6 CBSE: This syllabus is already inactive\. The list now shows it as it is\./);
});

test('A syllabus: a refused deactivation closes, says why and shows the syllabus as it is now', async () => {
  serve({
    [`GET ${at()}`]: detailOf({ published: revision(1) }),
    [`POST ${at('deactivate/')}`]: () => fail(409, { error: 'ALREADY_INACTIVE', message: 'This syllabus is already inactive.' }),
  });
  await open(`/sales-syllabus/${ID}`, ADMIN);
  await openMenu(button('More actions'));
  await click(menuItem('Deactivate'));
  await click(button('Deactivate', topDialog()));
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0);
  assert.match(bodyText(), /This syllabus is already inactive\. The page now shows it as it is\./);
  assert.equal(calls('GET', at()).length, 2);
});

test('Syllabus & Plans: one copy at a time, and a copy that answers after the Admin left does not bring them back', async () => {
  let answer;
  serve({
    [`GET ${SYLLABI}`]: list([ROW]),
    [`GET ${PRICING_URL}`]: PRICING_ANSWER,
    [`POST ${at('duplicate/')}`]: () => new Promise((resolve) => { answer = resolve; }),
  });
  const page = await open('/sales-syllabus', ADMIN);
  await openMenu(button('Actions for Grade 6 CBSE'));
  await click(menuItem('Duplicate'));
  await openMenu(button('Actions for Grade 6 CBSE'));
  assert.equal(menuItem('Duplicate').getAttribute('data-disabled'), '', 'no second copy while one is being made');
  await keyDown(document.activeElement, 'Escape');
  await page.go('/sales-pricing');
  await act(async () => answer({ status: 201, data: { ...detailOf({ draft: revision(1, { is_draft: true }) }), id: COPY_ID } }));
  await settle();
  assert.equal(page.location().pathname, '/sales-pricing', 'the Admin stays where they went');
  assert.equal(calls('POST', at('duplicate/')).length, 1);
});

test('A syllabus: a draft discarded after someone saved it again is refused, and the page shows it as it is now', async () => {
  serve({
    [`GET ${at()}`]: detailOf({ published: revision(1), draft: revision(2, { is_draft: true }) }),
    [`DELETE ${at('draft/')}`]: () => fail(409, { error: 'DRAFT_CHANGED', message: 'This draft was changed or published meanwhile. Reload it to see the latest version.' }),
  });
  await open(`/sales-syllabus/${ID}`, ADMIN);
  await openMenu(button('More actions'));
  await click(menuItem('Discard draft'));
  await click(button('Discard draft', topDialog()));
  assert.deepEqual(calls('DELETE', at('draft/'))[0].data, { revision: 2, updated_at: '2026-11-09T05:00:02.123456+05:30' });
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0, 'the dialog closes');
  assert.match(bodyText(), /This draft was changed or published meanwhile\. The page now shows it as it is: check it before discarding\./);
  assert.equal(calls('GET', at()).length, 2, 'the syllabus is read again');
});

test('A syllabus: its PDF downloads under the name the API gives; a refusal says why', async () => {
  serve({
    [`GET ${at()}`]: detailOf({ published: revision(1) }),
    [`GET ${at('revisions/1/pdf/')}`]: () => ok(Object.assign({ size: 10 }, {})),
  });
  globalThis.__salesApi.handler = ((serveFn) => (entry) => {
    if (entry.url === at('revisions/1/pdf/') && !entry.params) {
      return Promise.resolve({ status: 200, data: { size: 10 }, headers: { 'content-disposition': 'attachment; filename="Grade-6-CBSE-New-Syllabus-Plan-and-Price-r1.pdf"' } });
    }
    if (entry.url === at('revisions/1/pdf/')) return fail(409, { error: 'NO_PRICING', message: 'Set up the global pricing first: the PDF prices every package.' });
    return serveFn(entry);
  })(globalThis.__salesApi.handler);
  await open(`/sales-syllabus/${ID}`, ADMIN);
  await click(button('Download PDF'));
  assert.equal(saved.at(-1).name, 'Grade-6-CBSE-New-Syllabus-Plan-and-Price-r1.pdf');
  await click(button('Preview PDF'));
  assert.match(bodyText(), /Set up the global pricing first: the PDF prices every package\./);
});

test('Global Pricing: set up from nothing, checked before it is sent; each change is the next version', async () => {
  serve({
    [`GET ${PRICING_URL}`]: { current: null, versions: [] },
    [`POST ${PRICING_URL}`]: { current: PRICING, versions: [{ ...PRICING, effective_until: null }] },
  });
  await open('/sales-pricing', ADMIN);
  assert.match(bodyText(), /No pricing yet/);
  await click(button('Set up the pricing'));
  await typeInto(input('pricing-currency'), 'aed');
  await typeInto(input('pricing-standard-fee'), '45');
  await typeInto(input('pricing-offer-fee'), '50');
  await typeInto(input('pricing-single-payment-percent'), '5');
  await click(button('Save version 1', topDialog()));
  assert.equal(calls('POST', PRICING_URL).length, 0);
  assert.match(clean(topDialog().textContent), /The offer fee cannot be more than the standard fee\./);
  await typeInto(input('pricing-offer-fee'), '35');
  await click(button('Save version 1', topDialog()));
  assert.deepEqual(calls('POST', PRICING_URL)[0].data, {
    currency: 'AED', standard_fee: '45', offer_fee: '35', single_payment_percent: '5', single_payment_plan_types: ['REGULAR'], note: '',
  });
  assert.match(bodyText(), /Pricing version 1 is in effect\..*In effect: version 1/);
  assert.match(bodyText(), /AED 35 per class — every package is priced at it.*5% off Regular/);
  assert.ok(button('Change pricing'));
});

test('Global Pricing: the single-payment privilege is switched on or off; packages ticked at 0% read as off', async () => {
  // A version saved at 0% with packages ticked gives no privilege: the page says it is off.
  const OFF = { ...PRICING, single_payment_percent: '0.00', single_payment_plan_types: ['REGULAR', 'REVISION', 'BRIDGE_COURSE'] };
  const ON = { ...PRICING, id: 'p-2', version: 2 };
  serve({
    [`GET ${PRICING_URL}`]: { current: OFF, versions: [{ ...OFF, effective_until: null }] },
    [`POST ${PRICING_URL}`]: { current: ON, versions: [{ ...ON, effective_until: null }, { ...OFF, effective_until: ON.effective_from }] },
  });
  await open('/sales-pricing', ADMIN);
  assert.match(bodyText(), /Single payment\s*Off — the PDFs show no Single-Payment Privilege box/);
  await click(button('Change pricing'));
  assert.equal(input('pricing-single-payment').checked, false);
  assert.equal(input('pricing-single-payment-percent'), null);
  assert.match(clean(topDialog().textContent), /Off: no package offers a single-payment price, and the PDFs show no Single-Payment Privilege box\./);
  // Switched on, it needs its discount; Regular, as in the reference PDFs, is chosen.
  await click(input('pricing-single-payment'));
  assert.equal(input('pricing-single-payment-percent').value, '');
  await click(button('Save version 2', topDialog()));
  assert.equal(calls('POST', PRICING_URL).length, 0);
  assert.match(clean(topDialog().textContent), /Enter the discount, from 0\.01 to 99\.99%, or switch the privilege off\./);
  await typeInto(input('pricing-single-payment-percent'), '5');
  await click(button('Save version 2', topDialog()));
  assert.deepEqual(calls('POST', PRICING_URL)[0].data, {
    currency: 'AED', standard_fee: '45', offer_fee: '35', single_payment_percent: '5', single_payment_plan_types: ['REGULAR'], note: '',
  });
  assert.match(bodyText(), /Single payment\s*5% off Regular, rounded to the nearest whole AED — the PDFs show the Single-Payment Privilege box/);

  // Switched off, it sends no discount and no packages.
  await click(button('Change pricing'));
  assert.equal(input('pricing-single-payment-percent').value, '5');
  await click(input('pricing-single-payment'));
  await click(button('Save version 3', topDialog()));
  assert.deepEqual(calls('POST', PRICING_URL)[1].data, {
    currency: 'AED', standard_fee: '45', offer_fee: '35', single_payment_percent: '0', single_payment_plan_types: [], note: '',
  });
});

test('With no single-payment price on any package, the syllabus page and the editor say the PDF has no privilege box', async () => {
  const NO_BOX = /The pricing in effect gives these packages no single-payment privilege, so the PDF shows no Single-Payment Privilege box\./;
  serve({ [`GET ${at()}`]: detailOf({ published: revision(1) }) });
  await open(`/sales-syllabus/${ID}`, ADMIN);
  assert.doesNotMatch(bodyText(), NO_BOX);
  await mounted.pop().unmount();

  const OFF = { ...PRICING, single_payment_percent: '0.00' };
  const unboxed = PACKAGES.map((item) => ({ ...item, single_payment: null }));
  serve({
    [`GET ${at()}`]: { ...detailOf({ published: revision(1, { packages: unboxed }) }), pricing: OFF },
  });
  await open(`/sales-syllabus/${ID}`, ADMIN);
  assert.match(bodyText(), NO_BOX);
  await mounted.pop().unmount();

  // The editor prices its packages itself, at the same pricing.
  serve({
    [`GET ${at()}`]: { ...detailOf({ draft: revision(1, { is_draft: true, packages: unboxed }) }), pricing: OFF },
    [`GET ${PRICING_URL}`]: { current: OFF, versions: [{ ...OFF, effective_until: null }] },
  });
  await open(`/sales-syllabus/${ID}/edit`, ADMIN);
  assert.match(bodyText(), /Regular Course Package38 Classes.*AED 1,330/);
  assert.match(bodyText(), NO_BOX);
});

// ------------------------------------------------------------------ Plans & Pricing (BDEs: the catalogue on sale)
const BDE = { id: 'bde', role: 'BDE', permissions: ['accounts.view_own_enquiries', 'accounts.view_sales_catalogue'] };
const BDE_WITHOUT = { id: 'bde-2', role: 'BDE', permissions: ['accounts.view_own_enquiries'] };
const CATALOGUE = '/api/sales/catalogue/';
const BRIDGE_ID = '33333333-3333-4333-8333-333333333333';
const PLAN_ID = '44444444-4444-4444-8444-444444444444';
const onSale = (id, path = '') => `${CATALOGUE}${id}/${path}`;
// Version 3 of the pricing as the catalogue gives it: rates and privilege only (no note, author or history).
const ON_SALE_PRICING = {
  version: 3, currency: 'AED', standard_fee: '45', offer_fee: '35', single_payment_percent: '5',
  single_payment_plan_types: ['REGULAR', 'BRIDGE_COURSE'],
};
// Ten days: whole, half and no classes (day 6) -- 10 classes in all, as the backend's tests_selection DAYS.
const DAYS = [['Addition Subtraction Word problem', '1'], ['Multiplication Word problem', '1.5'], ['Division ,BODMAS,Word problem', '0.5'],
  ['Fraction, Types of fractions', '2'], ['Ratios', '1'], ['Revision of the week', '0'], ['Percentage', '1'], ['Factorization', '1'],
  ['LCM and HCF', '1'], ['Unit conversion', '1']];
const daysOf = (prefix) => DAYS.map(([name, classes], index) => ({
  id: `${prefix}-${index + 1}`, position: index + 1, name, regular_classes: null, revision_classes: null, bridge_classes: classes,
}));
function bridgeOnSale({ revision = 1, prefix = 'day', ...extra } = {}) {
  return {
    id: BRIDGE_ID, revision, title: 'Grade 7 CBSE', subtitle: 'Detailed Bridge Course Curriculum',
    package_title: 'Grade 7 CBSE – 1:1 Tuition Packages & Fee Details', grade: 7, board: 'CBSE', syllabus_version: '',
    structure: 'BRIDGE_COURSE', plan_types: ['BRIDGE_COURSE'],
    inclusions: ['Personalized 1:1 live sessions', 'Structured CBSE aligned learning', 'Dedicated mentor support'],
    chapters: daysOf(prefix), totals: { regular: '0', revision: '0', bridge: '10' },
    // The whole course, as the API prices it: 350 less 5% is 332.50, rounded half up to 333.
    packages: [{ plan_type: 'BRIDGE_COURSE', title: 'Bridge Course Package', classes: '10', fee_per_class: '35', total: '350',
      single_payment: { price: '333', saving: '17' } }],
    pricing: ON_SALE_PRICING,
    ...extra,
  };
}
const CHAPTER_WISE_ON_SALE = {
  ...revision(1), id: PLAN_ID, revision: 1, subtitle: 'Detailed Chapter-Wise 1:1 Learning Plan',
  package_title: 'Grade 6 CBSE – 1:1 Tuition Packages & Fee Details', pricing: ON_SALE_PRICING,
};
for (const field of ['number', 'is_draft', 'subtitle_display', 'package_title_display', 'created_at', 'created_by', 'updated_at',
  'updated_by', 'published_at', 'published_by']) delete CHAPTER_WISE_ON_SALE[field];
const CATALOGUE_ROWS = [
  { id: PLAN_ID, revision: 1, title: 'Grade 6 CBSE', grade: 6, board: 'CBSE', syllabus_version: 'New Syllabus', structure: 'CHAPTER_WISE',
    plan_types: ['REGULAR', 'REVISION', 'REGULAR_REVISION'], chapter_count: 10, totals: { regular: '38', revision: '19', bridge: null } },
  { id: BRIDGE_ID, revision: 1, title: 'Grade 7 CBSE', grade: 7, board: 'CBSE', syllabus_version: '', structure: 'BRIDGE_COURSE',
    plan_types: ['BRIDGE_COURSE'], chapter_count: 10, totals: { regular: null, revision: null, bridge: '10' } },
];
const dayBox = (n) => document.querySelector(`input[type="checkbox"][aria-label^="Day ${n}:"]`);
const pdfPost = () => calls('POST', onSale(BRIDGE_ID, 'selection/pdf/'));

test('Prices: a Bridge Course bought by the day is priced exactly as the API prices it, half up only at the end', () => {
  const days = daysOf('day');
  // Backend tests_selection: days 2 and 3 are 2 classes, AED 70; less 5% is 66.50, a half, rounded up to 67, saving 3.
  let picked = harness.bridgeSelection(days, ['day-3', 'day-2'], ON_SALE_PRICING);
  assert.deepEqual([picked.days.map((day) => day.position), picked.fullCourse, picked.classes], [[2, 3], false, '2']);
  assert.deepEqual(picked.package, { plan_type: 'BRIDGE_COURSE', title: harness.selectedDaysTitle, classes: '2', fee_per_class: '35',
    total: '70', single_payment: { price: '67', saving: '3' } });
  // Days 2 and 4, chosen in any order, keep the course's: 3.5 classes, AED 122.50 -> 116.375 -> 116, saving 6.50.
  picked = harness.bridgeSelection(days, ['day-4', 'day-2'], ON_SALE_PRICING);
  assert.deepEqual([picked.days.map((day) => day.position), picked.classes, picked.package.total, picked.package.single_payment],
    [[2, 4], '3.5', '122.5', { price: '116', saving: '6.5' }]);
  // Every day is the whole course: its own package, exactly as the API prices it.
  picked = harness.bridgeSelection(days, days.map((day) => day.id).reverse(), ON_SALE_PRICING);
  assert.equal(picked.fullCourse, true);
  assert.deepEqual(picked.package, bridgeOnSale().packages[0]);
  // A half class at a fee with fils: 1.5 x 35.25 = 52.875, less 5% is 50.23125 -> 50, saving 2.875.
  picked = harness.bridgeSelection(days, ['day-2'], { ...ON_SALE_PRICING, offer_fee: '35.25' });
  assert.deepEqual([picked.package.total, picked.package.single_payment], ['52.875', { price: '50', saving: '2.875' }]);
  // No privilege for a Bridge Course in the pricing, none chosen, no pricing.
  assert.equal(harness.bridgeSelection(days, ['day-2'], { ...ON_SALE_PRICING, single_payment_plan_types: ['REGULAR'] }).package.single_payment, null);
  assert.deepEqual([harness.bridgeSelection(days, [], ON_SALE_PRICING).classes, harness.bridgeSelection(days, [], ON_SALE_PRICING).package.total], ['0', '0']);
  assert.equal(harness.bridgeSelection(days, ['day-2'], null).package, null);
});

test('Plans & Pricing: the plans on sale, filtered in the API; none yet, a failure and a refusal each say so', async () => {
  serve({ [`GET ${CATALOGUE}`]: list(CATALOGUE_ROWS) });
  const page = await open('/plans', BDE);
  assert.deepEqual(headers(), ['Plan', 'Grade', 'Board', 'Version', 'Structure', 'Sold as', 'Classes', 'Syllabus PDF', 'Open']);
  assert.match(bodyText(), /Grade 6 CBSE.*38 Regular · 19 Revision.*Grade 7 CBSE.*10 classes over 10 days/);
  // Nothing an administrator manages: no status, author, draft, new syllabus or actions menu.
  assert.doesNotMatch(bodyText(), /Draft|Published|Last updated|New syllabus|Global pricing/);
  assert.equal(button('Actions for Grade 6 CBSE'), undefined);
  await choose('Filter by grade', 'Grade 7');
  assert.equal(calls('GET', CATALOGUE).at(-1).params.grade, '7');
  await click(link('Grade 7 CBSE'));
  assert.equal(page.location().pathname, `/plans/${BRIDGE_ID}`);
  await mounted.pop().unmount();

  serve({ [`GET ${CATALOGUE}`]: list([]) });
  await open('/plans', BDE);
  assert.match(bodyText(), /No plans on sale yet/);
  await mounted.pop().unmount();

  let answers = 0;
  serve({ [`GET ${CATALOGUE}`]: () => (answers++ ? ok(list(CATALOGUE_ROWS)) : fail(500, { message: 'Server error.' })) });
  await open('/plans', BDE);
  assert.match(bodyText(), /Server error\./);
  await click(button('Try again'));
  assert.match(bodyText(), /Grade 7 CBSE/);
  await mounted.pop().unmount();

  serve({ [`GET ${CATALOGUE}`]: () => fail(403, { detail: 'You do not have permission to perform this action.' }) });
  await open('/plans', BDE);
  assert.match(bodyText(), /You don't have access to plans and pricing\./);
});

test('A Bridge Course: days ticked one by one, Select all, Clear -- priced as they are ticked, drawn in the course order', async () => {
  serve({
    [`GET ${onSale(BRIDGE_ID)}`]: bridgeOnSale(),
    [`POST ${onSale(BRIDGE_ID, 'selection/pdf/')}`]: () => ok(new Blob(['%PDF'])),
  });
  await open(`/plans/${BRIDGE_ID}`, BDE);
  assert.deepEqual(headers(), ['Chosen', 'Day', 'Chapter name', 'Classes']);
  assert.match(bodyText(), /Single payment\s*5% off Bridge Course when paid in one instalment/);
  assert.deepEqual(rows().map((row) => clean(row.textContent)).slice(0, 2), ['1Addition Subtraction Word problem1', '2Multiplication Word problem1.5']);
  // The summary comes first in the page (above the days on a phone, beside them on a wide screen).
  assert.match(bodyText(), /Your selection\s*Choose at least one day, or Select all for the full course\..*0 of 10 days chosen/);
  assert.equal(button('Preview PDF').disabled, true);
  assert.equal(button('Download PDF').disabled, true);

  // Day 4, then day 2: in the course's order, 3.5 classes, AED 122.50, AED 116 paid at once.
  await click(dayBox(4));
  await click(dayBox(2));
  assert.match(bodyText(), /2 of 10 days chosen/);
  assert.match(bodyText(), /Your selection\s*Package\s*Bridge Course – Selected Days Package\s*Days\s*Days 2 and 4 of 10\s*Classes\s*3\.5 Classes/);
  assert.match(bodyText(), /Fee per class\s*AED 35\s*Total fee\s*AED 122\.50\s*Single payment\s*AED 116 \(saves AED 6\.50\)/);
  await click(button('Preview PDF'));
  assert.deepEqual(pdfPost()[0].data, { revision: 1, chapter_ids: ['day-2', 'day-4'] });
  assert.deepEqual(pdfPost()[0].params, { disposition: 'inline' });

  // Select all is the whole course: its own package and price, every day sent.
  await click(button('Select all'));
  assert.match(bodyText(), /10 of 10 days chosen/);
  assert.match(bodyText(), /Full course\s*Package\s*Bridge Course Package\s*Days\s*All 10 days\s*Classes\s*10 Classes/);
  assert.match(bodyText(), /Total fee\s*AED 350\s*Single payment\s*AED 333 \(saves AED 17\)/);
  assert.equal(button('Select all').disabled, true);
  await click(button('Download PDF'));
  assert.deepEqual(pdfPost()[1].data, { revision: 1, chapter_ids: daysOf('day').map((day) => day.id) });
  assert.equal(pdfPost()[1].params, null);

  // Clear: nothing chosen, nothing to draw.
  await click(button('Clear'));
  assert.match(bodyText(), /0 of 10 days chosen/);
  assert.equal(button('Download PDF').disabled, true);
  assert.equal(button('Clear').disabled, true);

  // A day without classes, alone, sells nothing.
  await click(dayBox(6));
  assert.match(bodyText(), /The days chosen have no classes: choose a day that has some\./);
  assert.equal(button('Preview PDF').disabled, true);
  assert.equal(pdfPost().length, 2);
});

test('A Bridge Course republished meanwhile: its PDF is refused, the page says so and reloads the new revision', async () => {
  let current = bridgeOnSale();
  serve({
    [`GET ${onSale(BRIDGE_ID)}`]: () => ok(current),
    [`POST ${onSale(BRIDGE_ID, 'selection/pdf/')}`]: () => fail(409, {
      error: 'REVISION_CHANGED', message: 'This syllabus was updated to revision 2: reload it and choose the days again.', revision: 2,
    }),
  });
  await open(`/plans/${BRIDGE_ID}`, BDE);
  await click(dayBox(1));
  await click(dayBox(3));
  current = bridgeOnSale({ revision: 2, prefix: 'r2' });
  await click(button('Preview PDF'));
  assert.match(bodyText(), /This plan was updated to revision 2 since you opened it\. Reload it and choose the days again\./);
  // The old days are not ticked, priced or drawn against the new revision: reload first.
  assert.equal(dayBox(1).disabled, true);
  assert.equal(button('Select all').disabled, true);
  assert.equal(button('Preview PDF').disabled, true);
  assert.equal(button('Download PDF').disabled, true);
  await click(button('Reload'));
  assert.equal(calls('GET', onSale(BRIDGE_ID)).length, 2);
  assert.doesNotMatch(bodyText(), /This plan was updated/);
  assert.match(bodyText(), /0 of 10 days chosen/);
  await click(dayBox(1));
  assert.equal(dayBox(1).checked, true);
  await mounted.pop().unmount();

  // Withdrawn meanwhile: not on sale. (A pricing giving only Regular the privilege gives this plan none.)
  serve({
    [`GET ${onSale(BRIDGE_ID)}`]: bridgeOnSale({ pricing: { ...ON_SALE_PRICING, single_payment_plan_types: ['REGULAR'] } }),
    [`POST ${onSale(BRIDGE_ID, 'selection/pdf/')}`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such syllabus on sale.' }),
  });
  await open(`/plans/${BRIDGE_ID}`, BDE);
  assert.match(bodyText(), /Single payment\s*None for this plan/);
  await click(dayBox(2));
  assert.match(bodyText(), /Total fee\s*AED 52\.50/);
  assert.doesNotMatch(bodyText(), /saves/);
  await click(button('Download PDF'));
  assert.match(bodyText(), /This plan is no longer on sale\./);
});

test('A chapter-wise plan: its chapters, priced packages and PDF -- nothing an administrator manages', async () => {
  serve({
    [`GET ${onSale(PLAN_ID)}`]: CHAPTER_WISE_ON_SALE,
    [`GET ${onSale(PLAN_ID, 'pdf/')}`]: () => ok(new Blob(['%PDF'])),
  });
  await open(`/plans/${PLAN_ID}`, BDE);
  assert.match(bodyText(), /Grade 6 · CBSE · New Syllabus · Chapter-wise/);
  // The privilege as it reaches this plan: Regular (the pricing's Bridge Course is not a package of this plan).
  assert.match(bodyText(), /Fee per class\s*AED 35 \(standard AED 45\)\s*Single payment\s*5% off Regular when paid in one instalment/);
  assert.match(bodyText(), /Regular Course Package38 Classes.*AED 1,330.*Single payment: AED 1,264 \(saves AED 66\)/);
  for (const label of ['Edit', 'Edit draft', 'Publish…', 'More actions', 'Discard draft', 'Deactivate', 'Duplicate revision 1']) {
    assert.equal(button(label), undefined, label);
  }
  assert.doesNotMatch(bodyText(), /History|Global pricing|Loaded from|Last saved/);
  await click(button('Preview syllabus PDF'));
  assert.deepEqual(calls('GET', onSale(PLAN_ID, 'pdf/'))[0].params, { disposition: 'inline', revision: 1 });
  await mounted.pop().unmount();

  serve({ [`GET ${onSale(PLAN_ID)}`]: { ...CHAPTER_WISE_ON_SALE, pricing: null, packages: null } });
  await open(`/plans/${PLAN_ID}`, BDE);
  assert.match(bodyText(), /Pricing is not set up yet, so the packages cannot be priced\./);
  assert.equal(button('Download syllabus PDF').disabled, true);
});

test('A plan that is not on sale, refused or failing says so', async () => {
  serve({ [`GET ${onSale(BRIDGE_ID)}`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such syllabus on sale.' }) });
  await open(`/plans/${BRIDGE_ID}`, BDE);
  assert.match(bodyText(), /This plan is not on sale/);
  assert.ok(link('Plans & Pricing'));
  await mounted.pop().unmount();

  serve({ [`GET ${onSale(BRIDGE_ID)}`]: () => fail(403, { detail: 'You do not have permission to perform this action.' }) });
  await open(`/plans/${BRIDGE_ID}`, BDE);
  assert.match(bodyText(), /You don't have access to plans and pricing\./);
  await mounted.pop().unmount();

  let answers = 0;
  serve({ [`GET ${onSale(BRIDGE_ID)}`]: () => (answers++ ? ok(bridgeOnSale()) : fail(500, { message: 'Server error.' })) });
  await open(`/plans/${BRIDGE_ID}`, BDE);
  assert.match(bodyText(), /Server error\./);
  await click(button('Try again'));
  assert.match(bodyText(), /0 of 10 days chosen/);
});

test('Access: Plans & Pricing opens for a BDE holding the catalogue, and for no one else', () => {
  assert.equal(canOpenPage(BDE, '/plans'), true);
  assert.equal(canOpenPage(BDE_WITHOUT, '/plans'), false);
  // An administrator holds the catalogue too, but quotes from Syllabus & Plans: /plans is the BDE workspace's.
  assert.equal(canOpenPage({ ...ADMIN, permissions: [...ADMIN.permissions, 'accounts.view_sales_catalogue'] }, '/plans'), false);
  assert.equal(canOpenPage(MENTOR, '/plans'), false);
  assert.equal(canOpenPage({ ...ROOT_MENTOR, permissions: [...ROOT_MENTOR.permissions, 'accounts.view_sales_catalogue'] }, '/plans'), false);
  // A BDE reaches nothing of the administrators' Sales Management.
  for (const path of ['/sales-syllabus', '/sales-pricing']) assert.equal(canOpenPage(BDE, path), false, path);
});

test('Access: Syllabus & Plans and Global Pricing open on their permissions, whatever the role holding them', () => {
  for (const path of ['/sales-syllabus', '/sales-pricing']) {
    assert.equal(canOpenPage(ADMIN, path), true, path);
    assert.equal(canOpenPage(ROOT_MENTOR, path), true, `${path}: a superuser holds them (D1)`);
    assert.equal(canOpenPage(ADMIN_WITHOUT, path), false, path);
    assert.equal(canOpenPage(MENTOR, path), false, path);
  }
});

// ------------------------------------------------------------------ quotes
const QUOTER = { id: 'bde', role: 'BDE', permissions: ['accounts.view_own_enquiries', 'accounts.view_sales_catalogue', 'accounts.create_sales_quotes'] };
const QUOTE_ADMIN = {
  id: 'admin', role: 'ADMIN',
  permissions: ['accounts.view_all_leads', 'accounts.view_sales_catalogue', 'accounts.create_sales_quotes', 'accounts.manage_sales_quotes'],
};
const QUOTES = '/api/sales/quotes/';
const ENQUIRIES = '/api/bde/enquiries/';
const LEAD_BDES = '/api/leads/bdes/';
const QUOTE_ID = '55555555-5555-4555-8555-555555555555';
const quoteAt = (path = '') => `${QUOTES}${QUOTE_ID}/${path}`;
const BALA = { id: 'bde', name: 'Bala BDE' };
const RIYA = { id: 'lead-1', parent_name: 'Riya Nair', student_name: 'Arjun' };
const ENQUIRY_ROWS = [
  { ...RIYA, grade: 6, phone: '+971 501234567', status: 'NEW' },
  { id: 'lead-2', parent_name: 'Omar Khan', student_name: 'Zara', grade: 7, phone: '+971 509876543', status: 'NEW' },
];
// A chapter-wise plan sold every way, Chapter Plan too.
const EVERY_WAY_ON_SALE = { ...CHAPTER_WISE_ON_SALE, plan_types: ['REGULAR', 'REVISION', 'CHAPTER_PLAN', 'REGULAR_REVISION'] };
const chapterBox = (n) => document.querySelector(`input[type="checkbox"][aria-label^="Chapter ${n}:"]`);
const radio = (text) => [...document.querySelectorAll('input[type="radio"]')].find((element) => clean(element.closest('label')?.textContent).startsWith(text));
const quotePosts = () => calls('POST', QUOTES);

// Grade 6, Regular + Revision, as the API answers it (backend sales.quotes.quote_data).
function quoteOf(extra = {}) {
  return {
    id: QUOTE_ID, reference: 'Q-000007', status: 'ISSUED', created_at: '2026-11-09T06:30:00+00:00', created_by: BALA, lead: RIYA, collection_mode: 'FULL', collection_intention_confirmed: true,
    syllabus: { id: PLAN_ID, title: 'Grade 6 CBSE', grade: 6, board: 'CBSE', structure: 'CHAPTER_WISE', syllabus_version: 'New Syllabus' },
    revision: 1, plan_type: 'REGULAR_REVISION', full_course: true, currency: 'AED', classes: '57', total_fee: '1995', payable_amount: '1929',
    pricing_version: 3, standard_fee: '45', offer_fee: '35', single_payment_percent: '5', single_payment_saving: '66', lines: PACKAGES,
    chapters: chaptersOf(GRADE_6, 'r1').map((chapter) => ({
      id: chapter.id, position: chapter.position, name: chapter.name, classes: String(Number(chapter.regular_classes) + Number(chapter.revision_classes)),
    })),
    cancelled_at: null, cancelled_by: null, cancel_reason: '',
    ...extra,
  };
}
const rowOf = (quote) => {
  const row = { ...quote, syllabus: { ...quote.syllabus } };
  for (const field of ['pricing_version', 'standard_fee', 'offer_fee', 'single_payment_percent', 'single_payment_saving', 'lines', 'chapters',
    'cancelled_at', 'cancelled_by', 'cancel_reason']) delete row[field];
  delete row.syllabus.syllabus_version;
  return row;
};
const BRIDGE_QUOTE = quoteOf({
  id: '66666666-6666-4666-8666-666666666666', reference: 'Q-000008', lead: null, status: 'CANCELLED',
  syllabus: { id: BRIDGE_ID, title: 'Grade 7 CBSE', grade: 7, board: 'CBSE', structure: 'BRIDGE_COURSE', syllabus_version: '' },
  plan_type: 'BRIDGE_COURSE', full_course: false, classes: '3.5', total_fee: '122.5', payable_amount: '116',
  created_by: { id: 'bde-3', name: 'Chitra BDE' },
});

async function typeText(element, value) {
  const prototype = element.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
    element.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
  await settle();
}

async function search(label, text, root = document.body) {
  const field = root.querySelector(`input[aria-label="${label}"]`);
  assert.ok(field, `no search ${label}`);
  await typeText(field, text);
  await fire(field.closest('form'), new window.Event('submit', { bubbles: true, cancelable: true }));
}

test('Prices: a quote is worked out as the API works it out -- two packages for Regular + Revision, chosen chapters, days or the whole course', () => {
  const grade6 = chaptersOf(GRADE_6, 'c');
  // Regular + Revision: two packages, each rounded on its own -- the Regular one's privilege only (the pricing names Regular).
  let preview = harness.quotePreview('REGULAR_REVISION', grade6, [], ON_SALE_PRICING, 'REGULAR', 'FULL');
  assert.deepEqual(preview.lines, PACKAGES);
  assert.deepEqual([preview.classes, preview.total_fee, preview.single_payment_saving, preview.payable_amount, preview.fullCourse],
    ['57', '1995', '66', '1929', true]);
  preview = harness.quotePreview('REVISION', grade6, [], ON_SALE_PRICING, 'REGULAR', 'FULL');
  assert.deepEqual([preview.lines.length, preview.classes, preview.total_fee, preview.single_payment_saving, preview.payable_amount],
    [1, '19', '665', '0', '665']);
  // A Chapter Plan: the chapters chosen, in the course's order, their Regular classes; no privilege names it.
  const plan = harness.chapterPlanSelection(grade6, ['c-6', 'c-1'], ON_SALE_PRICING);
  assert.deepEqual(plan.days.map((chapter) => chapter.position), [2, 7]);
  assert.deepEqual(plan.package, { plan_type: 'CHAPTER_PLAN', title: harness.chapterPlanTitle, classes: '10', fee_per_class: '35', total: '350',
    single_payment: null });
  // Even a pricing giving every package it may name the privilege (backend PRIVILEGE_PLAN_TYPES, a CHECK in the database).
  preview = harness.quotePreview('CHAPTER_PLAN', grade6, ['c-6', 'c-1'], { ...ON_SALE_PRICING, single_payment_plan_types: ['REGULAR', 'REVISION', 'BRIDGE_COURSE'] }, 'REGULAR', 'FULL');
  assert.deepEqual([preview.total_fee, preview.single_payment_saving, preview.payable_amount, preview.fullCourse], ['350', '0', '350', false]);
  // A Bridge Course: by the day, or -- no day, or every day -- the whole course.
  const days = daysOf('day');
  preview = harness.quotePreview('BRIDGE_COURSE', days, ['day-4', 'day-2'], ON_SALE_PRICING, 'REGULAR', 'FULL');
  assert.deepEqual([preview.lines[0].title, preview.classes, preview.total_fee, preview.single_payment_saving, preview.payable_amount, preview.fullCourse],
    [harness.selectedDaysTitle, '3.5', '122.5', '6.5', '116', false]);
  for (const ids of [[], days.map((day) => day.id)]) {
    preview = harness.quotePreview('BRIDGE_COURSE', days, ids, ON_SALE_PRICING, 'REGULAR', 'FULL');
    assert.deepEqual([preview.lines, preview.payable_amount, preview.fullCourse], [bridgeOnSale().packages, '333', true]);
  }
  // A whole course past 99.5 classes is summed whole: 105 + 50 classes, 3,675 less 5% is 3,491.25 -> 3,491.
  const long = [{ regular_classes: '60', revision_classes: '50', bridge_classes: null }, { regular_classes: '45', revision_classes: '0', bridge_classes: null }];
  preview = harness.quotePreview('REGULAR_REVISION', long, [], ON_SALE_PRICING, 'REGULAR', 'FULL');
  assert.deepEqual([preview.classes, preview.total_fee, preview.single_payment_saving, preview.payable_amount], ['155', '5425', '184', '5241']);
  // Fils kept to the end: 1.5 x 35.25 = 52.875, less 5% is 50.23125 -> 50, saving 2.875; payable 50.
  preview = harness.quotePreview('BRIDGE_COURSE', days, ['day-2'], { ...ON_SALE_PRICING, offer_fee: '35.25' }, 'REGULAR', 'FULL');
  assert.deepEqual([preview.total_fee, preview.single_payment_saving, preview.payable_amount], ['52.875', '2.875', '50']);
  assert.equal(harness.quotePreview('REGULAR', grade6, [], null, 'REGULAR', 'FULL'), null);
  for (const [fee, expected] of [['35.25', '53'], ['34.93', '52'], ['35', '53']]) {
    const rounded = harness.quotePreview('BRIDGE_COURSE', days, ['day-2'], { ...ON_SALE_PRICING, offer_fee: fee, single_payment_percent: '0' }, 'REGULAR', 'FULL');
    assert.equal(rounded.collection_amount, expected, 'whole AED rounds half up from the final package amount');
  }
  assert.deepEqual([quoteOf(), BRIDGE_QUOTE, { plan_type: 'BRIDGE_COURSE', full_course: true }, { plan_type: 'CHAPTER_PLAN' }].map(harness.quotePlanLabel),
    ['Regular + Revision', 'Bridge Course · Selected Chapters', 'Full Bridge Course', 'Chapter Plan · Regular classes']);
  assert.deepEqual([harness.enquiryLabel(RIYA), harness.enquiryLabel({ parent_name: 'Omar Khan', student_name: '' }), harness.enquiryLabel(null)],
    ['Riya Nair (parent of Arjun)', 'Omar Khan', '']);
});

const ENQUIRY = { ...RIYA, grade: 'Class 6', phone: '+971 501234567', phone_dial_code: '+971', phone_number: '501234567', status: 'NEW', bookings: [] };
const PLAN_STATE = `/api/sales/enquiries/${RIYA.id}/plan/`;
const enquiryPath = `/enquiries/${RIYA.id}?tab=plan-choosing`;
const emptyPlan = { lead: RIYA, latest_quote: null, current: null, locked: false, history: [] };
function studentApi(extra = {}) {
  serve({
    [`GET ${ENQUIRIES}${RIYA.id}/`]: ENQUIRY,
    [`GET ${PLAN_STATE}`]: emptyPlan,
    [`GET ${CATALOGUE}`]: list(CATALOGUE_ROWS),
    [`GET ${onSale(PLAN_ID)}`]: EVERY_WAY_ON_SALE,
    [`GET ${onSale(BRIDGE_ID)}`]: bridgeOnSale(),
    ...extra,
  });
}
const chooseCompletePayment = async () => { const option = radio('Single / Complete Payment'); if (option && !option.checked) await click(option); };
const selectSyllabus = async (title = 'Grade 6 CBSE') => click(button(`Select ${title}`));
const PAYMENT_BDE = { ...QUOTER, permissions: [...QUOTER.permissions, 'accounts.manage_initial_sales'] };
const SALE_URL = `/api/sales/enquiries/${RIYA.id}/sale/`;
const paymentPath = `/enquiries/${RIYA.id}?tab=sales`;
const saleQuote = (extra = {}) => quoteOf({ plan_type: 'CHAPTER_PLAN', class_mode: 'REVISION', classes: '10', total_fee: '500',
  payable_amount: '500', collection_amount: '500', single_payment_saving: '0', collection_mode: 'PARTIAL', ...extra });
const saleState = (extra = {}) => ({ enquiry_id: RIYA.id, quote: saleQuote(), sale: null, purchase: null,
  totals: { purchased_classes: '10', paid_classes: '0', unpaid_classes: '10', used_classes: '0', available_quota: '0',
    package_amount: '500', paid_amount: '0', remaining_amount: '500' }, payments: [], can_collect: true, stripe_configured: false,
  parent_email: 'parent@example.com', ...extra });
const startedSale = (extra = {}) => ({ id: 'initial-sale', kind: 'NEW', token_paid: '0', parent_email: 'parent@example.com', student: null,
  reservation_reference: null, expected_start_date: null, original_quote_id: QUOTE_ID, original_bde: BALA, ...extra });
const initialPayment = (extra = {}) => ({ id: 'initial-payment', purpose: 'TUITION', method: 'TRANSFER', method_label: 'Account Transfer',
  collection_mode: 'PARTIAL', amount: '300', currency: 'AED', classes: '6', status: 'SUCCEEDED', payment_date: '2026-11-09',
  recorded_by: BALA, transaction_reference: 'BANK-001', proof_name: 'receipt.png', proof_url: '/api/sales/payments/initial-payment/proof/', ...extra });
async function waitForAmount() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 230)); });
  await settle();
}

test('Without initial-sales permission the Sales tab cannot request or mutate financial data', async () => {
  studentApi({ [`GET ${SALE_URL}`]: saleState() });
  await open(paymentPath, QUOTER);
  assert.match(bodyText(), /do not have access to initial sales and payments/);
  assert.equal(calls('GET', SALE_URL).length, 0);
  assert.equal(button('Start New Sale'), undefined);
  assert.equal(button('Generate Stripe payment link'), undefined);
});

test('A refused foreign enquiry never loads its sale or offers collection controls', async () => {
  studentApi({ [`GET ${ENQUIRIES}${RIYA.id}/`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such enquiry.' }) });
  await open(paymentPath, PAYMENT_BDE);
  assert.equal(calls('GET', SALE_URL).length, 0);
  assert.equal(button('Start New Sale'), undefined);
  assert.equal(button('Generate Stripe payment link'), undefined);
});

test('Sales & Payment loads the immutable quote automatically and offers New or Token Sale without a catalogue request', async () => {
  studentApi({ [`GET ${SALE_URL}`]: saleState() });
  await open(paymentPath, PAYMENT_BDE);
  assert.match(bodyText(), /Selected quote.*Chapter Plan · Revision classes.*Purchased classes10.*AED 500/);
  assert.ok(radio('New Sale'));
  assert.ok(radio('Token Sale'));
  assert.equal(calls('GET', CATALOGUE).length, 0);
  assert.equal(button('Generate Stripe payment link'), undefined);
});

test('Initial direct tuition form calculates on the server, uploads a receipt and becomes read-only after enrollment', async () => {
  let state = saleState();
  studentApi({
    [`GET ${SALE_URL}`]: () => ok(state),
    [`POST ${SALE_URL}`]: () => ok(state = saleState({ sale: startedSale() })),
    [`GET ${SALE_URL}amount/`]: ({ params }) => { assert.equal(params.classes, '10'); return ok({ amount: '500', classes: '10', currency: 'AED' }); },
    [`POST ${SALE_URL}payments/`]: ({ data }) => {
      assert.equal(data.get('purpose'), 'TUITION'); assert.equal(data.get('collection_mode'), 'PARTIAL');
      assert.equal(data.get('method'), 'TRANSFER'); assert.equal(data.get('amount'), '500');
      assert.equal(data.get('payment_date'), '2026-01-01'); assert.equal(data.get('received_confirmed'), 'true');
      assert.equal(data.get('proof').name, 'receipt.png'); assert.ok(data.get('request_id'));
      state = saleState({ sale: startedSale({ student: { id: 'enrolled-student', student_code: 'EDP00018' } }),
        totals: { purchased_classes: '10', paid_classes: '10', unpaid_classes: '0', used_classes: '0', available_quota: '10', package_amount: '500', paid_amount: '500', remaining_amount: '0' },
        payments: [initialPayment({ amount: '500', classes: '10' })], can_collect: false });
      return ok({ payment: state.payments[0], state });
    },
  });
  await open(paymentPath, PAYMENT_BDE);
  await click(button('Start New Sale'));
  await waitForAmount();
  assert.match(bodyText(), /Amount payable: AED 500/);
  assert.equal(button('Generate Stripe payment link').disabled, true);
  await choose('payment-method', 'Account Transfer');
  assert.equal(button('Confirm received payment').disabled, true);
  await typeInto(input('payment-date'), '2026-01-01');
  const receipt = new File(['test PNG bytes'], 'receipt.png', { type: 'image/png' });
  Object.defineProperty(input('payment-proof'), 'files', { configurable: true, value: [receipt] });
  await fire(input('payment-proof'), new window.Event('change', { bubbles: true }));
  const confirm = [...document.querySelectorAll('input[type="checkbox"]')].find((box) => box.closest('label')?.textContent.includes('actually been received'));
  await click(confirm);
  assert.equal(button('Confirm received payment').disabled, false);
  await fire(button('Confirm received payment').closest('form'), new window.Event('submit', { bubbles: true, cancelable: true }));
  assert.match(bodyText(), /EDP00018.*Enrollment complete/);
  assert.equal(button('Confirm received payment'), undefined);
  assert.equal(button('Generate Stripe payment link'), undefined);
  assert.match(bodyText(), /Initial payment history.*AED 500/);
});

test('Token reservation requires an expected start date and requests exactly AED 100 with zero classes', async () => {
  let posted;
  studentApi({ [`GET ${SALE_URL}`]: saleState(), [`POST ${SALE_URL}`]: ({ data }) => {
    posted = data;
    return ok(saleState({ sale: startedSale({ kind: 'TOKEN', reservation_reference: 'TOK000001', expected_start_date: data.expected_start_date }) }));
  }, [`GET ${SALE_URL}amount/`]: ({ params }) => {
    assert.deepEqual(params, { purpose: 'TOKEN', collection_mode: 'FULL', classes: '0' });
    return ok({ amount: '100', classes: '0', currency: 'AED' });
  } });
  await open(paymentPath, PAYMENT_BDE);
  await click(radio('Token Sale'));
  await chooseCompletePayment();
  assert.equal(input('token-start-date').required, true);
  await typeInto(input('token-start-date'), '2027-01-10');
  await click(button('Start token reservation'));
  await waitForAmount();
  assert.equal(posted.expected_start_date, '2027-01-10');
  assert.match(bodyText(), /TOK000001.*2027-01-10/);
  assert.match(bodyText(), /Collect token · AED 100.*No classes allocated/);
  assert.equal(input('paid-classes'), null);
  assert.doesNotMatch(bodyText(), /Enrollment complete/);
});

test('An issued complete-payment quote is read-only; changing intention requires a reviewed explicit replacement', async () => {
  let state = saleState({ sale: startedSale(), quote: saleQuote({ collection_mode: 'FULL', single_payment_saving: '25', payable_amount: '475', collection_amount: '475' }) });
  const replacement = `/api/sales/enquiries/${RIYA.id}/installment-quote/`;
  studentApi({ [`GET ${SALE_URL}`]: () => ok(state), [`GET ${SALE_URL}amount/`]: { amount: '475', classes: '10', currency: 'AED' },
    [`GET ${replacement}`]: ({ params }) => {
      assert.deepEqual(params, { quote_id: QUOTE_ID, collection_mode: 'PARTIAL' });
      return ok({ quote_id: QUOTE_ID, collection_mode: 'PARTIAL', collection_subtotal: '500', collection_discount: '0', collection_amount: '500', pricing_version: 3 });
    },
    [`POST ${replacement}`]: ({ data }) => {
      assert.deepEqual(data, { quote_id: QUOTE_ID, collection_mode: 'PARTIAL' });
      state = saleState({ sale: startedSale(), quote: saleQuote({ id: 'replacement-quote', supersedes: QUOTE_ID }) });
      return ok(state.quote);
    },
  });
  await open(paymentPath, PAYMENT_BDE);
  await waitForAmount();
  assert.equal(document.getElementById('collection-mode'), null);
  assert.equal(input('paid-classes').readOnly, true);
  await click(button('Change collection intention'));
  assert.equal(button('Issue replacement quote', topDialog()).disabled, true);
  assert.match(clean(topDialog().textContent), /original quote and its history remain preserved/);
  await choose('replacement-collection-mode', 'Partial Payment');
  assert.match(clean(topDialog().textContent), /Replacement package: AED 500/);
  assert.equal(calls('POST', replacement).length, 0);
  await click(button('Issue replacement quote', topDialog()));
  assert.equal(calls('POST', replacement).length, 1);
  assert.equal(input('paid-classes').readOnly, false);
});

test('Generating a Stripe link remains pending and exposes sharing without marking a student enrolled', async () => {
  const pending = initialPayment({ method: 'STRIPE', method_label: 'Stripe', status: 'PENDING', amount: '500', classes: '10',
    proof_url: null, payment_url: 'https://checkout.stripe.com/c/pay/test-session' });
  studentApi({ [`GET ${SALE_URL}`]: saleState({ sale: startedSale(), stripe_configured: true }),
    [`GET ${SALE_URL}amount/`]: { amount: '500', classes: '10', currency: 'AED' },
    [`POST ${SALE_URL}payments/`]: ({ data }) => { assert.equal(data.get('method'), 'STRIPE'); return ok({ payment: pending,
      state: saleState({ sale: startedSale(), payments: [pending], stripe_configured: true }) }); },
  });
  await open(paymentPath, PAYMENT_BDE);
  await waitForAmount();
  await click(button('Generate Stripe payment link'));
  assert.match(bodyText(), /Awaiting payment/);
  assert.ok(button('Copy payment link'));
  assert.ok(document.querySelector('a[href*="checkout.stripe.com"]') || [...document.querySelectorAll('a')].some((a) => a.href.includes('wa.me') && decodeURIComponent(a.href).includes('checkout.stripe.com')));
  assert.doesNotMatch(bodyText(), /Enrollment complete/);
  assert.equal(input('payment-proof'), null);
});
const classModeRadio = (mode) => document.querySelector(`input[name="chapter-class-mode"][value="${mode}"]`);

test('BDE Autopay reviews all dated class allocations on the server before creating the combined paid Checkout', async () => {
  let reviewed;
  const reviewedRows = [{ position: 0, classes: '2', amount: '100', due_at: null },
    { position: 1, classes: '8', amount: '400', due_at: '2027-01-10T06:00:00Z' }];
  const pending = initialPayment({ method: 'STRIPE', method_label: 'Stripe', status: 'PENDING', amount: '100', classes: '2',
    proof_url: null, payment_url: 'https://checkout.stripe.com/c/pay/autopay-test' });
  studentApi({ [`GET ${SALE_URL}`]: saleState({ sale: startedSale(), quote: saleQuote({ collection_mode: 'AUTOPAY' }), billing_timezone: 'Asia/Dubai', stripe_configured: true, autopay_configured: true }),
    [`GET ${SALE_URL}amount/`]: { amount: '500', classes: '10', currency: 'AED' },
    [`POST ${SALE_URL}autopay/preview/`]: ({ data }) => { reviewed = data; return ok({ quote_id: QUOTE_ID, classes: '10', package_amount: '500', billing_timezone: 'Asia/Dubai', installments: reviewedRows, review_token: 'server-review', checkout_available: true }); },
    [`POST ${SALE_URL}autopay/`]: ({ data }) => {
      assert.equal(data.review_token, 'server-review'); assert.ok(data.request_id);
      assert.deepEqual(data.installments, reviewed.installments);
      assert.equal('amount' in data, false, 'the client never supplies a trusted schedule price');
      return ok(saleState({ sale: startedSale(), quote: saleQuote({ collection_mode: 'AUTOPAY' }), payments: [pending], stripe_configured: true }));
    },
  });
  await open(paymentPath, PAYMENT_BDE);
  assert.equal(document.getElementById('collection-mode'), null);
  assert.match(bodyText(), /Asia\/Dubai/);
  assert.equal(input('payment-proof'), null);
  assert.equal(button('Confirm schedule & generate Stripe Checkout'), undefined);
  await typeInto(input('autopay-initial-classes'), '2');
  await typeInto(input('autopay-classes-0'), '8');
  await typeInto(input('autopay-due-0'), '2027-01-10T10:00');
  await fire(button('Review complete schedule').closest('form'), new window.Event('submit', { bubbles: true, cancelable: true }));
  assert.match(bodyText(), /Review · 10 classes · AED 500.*Initial payment · 2 classesAED 100.*Installment 1 · 8 classesAED 400/);
  assert.equal(calls('POST', `${SALE_URL}autopay/`).length, 0);
  await click(button('Confirm schedule & generate Stripe Checkout'));
  assert.match(bodyText(), /Awaiting payment/);
  assert.doesNotMatch(bodyText(), /Enrollment complete/);
});

test('Editing an Autopay schedule invalidates its review and failed validation cannot create Checkout', async () => {
  studentApi({ [`GET ${SALE_URL}`]: saleState({ sale: startedSale(), quote: saleQuote({ collection_mode: 'AUTOPAY' }), billing_timezone: 'Asia/Dubai' }),
    [`GET ${SALE_URL}amount/`]: { amount: '500', classes: '10', currency: 'AED' },
    [`POST ${SALE_URL}autopay/preview/`]: () => fail(400, { error: 'INVALID_SCHEDULE', message: 'Cover exactly the package classes.' }),
  });
  await open(paymentPath, PAYMENT_BDE); assert.equal(document.getElementById('collection-mode'), null);
  await typeInto(input('autopay-initial-classes'), '2'); await typeInto(input('autopay-classes-0'), '9'); await typeInto(input('autopay-due-0'), '2027-01-10T10:00');
  await fire(button('Review complete schedule').closest('form'), new window.Event('submit', { bubbles: true, cancelable: true }));
  assert.match(bodyText(), /Cover exactly the package classes/);
  assert.equal(button('Confirm schedule & generate Stripe Checkout'), undefined);
  await click(button('Add installment'));
  assert.ok(input('autopay-classes-1'));
  await click(button('Remove installment 2'));
  assert.equal(input('autopay-classes-1'), null);
});

test('Autopay history is visible after enrollment while BDE collection controls remain absent', async () => {
  const agreement = { id: 'agreement', status: 'ACTIVE', setup_status: 'READY', setup_message: '', billing_timezone: 'Asia/Dubai',
    creator: { name: 'Bala', role: 'BDE' }, source: 'BDE_INITIAL', package_amount: '500', remaining_amount: '400', next_collection_at: '2027-01-10T06:00:00Z',
    card_brand: 'visa', card_last4: '4242', stripe_customer_id: 'cus_test', stripe_payment_method_id: 'pm_test', installments: [
      { id: 'initial', position: 0, classes: '2', amount: '100', status: 'PAID', due_at: null, attempts: [] },
      { id: 'next', position: 1, classes: '8', amount: '400', status: 'FAILED', due_at: '2027-01-10T06:00:00Z',
        attempts: [{ id: 'attempt', number: 1, status: 'FAILED', created_at: '2027-01-10T06:00:00Z', error_code: 'card_declined', stripe_payment_intent_id: 'pi_test' }] },
    ] };
  studentApi({ [`GET ${SALE_URL}`]: saleState({ sale: startedSale({ student: { id: 'student', student_code: 'EDP00018' } }), autopay: agreement }) });
  await open(paymentPath, PAYMENT_BDE);
  assert.match(bodyText(), /AutopayACTIVE.*Bala · BDE.*AED 400.*4242/);
  assert.match(bodyText(), /unpaid installment blocks later collections/);
  assert.equal(input('collection-mode'), null);
  assert.equal(button('Generate Stripe payment link'), undefined);
  assert.equal(button('Generate initial Checkout again'), undefined);
});

test('Stripe Billing history shows independent outstanding invoices and provider recovery without BDE controls', async () => {
  const agreement = { id: 'native-agreement', collection_engine: 'STRIPE_BILLING', billing_status: 'PROVISIONED',
    billing_message: '', status: 'ACTIVE', setup_status: 'READY', billing_timezone: 'Asia/Dubai',
    stripe_subscription_id: 'sub_native', stripe_subscription_status: 'past_due', stripe_schedule_id: 'sub_sched_native',
    stripe_schedule_status: 'active', next_retry_at: '2027-01-28T06:00:00Z',
    creator: { name: 'Bala', role: 'BDE' }, source: 'BDE_INITIAL', package_amount: '500', remaining_amount: '250',
    next_collection_at: '2027-02-10T06:00:00Z', card_brand: 'visa', card_last4: '4242', stripe_customer_id: 'cus_test',
    installments: [
      { id: 'initial', position: 0, classes: '2', amount: '100', status: 'PAID', due_at: null, attempts: [] },
      { id: 'december', position: 1, classes: '3', amount: '150', status: 'FAILED', due_at: '2026-12-10T06:00:00Z',
        stripe_invoice_id: 'in_december', stripe_invoice_number: 'EDP-DEC', stripe_invoice_status: 'open',
        next_payment_attempt: '2027-01-28T06:00:00Z', attempts: [] },
      { id: 'january', position: 2, classes: '3', amount: '150', status: 'PAID', due_at: '2027-01-10T06:00:00Z',
        stripe_invoice_id: 'in_january', stripe_invoice_number: 'EDP-JAN', stripe_invoice_status: 'paid', attempts: [] },
      { id: 'february', position: 3, classes: '2', amount: '100', status: 'SCHEDULED', due_at: '2027-02-10T06:00:00Z', attempts: [] },
    ] };
  studentApi({ [`GET ${SALE_URL}`]: saleState({ sale: startedSale({ student: { id: 'student', student_code: 'EDP00018' } }), autopay: agreement }) });
  await open(paymentPath, PAYMENT_BDE);
  assert.match(bodyText(), /Stripe Billing/);
  assert.match(bodyText(), /past_due/);
  assert.match(bodyText(), /EDP-DEC · open/);
  assert.match(bodyText(), /EDP-JAN · paid/);
  assert.match(bodyText(), /sub_native · sub_sched_native/);
  assert.doesNotMatch(bodyText(), /unpaid installment blocks later collections/);
  assert.equal(button('Generate Stripe payment link'), undefined);
  assert.equal(input('collection-mode'), null);
  assert.equal(calls('POST', `${SALE_URL}payments/`).length, 0);
});

test('Parent authentication confirms the existing PaymentIntent through Stripe and never grants quota in the browser', async () => {
  let confirmation;
  window.Stripe = (key) => {
    assert.equal(key, 'pk_test_fixture');
    return { confirmCardPayment: async (...args) => { confirmation = args; return { paymentIntent: { status: 'succeeded' } }; } };
  };
  serve({ 'GET /api/sales/autopay/actions/private-fixture/': {
    status: 'REQUIRES_CUSTOMER_ACTION', needs_action: true, amount: '150', package_amount: '500', currency: 'AED',
    billing_timezone: 'Asia/Dubai', consent_text: 'Agreed card collections', terms_url: 'https://eduport.test/terms',
    schedule: [{ position: 1, amount: '150', classes: '3', due_at: '2027-01-10T06:00:00Z' }],
    publishable_key: 'pk_test_fixture', client_secret: 'pi_fixture_secret', payment_method_id: 'pm_fixture',
  } });
  try {
    await open('/autopay/confirm/private-fixture', PAYMENT_BDE);
    await click(button('Authenticate AED 150'));
    assert.deepEqual(confirmation, ['pi_fixture_secret', { payment_method: 'pm_fixture' }]);
    assert.match(bodyText(), /Authentication submitted.*once Stripe verifies the payment/);
    assert.equal(globalThis.__salesApi.calls.filter((entry) => entry.method === 'POST').length, 0);
    assert.doesNotMatch(bodyText(), /Enrollment complete|quota credited/);
  } finally { delete window.Stripe; }
});

test('Chapter Plan mode switches preserve chapter ids, update the count column and recalculate the quote', async () => {
  studentApi();
  await open(enquiryPath, QUOTER);
  await selectSyllabus();
  await chooseCompletePayment();
  assert.equal(classModeRadio('REGULAR'), null);
  await click(radio('Chapter Plan'));
  await chooseCompletePayment();
  assert.equal(classModeRadio('REGULAR').checked, true);
  assert.equal(classModeRadio('REVISION').checked, false);
  await click(chapterBox(1));
  await chooseCompletePayment();
  await click(chapterBox(2));
  await chooseCompletePayment();
  assert.ok(headers().includes('Regular classes'));
  assert.match(bodyText(), /Chapter Plan PackageAED 315.*9 Classes × AED 35/);
  await click(classModeRadio('REVISION'));
  assert.equal(chapterBox(1).checked, true);
  assert.equal(chapterBox(2).checked, true);
  assert.ok(headers().includes('Revision classes'));
  assert.equal(headers().includes('Regular classes'), false);
  assert.equal(clean(rows()[0].querySelector('td:last-child').textContent), '2');
  assert.match(bodyText(), /Chapter Plan PackageAED 140.*4 Classes × AED 35/);
  await click(classModeRadio('REGULAR'));
  assert.equal(chapterBox(1).checked, true);
  assert.equal(chapterBox(2).checked, true);
  assert.match(bodyText(), /Chapter Plan PackageAED 315.*9 Classes × AED 35/);
  await click(button('Change syllabus'));
  await selectSyllabus();
  await chooseCompletePayment();
  assert.equal(chapterBox(1).checked, true);
  assert.equal(classModeRadio('REGULAR').checked, true);
});

test('Chapter Plan Select all and Clear work in both modes; the toggle is absent from every other plan', async () => {
  studentApi();
  await open(enquiryPath, QUOTER);
  await selectSyllabus();
  await chooseCompletePayment();
  await click(radio('Chapter Plan'));
  await chooseCompletePayment();
  for (const [mode, classes] of [['REGULAR', '38'], ['REVISION', '19']]) {
    await click(classModeRadio(mode));
    await click(button('Select all'));
    assert.equal([...document.querySelectorAll('input[type="checkbox"]')].every((box) => box.checked), true);
    assert.match(bodyText(), new RegExp(`10 of 10 chapters chosen.*${classes} Classes × AED 35`));
    await click(button('Clear'));
    assert.equal([...document.querySelectorAll('input[type="checkbox"]')].some((box) => box.checked), false);
    assert.equal(classModeRadio(mode).checked, true);
    assert.equal(button('Create quote…').disabled, true);
  }
  for (const plan of ['Regular Only', 'Revision Only', 'Regular + Revision']) {
    await click(radio(plan));
    assert.equal(classModeRadio('REGULAR'), null);
    assert.equal(classModeRadio('REVISION'), null);
  }
  await click(button('Change syllabus'));
  await selectSyllabus('Grade 7 CBSE');
  await chooseCompletePayment();
  for (const plan of ['Full Bridge Course', 'Selected Chapters']) {
    await click(radio(plan));
    assert.equal(classModeRadio('REGULAR'), null);
    assert.equal(classModeRadio('REVISION'), null);
  }
});

test('Missing, invalid and zero Revision counts block quoting without falling back to Regular or dropping chapters', async () => {
  for (const invalid of [null, '-1', '0.25', '100', '0']) {
    const chapters = EVERY_WAY_ON_SALE.chapters.map((chapter) => ({ ...chapter, revision_classes: invalid }));
    studentApi({ [`GET ${onSale(PLAN_ID)}`]: { ...EVERY_WAY_ON_SALE, chapters } });
    await open(enquiryPath, QUOTER);
    await selectSyllabus();
  await chooseCompletePayment();
    await click(radio('Chapter Plan'));
  await chooseCompletePayment();
    await click(chapterBox(1));
  await chooseCompletePayment();
    await click(classModeRadio('REVISION'));
    assert.equal(chapterBox(1).checked, true);
    assert.equal(button('Create quote…').disabled, true);
    assert.equal(headers().includes('Regular classes'), false);
    assert.match(bodyText(), invalid === '0' ? /no Revision classes/ : /Revision is unavailable/);
    if (invalid !== '0') assert.match(clean(rows()[0].textContent), /Revision unavailable/);
    await click(classModeRadio('REGULAR'));
    assert.equal(chapterBox(1).checked, true);
    assert.equal(button('Create quote…').disabled, false);
    await mounted.pop().unmount();
  }
});

test('Chapter Plan Revision request pins mode, chapters, revision and Admin pricing; confirmation and saved detail show Revision', async () => {
  const issued = quoteOf({ plan_type: 'CHAPTER_PLAN', class_mode: 'REVISION', full_course: false, is_current: true,
    classes: '4', total_fee: '141', payable_amount: '141', single_payment_saving: '0',
    lines: [{ plan_type: 'CHAPTER_PLAN', title: 'Chapter Plan Package', classes: '4', fee_per_class: '35.25', total: '141', single_payment: null }],
    chapters: EVERY_WAY_ON_SALE.chapters.slice(0, 2).map((chapter) => ({ id: chapter.id, position: chapter.position, name: chapter.name, classes: '2', revision_classes: '2' })) });
  studentApi({ [`GET ${onSale(PLAN_ID)}`]: { ...EVERY_WAY_ON_SALE, pricing: { ...ON_SALE_PRICING, offer_fee: '35.25' } },
    [`POST ${QUOTES}`]: issued, [`GET ${quoteAt()}`]: issued });
  const page = await open(enquiryPath, QUOTER);
  await selectSyllabus();
  await chooseCompletePayment();
  await click(radio('Chapter Plan'));
  await chooseCompletePayment();
  await click(chapterBox(1));
  await chooseCompletePayment();
  await click(chapterBox(2));
  await chooseCompletePayment();
  await click(classModeRadio('REVISION'));
  assert.match(bodyText(), /Chapter Plan PackageAED 141.*4 Classes/);
  await click(button('Create quote…'));
  assert.match(clean(topDialog().textContent), /Chapter Plan · Revision classes/);
  await click(button('Issue quote', topDialog()));
  assert.deepEqual(quotePosts()[0].data, { syllabus: PLAN_ID, revision: 1, plan_type: 'CHAPTER_PLAN', class_mode: 'REVISION', collection_mode: 'FULL',
    chapter_ids: EVERY_WAY_ON_SALE.chapters.slice(0, 2).map((chapter) => chapter.id), lead: RIYA.id, replaces: null, pricing_version: ON_SALE_PRICING.version });
  assert.match(bodyText(), /Current selected plan.*Chapter Plan · Revision classes/);
  assert.ok(headers().includes('Revision classes'));
  assert.equal(headers().includes('Regular classes'), false);
  await click(button('Edit / change plan'));
  assert.equal(classModeRadio('REVISION').checked, true);
  assert.equal(chapterBox(1).checked, true);
  assert.equal(chapterBox(2).checked, true);
  await page.go(`/quotes/${QUOTE_ID}`);
  await settle();
  assert.match(bodyText(), /Quote Q-000007.*Chapter Plan · Revision classes/);
  assert.match(bodyText(), /4 Classes × AED 35.25/);
});

test('Syllabus cards use catalogue totals and enabled plans, with a distinct Bridge Course structure', async () => {
  const grade9 = { ...CATALOGUE_ROWS[0], title: 'Grade 9 CBSE', grade: 9, plan_types: ['REGULAR', 'REVISION', 'CHAPTER_PLAN', 'REGULAR_REVISION'],
    totals: { regular: '79', revision: '41', bridge: null } };
  const bridge = { ...CATALOGUE_ROWS[1], totals: { regular: null, revision: null, bridge: '30' } };
  studentApi({ [`GET ${CATALOGUE}`]: list([bridge, grade9]) });
  await open(enquiryPath, QUOTER);
  const cards = [...document.querySelectorAll('ul[aria-label="Plans on sale"] article')];
  assert.equal(cards.length, 2);
  assert.equal(document.querySelector('table'), null, 'the enquiry catalogue uses cards at desktop widths too');
  assert.match(clean(cards[0].textContent), /Grade 7 CBSEBridge Course.*30 classes/);
  assert.doesNotMatch(clean(cards[0].textContent), /Regular|Revision|Plan options|Full Bridge Course|Selected Chapters/);
  assert.match(clean(cards[1].textContent), /Grade 9 CBSEChapter-wise.*120 classes.*79 Regular · 41 Revision/);
  const badges = cards[1].querySelector('[aria-label="Plan options for Grade 9 CBSE"]');
  assert.deepEqual([...badges.querySelectorAll('[data-slot="badge"]')].map((badge) => clean(badge.textContent)),
    ['Regular', 'Revision', 'Chapter Plan', 'Regular + Revision']);
  assert.equal(calls('GET', CATALOGUE).length, 1);
  assert.equal(calls('GET', onSale(PLAN_ID)).length, 0, 'cards need no detail requests');
  await selectSyllabus('Grade 7 CBSE');
  await chooseCompletePayment();
  assert.deepEqual([...document.querySelectorAll('input[name="quote-plan-type"]')].map((el) => el.value), ['full', 'selected']);
  await mounted.pop().unmount();

  studentApi({ [`GET ${CATALOGUE}`]: list([{ ...grade9, plan_types: ['REVISION'], totals: { regular: '1.5', revision: '2', bridge: null } }]),
    [`GET ${onSale(PLAN_ID)}`]: { ...EVERY_WAY_ON_SALE, title: grade9.title, grade: 9, revision: 4, plan_types: ['REVISION'] } });
  await open(enquiryPath, QUOTER);
  const card = document.querySelector('ul[aria-label="Plans on sale"] article');
  assert.match(clean(card.textContent), /3.5 classes.*1.5 Regular · 2 Revision/);
  assert.deepEqual([...card.querySelectorAll('[aria-label^="Plan options"] [data-slot="badge"]')].map((badge) => clean(badge.textContent)), ['Revision']);
  await selectSyllabus(grade9.title);
  await chooseCompletePayment();
  assert.deepEqual([...document.querySelectorAll('input[name="quote-plan-type"]')].map((el) => el.value), ['REVISION']);
  assert.match(bodyText(), /Revision 4/);
});

test('Syllabus card search, structure, board, grade and pagination retain the enquiry tab', async () => {
  studentApi({ [`GET ${CATALOGUE}`]: { count: 26, results: CATALOGUE_ROWS } });
  const page = await open(enquiryPath, QUOTER);
  await click(button('Next'));
  assert.equal(calls('GET', CATALOGUE).at(-1).params.page, 2);
  const search = document.querySelector('input[aria-label="Search plans"]');
  await typeInto(search, 'Grade 7');
  await fire(search.closest('form'), new window.Event('submit', { bubbles: true, cancelable: true }));
  assert.deepEqual(calls('GET', CATALOGUE).at(-1).params, { page: 1, page_size: 25, q: 'Grade 7' });
  await choose('Filter by structure', 'Bridge Course');
  await choose('Filter by board', 'CBSE');
  await choose('Filter by grade', 'Grade 7');
  assert.deepEqual(calls('GET', CATALOGUE).at(-1).params,
    { page: 1, page_size: 25, q: 'Grade 7', structure: 'BRIDGE_COURSE', board: 'CBSE', grade: '7' });
  assert.equal(new URLSearchParams(page.location().search).get('tab'), 'plan-choosing');
  await click(button('Clear all filters'));
  assert.deepEqual(calls('GET', CATALOGUE).at(-1).params, { page: 1, page_size: 25 });
  assert.equal(search.value, '');
  assert.equal(new URLSearchParams(page.location().search).get('tab'), 'plan-choosing');
});

test('Compact syllabus card actions preview and download each pinned PDF, sharing only the existing WhatsApp message', async () => {
  studentApi(Object.fromEntries([PLAN_ID, BRIDGE_ID].map((id) => [`GET ${onSale(id, 'pdf/')}`, () => Promise.resolve({
    data: new Blob(['%PDF-']), headers: { 'content-disposition': `attachment; filename="${id}.pdf"` },
  })])));
  await open(enquiryPath, QUOTER);
  const cards = [...document.querySelectorAll('ul[aria-label="Plans on sale"] article')];
  for (const [index, id] of [PLAN_ID, BRIDGE_ID].entries()) {
    const card = cards[index];
    const whatsapp = card.querySelector('a[aria-label$="through WhatsApp"]');
    assert.equal(clean(whatsapp.textContent), 'Share');
    const url = new URL(whatsapp.href);
    assert.equal(url.hostname, 'wa.me');
    assert.equal(url.pathname, '/971501234567');
    assert.match(url.searchParams.get('text'), /Hello Riya Nair.*I will attach the syllabus PDF/);
    assert.doesNotMatch(url.searchParams.get('text'), /https?:|localhost|blob:|\/api\//);
    await click(button('Preview', card));
    assert.ok(document.querySelector('iframe[src^="blob:"]'));
    assert.deepEqual(calls('GET', onSale(id, 'pdf/')).at(-1).params, { disposition: 'inline', revision: 1 });
    await fire(topDialog(), new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await click(button('Download', card));
    assert.equal(saved.at(-1).name, `${id}.pdf`);
    assert.deepEqual(calls('GET', onSale(id, 'pdf/')).at(-1).params, { revision: 1 });
  }
});

test('Student quote: select syllabus first, then its enabled plan; fixed student and pricing are confirmed before saving', async () => {
  studentApi({ [`POST ${QUOTES}`]: quoteOf({ is_current: true }) });
  const page = await open(enquiryPath, QUOTER);
  assert.equal(radio('Regular Only'), undefined);
  assert.equal(button('Create quote…'), undefined);
  await selectSyllabus();
  await chooseCompletePayment();
  assert.equal(radio('Regular Only').checked, false);
  assert.equal(button('Create quote…').disabled, true);
  await click(radio('Regular + Revision'));
  await chooseCompletePayment();
  assert.match(bodyText(), /Revision Course .*PackageAED 665/);
  assert.match(bodyText(), /57 Classes.*AED 1,995.*AED 66.*AED 1,929/);
  await click(button('Create quote…'));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /For Riya Nair \(parent of Arjun\)/);
  assert.equal(radio('No enquiry'), undefined);
  assert.equal(quotePosts().length, 0);
  await click(button('Issue quote', dialog));
  assert.deepEqual(quotePosts()[0].data, { syllabus: PLAN_ID, revision: 1, plan_type: 'REGULAR_REVISION', collection_mode: 'FULL', chapter_ids: [], lead: RIYA.id, replaces: null, pricing_version: ON_SALE_PRICING.version });
  assert.equal(page.location().pathname, `/enquiries/${RIYA.id}`);
  assert.match(bodyText(), /Current selected plan.*Q-000007.*57 Classes/);
  assert.match(bodyText(), /Quote history.*Q-000007/);
  assert.ok(button('Edit / change plan'));
  assert.ok(button('Download quote PDF'));
});

test('Student Chapter Plan: scoped chapters, calculation and validation; selections survive retry and back navigation', async () => {
  let posts = 0;
  studentApi({ [`POST ${QUOTES}`]: () => posts++ ? ok(quoteOf({ plan_type: 'CHAPTER_PLAN', full_course: false, is_current: true })) : fail(400, { error: 'VALIDATION_ERROR', message: 'Choose one of your own enquiries.', fields: { lead: ['Choose one of your own enquiries.'] } }) });
  await open(enquiryPath, QUOTER);
  await selectSyllabus();
  await chooseCompletePayment();
  await click(radio('Chapter Plan'));
  await chooseCompletePayment();
  assert.equal(button('Create quote…').disabled, true);
  await click(chapterBox(7));
  await chooseCompletePayment();
  await click(chapterBox(2));
  await chooseCompletePayment();
  assert.match(bodyText(), /2 of 10 chapters chosen.*Chapter Plan PackageAED 350.*10 Classes × AED 35/);
  await click(button('Change syllabus'));
  await selectSyllabus();
  await chooseCompletePayment();
  assert.equal(chapterBox(7).checked, true);
  assert.equal(chapterBox(2).checked, true);
  await click(button('Create quote…'));
  await click(button('Issue quote', topDialog()));
  assert.deepEqual(quotePosts()[0].data.chapter_ids, ['r1-1', 'r1-6']);
  assert.equal(quotePosts()[0].data.lead, RIYA.id);
  assert.match(clean(topDialog().textContent), /Choose one of your own enquiries/);
  await click(button('Issue quote', topDialog()));
  assert.match(bodyText(), /Current selected plan/);
});

test('Student Bridge Course: Full Bridge Course or Selected Chapters; stale revision blocks quoting until reload', async () => {
  let current = bridgeOnSale();
  let posts = 0;
  studentApi({
    [`GET ${onSale(BRIDGE_ID)}`]: () => ok(current),
    [`POST ${QUOTES}`]: () => posts++ ? ok(quoteOf({ syllabus: { ...BRIDGE_QUOTE.syllabus }, plan_type: 'BRIDGE_COURSE', is_current: true })) : fail(409, { error: 'REVISION_CHANGED', message: 'The syllabus was updated. Reload and select the plan again.', revision: 2 }),
  });
  await open(enquiryPath, QUOTER);
  await selectSyllabus('Grade 7 CBSE');
  await chooseCompletePayment();
  assert.deepEqual([...document.querySelectorAll('input[name="quote-plan-type"]')].map((el) => el.value), ['full', 'selected']);
  await click(radio('Full Bridge Course'));
  await chooseCompletePayment();
  assert.match(bodyText(), /Bridge Course PackageAED 350.*10 Classes.*AED 333/);
  await click(radio('Selected Chapters'));
  await chooseCompletePayment();
  assert.doesNotMatch(bodyText(), /Choose at least one chapter for the Chapter Plan/);
  assert.equal(button('Create quote…').disabled, true);
  await click(chapterBox(4));
  await chooseCompletePayment();
  await click(chapterBox(2));
  await chooseCompletePayment();
  assert.match(bodyText(), /3.5 Classes.*AED 123.*AED 116/);
  await click(button('Create quote…'));
  current = bridgeOnSale({ revision: 2, prefix: 'r2' });
  await click(button('Issue quote', topDialog()));
  assert.equal(topDialog(), undefined);
  assert.equal(button('Create quote…').disabled, true);
  assert.deepEqual(quotePosts()[0].data.chapter_ids, ['day-2', 'day-4']);
  await click(button('Try again'));
  await click(radio('Selected Chapters'));
  await chooseCompletePayment();
  assert.equal(chapterBox(2).checked, false);
  await click(button('Select all'));
  await chooseCompletePayment();
  assert.match(bodyText(), /All chapters selected · Full course/);
  await click(button('Create quote…'));
  assert.match(clean(topDialog().textContent), /full course/);
  await click(button('Issue quote', topDialog()));
  assert.equal(quotePosts()[1].data.revision, 2);
  assert.deepEqual(quotePosts()[1].data.chapter_ids, daysOf('r2').map((day) => day.id));
});

test('Common catalogue cannot create a quote; student selection requires permissions and pricing', async () => {
  studentApi();
  await open(`/plans/${PLAN_ID}`, QUOTER);
  assert.equal(button('Create quote…'), undefined);
  assert.ok(link('My Enquiries'));
  await mounted.pop().unmount();
  await open(enquiryPath, BDE);
  assert.equal(button('Plan Choosing'), undefined);
  assert.equal(calls('GET', PLAN_STATE).length, 0);
  await mounted.pop().unmount();
  studentApi({ [`GET ${onSale(PLAN_ID)}`]: { ...EVERY_WAY_ON_SALE, pricing: null, packages: null } });
  await open(enquiryPath, QUOTER);
  await selectSyllabus();
  await chooseCompletePayment();
  await click(radio('Regular Only'));
  await chooseCompletePayment();
  assert.equal(button('Create quote…').disabled, true);
  assert.match(bodyText(), /Pricing is not set up yet/);
});

test('Saved student quote: replacement preserves history and sends the expected current quote', async () => {
  const old = quoteOf({ is_current: true, selection_status: 'CURRENT' });
  const updated = quoteOf({ id: 'replacement-id', reference: 'Q-000009', is_current: true, supersedes: old.id, plan_type: 'REVISION' });
  studentApi({ [`GET ${PLAN_STATE}`]: { ...emptyPlan, latest_quote: old.id, current: old, history: [rowOf(old)] }, [`POST ${QUOTES}`]: updated });
  await open(enquiryPath, QUOTER);
  assert.match(bodyText(), /Current selected plan/);
  await click(button('Edit / change plan'));
  assert.equal(radio('Regular + Revision').checked, true);
  await click(radio('Revision Only'));
  await chooseCompletePayment();
  await click(button('Create quote…'));
  assert.match(clean(topDialog().textContent), /previous quote remains in history/);
  await click(button('Issue quote', topDialog()));
  assert.equal(quotePosts()[0].data.replaces, old.id);
  assert.equal(quotePosts()[0].data.plan_type, 'REVISION');
  assert.match(bodyText(), /Q-000009.*Quote history.*Q-000009.*Current.*Q-000007.*Previous/);
});

test('Tab order and Sales & Payment are preserved; locked plans can be viewed and downloaded but cannot change', async () => {
  const old = quoteOf({ is_current: true });
  studentApi({ [`GET ${PLAN_STATE}`]: { ...emptyPlan, locked: true, current: old, latest_quote: old.id, history: [rowOf(old)] },
    [`GET ${quoteAt('pdf/')}`]: () => Promise.resolve({ data: new Blob(['%PDF-']), headers: {} }) });
  const user = { ...QUOTER, permissions: [...QUOTER.permissions, 'accounts.view_own_lead_communications'] };
  await open(enquiryPath, user);
  const tabs = [...document.querySelectorAll('[role="tab"]')].map((el) => clean(el.textContent));
  assert.equal(tabs.indexOf('Plan Choosing'), tabs.indexOf('Follow-ups') + 1);
  assert.equal(tabs.indexOf('Sales & Payment'), tabs.indexOf('Plan Choosing') + 1);
  assert.equal(button('Edit / change plan').disabled, true);
  assert.match(bodyText(), /locked against plan changes/);
  await click(button('Download quote PDF'));
  assert.equal(saved.at(-1).name, 'Q-000007.pdf');
  await fire(button('Sales & Payment'), new window.MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
  assert.match(bodyText(), /do not have access to initial sales and payments/);
});

test('Catalogue sharing never sends an authenticated or localhost link; preview and download still work', async () => {
  studentApi({ [`GET ${onSale(PLAN_ID, 'pdf/')}`]: () => Promise.resolve({ data: new Blob(['%PDF-']), headers: { 'content-disposition': 'attachment; filename="syllabus.pdf"' } }) });
  await open('/plans', BDE);
  const whatsapp = document.querySelector('a[aria-label="Share Grade 6 CBSE through WhatsApp"]');
  const message = new URL(whatsapp.href).searchParams.get('text');
  assert.match(message, /Grade 6 CBSE.*Eduport Plus/);
  assert.doesNotMatch(message, /https?:|localhost|blob:|\/api\//);
  assert.equal(whatsapp.getAttribute('target'), '_blank');
  assert.match(whatsapp.getAttribute('rel'), /noopener/);
  await click(button('Preview syllabus PDF'));
  assert.ok(document.querySelector('iframe[src^="blob:"]'));
  await fire(topDialog(), new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await click(button('Download syllabus PDF'));
  assert.equal(saved.at(-1).name, 'syllabus.pdf');
});

test('Changing syllabus resets selections and shows only its enabled plans', async () => {
  studentApi({ [`GET ${onSale(PLAN_ID)}`]: { ...EVERY_WAY_ON_SALE, plan_types: ['REVISION'] } });
  await open(enquiryPath, QUOTER);
  await selectSyllabus();
  await chooseCompletePayment();
  assert.equal(radio('Regular Only'), undefined);
  assert.ok(radio('Revision Only'));
  await click(button('Change syllabus'));
  await selectSyllabus('Grade 7 CBSE');
  await chooseCompletePayment();
  assert.equal(radio('Revision Only'), undefined);
  await click(radio('Selected Chapters'));
  await chooseCompletePayment();
  assert.ok(chapterBox(2).getAttribute('aria-label').includes(DAYS[1][0]));
  assert.equal(chapterBox(2).checked, false);
});

test("My Quotes: a BDE's own quotes, searched and filtered in the API -- no BDE column or filter; empty, failing and refused each say so", async () => {
  serve({ [`GET ${QUOTES}`]: list([rowOf(quoteOf()), rowOf(BRIDGE_QUOTE)]) });
  const page = await open('/quotes', QUOTER);
  assert.match(bodyText(), /My Quotes\s*The quotes you have issued/);
  assert.deepEqual(calls('GET', QUOTES)[0].params, { page: 1, page_size: 25 });
  assert.deepEqual(headers(), ['Quote', 'Date', 'Plan', 'Enquiry', 'Payable at once', 'Status', 'Open']);
  const cells = (row) => [...row.querySelectorAll('td')].map((td) => clean(td.textContent));
  assert.deepEqual(cells(rows()[0]).slice(0, 6), ['Q-000007', 'Nov 9, 2026', 'Grade 6 CBSERegular + Revision', 'Riya Nair (parent of Arjun)', 'AED 1,929', 'Issued']);
  assert.deepEqual(cells(rows()[1]).slice(0, 6), ['Q-000008', 'Nov 9, 2026', 'Grade 7 CBSEBridge Course · Selected Chapters', '—', 'AED 116', 'Cancelled']);
  assert.equal(document.querySelector('[aria-label="Filter by BDE"]'), null);
  assert.equal(calls('GET', LEAD_BDES).length, 0);
  assert.ok(link('New quote'));
  await choose('Filter by status', 'Cancelled');
  assert.equal(calls('GET', QUOTES).at(-1).params.status, 'CANCELLED');
  await search('Search quotes', 'Q-7');
  assert.deepEqual(calls('GET', QUOTES).at(-1).params, { page: 1, page_size: 25, q: 'Q-7', status: 'CANCELLED' });
  // A BDE cannot widen the list from the URL: created_by is a manager's filter only.
  await page.go('/quotes?created_by=bde-3');
  assert.equal(calls('GET', QUOTES).at(-1).params.created_by, undefined);
  await click(link('Q-000007'));
  assert.equal(page.location().pathname, `/quotes/${QUOTE_ID}`);
  await mounted.pop().unmount();

  serve({ [`GET ${QUOTES}`]: list([]) });
  await open('/quotes', QUOTER);
  assert.match(bodyText(), /No quotes yet\s*Open a student’s enquiry/);
  assert.ok(link('My Enquiries'));
  await mounted.pop().unmount();
  await open('/quotes?status=ISSUED', QUOTER);
  assert.match(bodyText(), /No quotes match these filters/);
  await mounted.pop().unmount();

  let answers = 0;
  serve({ [`GET ${QUOTES}`]: () => (answers++ ? ok(list([rowOf(quoteOf())])) : fail(500, { message: 'Server error.' })) });
  await open('/quotes', QUOTER);
  assert.match(bodyText(), /Server error\./);
  await click(button('Try again'));
  assert.match(bodyText(), /Q-000007/);
  await mounted.pop().unmount();

  serve({ [`GET ${QUOTES}`]: () => fail(403, { detail: 'You do not have permission to perform this action.' }) });
  await open('/quotes', QUOTER);
  assert.match(bodyText(), /You don't have access to quotes\./);
});

test("Quotes (Admin): every BDE's quotes with who issued each, narrowed to one BDE; no BDE list, no filter", async () => {
  serve({
    [`GET ${QUOTES}`]: list([rowOf(quoteOf()), rowOf(BRIDGE_QUOTE)]),
    [`GET ${LEAD_BDES}`]: { results: [{ id: 'bde', full_name: 'Bala BDE', assignable: true }, { id: 'bde-3', full_name: 'Chitra BDE', assignable: false }] },
  });
  await open('/quotes', QUOTE_ADMIN);
  assert.match(bodyText(), /Quotes\s*Every quote the BDEs have issued/);
  assert.doesNotMatch(bodyText(), /My Quotes/);
  assert.equal(link('New quote'), undefined, "an administrator's Hub has no Plans & Pricing to quote from");
  assert.deepEqual(headers(), ['Quote', 'Date', 'Plan', 'Enquiry', 'BDE', 'Payable at once', 'Status', 'Open']);
  assert.match(clean(rows()[1].textContent), /Chitra BDE/);
  await choose('Filter by BDE', 'Chitra BDE (inactive)');
  assert.equal(calls('GET', QUOTES).at(-1).params.created_by, 'bde-3');
  await click(button('Clear all filters'));
  assert.equal(calls('GET', QUOTES).at(-1).params.created_by, undefined);
  await mounted.pop().unmount();

  serve({ [`GET ${QUOTES}`]: list([]), [`GET ${LEAD_BDES}`]: () => fail(403, { detail: 'No.' }) });
  await open('/quotes', QUOTE_ADMIN);
  assert.match(bodyText(), /No quotes yet\s*Quotes appear here as BDEs issue them from an enquiry’s Plan Choosing tab\./);
  assert.equal(document.querySelector('[aria-label="Filter by BDE"]'), null);
});

test('A quote: as issued -- packages, figures, chapters covered -- its PDF previewed and downloaded; a BDE cannot cancel it', async () => {
  serve({
    [`GET ${quoteAt()}`]: quoteOf(),
    [`GET ${quoteAt('pdf/')}`]: () => Promise.resolve({
      status: 200, data: new Blob(['%PDF']), headers: { 'content-disposition': 'attachment; filename="Q-000007-Grade-6-CBSE-New-Syllabus-Plan-and-Price.pdf"' },
    }),
  });
  await open(`/quotes/${QUOTE_ID}`, QUOTER);
  assert.match(bodyText(), /Quote Q-000007\s*Grade 6 CBSE · Regular \+ Revision/);
  assert.match(bodyText(), /QuoteIssued\s*Reference\s*Q-000007\s*Issued\s*Nov 9, 2026.*Issued by\s*Bala BDE\s*For enquiry\s*Riya Nair \(parent of Arjun\)/);
  assert.match(bodyText(), /Plan\s*Grade 6 CBSE\s*Grade 6 · CBSE · New Syllabus · Chapter-wise\s*Quoted as\s*Regular \+ Revision\s*Revision 1 · pricing version 3/);
  assert.match(bodyText(), /Fee per class\s*AED 35 \(standard AED 45\)/);
  assert.match(bodyText(), /Packages\s*Regular Course PackageAED 1,330.*Total fee\s*AED 1,995\s*Single-payment saving\s*AED 66\s*Payable at once\s*AED 1,929/);
  assert.match(bodyText(), /Chapters covered \(10\)/);
  assert.equal(link('Riya Nair (parent of Arjun)').getAttribute('href'), '/enquiries/lead-1');
  assert.equal(button('Cancel quote…'), undefined);
  await click(button('Preview PDF'));
  assert.deepEqual(calls('GET', quoteAt('pdf/'))[0].params, { disposition: 'inline' });
  await click(button('Download PDF'));
  assert.equal(calls('GET', quoteAt('pdf/'))[1].params, null);
  assert.equal(saved.at(-1).name, 'Q-000007-Grade-6-CBSE-New-Syllabus-Plan-and-Price.pdf');
  await mounted.pop().unmount();

  serve({ [`GET ${quoteAt()}`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such quote.' }) });
  await open(`/quotes/${QUOTE_ID}`, QUOTER);
  assert.match(bodyText(), /Quote not found/);
  assert.ok(link('My Quotes'));
  await mounted.pop().unmount();

  serve({ [`GET ${quoteAt()}`]: () => fail(403, { detail: 'You do not have permission to perform this action.' }) });
  await open(`/quotes/${QUOTE_ID}`, QUOTER);
  assert.match(bodyText(), /You don't have access to quotes\./);
});

test('Cancelling a quote: administrators only, a reason required; cancelled, it stays so and its PDF still downloads', async () => {
  const cancelled = quoteOf({
    status: 'CANCELLED', cancelled_at: '2026-11-10T06:30:00+00:00', cancelled_by: { id: 'admin', name: 'Asha Admin' },
    cancel_reason: 'Parent chose another plan.',
  });
  serve({
    [`GET ${quoteAt()}`]: quoteOf(),
    [`POST ${quoteAt('cancel/')}`]: cancelled,
    [`GET ${quoteAt('pdf/')}`]: () => ok(new Blob(['%PDF'])),
  });
  await open(`/quotes/${QUOTE_ID}`, QUOTE_ADMIN);
  // Every lead is the administrator's to open.
  assert.equal(link('Riya Nair (parent of Arjun)').getAttribute('href'), '/leads/lead-1');
  await click(button('Cancel quote…'));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /Cancel quote Q-000007.*marked CANCELLED on every page.*Why is it cancelled\?/);
  assert.equal(button('Cancel quote', dialog).disabled, true, 'a reason is required');
  const reason = dialog.querySelector('textarea');
  assert.equal(reason.maxLength, 255);
  await typeText(reason, '   ');
  assert.equal(button('Cancel quote', dialog).disabled, true, 'spaces are no reason');
  await typeText(reason, '  Parent chose another plan. ');
  assert.equal(calls('POST', quoteAt('cancel/')).length, 0);
  await click(button('Cancel quote', dialog));
  assert.deepEqual(calls('POST', quoteAt('cancel/'))[0].data, { reason: 'Parent chose another plan.' });
  assert.equal(topDialog(), undefined);
  assert.match(bodyText(), /Quote Q-000007 is cancelled\./);
  assert.match(bodyText(), /Cancelled on Nov 10, 2026.* by Asha Admin\. It is no longer valid\.\s*Reason: Parent chose another plan\./);
  assert.match(bodyText(), /QuoteCancelled/);
  // Its figures as issued, and no way back.
  assert.match(bodyText(), /Payable at once\s*AED 1,929/);
  assert.equal(button('Cancel quote…'), undefined);
  await click(button('Download PDF'));
  assert.equal(calls('GET', quoteAt('pdf/')).length, 1);
  assert.equal(saved.at(-1).name, 'Q-000007.pdf');
  await mounted.pop().unmount();

  // Cancelled meanwhile by someone else: the dialog says so and the page shows the quote as it is now.
  let reads = 0;
  serve({
    [`GET ${quoteAt()}`]: () => ok(reads++ ? cancelled : quoteOf()),
    [`POST ${quoteAt('cancel/')}`]: () => fail(409, { error: 'ALREADY_CANCELLED', message: 'This quote is already cancelled.' }),
  });
  await open(`/quotes/${QUOTE_ID}`, QUOTE_ADMIN);
  await click(button('Cancel quote…'));
  await typeText(topDialog().querySelector('textarea'), 'Duplicate.');
  await click(button('Cancel quote', topDialog()));
  assert.equal(reads, 2);
  assert.match(bodyText(), /Cancelled on Nov 10, 2026/);
  assert.equal(button('Cancel quote…'), undefined);
});

test('Access: Quotes open for whoever issues or manages quotes, whatever the role; the sidebar names them My Quotes and Quotes', () => {
  assert.equal(canOpenPage(QUOTER, '/quotes'), true);
  assert.equal(canOpenPage(BDE, '/quotes'), false);
  assert.equal(canOpenPage(QUOTE_ADMIN, '/quotes'), true);
  assert.equal(canOpenPage({ ...ADMIN, permissions: [...ADMIN.permissions, 'accounts.manage_sales_quotes'] }, '/quotes'), true);
  assert.equal(canOpenPage(ADMIN, '/quotes'), false);
  assert.equal(canOpenPage(MENTOR, '/quotes'), false);
  assert.equal(canOpenPage({ ...ROOT_MENTOR, permissions: [...ROOT_MENTOR.permissions, 'accounts.manage_sales_quotes'] }, '/quotes'), true);
  const titles = (user) => harness.workspaceFor(user).sections.flatMap((section) => section.items.map((item) => item.title));
  const bde = titles(QUOTER);
  assert.deepEqual(bde.slice(bde.indexOf('Plans & Pricing'), bde.indexOf('Plans & Pricing') + 2), ['Plans & Pricing', 'My Quotes']);
  assert.equal(titles(BDE).includes('My Quotes'), false);
  const admin = titles({ ...QUOTE_ADMIN, permissions: [...QUOTE_ADMIN.permissions, 'accounts.manage_sales_pricing'] });
  assert.deepEqual(admin.slice(admin.indexOf('Global Pricing'), admin.indexOf('Global Pricing') + 2), ['Global Pricing', 'Quotes']);
  assert.equal(titles(ADMIN).includes('Quotes'), false);
});

test('Reviewed pricing changed: reload is required and the new price must be reviewed before issuing', async () => {
  let current = EVERY_WAY_ON_SALE;
  studentApi({
    [`GET ${onSale(PLAN_ID)}`]: () => ok(current),
    [`POST ${QUOTES}`]: () => fail(409, { error: 'PRICING_CHANGED', message: 'Pricing changed meanwhile. Reload the syllabus and review the new amount.' }),
  });
  await open(enquiryPath, QUOTER);
  await selectSyllabus();
  await chooseCompletePayment();
  await click(radio('Regular Only'));
  await chooseCompletePayment();
  await click(button('Create quote…'));
  current = { ...EVERY_WAY_ON_SALE, pricing: { ...ON_SALE_PRICING, version: 4, offer_fee: '40' } };
  await click(button('Issue quote', topDialog()));
  assert.match(bodyText(), /Pricing changed meanwhile/);
  assert.equal(button('Create quote…').disabled, true);
  await click(button('Try again'));
  await click(radio('Regular Only'));
  await chooseCompletePayment();
  assert.match(bodyText(), /38 Classes × AED 40/);
});

test('Concurrent plan replacement or payment lock refreshes the saved plan before any further edit', async () => {
  for (const code of ['PLAN_CHANGED', 'PLAN_LOCKED']) {
    let current = emptyPlan;
    studentApi({
      [`GET ${PLAN_STATE}`]: () => ok(current),
      [`POST ${QUOTES}`]: () => fail(409, { error: code, message: 'Reload the enquiry.' }),
    });
    await open(enquiryPath, QUOTER);
    await selectSyllabus();
  await chooseCompletePayment();
    await click(radio('Regular Only'));
  await chooseCompletePayment();
    await click(button('Create quote…'));
    const quote = quoteOf({ is_current: true });
    current = { ...emptyPlan, current: quote, latest_quote: quote.id, history: [rowOf(quote)], locked: code === 'PLAN_LOCKED' };
    await click(button('Issue quote', topDialog()));
    assert.match(bodyText(), /Current selected plan/);
    assert.equal(Boolean(button('Edit / change plan').disabled), code === 'PLAN_LOCKED');
    assert.equal(button('Create quote…'), undefined);
    await mounted.pop().unmount();
  }
});

test('Supported device shares the PDF file and message, retaining it for a fresh tap if browser activation expires', async () => {
  let shared;
  let attempts = 0;
  navigator.canShare = () => true;
  navigator.share = async (payload) => {
    if (!attempts++) throw Object.assign(new Error('Fresh tap needed'), { name: 'NotAllowedError' });
    shared = payload;
  };
  try {
    studentApi({ [`GET ${onSale(PLAN_ID, 'pdf/')}`]: () => Promise.resolve({ data: new Blob(['%PDF-']), headers: { 'content-disposition': 'attachment; filename="course.pdf"' } }) });
    await open('/plans', BDE);
    await click(button('Share PDF for Grade 6 CBSE'));
    assert.match(bodyText(), /The PDF is ready. Tap Share PDF again/);
    await click(button('Share PDF for Grade 6 CBSE'));
    assert.equal(shared.files[0].name, 'course.pdf');
    assert.equal(shared.files[0].type, 'application/pdf');
    assert.match(shared.text, /Grade 6 CBSE.*Eduport Plus/);
    assert.equal(shared.url, undefined);
    assert.equal(calls('GET', onSale(PLAN_ID, 'pdf/')).length, 1);
  } finally {
    delete navigator.share;
    delete navigator.canShare;
  }
});

test('Small screens use syllabus and chapter cards throughout the student selection', async () => {
  const width = window.innerWidth;
  window.innerWidth = 390;
  try {
    studentApi();
    await open(enquiryPath, QUOTER);
    assert.ok(document.querySelector('ul[aria-label="Plans on sale"]'));
    await selectSyllabus('Grade 7 CBSE');
  await chooseCompletePayment();
    await click(radio('Selected Chapters'));
  await chooseCompletePayment();
    assert.ok(document.querySelector('ul[aria-label="Chapters of the Bridge Course"]'));
    await click(chapterBox(2));
  await chooseCompletePayment();
    assert.match(bodyText(), /1.5 Classes.*AED 53/);
    assert.equal(button('Create quote…').disabled, false);
  } finally {
    window.innerWidth = width;
  }
});

test('A stale syllabus PDF blocks a student quote until the revision is reloaded', async () => {
  studentApi({ [`GET ${onSale(PLAN_ID, 'pdf/')}`]: () => fail(409, { error: 'REVISION_CHANGED', message: 'This syllabus was republished.', revision: 2 }) });
  await open(enquiryPath, QUOTER);
  await selectSyllabus();
  await chooseCompletePayment();
  await click(radio('Regular Only'));
  await chooseCompletePayment();
  await click(button('Preview syllabus PDF'));
  assert.deepEqual(calls('GET', onSale(PLAN_ID, 'pdf/'))[0].params, { disposition: 'inline', revision: 1 });
  assert.equal(button('Create quote…').disabled, true);
  assert.ok(button('Try again'));
});

test('Collection intention is mandatory; complete, partial and Autopay quotes price and hand off their fixed intention', async () => {
  for (const [mode, label, payable] of [['FULL', 'Single / Complete Payment', '2627'], ['PARTIAL', 'Partial Payment', '2765'], ['AUTOPAY', 'Autopay', '2765']]) {
    let issued;
    const source = bridgeOnSale();
    const detail = { ...source, pricing: { ...source.pricing, offer_fee: '276.5' } };
    studentApi({
      [`GET ${onSale(BRIDGE_ID)}`]: detail,
      [`POST ${QUOTES}`]: ({ data }) => {
        assert.equal(data.collection_mode, mode);
        assert.equal('payable_amount' in data, false);
        assert.equal('collection_amount' in data, false);
        issued = quoteOf({ collection_mode: mode, collection_intention_confirmed: true, plan_type: 'BRIDGE_COURSE',
          syllabus: BRIDGE_QUOTE.syllabus, classes: '10', total_fee: '2765', payable_amount: payable, collection_amount: payable,
          single_payment_saving: mode === 'FULL' ? '138' : '0' });
        return ok(issued);
      },
      [`GET ${SALE_URL}`]: () => ok(saleState({ quote: issued, sale: startedSale(), autopay_configured: false })),
      [`GET ${SALE_URL}amount/`]: ({ params }) => {
        assert.equal(params.collection_mode, mode);
        return ok({ amount: payable, classes: '10', currency: 'AED' });
      },
    });
    const page = await open(enquiryPath, PAYMENT_BDE);
    await selectSyllabus('Grade 7 CBSE');
    await click(radio('Full Bridge Course'));
    const choices = [...document.querySelectorAll('input[name="quote-collection-intention"]')];
    assert.equal(choices.length, 3);
    assert.equal(choices.some((choice) => choice.checked), false, 'no collection intention is inferred from the course plan');
    assert.equal(button('Create quote…').disabled, true);
    assert.match(bodyText(), /Package before collection choiceAED 2,765/);
    await click(document.querySelector(`input[name="quote-collection-intention"][value="${mode}"]`));
    assert.equal(button('Create quote…').disabled, false);
    assert.ok(bodyText().includes(label));
    await click(button('Create quote…'));
    assert.match(clean(topDialog().textContent), new RegExp(`AED ${mode === 'FULL' ? '2,627' : '2,765'}`));
    await click(button('Issue quote', topDialog()));
    await page.go(paymentPath); await settle();
    assert.match(bodyText(), /Collection intention from quote/);
    assert.ok(bodyText().includes(label));
    assert.equal(document.getElementById('collection-mode'), null);
    assert.equal(calls('POST', `/api/sales/enquiries/${RIYA.id}/installment-quote/`).length, 0);
    if (mode === 'AUTOPAY') assert.ok(input('autopay-initial-classes'));
    else { await waitForAmount(); assert.equal(input('paid-classes').readOnly, mode === 'FULL'); }
    await mounted.pop().unmount();
  }
});

test('Switching quote intention preserves chosen chapters and Revision class mode', async () => {
  studentApi();
  await open(enquiryPath, QUOTER);
  await selectSyllabus();
  await click(radio('Chapter Plan'));
  await click(chapterBox(1));
  await click(classModeRadio('REVISION'));
  for (const mode of ['FULL', 'PARTIAL', 'AUTOPAY']) {
    await click(document.querySelector(`input[name="quote-collection-intention"][value="${mode}"]`));
    assert.equal(chapterBox(1).checked, true);
    assert.equal(classModeRadio('REVISION').checked, true);
    assert.ok(headers().includes('Revision classes'));
    assert.match(bodyText(), /2 Classes × AED 35/);
  }
});

test('Historical quotes without any purchase or collection block both sale types and never imply complete payment', async () => {
  studentApi({ [`GET ${SALE_URL}`]: saleState({ quote: saleQuote({ collection_intention_confirmed: false, collection_mode: 'FULL' }), can_collect: false }) });
  await open(paymentPath, PAYMENT_BDE);
  assert.match(bodyText(), /Not recorded \(historical quote\)/);
  assert.match(bodyText(), /historical quote has no recorded collection intention/);
  assert.equal(button('Start New Sale').disabled, true);
  await fire(button('Start New Sale').closest('form'), new window.Event('submit', { bubbles: true, cancelable: true }));
  assert.equal(calls('POST', SALE_URL).length, 0);
  await click(radio('Token Sale'));
  assert.equal(button('Start token reservation').disabled, true);
  assert.equal(calls('GET', `${SALE_URL}amount/`).length, 0);
  await click(radio('New Sale'));
  await click(button('Create replacement quote'));
  assert.match(clean(topDialog().textContent), /Current: Not recorded \(historical quote\)/);
  assert.equal(button('Issue replacement quote', topDialog()).disabled, true);
  await click(document.getElementById('replacement-collection-mode'));
  assert.equal(document.querySelectorAll('[role="option"]').length, 3);
});

test('Each explicit historical replacement intention enables New Sale while the original remains history', async () => {
  for (const [mode, label] of [['FULL', 'Single / Complete Payment'], ['PARTIAL', 'Partial Payment'], ['AUTOPAY', 'Autopay']]) {
    const old = saleQuote({ collection_intention_confirmed: false });
    let state = saleState({ quote: old, can_collect: false });
    const replacement = `/api/sales/enquiries/${RIYA.id}/installment-quote/`;
    studentApi({ [`GET ${SALE_URL}`]: () => ok(state),
      [`GET ${replacement}`]: ({ params }) => { assert.equal(params.collection_mode, mode); return ok({ quote_id: old.id, collection_mode: mode, collection_subtotal: '500', collection_discount: '0', collection_amount: '500', pricing_version: 3 }); },
      [`POST ${replacement}`]: ({ data }) => { assert.equal(data.collection_mode, mode); state = saleState({ quote: saleQuote({ id: 'new-' + mode, collection_mode: mode, collection_intention_confirmed: true, supersedes: old.id }) }); return ok(state.quote); },
      [`POST ${SALE_URL}`]: ({ data }) => { assert.deepEqual(data, { kind: 'NEW' }); state = { ...state, sale: startedSale() }; return ok(state); },
      [`GET ${SALE_URL}amount/`]: { amount: '500', classes: '10', currency: 'AED' },
    });
    await open(paymentPath, PAYMENT_BDE);
    await click(button('Create replacement quote'));
    await choose('replacement-collection-mode', label);
    await click(button('Issue replacement quote', topDialog()));
    assert.equal(old.collection_intention_confirmed, false);
    assert.equal(button('Start New Sale').disabled, false);
    const priorSales = calls('POST', SALE_URL).length;
    await click(button('Start New Sale'));
    assert.equal(calls('POST', SALE_URL).length, priorSales + 1);
    assert.ok(bodyText().includes(label));
    if (mode === 'AUTOPAY') assert.ok(input('autopay-initial-classes'));
    else await waitForAmount();
    await mounted.pop().unmount();
  }
});

test('An existing empty historical sale cannot collect or request a payment amount before replacement', async () => {
  studentApi({ [`GET ${SALE_URL}`]: saleState({ sale: startedSale(), quote: saleQuote({ collection_intention_confirmed: false }), can_collect: false }) });
  await open(paymentPath, PAYMENT_BDE);
  assert.match(bodyText(), /Replacement quote required.*historical quote has no recorded collection intention/);
  assert.equal(input('paid-classes'), null);
  assert.equal(button('Generate Stripe payment link'), undefined);
  assert.equal(calls('GET', `${SALE_URL}amount/`).length, 0);
  assert.ok(button('Create replacement quote'));
});

test('Historical purchases retain frozen collection controls without a forced replacement', async () => {
  studentApi({ [`GET ${SALE_URL}`]: saleState({ sale: startedSale(), quote: saleQuote({ collection_intention_confirmed: false }), purchase: { id: 'historical-purchase', collection_mode: 'PARTIAL' } }),
    [`GET ${SALE_URL}amount/`]: { amount: '300', classes: '6', currency: 'AED' } });
  await open(paymentPath, PAYMENT_BDE); await waitForAmount();
  assert.match(bodyText(), /Frozen collection terms/);
  assert.equal(button('Create replacement quote'), undefined);
  assert.equal(button('Change collection intention'), undefined);
  assert.ok(input('paid-classes'));
});

test('Historical paid token reservation keeps payment history and can collect tuition without forced replacement', async () => {
  studentApi({ [`GET ${SALE_URL}`]: saleState({ quote: saleQuote({ collection_intention_confirmed: false }),
      sale: startedSale({ kind: 'TOKEN', token_paid: '100', expected_start_date: '2027-01-10', reservation_reference: 'TOK-HISTORY' }),
      payments: [initialPayment({ purpose: 'TOKEN', amount: '100', classes: '0' })] }),
    [`GET ${SALE_URL}amount/`]: { amount: '400', classes: '10', currency: 'AED' } });
  await open(paymentPath, PAYMENT_BDE); await waitForAmount();
  assert.match(bodyText(), /TOK-HISTORY.*Token paid: AED 100/);
  assert.equal(button('Create replacement quote'), undefined);
  assert.ok(input('paid-classes'));
  assert.match(bodyText(), /Initial payment history/);
});

test('Token Sale with an AUTOPAY quote stays blocked until an explicit FULL or PARTIAL replacement', async () => {
  for (const [mode, label] of [['FULL', 'Single / Complete Payment'], ['PARTIAL', 'Partial Payment']]) {
    let state = saleState({ quote: saleQuote({ collection_mode: 'AUTOPAY' }) });
    const replacement = `/api/sales/enquiries/${RIYA.id}/installment-quote/`;
    studentApi({ [`GET ${SALE_URL}`]: () => ok(state),
      [`GET ${replacement}`]: ({ params }) => { assert.equal(params.collection_mode, mode); return ok({ quote_id: QUOTE_ID, collection_mode: mode, collection_subtotal: '500', collection_discount: '0', collection_amount: '500', pricing_version: 3 }); },
      [`POST ${replacement}`]: ({ data }) => { assert.equal(data.collection_mode, mode); state = saleState({ quote: saleQuote({ id: 'token-' + mode, collection_mode: mode, supersedes: QUOTE_ID }) }); return ok(state.quote); },
      [`POST ${SALE_URL}`]: ({ data }) => { assert.deepEqual(data, { kind: 'TOKEN', expected_start_date: '2027-01-10' }); state = { ...state, sale: startedSale({ kind: 'TOKEN', expected_start_date: data.expected_start_date, reservation_reference: 'TOK-NEW' }) }; return ok(state); },
      [`GET ${SALE_URL}amount/`]: ({ params }) => { assert.deepEqual(params, { purpose: 'TOKEN', collection_mode: 'FULL', classes: '0' }); return ok({ amount: '100', classes: '0', currency: 'AED' }); },
    });
    await open(paymentPath, PAYMENT_BDE);
    assert.equal(button('Start New Sale').disabled, false, 'New Sale Autopay stays available');
    await click(radio('Token Sale'));
    assert.equal(button('Start token reservation').disabled, true);
    assert.match(bodyText(), /Token Sale requires a FULL or PARTIAL quote/);
    await click(button('Create replacement quote'));
    await click(document.getElementById('replacement-collection-mode'));
    assert.equal([...document.querySelectorAll('[role="option"]')].some((option) => clean(option.textContent) === 'Autopay'), false);
    await click([...document.querySelectorAll('[role="option"]')].find((option) => clean(option.textContent) === label));
    await click(button('Issue replacement quote', topDialog()));
    await typeInto(input('token-start-date'), '2027-01-10');
    assert.equal(button('Start token reservation').disabled, false);
    await click(button('Start token reservation')); await waitForAmount();
    assert.match(bodyText(), /Collect token · AED 100/);
    assert.equal(input('autopay-initial-classes'), null);
    await mounted.pop().unmount();
  }
});

test('Existing invalid Token/AUTOPAY drafts cannot display collection or Autopay schedule controls', async () => {
  studentApi({ [`GET ${SALE_URL}`]: saleState({ sale: startedSale({ kind: 'TOKEN' }), quote: saleQuote({ collection_mode: 'AUTOPAY' }), can_collect: false }) });
  await open(paymentPath, PAYMENT_BDE);
  assert.match(bodyText(), /Token Sale requires a FULL or PARTIAL quote/);
  assert.equal(input('autopay-initial-classes'), null);
  assert.equal(button('Generate Stripe payment link'), undefined);
  assert.equal(calls('GET', `${SALE_URL}amount/`).length, 0);
});

// ------------------------------------------------------------------ run
let failed = 0;
for (const { name, fn } of tests) {
  globalThis.__salesApi = { calls: [], handler: () => fail(404, { message: 'No handler' }) };
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
console.log(`${tests.length - failed}/${tests.length} sales tests passed.`);
window.close();
process.exit(failed ? 1 : 0);
