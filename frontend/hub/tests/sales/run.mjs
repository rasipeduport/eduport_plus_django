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
  assert.match(bodyText(), /A Bridge Course is sold as one plan: the whole course\./);
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

test('Access: Syllabus & Plans and Global Pricing open on their permissions, whatever the role holding them', () => {
  for (const path of ['/sales-syllabus', '/sales-pricing']) {
    assert.equal(canOpenPage(ADMIN, path), true, path);
    assert.equal(canOpenPage(ROOT_MENTOR, path), true, `${path}: a superuser holds them (D1)`);
    assert.equal(canOpenPage(ADMIN_WITHOUT, path), false, path);
    assert.equal(canOpenPage(MENTOR, path), false, path);
  }
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
