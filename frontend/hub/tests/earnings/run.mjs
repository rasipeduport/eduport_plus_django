// Tutor Earnings tests: the rupee figures as the Hub writes them, who is
// offered which page and sidebar item, a tutor's My Earnings showing their own
// figures and no administrator control, the Admin's overview and one tutor's
// page, and the actions there -- recording a payment once (its request key,
// the duplicate warning), voiding it, a tutor's own rates and the initial
// pricing -- rendered for real in jsdom (harness.jsx) with the API stood in
// for (api-stub.js). The backend decides; these check what is offered and sent.
//
//   npm run test:earnings
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
const bundle = path.join(tmpdir(), `hub-earnings-${process.pid}.mjs`);
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

const { mount, act, earnings, access, navigation } = await import(pathToFileURL(bundle).href);

// ------------------------------------------------------------------ helpers
const tests = [];
let cleanup;
const test = (name, fn) => tests.push({ name, fn });
const settle = async () => { for (let i = 0; i < 6; i++) await act(async () => new Promise((resolve) => setTimeout(resolve, 0))); };
const click = async (el) => { assert.ok(el, 'nothing to click'); await act(async () => el.click()); await settle(); };
const text = () => document.body.textContent.replace(/\s+/g, ' ');
const buttons = (label) => [...document.querySelectorAll('button')].filter((el) => el.textContent.trim() === label);
const open = async (kind, props) => { cleanup = await mount(kind, props); await settle(); };
const refusal = (status, data) => Object.assign(new Error(`answered ${status}`), { response: { status, data } });
const serve = (routes) => {
  globalThis.__earningsApi = {
    calls: [],
    handler: async (entry) => {
      const answer = routes[`${entry.method} ${entry.url}`];
      if (answer === undefined) return { data: {} };
      const value = typeof answer === 'function' ? answer(entry) : answer;
      if (value instanceof Error) throw value;
      return { data: value };
    },
  };
};
const calls = (method, url) => globalThis.__earningsApi.calls.filter((entry) => entry.method === method && entry.url === url);
const type = async (el, value) => {
  assert.ok(el, 'no field to type in');
  const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
  await act(async () => el.dispatchEvent(new window.Event('input', { bubbles: true })));
  await settle();
};
const check = async (el) => { assert.ok(el, 'no checkbox'); await act(async () => el.click()); await settle(); };
// A row menu (Radix dropdown): opened from its trigger, its items as offered.
const menuItems = async (trigger) => {
  await act(async () => trigger.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
  await settle();
  return [...document.querySelectorAll('[role="menuitem"]')];
};

// ---------------------------------------------------------------- fixtures
const user = (role, permissions, extra = {}) => ({ id: `${role.toLowerCase()}-1`, role, permissions, full_name: role, ...extra });
const ADMIN_PERMS = ['accounts.view_tutor_earnings', 'accounts.manage_tutor_rates', 'accounts.manage_tutor_payments', 'accounts.correct_tutor_earnings'];
const ADMIN = user('ADMIN', ADMIN_PERMS);
const TUTOR = user('TUTOR', ['accounts.view_own_earnings', 'accounts.view_staff_dashboard', 'accounts.view_tutored_sessions']);
const MENTOR = user('MENTOR', ['accounts.view_staff_dashboard', 'accounts.view_mentored_sessions', 'accounts.manage_session']);
const SUPERUSER = user('ADMIN', [...ADMIN_PERMS, 'accounts.view_own_earnings'], { is_superuser: true });
const TUTOR_ID = 'tutor-a';
const PERSON = { id: 'admin-1', name: 'Asha Admin' };
const STATUS = {
  currency: 'INR', activated_at: '2026-11-15T16:53:53+00:00', months: ['2026-12', '2026-11'],
  pricing: { started_at: '2026-11-20T05:00:00+00:00', started_by: PERSON },
  last_sync: { started_at: '2026-12-10T05:06:00+00:00', finished_at: '2026-12-10T05:06:01+00:00', status: 'SUCCEEDED', earned_count: 0, waiting_count: 0 },
};
const COUNTS = { diagnostic: 0, demo: 1, sessions: 1, session_hours: '1.50', classes: 2 };
const entry = (id, classType, extra) => ({ id, kind: 'EARNING', class_type: classType, source_id: `${id}-src`,
  class_start: '2026-11-25T10:30:00+00:00', class_end: '2026-11-25T12:00:00+00:00', month: '2026-11', reason: null,
  created_at: '2026-11-25T12:06:00+00:00', reverses_id: null, reversed: false, reversal: null,
  details: { student_name: 'Riya', started_at: '2026-11-25T10:31:00+00:00', completed_at: '2026-11-25T13:00:00+00:00' }, ...extra });
const ENTRIES = [
  entry('e-session', 'SESSION', { units: '1.50', unit: 'HOUR', rate: '450.00', amount: '675.00', rate_source: 'TUTOR', created_by: null }),
  entry('e-demo', 'DEMO', { units: '1.00', unit: 'CLASS', rate: '300.00', amount: '300.00', rate_source: 'GLOBAL', created_by: null }),
];
const payment = (id, extra) => ({ id, amount: '500.00', currency: 'INR', paid_on: '2026-12-05', method: 'ACCOUNT_TRANSFER',
  method_label: 'Account Transfer', reference: `UTR ${id}`, notes: '', recorded_at: '2026-12-05T06:00:00+00:00', voided: false,
  voided_at: null, void_reason: null, recorded_by: PERSON, voided_by: null, ...extra });
const breakdown = (admin) => [
  { class_type: 'DIAGNOSTIC', unit: 'CLASS', classes: 0, units: '0.00', amount: '0.00', lines: [] },
  { class_type: 'DEMO', unit: 'CLASS', classes: 1, units: '1.00', amount: '300.00', lines: [{ rate: '300.00', classes: 1, units: '1.00', amount: '300.00', ...(admin ? { rate_source: 'GLOBAL' } : {}) }] },
  { class_type: 'SESSION', unit: 'HOUR', classes: 1, units: '1.50', amount: '675.00', lines: [{ rate: '450.00', classes: 1, units: '1.50', amount: '675.00', ...(admin ? { rate_source: 'TUTOR' } : {}) }] },
];
const rates = (admin) => [['DIAGNOSTIC', 'CLASS', '300.00', 'GLOBAL', '300.00'], ['DEMO', 'CLASS', '300.00', 'GLOBAL', '300.00'], ['SESSION', 'HOUR', '450.00', 'TUTOR', '400.00']]
  .map(([classType, unit, amount, source, global]) => ({ class_type: classType, unit, amount, ...(admin ? { source, global_amount: global, effective_from: STATUS.activated_at } : {}) }));
// A tutor reads when pricing started and the sync last ran -- not who started it, or how the sync went.
const TUTOR_STATUS = { ...STATUS, pricing: { started_at: STATUS.pricing.started_at },
  last_sync: { started_at: STATUS.last_sync.started_at, finished_at: STATUS.last_sync.finished_at } };
const detail = (admin, extra = {}) => ({
  ...(admin ? STATUS : TUTOR_STATUS), period: { month: null },
  tutor: { id: TUTOR_ID, name: 'Tutor A', email: 'a@hub.test', active: true, is_tutor: true },
  summary: { earned: '975.00', paid: '500.00', outstanding: '475.00', balance_state: 'pending', earned_all_time: '975.00',
    paid_all_time: '500.00', payments: 1, voided_payments: 1, last_paid_on: '2026-12-05', ...COUNTS },
  breakdown: breakdown(admin), adjustments: '0.00', months_breakdown: [{ month: '2026-11', earned: '975.00', ...COUNTS }],
  rates: rates(admin),
  not_counted: [{ class_type: 'SESSION', source_id: 'ses-due', reason: 'NOTES_DUE', class_start: '2026-12-09T10:30:00+00:00',
    class_end: '2026-12-09T11:30:00+00:00', title: 'Algebra', student_name: 'Riya', student_id: 'stu-x' }],
  payments: [payment('pay-1'), payment('pay-0', { amount: '50.00', voided: true, voided_at: '2026-12-05T06:10:00+00:00', void_reason: 'Typed wrongly', voided_by: PERSON })]
    .map((row) => (admin ? row : (({ recorded_by: _r, voided_by: _v, ...rest }) => rest)(row))),
  ...(admin ? { own_rates: true, rate_history: { tutor: [], global: [] }, review: [] } : {}),
  ...extra,
});
const page = (results) => ({ count: results.length, page: 1, page_size: 25, results });
const OVERVIEW = {
  ...STATUS, period: { month: null },
  totals: { earned: '111425.00', paid: '82900.00', pending: '28525.00', overpaid: '0.00', tutors: 2, tutors_with_balance: 1, payments: 11, ...COUNTS },
  not_counted: { NOTES_DUE: 6, REPORT_DUE: 0, SLOT_NOT_ENDED: 1, BEING_ADDED: 0 },
  review_count: 1,
  tutors: [
    { id: TUTOR_ID, name: 'Tutor A', email: 'a@hub.test', active: true, ...COUNTS, earned: '27625.00', paid: '20000.00', outstanding: '7625.00', balance_state: 'pending', own_rates: true },
    { id: 'tutor-b', name: 'Tutor B', email: 'b@hub.test', active: true, diagnostic: 0, demo: 0, sessions: 0, session_hours: '0.00', classes: 0, earned: '0.00', paid: '0.00', outstanding: '0.00', balance_state: 'none', own_rates: false },
  ],
};
const DETAIL_URL = `/api/earnings/tutors/${TUTOR_ID}/`;

// ------------------------------------------------------------------ tests
test('Rupees as the Hub writes them: Indian grouping, paise only when there are some', () => {
  const { formatInr, countsLine, rateLabel, unitsLabel, balanceLabel, dayLabel, stampLabel } = earnings;
  assert.equal(formatInr('27625.00'), '₹27,625');
  assert.equal(formatInr('111425.00'), '₹1,11,425');
  assert.equal(formatInr('675.50'), '₹675.50');
  assert.equal(formatInr('-400.00'), '−₹400');
  assert.equal(formatInr('600.00', { signed: true }), '+₹600');
  assert.equal(formatInr(null), '—');
  assert.equal(countsLine(COUNTS), '0 Diagnostic · 1 Demo · 1 session · 1.5 payable hours');
  // Class times in India time, whatever the device's zone; a payment date as the calendar day it is.
  assert.equal(stampLabel('2026-11-30T18:45:00+00:00'), '1 Dec 2026, 12:15 AM');
  assert.equal(dayLabel('2026-12-05'), '5 Dec 2026');
  assert.equal(rateLabel('450.00', 'HOUR'), '₹450 / hour');
  assert.equal(rateLabel('300.00', 'CLASS'), '₹300 / class');
  assert.equal(unitsLabel('1.50', 'HOUR'), '1.5 h');
  assert.equal(balanceLabel('overpaid', '-450.00'), 'Overpaid ₹450');
  assert.deepEqual(earnings.PAYMENT_METHODS.map((m) => m.value), ['ACCOUNT_TRANSFER', 'UPI']);
});

test('Who opens what: Tutor Earnings for administrators, My Earnings for tutors, nothing for mentors', () => {
  const { canOpenPage } = access;
  assert.ok(canOpenPage(ADMIN, '/tutor-earnings'));
  assert.ok(!canOpenPage(ADMIN, '/my-earnings'));
  assert.ok(canOpenPage(TUTOR, '/my-earnings'));
  assert.ok(!canOpenPage(TUTOR, '/tutor-earnings'));
  assert.ok(!canOpenPage(MENTOR, '/tutor-earnings') && !canOpenPage(MENTOR, '/my-earnings'));
  // A superuser holds a tutor's permission too, but My Earnings is a tutor's page.
  assert.ok(canOpenPage(SUPERUSER, '/tutor-earnings') && !canOpenPage(SUPERUSER, '/my-earnings'));
  assert.equal(canOpenPage(TUTOR, '/hourly-earnings'), false, 'the old address is only a redirect now');
  const urls = (who) => navigation.workspaceFor(who).sections.flatMap((section) => section.items.map((item) => item.url));
  assert.ok(urls(TUTOR).includes('/my-earnings') && !urls(TUTOR).includes('/hourly-earnings'));
  assert.ok(urls(ADMIN).includes('/tutor-earnings'));
  const item = navigation.workspaceFor(ADMIN).sections.flatMap((section) => section.items).find((entry) => entry.url === '/tutor-earnings');
  assert.equal(item.badge, undefined, 'no longer Coming Soon');
});

test("My Earnings: the tutor's own figures, sessions and hours apart, and no administrator control", async () => {
  serve({ 'GET /api/earnings/me/': detail(false), 'GET /api/earnings/me/entries/': page(ENTRIES.map(({ rate_source: _s, created_by: _c, ...row }) => row)) });
  await open('mine');
  const shown = text();
  for (const words of ['₹975', '₹500', '₹475', 'Pending amount', '1 session · 1.5 payable hours', '₹450 / hour', 'Your rate',
    'Notes due', 'Typed wrongly', 'How a class counts']) {
    assert.ok(shown.includes(words), `${words} in ${shown}`);
  }
  for (const words of ['Record payment', 'Void payment', 'Reverse earning', 'Add adjustment', 'Rate source', 'Global rate', 'Tutor rate',
    'Edit tutor rates', 'Asha Admin']) {
    assert.ok(!shown.includes(words), `no ${words}`);
  }
  assert.equal(document.querySelectorAll('button[aria-label^="Actions for"]').length, 0, 'no row actions');
  assert.ok(document.querySelector('a[href="/sessions?tab=needs_action"]'), 'a way to submit the notes due');
  // Only ever the tutor's own endpoints, naming no tutor.
  const urls = globalThis.__earningsApi.calls.map((c) => c.url);
  assert.ok(urls.every((url) => url.startsWith('/api/earnings/me/')), urls.join(', '));
  assert.ok(globalThis.__earningsApi.calls.every((c) => !JSON.stringify(c.params || {}).includes('tutor')));
});

test('Admin overview: every tutor, balances, the not-counted note and what needs review', async () => {
  const item = { problem: 'TUTOR_CHANGED', entry: ENTRIES[1], tutor: { id: TUTOR_ID, name: 'Tutor A' },
    current: { tutor_id: 'tutor-b', class_start: ENTRIES[1].class_start, class_end: ENTRIES[1].class_end, eligible: false },
    current_tutor: { id: 'tutor-b', name: 'Tutor B' } };
  serve({ 'GET /api/earnings/overview/': OVERVIEW, 'GET /api/earnings/review/': { items: [item] },
    'POST /api/earnings/entries/e-demo/keep/': { success: true, review: { id: 'rev-2', entry_id: 'e-demo' } } });
  await open('overview', { user: ADMIN });
  const shown = text();
  for (const words of ['₹1,11,425', '₹82,900', '₹28,525', 'Tutor A', '₹7,625', 'Nothing earned yet', 'Tutor rate', 'Global rate',
    'Session hours', '6 notes due', '1 slot not over yet', 'Needs review']) {
    assert.ok(shown.includes(words), `${words} in ${shown}`);
  }
  assert.ok(document.querySelector(`a[href="/tutor-earnings/${TUTOR_ID}"]`));
  // The review list: reverse or keep as earned, each with its reason.
  await click(buttons('Needs review1')[0]);
  assert.ok(text().includes("now assigned to another tutor. It is now Tutor B's."), text());
  await click(buttons('Keep as earned…')[0]);
  await type(document.querySelector('#keep-reason'), 'Reassigned after the class; Tutor A taught it');
  await click(buttons('Keep as earned').at(-1));
  assert.deepEqual(calls('POST', '/api/earnings/entries/e-demo/keep/').map((c) => c.data),
    [{ reason: 'Reassigned after the class; Tutor A taught it', seen: { problem: item.problem, current: item.current } }]);
  assert.equal(calls('GET', '/api/earnings/review/').length, 2, 'the list reloads');
});

test('Admin overview before pricing: the initial rates are asked for, and start pricing once confirmed', async () => {
  const rates = { ...STATUS, pricing: null, rates: [], history: [], tutors: [{ id: TUTOR_ID, name: 'Tutor A', email: 'a@hub.test', active: true, own_rates: [] }] };
  serve({ 'GET /api/earnings/overview/': { ...OVERVIEW, pricing: null }, 'GET /api/earnings/rates/': rates,
    'POST /api/earnings/rates/initial/': { ...rates, pricing: STATUS.pricing } });
  await open('overview', { user: ADMIN });
  assert.ok(text().includes('Set the initial rates to start pricing'));
  await click(buttons('Set initial rates')[0]);
  const start = () => buttons('Start pricing')[0];
  assert.ok(start().disabled);
  await type(document.querySelector('#initial-DIAGNOSTIC'), '300');
  await type(document.querySelector('#initial-DEMO'), '300');
  await type(document.querySelector('#initial-SESSION'), '400.50');
  await check([...document.querySelectorAll('input[type="checkbox"]')].at(-1));
  assert.ok(start().disabled, 'every global rate first, Demo Conversion included');
  await check([...document.querySelectorAll('input[type="checkbox"]')].at(-1));
  await type(document.querySelector('#initial-DEMO_CONVERSION'), '450');
  assert.ok(start().disabled, 'pricing starts only once confirmed');
  await check([...document.querySelectorAll('input[type="checkbox"]')].at(-1));
  assert.ok(!start().disabled);
  await click(start());
  assert.deepEqual(calls('POST', '/api/earnings/rates/initial/').map((c) => c.data),
    [{ global: { DIAGNOSTIC: '300', DEMO: '300', SESSION: '400.50', DEMO_CONVERSION: '450' }, tutors: [], reason: '', confirm: true }]);
});

test('Tutor page: Record payment -- checked, reviewed, sent once with its key, and confirmed when it may be a duplicate', async () => {
  let attempts = 0;
  serve({
    [`GET ${DETAIL_URL}`]: detail(true),
    [`GET ${DETAIL_URL}entries/`]: page(ENTRIES),
    [`POST ${DETAIL_URL}payments/`]: (call) => {
      attempts += 1;
      if (!call.data.confirm_duplicate) return refusal(409, { code: 'POSSIBLE_DUPLICATE', error: 'A payment of ₹475.00 to Tutor A dated 5 Dec 2026 was already recorded by Asha Admin.' });
      return { success: true, created: true, payment: payment('pay-2', { amount: '475.00' }), outstanding: '0.00' };
    },
  });
  await open('detail', { user: ADMIN, tutorId: TUTOR_ID });
  for (const words of ['Tutor-specific rates', 'Rate applied', 'Rate source', 'Recorded by', 'Asha Admin', 'Overrides the global ₹400 / hour']) {
    assert.ok(text().includes(words), words);
  }
  await click(buttons('Record payment')[0]);
  const amount = document.querySelector('#payment-amount');
  await type(amount, '500');
  await type(document.querySelector('#payment-reference'), 'NEFT N0362');
  await click(buttons('Review payment')[0]);
  assert.ok(text().includes('at most the ₹475 outstanding'), text());
  await type(document.querySelector('#payment-amount'), '475');
  await click(buttons('Review payment')[0]);
  assert.ok(text().includes('Record ₹475 for Tutor A?'), text());
  await click(buttons('Record payment').at(-1));
  assert.ok(text().includes('Possible duplicate'), text());
  assert.ok(buttons('Record payment').at(-1).disabled, 'confirmed as a separate payment first');
  // Confirmed, then changed: the changed payment is asked about afresh.
  await check([...document.querySelectorAll('[role="dialog"] input[type="checkbox"]')][0]);
  await click(buttons('Back')[0]);
  await type(document.querySelector('#payment-amount'), '470');
  await click(buttons('Review payment')[0]);
  assert.ok(!text().includes('Possible duplicate'), 'no confirmation carried over');
  await click(buttons('Record payment').at(-1));
  assert.ok(text().includes('Possible duplicate'), text());
  await check([...document.querySelectorAll('[role="dialog"] input[type="checkbox"]')][0]);
  await click(buttons('Record payment').at(-1));
  const sent = calls('POST', `${DETAIL_URL}payments/`).map((c) => c.data);
  assert.equal(attempts, 3);
  assert.deepEqual(sent.map((c) => c.confirm_duplicate), [false, false, true]);
  assert.ok(sent.every((c) => c.request_id === sent[0].request_id), 'one key for the dialog: never recorded twice');
  assert.match(sent[0].request_id, /^[0-9a-f-]{36}$/);
  assert.deepEqual({ ...sent[2], request_id: 'key', paid_on: 'today' },
    { request_id: 'key', amount: '470', paid_on: 'today', method: 'ACCOUNT_TRANSFER', reference: 'NEFT N0362', notes: '', confirm_duplicate: true });
});

test('Tutor page: void a payment with its reason; reverse an earning with its reason', async () => {
  serve({
    [`GET ${DETAIL_URL}`]: detail(true),
    [`GET ${DETAIL_URL}entries/`]: page(ENTRIES),
    'POST /api/earnings/payments/pay-1/void/': { success: true, payment: payment('pay-1', { voided: true }), outstanding: '975.00' },
    'POST /api/earnings/entries/e-session/reverse/': { success: true, entry: { ...ENTRIES[0], kind: 'REVERSAL', amount: '-675.00' } },
  });
  await open('detail', { user: ADMIN, tutorId: TUTOR_ID });
  const voidTrigger = document.querySelector('button[aria-label="Actions for the payment of 5 Dec 2026"]');
  const [voidItem] = await menuItems(voidTrigger);
  assert.equal(voidItem.textContent.trim(), 'Void payment…');
  await click(voidItem);
  assert.ok(buttons('Void payment').at(-1).disabled, 'a reason first');
  await type(document.querySelector('#void-reason'), 'Typed the wrong amount');
  await click(buttons('Void payment').at(-1));
  assert.deepEqual(calls('POST', '/api/earnings/payments/pay-1/void/').map((c) => c.data), [{ reason: 'Typed the wrong amount' }]);

  const [reverseTrigger] = document.querySelectorAll('button[aria-label="Actions for this earning"]');
  const [reverseItem] = await menuItems(reverseTrigger);
  await click(reverseItem);
  await type(document.querySelector('#reverse-reason'), 'Taught by someone else');
  await click(buttons('Reverse earning').at(-1));
  assert.deepEqual(calls('POST', '/api/earnings/entries/e-session/reverse/').map((c) => c.data), [{ reason: 'Taught by someone else' }]);
});

test('Needs review: an earning kept as earned with its reason leaves the list; the tutor page offers keep and reverse', async () => {
  const item = { problem: 'TIMES_CHANGED', entry: ENTRIES[0], tutor: { id: TUTOR_ID, name: 'Tutor A' },
    current: { tutor_id: TUTOR_ID, class_start: '2026-11-25T10:30:00+00:00', class_end: '2026-11-25T12:30:00+00:00', eligible: true },
    current_tutor: { id: TUTOR_ID, name: 'Tutor A' } };
  let kept = false;
  serve({
    [`GET ${DETAIL_URL}`]: () => detail(true, { review: kept ? [] : [item] }),
    [`GET ${DETAIL_URL}entries/`]: page(ENTRIES),
    'POST /api/earnings/entries/e-session/keep/': (call) => {
      kept = true;
      return { success: true, review: { id: 'rev-1', entry_id: 'e-session', problem: item.problem, current: item.current,
        reason: call.data.reason, created_at: '2026-12-10T06:00:00+00:00', created_by: PERSON } };
    },
  });
  await open('detail', { user: ADMIN, tutorId: TUTOR_ID });
  assert.ok(text().includes('1 earning needs review'), text());
  assert.ok(text().includes('rescheduled after it earned. It now reads 25 Nov 2026, 4:00 PM – 25 Nov 2026, 6:00 PM.'), text());
  assert.equal(buttons('Reverse earning…').length, 1);
  await click(buttons('Keep as earned…')[0]);
  assert.ok(text().includes('Keep ₹675 as earned for Tutor A?'), text());
  assert.ok(buttons('Keep as earned').at(-1).disabled, 'a reason first');
  await type(document.querySelector('#keep-reason'), 'The class ran two hours, as paid');
  await click(buttons('Keep as earned').at(-1));
  assert.deepEqual(calls('POST', '/api/earnings/entries/e-session/keep/').map((c) => c.data),
    [{ reason: 'The class ran two hours, as paid', seen: { problem: 'TIMES_CHANGED', current: item.current } }]);
  assert.ok(!text().includes('needs review'), 'gone from the list');
  assert.ok(text().includes('Kept as earned.'), text());
  await cleanup(); cleanup = null;

  // Without the corrections permission, the item is listed with no action.
  serve({ [`GET ${DETAIL_URL}`]: detail(true, { review: [item] }), [`GET ${DETAIL_URL}entries/`]: page(ENTRIES) });
  await open('detail', { user: user('ADMIN', ['accounts.view_tutor_earnings']), tutorId: TUTOR_ID });
  assert.ok(text().includes('1 earning needs review'));
  for (const label of ['Keep as earned…', 'Reverse earning…']) assert.equal(buttons(label).length, 0, label);
});

test('Needs review: a class changed since it was shown is not kept, and the tutor page is read again', async () => {
  const item = { problem: 'TIMES_CHANGED', entry: ENTRIES[0], tutor: { id: TUTOR_ID, name: 'Tutor A' },
    current: { tutor_id: TUTOR_ID, class_start: '2026-11-25T10:30:00+00:00', class_end: '2026-11-25T12:30:00+00:00', eligible: true },
    current_tutor: { id: TUTOR_ID, name: 'Tutor A' } };
  serve({
    [`GET ${DETAIL_URL}`]: detail(true, { review: [item] }),
    [`GET ${DETAIL_URL}entries/`]: page(ENTRIES),
    'POST /api/earnings/entries/e-session/keep/': () =>
      refusal(409, { code: 'REVIEW_CHANGED', error: 'This class changed since you opened it. Review it again.' }),
  });
  await open('detail', { user: ADMIN, tutorId: TUTOR_ID });
  await click(buttons('Keep as earned…')[0]);
  await type(document.querySelector('#keep-reason'), 'Ran as paid');
  await click(buttons('Keep as earned').at(-1));
  assert.ok(text().includes('This class changed since you opened it. Review it again.'), text());
  assert.equal(calls('GET', DETAIL_URL).length, 2, 'the tutor page is read again');
});

test('Tutor page: an adjustment deducts with its sign, month and reason', async () => {
  serve({
    [`GET ${DETAIL_URL}`]: detail(true),
    [`GET ${DETAIL_URL}entries/`]: page(ENTRIES),
    [`POST ${DETAIL_URL}adjustments/`]: (call) => ({ success: true,
      entry: { ...ENTRIES[0], id: 'adj-1', kind: 'ADJUSTMENT', amount: call.data.amount, reason: call.data.reason } }),
  });
  await open('detail', { user: ADMIN, tutorId: TUTOR_ID });
  await click(buttons('Add adjustment')[0]);
  await check(document.querySelectorAll('input[name="adjustment-direction"]')[1]);
  await type(document.querySelector('#adjustment-amount'), '150.50');
  await type(document.querySelector('#adjustment-reason'), 'Class cut short by 20 minutes');
  await click(buttons('Add adjustment').at(-1));
  assert.deepEqual(calls('POST', `${DETAIL_URL}adjustments/`).map((c) => c.data),
    [{ amount: '-150.50', month: '2026-12', reason: 'Class cut short by 20 minutes', entry: null }]);
  assert.ok(text().includes('Adjustment of −₹150.50 added.'), text());
});

test('Global rates: only a changed rate is sent, with its reason', async () => {
  const ratesData = { ...STATUS, history: [], tutors: [],
    rates: [['DIAGNOSTIC', 'CLASS', '300.00'], ['DEMO', 'CLASS', '300.00'], ['SESSION', 'HOUR', '400.00']]
      .map(([classType, unit, amount]) => ({ class_type: classType, unit, amount, effective_from: STATUS.activated_at })) };
  serve({ 'GET /api/earnings/overview/': OVERVIEW, 'GET /api/earnings/rates/': ratesData, 'POST /api/earnings/rates/': ratesData });
  await open('overview', { user: ADMIN });
  await click(buttons('Global rates')[0]);
  await type(document.querySelector('#global-SESSION'), '425');
  await type(document.querySelector('#global-reason'), 'Annual revision');
  await click(buttons('Save new rates')[0]);
  assert.deepEqual(calls('POST', '/api/earnings/rates/').map((c) => c.data), [{ rates: { SESSION: '425' }, reason: 'Annual revision' }]);
});

test("Tutor page: a tutor's own rates -- only what changed is sent, None for back to the global rate", async () => {
  serve({
    [`GET ${DETAIL_URL}`]: detail(true),
    [`GET ${DETAIL_URL}entries/`]: page(ENTRIES),
    [`POST ${DETAIL_URL}rates/`]: detail(true),
  });
  await open('detail', { user: ADMIN, tutorId: TUTOR_ID });
  await click(buttons('Edit tutor rates')[0]);
  const save = () => buttons('Save tutor rates')[0];
  assert.ok(save().disabled, 'nothing changed yet');
  await check(document.querySelector('input[name="rate-SESSION"]'));  // Global for Normal Sessions
  await check([...document.querySelectorAll('input[name="rate-DEMO"]')][1]);  // a Demo rate of their own
  await type(document.querySelector('input[aria-label="Demo tutor rate in rupees"]'), '350');
  assert.ok(save().disabled, 'a reason first');
  await type(document.querySelector('#tutor-rates-reason'), 'Senior tutor');
  await click(save());
  assert.deepEqual(calls('POST', `${DETAIL_URL}rates/`).map((c) => c.data), [{ rates: { DEMO: '350', SESSION: null }, reason: 'Senior tutor' }]);
});

test('Tutor page actions follow their own permissions; nothing to pay while nothing is owed', async () => {
  serve({ [`GET ${DETAIL_URL}`]: detail(true), [`GET ${DETAIL_URL}entries/`]: page(ENTRIES) });
  await open('detail', { user: user('ADMIN', ['accounts.view_tutor_earnings']), tutorId: TUTOR_ID });
  for (const label of ['Record payment', 'Add adjustment', 'Edit tutor rates']) assert.equal(buttons(label).length, 0, label);
  assert.equal(document.querySelectorAll('button[aria-label^="Actions for"]').length, 0, 'no row actions');
  await cleanup(); cleanup = null;

  const paid = detail(true, { summary: { ...detail(true).summary, outstanding: '0.00', balance_state: 'paid' } });
  serve({ [`GET ${DETAIL_URL}`]: paid, [`GET ${DETAIL_URL}entries/`]: page(ENTRIES) });
  await open('detail', { user: ADMIN, tutorId: TUTOR_ID });
  assert.ok(buttons('Record payment').every((el) => el.disabled), 'Record payment waits for an outstanding balance');
  await cleanup(); cleanup = null;

  // A former tutor is still paid what they are owed, but has no rates to change.
  const former = detail(true, { tutor: { ...detail(true).tutor, active: false, is_tutor: false } });
  serve({ [`GET ${DETAIL_URL}`]: former, [`GET ${DETAIL_URL}entries/`]: page(ENTRIES) });
  await open('detail', { user: ADMIN, tutorId: TUTOR_ID });
  for (const label of ['Edit tutor rates', 'Edit']) assert.equal(buttons(label).length, 0, label);
  assert.ok(buttons('Record payment').some((el) => !el.disabled), 'still paid');
  assert.ok(text().includes('All time · 1 payment · 1 voided, not counted'), text());
});

// -------------------------------------------------------- Demo conversion
const CONVERSION_ENTRY = entry('e-conv', 'DEMO_CONVERSION', {
  source_id: 'sale-1', units: '1.00', unit: 'CONVERSION', rate: '350.00', amount: '150.00', rate_source: 'GLOBAL',
  created_by: null, month: '2026-12', converts_id: 'e-demo',
  details: { sale_id: 'sale-1', student_name: 'Riya', student_code: 'EDP00051', converted_at: '2026-12-04T12:00:00+00:00', demo_amount: '300.00',
    conversion_rate: '350.00', incentive: '50.00', final_amount: '350.00', is_redemo: false },
});
const CONVERTED_DEMO = { ...ENTRIES[1], conversion: { id: 'e-conv', amount: '150.00', month: '2026-12', converted_at: '2026-12-04T12:00:00+00:00', reversed: false } };
const CONVERTED_COUNTS = { ...COUNTS, conversions: 1, demo_earned: '300.00', conversion_earned: '150.00' };
const conversionDetail = (admin) => detail(admin, {
  summary: { ...detail(admin).summary, earned: '1125.00', ...CONVERTED_COUNTS },
  breakdown: [...breakdown(admin), { class_type: 'DEMO_CONVERSION', unit: 'CONVERSION', classes: 1, units: '1.00', amount: '150.00',
    lines: [{ rate: '350.00', classes: 1, units: '1.00', amount: '150.00', ...(admin ? { rate_source: 'GLOBAL' } : {}) }] }],
  months_breakdown: [{ month: '2026-12', earned: '150.00', ...COUNTS, demo: 0, sessions: 0, session_hours: '0.00', classes: 0,
    conversions: 1, demo_earned: '0.00', conversion_earned: '150.00' }, { month: '2026-11', earned: '975.00', ...COUNTS }],
  rates: [...rates(admin), { class_type: 'DEMO_CONVERSION', unit: 'CONVERSION', amount: '350.00',
    ...(admin ? { source: 'GLOBAL', global_amount: '350.00', effective_from: STATUS.activated_at } : {}) }],
  // A tutor reads no source for a conversion: its sale is an administrator's.
  not_counted: [['sale-2', 'Kabir'], ['sale-3', 'Meera']].map(([sale, student]) => ({ class_type: 'DEMO_CONVERSION',
    source_id: admin ? sale : null, reason: 'WAITING_FOR_DEMO', class_start: '2026-12-09T10:30:00+00:00',
    class_end: '2026-12-09T11:30:00+00:00', title: null, student_name: student, is_redemo: true, converted_at: '2026-12-09T11:00:00+00:00' })),
});
// The ledger as a tutor reads it: no rate source or author, and no sale on a conversion line.
const asTutor = (row) => {
  const { rate_source: _s, created_by: _c, ...rest } = row;
  if (rest.class_type !== 'DEMO_CONVERSION') return rest;
  const { sale_id: _sale, ...details } = rest.details;
  return { ...rest, source_id: null, details };
};

test('Demo conversion as the Hub writes it: per converted Demo, apart from the class count', () => {
  const { rateLabel, unitsLabel, countsLine, whyItCounts, classTypeLabel, unitPhrase, CLASS_TYPES } = earnings;
  assert.deepEqual(CLASS_TYPES.map((t) => t.value), ['DIAGNOSTIC', 'DEMO', 'SESSION', 'DEMO_CONVERSION']);
  assert.equal(rateLabel('350.00', 'CONVERSION'), '₹350 / converted Demo');
  assert.equal(unitsLabel('2.00', 'CONVERSION'), '2 conversions');
  assert.equal(unitPhrase('CONVERSION'), 'per converted Demo');
  assert.equal(classTypeLabel('DEMO_CONVERSION', { singular: true }), 'Demo conversion');
  assert.equal(countsLine(CONVERTED_COUNTS), '0 Diagnostic · 1 Demo · 1 session · 1.5 payable hours · 1 converted');
  assert.equal(whyItCounts(CONVERSION_ENTRY), 'Enrolled 4 Dec 2026, 5:30 PM · Demo earned ₹300 → ₹350 converted');
});

test('Admin overview: the Demo conversions -- Demos, conversions, what each earned -- and a Converted column', async () => {
  serve({ 'GET /api/earnings/overview/': { ...OVERVIEW, totals: { ...OVERVIEW.totals, ...CONVERTED_COUNTS },
    tutors: [{ ...OVERVIEW.tutors[0], ...CONVERTED_COUNTS, conversions: 3 }, OVERVIEW.tutors[1]] } });
  await open('overview', { user: ADMIN });
  const shown = text();
  for (const words of ['Demo conversions', 'Eligible Demos', 'Converted Demos', 'Demo earnings', '₹300', 'Conversion incentives', '+₹150',
    'Total earnings', '₹1,11,425', 'Converted', '1 session · 1.5 payable hours · 1 converted']) {
    assert.ok(shown.includes(words), `${words} in ${shown}`);
  }
  const headers = [...document.querySelectorAll('th')].map((th) => th.textContent.trim());
  const at = headers.indexOf('Converted');
  assert.ok(at > headers.indexOf('Demo'), headers.join(' | '));
  const cells = [...document.querySelectorAll('tbody tr')][0].querySelectorAll('td');
  assert.equal(cells[at].textContent.trim(), '3');
});

test('Tutor page: the Demo Conversion row, the conversion in the ledger, and a converted Demo marked as such', async () => {
  serve({ [`GET ${DETAIL_URL}`]: conversionDetail(true), [`GET ${DETAIL_URL}entries/`]: page([CONVERSION_ENTRY, CONVERTED_DEMO, ENTRIES[0]]),
    'POST /api/earnings/entries/e-demo/reverse/': { success: true, entry: { ...CONVERTED_DEMO, kind: 'REVERSAL', amount: '-300.00' } } });
  await open('detail', { user: ADMIN, tutorId: TUTOR_ID });
  const shown = text();
  for (const words of ['Demo Conversion', 'rate − Demo earning', '₹350 / converted Demo', '1 conversion', '+₹150', 'Demo conversion',
    'Enrolled 4 Dec 2026, 5:30 PM · Demo earned ₹300 → ₹350 converted', 'Converted', 'Waiting for its Demo', 'Kabir',
    'In all, for a converted Demo', 'Conversions']) {
    assert.ok(shown.includes(words), `${words} in ${shown}`);
  }
  // The class total leaves the conversion out: 1 Demo + 1 session.
  const footer = document.querySelector('table[aria-label="Earnings by class type"] tfoot tr');
  assert.equal(footer.querySelectorAll('td')[1].textContent.trim(), '2');
  // Reversing a converted Demo says its conversion is a line of its own.
  const triggers = document.querySelectorAll('button[aria-label="Actions for this earning"]');
  const [item] = await menuItems(triggers[1]);
  await click(item);
  assert.ok(text().includes('This Demo converted (+₹150). Its conversion is a separate line'), text());
});

test("Tutor page: a tutor's own Demo Conversion rate -- global, or their own amount -- sent with the others", async () => {
  serve({ [`GET ${DETAIL_URL}`]: conversionDetail(true), [`GET ${DETAIL_URL}entries/`]: page(ENTRIES), [`POST ${DETAIL_URL}rates/`]: conversionDetail(true) });
  await open('detail', { user: ADMIN, tutorId: TUTOR_ID });
  await click(buttons('Edit tutor rates')[0]);
  assert.ok(text().includes('Demo Conversion · per converted Demo'), text());
  assert.equal(document.querySelectorAll('input[name="rate-DEMO_CONVERSION"]').length, 2, 'global or tutor rate');
  await check([...document.querySelectorAll('input[name="rate-DEMO_CONVERSION"]')][1]);
  await type(document.querySelector('input[aria-label="Demo Conversion tutor rate in rupees"]'), '400');
  await type(document.querySelector('#tutor-rates-reason'), 'Strong converter');
  await click(buttons('Save tutor rates')[0]);
  assert.deepEqual(calls('POST', `${DETAIL_URL}rates/`).map((c) => c.data), [{ rates: { DEMO_CONVERSION: '400' }, reason: 'Strong converter' }]);
});

test('Global rates: a Demo Conversion rate not set yet may stay blank, and is sent once entered', async () => {
  const ratesData = { ...STATUS, history: [], tutors: [],
    rates: [['DIAGNOSTIC', 'CLASS', '300.00'], ['DEMO', 'CLASS', '300.00'], ['SESSION', 'HOUR', '400.00'], ['DEMO_CONVERSION', 'CONVERSION', null]]
      .map(([classType, unit, amount]) => ({ class_type: classType, unit, amount, effective_from: amount ? STATUS.activated_at : null })) };
  serve({ 'GET /api/earnings/overview/': OVERVIEW, 'GET /api/earnings/rates/': ratesData, 'POST /api/earnings/rates/': ratesData });
  await open('overview', { user: ADMIN });
  await click(buttons('Global rates')[0]);
  assert.ok(text().includes('Not set yet'), text());
  assert.equal(document.querySelector('#global-DEMO_CONVERSION').getAttribute('aria-invalid'), null, 'blank is fine while it is not set');
  await type(document.querySelector('#global-SESSION'), '425');
  await type(document.querySelector('#global-reason'), 'Annual revision');
  assert.ok(!buttons('Save new rates')[0].disabled, 'another rate changes without it');
  await type(document.querySelector('#global-DEMO_CONVERSION'), '350');
  await click(buttons('Save new rates')[0]);
  assert.deepEqual(calls('POST', '/api/earnings/rates/').map((c) => c.data),
    [{ rates: { SESSION: '425', DEMO_CONVERSION: '350' }, reason: 'Annual revision' }]);
});

test('My Earnings: a tutor reads their conversions and how a conversion counts', async () => {
  serve({ 'GET /api/earnings/me/': conversionDetail(false),
    'GET /api/earnings/me/entries/': page([CONVERSION_ENTRY, CONVERTED_DEMO].map(asTutor)) });
  await open('mine');
  const shown = text();
  for (const words of ['Demo conversion:', 'the last one taught before enrolling', '₹350 / converted Demo', '+₹150', '1 converted',
    'Kabir', 'Meera', 'Waiting for its Demo']) {
    assert.ok(shown.includes(words), `${words} in ${shown}`);
  }
  assert.ok(!shown.includes('Rate source'), 'no administrator detail');
  assert.ok(!shown.includes('sale-'), 'no sale on the page');
});

// ---------------------------------------------------------------------- run
let failures = 0;
for (const { name, fn } of tests) {
  try { await fn(); console.log(`PASS ${name}`); }
  catch (err) { failures++; console.log(`FAIL ${name}: ${err.stack}`); }
  finally { if (cleanup) await cleanup(); cleanup = null; await settle(); }
}
console.error = quiet;
console.log(`${tests.length - failures}/${tests.length} Tutor Earnings tests passed.`);
window.close(); process.exit(failures ? 1 : 0);
