// Lead management tests: the real Leads pages (src/pages/LeadsPage.jsx,
// LeadPage.jsx) and a BDE's My Enquiries (EnquiriesPage.jsx, EnquiryPage.jsx) in
// jsdom, their API answered per test by api-stub.js -- an administrator
// listing, filtering, adding and assigning leads, including the API's
// refusals; a BDE seeing their own leads with their status, calling or
// messaging the parent and sending their booking links; and who may open
// which page.
//
//   npm run test:leads
//
// Which callers the Hub routes to each page across the whole Hub is the access
// tests' job (tests/access, paths /leads and /enquiries).
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
const bundle = path.join(tmpdir(), `hub-leads-${process.pid}.mjs`);
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

/** The options the Radix Select labelled `label` (or with that id) offers, closed again afterwards. */
async function optionsOf(label) {
  const trigger = document.querySelector(`[aria-label="${label}"]`) ?? document.getElementById(label);
  assert.ok(trigger, `no select labelled ${label}`);
  trigger.focus();
  await keyDown(trigger, 'Enter');
  const options = [...document.querySelectorAll('[role="option"]')].map((element) => clean(element.textContent));
  await keyDown(document.activeElement, 'Escape');
  return options;
}

const rows = () => [...document.querySelectorAll('tbody tr')];
const headers = () => [...document.querySelectorAll('th')].map((th) => clean(th.textContent));
const link = (text) => [...document.querySelectorAll('a')].find((a) => clean(a.textContent) === text);

/** The lead page's fields ("Email", "Owner", ...) as { label: value }. */
function fields() {
  return Object.fromEntries([...document.querySelectorAll('dt')].map((dt) => [clean(dt.textContent), clean(dt.nextElementSibling?.textContent)]));
}

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
  globalThis.__leadsApi.handler = (entry) => {
    const answer = table[`${entry.method} ${entry.url}`];
    if (answer === undefined) return fail(404, { error: 'NOT_FOUND', message: `No answer for ${entry.method} ${entry.url}` });
    return typeof answer === 'function' ? answer(entry) : ok(answer);
  };
}

const calls = (method, url) => globalThis.__leadsApi.calls.filter((entry) => entry.method === method && entry.url === url);

// ------------------------------------------------------------------ fixtures
const ADMIN = { id: 'admin', role: 'ADMIN', permissions: ['accounts.add_lead', 'accounts.assign_lead_owner', 'accounts.view_all_bookings', 'accounts.view_all_leads'] };
const VIEWER = { id: 'viewer', role: 'ADMIN', permissions: ['accounts.view_all_leads'] };
const BDE = { id: 'bde-1', role: 'BDE', permissions: ['accounts.add_enquiry', 'accounts.view_own_booking_links', 'accounts.view_own_enquiries'] };

const LEADS = '/api/leads/';
const BDES = '/api/leads/bdes/';
// Account ids are UUIDs: the owner filter drops anything else from the URL.
const ANIL = { id: '11111111-1111-4111-8111-111111111111', full_name: 'Anil Kumar' };
const BINA = { id: '22222222-2222-4222-8222-222222222222', full_name: 'Bina Das' };
const BDE_OPTIONS = [{ ...ANIL, assignable: true }, { ...BINA, assignable: true },
  { id: '00000000-0000-4000-8000-000000000000', full_name: 'Old Hand', assignable: false }];

const WEBSITE = { id: 'lead-web', parent_name: 'Meera Menon', phone: '+91 9876543210', student_name: 'Kavya', grade: 'Class 7',
  source: 'WEBSITE', source_label: 'Website', status: 'NEW', status_label: 'New', next_booking: null, added_at: null,
  owner: null, created_at: '2026-11-06T04:00:00+00:00' };
const OWNED = { id: 'lead-own', parent_name: 'Asha Nair', phone: '+971 501234567', student_name: 'Riya', grade: 'Class 8',
  source: 'DEMO_LINK', source_label: 'Demo link', status: 'DEMO_BOOKED', status_label: 'Demo booked',
  next_booking: { id: 'b-1', booking_type: 'DEMO', date: '2026-11-08', time: '19:30', starts_at: '2026-11-08T14:00:00+00:00' },
  added_at: '2026-11-01T04:00:00+00:00', owner: ANIL, created_at: '2026-11-01T04:00:00+00:00' };
const list = (results, count = results.length) => ({ results, count, page: 1, page_size: 25 });
const detailOf = (row, extra = {}) => ({
  ...row, phone_dial_code: row.phone.split(' ')[0], phone_number: row.phone.split(' ')[1], parent_email: '',
  school_name: 'Kendriya Vidyalaya', syllabus: 'CBSE', country: 'India', timezone: 'Asia/Kolkata', bookings: [],
  added_by: null, source_details: {}, ...extra,
});

const LINKS = { links: [
  { booking_type: 'DEMO', url: 'https://plus.eduport.app/demo?ref=DemoToken', created_at: '2026-10-27T09:00:00+05:30' },
  { booking_type: 'DIAGNOSTIC', url: 'https://plus.eduport.app/exam?ref=DiagToken', created_at: '2026-10-27T09:00:00+05:30' },
] };

// ------------------------------------------------------------------ the tests
const tests = [];
const test = (name, fn) => tests.push({ name, fn });

test('Leads: every lead with when it came in, its source, status and owner; Assign or Reassign each', async () => {
  serve({ [`GET ${LEADS}`]: list([WEBSITE, OWNED]), [`GET ${BDES}`]: { results: BDE_OPTIONS } });
  await open('/leads', ADMIN);
  assert.deepEqual(calls('GET', LEADS)[0].params, { page: 1, page_size: 25 });
  assert.deepEqual(headers(), ['Received', 'Student', 'Parent', 'Source', 'Status', 'Next booking', 'Owner', 'Open']);
  const [web, own] = rows();
  assert.match(clean(web.textContent), /6 Nov 2026.*Kavya.*Class 7.*Meera Menon.*\+91 9876543210.*Website.*New.*—.*Unassigned/);
  assert.match(clean(own.textContent), /Riya.*Asha Nair.*Demo link.*Demo booked.*Sun, 8 Nov.*7:30 PM IST.*Anil Kumar/);
  assert.ok(button('Assign', web) && !button('Reassign', web));
  assert.ok(button('Reassign', own) && !button('Assign', own));
  assert.equal(web.querySelector('a').getAttribute('href'), '/leads/lead-web');
  assert.ok(button('Add Lead'));
});

test('Leads: the filters -- status, source and owner, Unassigned included -- go to the API from the URL', async () => {
  serve({ [`GET ${LEADS}`]: list([WEBSITE]), [`GET ${BDES}`]: { results: BDE_OPTIONS } });
  await open('/leads', ADMIN);
  assert.deepEqual(await optionsOf('Filter by owner'), ['All owners', 'Unassigned', 'Anil Kumar', 'Bina Das', 'Old Hand (inactive)']);
  const statuses = await optionsOf('Filter by status');
  assert.deepEqual(statuses, ['All statuses', 'New', 'Booked (any type)', 'Diagnostic booked', 'Demo booked',
    'Completed (any type)', 'Diagnostic completed', 'Demo completed', 'Re-Demo required', 'Not started (any type)',
    'Diagnostic not started',
    'Demo not started', 'Cancelled (any type)', 'Diagnostic cancelled', 'Demo cancelled']);
  assert.ok((await optionsOf('Filter by source')).includes('Website'));
  assert.ok((await optionsOf('Filter by source')).includes('Landing page'));

  await choose('Filter by owner', 'Unassigned');
  await choose('Filter by source', 'Landing page');
  await choose('Filter by status', 'Demo completed');
  assert.deepEqual(calls('GET', LEADS).at(-1).params,
    { page: 1, page_size: 25, owner: 'unassigned', source: 'LANDING_PAGE', status: 'DEMO_COMPLETED' });
  await choose('Filter by owner', 'Bina Das');
  assert.equal(calls('GET', LEADS).at(-1).params.owner, BINA.id);
});

test('Leads: the dates a lead came in on go to the API from the URL, and Clear all filters drops them', async () => {
  serve({ [`GET ${LEADS}`]: list([WEBSITE]), [`GET ${BDES}`]: { results: BDE_OPTIONS } });
  const page = await open('/leads?status=NEW&from=2026-11-02&to=2026-11-08&page=2', ADMIN);
  assert.deepEqual(calls('GET', LEADS).at(-1).params,
    { page: 2, page_size: 25, status: 'NEW', from: '2026-11-02', to: '2026-11-08' });
  assert.match(clean(document.querySelector('[aria-label="Filter by received date"]').textContent), /2 Nov 2026 – 8 Nov 2026/);
  await click(button('Clear all filters'));
  assert.deepEqual(calls('GET', LEADS).at(-1).params, { page: 1, page_size: 25 });
  assert.equal(page.location().search, '');
  await page.unmount();

  // A range that ends before it starts is not sent.
  await open('/leads?from=2026-11-08&to=2026-11-02', ADMIN);
  assert.deepEqual(calls('GET', LEADS).at(-1).params, { page: 1, page_size: 25, from: '2026-11-08' });
});

test('Leads: an administrator adds a lead by hand, with the email; it lands unassigned and the list is read again', async () => {
  let posted = null;
  serve({
    [`GET ${LEADS}`]: list([WEBSITE]),
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
    [`POST ${LEADS}`]: (entry) => {
      posted = entry.data;
      return ok(detailOf({ ...WEBSITE, id: 'lead-new', student_name: 'Arjun', source: 'PHONE_CALL', source_label: 'Phone call' }));
    },
  });
  await open('/leads', ADMIN);
  await click(button('Add Lead'));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /added unassigned; assign it to a BDE/);
  await click(button('Add lead', dialog));
  assert.match(clean(topDialog().textContent), /Enter the parent's name\..*Choose how this lead reached Eduport Plus\./);
  assert.equal(calls('POST', LEADS).length, 0, 'nothing is sent until the form is complete');

  await typeInto(document.getElementById('enquiry-parent-name'), ' Meera Menon ');
  await typeInto(document.getElementById('enquiry-phone-number'), '98765 43210');
  await typeInto(document.getElementById('enquiry-parent-email'), 'meera@example.com');
  await typeInto(document.getElementById('enquiry-student-name'), 'Arjun');
  await choose('enquiry-grade', 'Class 6');
  await choose('enquiry-source', 'Phone call');
  await click(button('Add lead', topDialog()));
  assert.deepEqual(posted, {
    parent_name: 'Meera Menon', phone_dial_code: '+91', phone_number: '98765 43210', student_name: 'Arjun', grade: 'Class 6',
    source: 'PHONE_CALL', school_name: '', syllabus: '', country: '', student_timezone: '', parent_email: 'meera@example.com',
  });
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0);
  assert.match(bodyText(), /Added the lead for Arjun\. Assign it to a BDE when you are ready\. Open it/);
  assert.equal(link('Open it').getAttribute('href'), '/leads/lead-new');
  assert.equal(calls('GET', LEADS).length, 2, 'the list is read again');
});

test('Leads: a child who already has a lead is pointed to, not added twice', async () => {
  serve({
    [`GET ${LEADS}`]: list([WEBSITE]),
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
    [`POST ${LEADS}`]: () => fail(409, { error: 'LEAD_EXISTS', message: 'A lead for this child and phone number already exists.', lead_id: 'lead-web' }),
  });
  await open('/leads', ADMIN);
  await click(button('Add Lead'));
  await typeInto(document.getElementById('enquiry-parent-name'), 'Meera');
  await typeInto(document.getElementById('enquiry-phone-number'), '9876543210');
  await typeInto(document.getElementById('enquiry-student-name'), 'Kavya');
  await choose('enquiry-grade', 'Class 7');
  await choose('enquiry-source', 'Walk-in');
  await click(button('Add lead', topDialog()));
  assert.match(clean(topDialog().textContent), /A lead for this child and phone number already exists\. Open it/);
  assert.equal([...topDialog().querySelectorAll('a')].find((a) => clean(a.textContent) === 'Open it').getAttribute('href'), '/leads/lead-web');
});

test('Leads: assigning an unassigned lead offers active BDEs only and sends who owned it -- nobody', async () => {
  let put = null;
  serve({
    [`GET ${LEADS}`]: list([WEBSITE, OWNED]),
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
    [`PUT ${LEADS}lead-web/owner/`]: (entry) => {
      put = entry.data;
      return ok({ ...detailOf(WEBSITE), owner: BINA, changed: true });
    },
  });
  await open('/leads', ADMIN);
  await click(button('Assign', rows()[0]));
  assert.match(clean(topDialog().textContent), /Assign lead.*Kavya's lead has no BDE yet/);
  assert.deepEqual(await optionsOf('BDE'), ['Anil Kumar', 'Bina Das'], 'an inactive BDE is never offered');
  await choose('BDE', 'Bina Das');
  await click(button('Assign', topDialog()));
  assert.deepEqual(put, { bde_id: BINA.id, current_owner_id: null });
  assert.match(bodyText(), /Kavya's lead is now Bina Das's\./);
  assert.equal(calls('GET', LEADS).length, 2);
});

test("Leads: reassigning never offers the current owner and sends them; a change made meanwhile is refused and shown", async () => {
  let fresh = false;
  serve({
    [`GET ${LEADS}`]: () => ok(list([WEBSITE, fresh ? { ...OWNED, owner: BINA } : OWNED])),
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
    [`PUT ${LEADS}lead-own/owner/`]: (entry) => {
      if (entry.data.current_owner_id === ANIL.id) {
        fresh = true;
        return fail(409, { error: 'OWNER_CHANGED', message: 'Someone else changed who owns this lead. Check the new owner before assigning it again.' });
      }
      return ok({ ...detailOf(OWNED), owner: ANIL, changed: true });
    },
  });
  await open('/leads', ADMIN);
  await click(button('Reassign', rows()[1]));
  assert.match(clean(topDialog().textContent), /Riya's lead is Anil Kumar's/);
  assert.deepEqual(await optionsOf('BDE'), ['Bina Das']);
  await choose('BDE', 'Bina Das');
  await click(button('Reassign', topDialog()));
  assert.deepEqual(calls('PUT', `${LEADS}lead-own/owner/`)[0].data, { bde_id: BINA.id, current_owner_id: ANIL.id });
  assert.match(clean(topDialog().textContent), /Someone else changed who owns this lead/);
  // The list is read again and the open dialog follows it: the owner is Bina now.
  assert.equal(calls('GET', LEADS).length, 2);
  assert.match(clean(topDialog().textContent), /Riya's lead is Bina Das's/);
  assert.deepEqual(await optionsOf('BDE'), ['Anil Kumar']);
  await choose('BDE', 'Anil Kumar');
  await click(button('Reassign', topDialog()));
  assert.deepEqual(calls('PUT', `${LEADS}lead-own/owner/`)[1].data, { bde_id: ANIL.id, current_owner_id: BINA.id });
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0);
});

test('Leads: without the permissions to add or assign, neither is offered', async () => {
  serve({ [`GET ${LEADS}`]: list([WEBSITE, OWNED]), [`GET ${BDES}`]: { results: BDE_OPTIONS } });
  await open('/leads', VIEWER);
  assert.ok(!button('Add Lead') && !button('Assign') && !button('Reassign'));
  assert.ok(!headers().includes('Assign'));
  assert.ok(headers().includes('Owner'));
});

test('Lead page: the parent, the child, where it came from, its owner and bookings; assigning it from here', async () => {
  const booking = { id: 'b-9', booking_type: 'DIAGNOSTIC', date: '2026-11-09', time: '10:00', starts_at: '2026-11-09T04:30:00+00:00',
    status: 'BOOKED', ended: false, activity_state: 'UPCOMING', started_at: null, booked_at: '2026-11-06T05:00:00+00:00',
    cancelled_at: null, tutor: null, tutor_meet_link: null, parent_confirmation: 'AWAITING', actions: { cancel: false, no_show: false } };
  const lead = detailOf({ ...WEBSITE, status: 'DIAGNOSTIC_BOOKED', status_label: 'Diagnostic booked' }, {
    parent_email: 'meera@example.com', source_details: { utm_source: 'instagram', utm_campaign: 'maths-uae' }, bookings: [booking],
  });
  serve({
    [`GET ${LEADS}lead-web/`]: lead,
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
    [`PUT ${LEADS}lead-web/owner/`]: () => ok({ ...lead, owner: ANIL, added_at: '2026-11-06T06:00:00+00:00', changed: true }),
  });
  await open('/leads/lead-web', ADMIN);
  const shown = fields();
  assert.equal(shown.Email, 'meera@example.com');
  assert.deepEqual([shown.Source, shown['Campaign source'], shown.Campaign, shown.Status],
    ['Website', 'instagram', 'maths-uae', 'Diagnostic booked']);
  assert.deepEqual([shown.Owner, shown.Received, 'Added by' in shown], ['Unassigned', '6 Nov 2026', false]);
  assert.equal(link('Call').getAttribute('href'), 'tel:+919876543210');
  assert.equal(link('WhatsApp').getAttribute('href'), 'https://wa.me/919876543210');
  assert.equal(link('Open').getAttribute('href'), '/bookings/diagnostic?when=all&booking=b-9');

  await click(button('Assign'));
  await choose('BDE', 'Anil Kumar');
  await click(button('Assign', topDialog()));
  assert.deepEqual(calls('PUT', `${LEADS}lead-web/owner/`)[0].data, { bde_id: ANIL.id, current_owner_id: null });
  assert.match(bodyText(), /Kavya's lead is now Anil Kumar's\./);
  assert.deepEqual([fields().Owner, fields()['Owner since']], ['Anil Kumar', '6 Nov 2026']);
  assert.ok(button('Reassign'));
});

test('Lead page: one that does not exist', async () => {
  serve({ [`GET ${BDES}`]: { results: [] } });
  await open('/leads/lead-gone', ADMIN);
  assert.match(bodyText(), /Lead not found/);
});

test('My Enquiries: a BDE sees their own enquiries with the status their bookings give, and their booking links; no owner, no assigning', async () => {
  serve({
    [`GET /api/bde/enquiries/`]: list([{ ...OWNED, owner: undefined, created_at: undefined },
      { ...WEBSITE, id: 'lead-given', owner: undefined, added_at: '2026-11-06T06:00:00+00:00' }]),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/enquiries', BDE);
  assert.match(bodyText(), /My Enquiries.*Every enquiry that is yours/);
  assert.deepEqual(headers(), ['Parent', 'Phone', 'Student', 'Class', 'Source', 'Status', 'Next booking', 'Open']);
  const [own, given] = rows();
  assert.match(clean(own.textContent), /Riya.*Demo link.*Demo booked/);
  assert.match(clean(given.textContent), /Kavya.*Website.*New/);
  assert.equal(given.querySelector('a').getAttribute('href'), '/enquiries/lead-given');
  assert.ok(button('Copy Demo Link') && button('Copy Diagnostic Link'), 'the booking links are shared from My Enquiries');
  assert.ok(button('Add Enquiry') && !button('Add lead'), 'a BDE adds enquiries');
  assert.ok(!button('Assign') && !button('Reassign'));
  assert.ok(!globalThis.__leadsApi.calls.some((entry) => entry.url.startsWith('/api/leads/')), "the administrators' API is never called");
  assert.ok((await optionsOf('Filter by status')).includes('Diagnostic completed'));
  // The dashboard's Upcoming Bookings tile lands here filtered to bookings of either type to come.
  await mounted.pop().unmount();
  await open('/enquiries?status=BOOKED', BDE);
  assert.equal(calls('GET', '/api/bde/enquiries/').at(-1).params.status, 'BOOKED');
  assert.equal(clean(document.querySelector('[aria-label="Filter by status"]').textContent), 'Booked (any type)');
});

test("My Enquiries: an enquiry's page calls or messages the parent, and sends the BDE's booking link to the parent's WhatsApp", async () => {
  serve({
    [`GET /api/bde/enquiries/lead-given/`]: detailOf({ ...WEBSITE, id: 'lead-given', owner: undefined }, { parent_email: 'meera@example.com' }),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/enquiries/lead-given', BDE);
  assert.equal(fields().Email, 'meera@example.com');
  assert.equal(link('Call').getAttribute('href'), 'tel:+919876543210');
  assert.equal(link('WhatsApp').getAttribute('href'), 'https://wa.me/919876543210');
  const trigger = button('More ways to share the demo link');
  trigger.focus();
  await keyDown(trigger, 'Enter');
  const send = [...document.querySelectorAll('[role="menuitem"]')].find((item) => clean(item.textContent) === 'Send to the parent on WhatsApp');
  assert.ok(send, 'the menu sends the link to this parent');
  assert.equal(send.getAttribute('href'),
    `https://wa.me/919876543210?text=${encodeURIComponent('Book a demo class with Eduport Plus: https://plus.eduport.app/demo?ref=DemoToken')}`);
});

test('My Enquiries: an enquiry reassigned to another BDE is answered as one that does not exist', async () => {
  serve({
    [`GET /api/bde/enquiries/lead-moved/`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such enquiry.' }),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/enquiries/lead-moved', BDE);
  assert.match(bodyText(), /Enquiry not found.*assigned to another BDE, or it is not one of your enquiries\./);
});

test("Layout: the Leads pages take the design-system layout, never the legacy wrapper and its extra top padding", async () => {
  serve({
    [`GET ${LEADS}`]: list([WEBSITE]),
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
    [`GET ${LEADS}lead-web/`]: detailOf(WEBSITE),
  });
  for (const at of ['/leads', '/leads/lead-web']) {
    await open(at, ADMIN, { layout: true });
    assert.ok(document.querySelector('[data-slot="sidebar-inset"]'), `${at} renders inside the Hub layout`);
    assert.ok(document.querySelector('h1'), `${at} renders its page`);
    assert.ok(!document.querySelector('.legacy-ui'), `${at} is not wrapped in .legacy-ui`);
    await mounted.pop().unmount();
  }
});

test('Access: Leads is for holders of accounts.view_all_leads; My Enquiries for BDEs only', () => {
  assert.equal(canOpenPage(ADMIN, '/leads'), true);
  assert.equal(canOpenPage(VIEWER, '/leads'), true);
  assert.equal(canOpenPage(BDE, '/leads'), false);
  assert.equal(canOpenPage({ role: 'TUTOR', permissions: ['accounts.view_assigned_bookings'] }, '/leads'), false);
  assert.equal(canOpenPage(BDE, '/enquiries'), true);
  // A superuser holds a BDE's permissions too (D1) but owns no leads.
  assert.equal(canOpenPage({ role: 'ADMIN', permissions: [...ADMIN.permissions, 'accounts.view_own_enquiries'] }, '/enquiries'), false);
  assert.equal(homePage(VIEWER), '/leads');
});

// ------------------------------------------------- the BDE workspace (redesign)
// The BDE dashboard and My Enquiries as the BDE Hub redesign (Phase 3) builds
// them: today's agenda in Indian time, the Demo and Diagnostic colours, the
// workspace's own words (enquiries, never leads), the list's search, filters
// and pages in the URL, and a phone's cards.

const DASHBOARD = '/api/bde/dashboard/';
const ENQUIRIES = '/api/bde/enquiries/';
const TODAY = '2026-11-08';
const RIYA = { id: 'lead-own', parent_name: 'Asha Nair', student_name: 'Riya', grade: 'Class 8' };
const KAVYA = { id: 'lead-web', parent_name: 'Meera Menon', student_name: 'Kavya', grade: 'Class 7' };
const EVENING_DEMO = { id: 'b-1', booking_type: 'DEMO', date: TODAY, time: '19:30', starts_at: '2026-11-08T14:00:00+00:00',
  status: 'BOOKED', activity_state: 'UPCOMING', tutor: { full_name: 'Jack Sabastian' }, enquiry: RIYA };
const MORNING_DIAGNOSTIC = { id: 'b-0', booking_type: 'DIAGNOSTIC', date: TODAY, time: '09:30', starts_at: '2026-11-08T04:00:00+00:00',
  status: 'COMPLETED', activity_state: 'COMPLETED', tutor: null, enquiry: KAVYA };
const dashboardOf = (agenda) => ({
  timezone: 'Asia/Kolkata', enquiries: { total: 2, last_7_days: 1 },
  bookings: { DEMO: { total: 3, upcoming: 1 }, DIAGNOSTIC: { total: 2, upcoming: 0 } },
  upcoming: { total: 1, rows: [{ id: 'b-1', booking_type: 'DEMO', date: TODAY, time: '19:30', starts_at: '2026-11-08T14:00:00+00:00', enquiry: RIYA }] },
  agenda,
  recent_enquiries: [{ ...OWNED, owner: undefined, created_at: undefined }],
});
const agendaItems = () => [...document.querySelectorAll('[aria-label="Today\'s bookings"] > li')];
/** The KPI tile labelled `label`. */
const tile = (label) => [...document.querySelectorAll('a, div')].find((el) => el.classList.contains('rounded-xl')
  && [...el.querySelectorAll('p')].some((p) => clean(p.textContent) === label));
const pageButtons = () => [...document.querySelectorAll('nav[aria-label="Pagination"] button[aria-label^="Page "]')]
  .map((b) => b.getAttribute('aria-label'));
const search = () => document.querySelector('input[aria-label="Search enquiries"]');
async function submitSearch(text) {
  await typeInto(search(), text);
  await fire(search().form, new window.Event('submit', { bubbles: true, cancelable: true }));
}
/** Lay the page out as a phone (390px wide) while `fn` runs. */
async function onAPhone(fn) {
  const wide = window.innerWidth;
  Object.defineProperty(window, 'innerWidth', { value: 390, configurable: true, writable: true });
  try {
    await fn();
  } finally {
    Object.defineProperty(window, 'innerWidth', { value: wide, configurable: true, writable: true });
  }
}

test("BDE dashboard: today's agenda is the bookings on the API's Indian date, soonest first, each with where it stands", async () => {
  serve({
    [`GET ${DASHBOARD}`]: dashboardOf({ date: TODAY, total: 2, rows: [MORNING_DIAGNOSTIC, EVENING_DEMO] }),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/dashboard', BDE);
  assert.equal(calls('GET', DASHBOARD).length, 1);
  // The day is the API's (8 November, a Sunday), whatever this device's clock says.
  assert.match(bodyText(), /Today's Agenda\s*Sun, 8 Nov · Indian time \(IST\)\s*2 bookings/);
  const [morning, evening] = agendaItems();
  assert.equal(agendaItems().length, 2);
  assert.match(clean(morning.textContent), /^9:30 AM\s*Diagnostic test · Kavya\s*Completed\s*Class 7 · Parent: Meera Menon$/);
  assert.match(clean(evening.textContent), /^7:30 PM\s*Demo class · Riya\s*Upcoming\s*Class 8 · Parent: Asha Nair · Tutor: Jack Sabastian$/);
  assert.equal(morning.querySelector('a').getAttribute('href'), '/enquiries/lead-web?tab=bookings&highlight=b-0');
  assert.equal(evening.querySelector('a').getAttribute('href'), '/enquiries/lead-own?tab=bookings&highlight=b-1');
  assert.match(clean(tile('Demo Bookings').textContent), /Demo Bookings\s*3\s*1 upcoming/);
  assert.match(clean(tile('Diagnostic Bookings').textContent), /Diagnostic Bookings\s*2\s*None upcoming/);
});

test('BDE dashboard: the Demo and Diagnostic tiles wear their colours; an empty agenda says so', async () => {
  serve({ [`GET ${DASHBOARD}`]: dashboardOf({ date: TODAY, total: 0, rows: [] }), [`GET /api/bde/booking-links/`]: LINKS });
  await open('/dashboard', BDE);
  const icon = (label) => tile(label).querySelector('span');
  assert.ok(icon('Demo Bookings').classList.contains('text-demo-text'), 'Demo is blue');
  assert.ok(icon('Diagnostic Bookings').classList.contains('text-diagnostic-text'), 'Diagnostic is green');
  assert.equal(agendaItems().length, 0);
  assert.match(bodyText(), /Nothing booked for today/);
});

test('BDE dashboard: Add Enquiry adds one in the workspace\'s own words and opens it', async () => {
  serve({
    [`GET ${DASHBOARD}`]: dashboardOf({ date: TODAY, total: 0, rows: [] }),
    [`GET /api/bde/booking-links/`]: LINKS,
    [`POST ${ENQUIRIES}`]: (entry) => ok({ ...detailOf({ ...WEBSITE, id: 'lead-new', owner: undefined }), student_name: entry.data.student_name }),
    [`GET ${ENQUIRIES}lead-new/`]: detailOf({ ...WEBSITE, id: 'lead-new', owner: undefined }),
  });
  const page = await open('/dashboard', BDE);
  assert.ok(button('Add Enquiry') && !button('Add lead'));
  await click(button('Add Enquiry'));
  const dialog = topDialog();
  assert.match(clean(dialog.textContent), /^Add Enquiry.*An enquiry that reached you outside your booking links\. It is added to your enquiries straight away\./);
  assert.doesNotMatch(clean(dialog.textContent), /\blead/i);
  await typeInto(dialog.querySelector('#enquiry-parent-name'), 'Meera Menon');
  await typeInto(dialog.querySelector('#enquiry-phone-number'), '9876543210');
  await typeInto(dialog.querySelector('#enquiry-student-name'), 'Kavya');
  await choose('enquiry-grade', 'Class 7');
  await choose('enquiry-source', 'Phone call');
  await click(button('Add Enquiry', topDialog()));
  const [posted] = calls('POST', ENQUIRIES);
  assert.equal(posted.data.student_name, 'Kavya');
  assert.equal(posted.data.source, 'PHONE_CALL');
  assert.equal(page.location().pathname, '/enquiries/lead-new');
});

test('BDE dashboard: a failed load offers Try again; a refusal does not', async () => {
  let attempts = 0;
  serve({
    [`GET ${DASHBOARD}`]: () => (++attempts === 1 ? fail(500, {}) : ok(dashboardOf({ date: TODAY, total: 0, rows: [] }))),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/dashboard', BDE);
  assert.match(bodyText(), /Could not load your dashboard\./);
  await click(button('Try again'));
  assert.match(bodyText(), /Today's Agenda/);
  await mounted.pop().unmount();

  serve({
    [`GET ${DASHBOARD}`]: () => fail(403, { error: 'NOT_A_BDE', message: 'Enquiries belong to BDE accounts, and this account is not one.' }),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/dashboard', BDE);
  assert.match(bodyText(), /this account is not one\./);
  assert.ok(!button('Try again'));
});

test('My Enquiries: search, status and source live in the URL and the API; each change goes back to page 1; Clear drops them all', async () => {
  serve({ [`GET ${ENQUIRIES}`]: list([{ ...OWNED, owner: undefined }], 60), [`GET /api/bde/booking-links/`]: LINKS });
  const page = await open('/enquiries?page=2', BDE);
  assert.deepEqual(calls('GET', ENQUIRIES).at(-1).params, { page: 2, page_size: 25 });

  await submitSearch('  Asha  ');
  assert.equal(page.location().search, '?q=Asha');
  assert.deepEqual(calls('GET', ENQUIRIES).at(-1).params, { page: 1, page_size: 25, q: 'Asha' });

  await choose('Filter by status', 'Demo booked');
  await choose('Filter by source', 'Website');
  assert.deepEqual(Object.fromEntries(new URLSearchParams(page.location().search)), { q: 'Asha', status: 'DEMO_BOOKED', source: 'WEBSITE' });
  assert.deepEqual(calls('GET', ENQUIRIES).at(-1).params, { page: 1, page_size: 25, q: 'Asha', status: 'DEMO_BOOKED', source: 'WEBSITE' });

  await choose('Filter by status', 'All statuses');
  assert.equal(new URLSearchParams(page.location().search).get('status'), null);

  await click(button('Clear'));
  assert.equal(page.location().search, '');
  assert.deepEqual(calls('GET', ENQUIRIES).at(-1).params, { page: 1, page_size: 25 });
  assert.equal(search().value, '', 'the search box follows the URL');
  assert.ok(!button('Clear'), 'nothing left to clear');
});

test('My Enquiries: numbered pages, Previous and Next move through the list, kept in the URL', async () => {
  serve({ [`GET ${ENQUIRIES}`]: list([{ ...OWNED, owner: undefined }], 130), [`GET /api/bde/booking-links/`]: LINKS });
  const page = await open('/enquiries', BDE);
  assert.deepEqual(pageButtons(), ['Page 1', 'Page 2', 'Page 3', 'Page 4', 'Page 5', 'Page 6']);
  assert.equal(button('Page 1').getAttribute('aria-current'), 'page');
  assert.ok(button('Previous').disabled);
  assert.match(bodyText(), /Showing 1–25 of 130/);

  await click(button('Page 3'));
  assert.equal(page.location().search, '?page=3');
  assert.equal(calls('GET', ENQUIRIES).at(-1).params.page, 3);
  assert.match(bodyText(), /Showing 51–75 of 130/);
  await click(button('Next'));
  assert.equal(page.location().search, '?page=4');
  await click(button('Previous'));
  assert.equal(page.location().search, '?page=3');
  await mounted.pop().unmount();

  // Many pages: the first, the last and the current page's neighbours, the rest elided.
  serve({ [`GET ${ENQUIRIES}`]: list([{ ...OWNED, owner: undefined }], 300), [`GET /api/bde/booking-links/`]: LINKS });
  await open('/enquiries?page=6', BDE);
  assert.deepEqual(pageButtons(), ['Page 1', 'Page 5', 'Page 6', 'Page 7', 'Page 12']);
  assert.ok(button('Next') && !button('Next').disabled);
});

test('My Enquiries: on a phone each enquiry is a card that opens it -- no table to scroll sideways', async () => {
  serve({
    [`GET ${ENQUIRIES}`]: list([{ ...OWNED, owner: undefined }, { ...WEBSITE, id: 'lead-given', owner: undefined }]),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await onAPhone(async () => {
    await open('/enquiries', BDE);
    assert.equal(document.querySelector('table'), null, 'no table on a phone');
    const cards = [...document.querySelectorAll('[aria-label="Your enquiries"] > li')];
    assert.equal(cards.length, 2);
    assert.match(clean(cards[0].textContent), /^Riya\s*Class 8 · Asha Nair\s*Demo booked\s*Phone\s*\+971 501234567\s*Source\s*Demo link\s*Next booking\s*Sun, 8 Nov · 7:30 PM IST$/);
    assert.match(clean(cards[1].textContent), /Kavya.*New.*Website.*Next booking\s*—/);
    const links = cards.map((card) => [...card.querySelectorAll('a')].map((a) => [clean(a.textContent), a.getAttribute('href')]));
    assert.deepEqual(links, [[['Riya', '/enquiries/lead-own']], [['Kavya', '/enquiries/lead-given']]]);
  });
});

test('My Enquiries: with nothing to list it says why -- nothing matches, or nothing yet -- and what to do', async () => {
  serve({ [`GET ${ENQUIRIES}`]: list([], 0), [`GET /api/bde/booking-links/`]: LINKS });
  const page = await open('/enquiries?q=zzz', BDE);
  assert.match(bodyText(), /No enquiries match these filters/);
  assert.equal(document.querySelector('nav[aria-label="Pagination"]'), null);
  await click(button('Clear filters'));
  assert.equal(page.location().search, '');
  assert.match(bodyText(), /No enquiries yet.*add an enquiry that reached you another way/);
  const addButtons = [...document.querySelectorAll('button')].filter((b) => clean(b.textContent) === 'Add Enquiry');
  assert.equal(addButtons.length, 2, 'beside the title and in the empty list');
  await click(addButtons[1]);
  assert.match(clean(topDialog().textContent), /^Add Enquiry/);
});

test('My Enquiries: a failed load offers Try again, then the list loads', async () => {
  let attempts = 0;
  serve({
    [`GET ${ENQUIRIES}`]: () => (++attempts === 1 ? fail(500, {}) : ok(list([{ ...OWNED, owner: undefined }]))),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/enquiries', BDE);
  assert.match(bodyText(), /Could not load your enquiries\./);
  await click(button('Try again'));
  assert.equal(rows().length, 1);
  assert.doesNotMatch(bodyText(), /Could not load/);
});

test("Access: the rest of the BDE workspace -- its temporary pages too -- is for BDEs, never another role or a superuser", () => {
  const superuser = { role: 'ADMIN', permissions: [...ADMIN.permissions, 'accounts.view_own_enquiries', 'accounts.view_all_activity'] };
  for (const at of ['/demo-bookings', '/diagnostic-bookings', '/sales', '/plans']) {
    assert.equal(canOpenPage(BDE, at), true, `${at} for a BDE`);
    assert.equal(canOpenPage({ role: 'BDE', permissions: [] }, at), false, `${at} for a BDE holding nothing`);
    assert.equal(canOpenPage(ADMIN, at), false, `${at} for an administrator`);
    assert.equal(canOpenPage(superuser, at), false, `${at} for a superuser`);
    assert.equal(canOpenPage({ role: 'SALES_TL', permissions: [] }, at), false, `${at} for a Sales TL`);
  }
  // Follow-ups are the leads' parent communication: a BDE who may see it, as the API asks (Phase 6).
  const communicating = { ...BDE, permissions: [...BDE.permissions, 'accounts.view_own_lead_communications'] };
  assert.equal(canOpenPage(BDE, '/follow-ups'), false, 'Follow-ups need accounts.view_own_lead_communications');
  assert.equal(canOpenPage(communicating, '/follow-ups'), true);
  assert.equal(canOpenPage({ ...superuser, permissions: [...superuser.permissions, 'accounts.view_own_lead_communications'] }, '/follow-ups'), false);
  assert.equal(canOpenPage({ role: 'ADMIN', permissions: ['accounts.view_all_communications'] }, '/follow-ups'), false);
  // Activity is everyone's who keeps one: a BDE's own (the BDE workspace), or the log.
  assert.equal(canOpenPage(BDE, '/activity'), true);
  assert.equal(canOpenPage({ role: 'BDE', permissions: [] }, '/activity'), false);
  assert.equal(canOpenPage(ADMIN, '/activity'), false);
  assert.equal(homePage(BDE), '/dashboard');
});

// ------------------------------------------------------- Student Time (Student Local Time)
// The zone a lead's student is in (student_timezone, backend bookings.student_timezones): set or
// corrected by its BDE (their own enquiries) or an administrator (any lead), and read beside each
// booking's Indian time from the booking's own instant. Every instant here is the very IST date and
// time it is booked at.
const SUN_8_NOV_0730 = '2026-11-08T02:00:00+00:00'; // Sun 8 Nov, 7:30 AM IST -- 6:00 AM in Dubai
const SAT_7_NOV_0730 = '2026-11-07T02:00:00+00:00'; // Sat 7 Nov, 7:30 AM IST -- 9:00 PM on Fri 6 Nov in New York (EST)
const MON_2_NOV_1930 = '2026-11-02T14:00:00+00:00'; // Mon 2 Nov, 7:30 PM IST -- 9:00 AM in New York (EST)
const MON_9_NOV_1930 = '2026-11-09T14:00:00+00:00'; // Mon 9 Nov, 7:30 PM IST -- 6:00 PM in Dubai
const CHANGE_STUDENT_TIMEZONE = 'accounts.change_student_timezone';
const ADMIN_TZ = { ...ADMIN, id: 'admin-tz', permissions: [...ADMIN.permissions, CHANGE_STUDENT_TIMEZONE].sort() };
const BDE_TZ = { ...BDE, id: 'bde-tz', permissions: [...BDE.permissions, CHANGE_STUDENT_TIMEZONE].sort() };
/** A booking of a lead in full (backend enquiries._booking_entry): flat, its own instant, the student's zone. */
const entryAt = (id, booking_type, date, time, starts_at, student_timezone, extra = {}) => ({ id, booking_type, date, time,
  starts_at, student_timezone, status: 'BOOKED', ended: false, activity_state: 'UPCOMING', started_at: null,
  booked_at: '2026-11-01T05:00:00+00:00', cancelled_at: null, tutor: null, tutor_meet_link: null, parent_confirmation: 'AWAITING',
  actions: { cancel: false, no_show: false }, ...extra });
const TIMEZONE_CHOICES = ['Not set', 'India', 'United Arab Emirates', 'Qatar', 'Saudi Arabia', 'Kuwait', 'Bahrain', 'Oman',
  'Singapore', 'United Kingdom', 'US — Eastern', 'US — Central', 'US — Mountain', 'US — Pacific', 'Australia — Sydney',
  'Australia — Perth', 'Sri Lanka', 'Nepal', 'Bangladesh'];

test("Lead page: the student's timezone is set and cleared from the Parent panel; the bookings' Student Time follows", async () => {
  const booking = entryAt('b-9', 'DIAGNOSTIC', '2026-11-09', '19:30', MON_9_NOV_1930, null);
  const lead = detailOf(WEBSITE, { student_timezone: null, bookings: [booking] });
  const puts = [];
  serve({
    [`GET ${LEADS}lead-web/`]: lead,
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
    [`PUT ${LEADS}lead-web/student-timezone/`]: (entry) => {
      puts.push(entry.data);
      const zone = entry.data.student_timezone;
      return ok({ ...lead, student_timezone: zone, bookings: [{ ...booking, student_timezone: zone }], changed: true });
    },
  });
  await open('/leads/lead-web', ADMIN_TZ);
  assert.equal(fields()['Student timezone'], 'Not setChange');
  assert.ok(!headers().includes('Student Time'), 'no zone known: the bookings add nothing');

  await click(button('Change student timezone'));
  assert.match(clean(topDialog().textContent),
    /^Change student timezone.*Booking times stay in Indian time \(IST\); only the Student Time shown beside them changes\./);
  assert.equal(clean(document.getElementById('student-timezone').textContent), 'Not set');
  assert.deepEqual(await optionsOf('Student timezone'), TIMEZONE_CHOICES);
  await choose('Student timezone', 'United Arab Emirates');
  await click(button('Save', topDialog()));
  assert.deepEqual(puts, [{ student_timezone: 'Asia/Dubai' }]);
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0);
  assert.match(bodyText(), /Kavya's timezone is now United Arab Emirates \(Asia\/Dubai\)\./);
  assert.equal(fields()['Student timezone'], 'United Arab Emirates (Asia/Dubai)Change');
  // The lead as the API answers it: its booking at the student's time, in a column of its own.
  assert.deepEqual(headers(), ['When (IST)', 'Student Time', 'Type', 'Status', 'Tutor', 'Booked on', 'Open']);
  assert.match(clean(rows()[0].textContent), /^Mon, 9 Nov · 7:30 PM IST6:00 PM UAEDiagnostic test/);

  // Not set clears it: null is sent.
  await click(button('Change student timezone'));
  assert.equal(clean(document.getElementById('student-timezone').textContent), 'United Arab Emirates', 'the saved zone, chosen');
  await choose('Student timezone', 'Not set');
  await click(button('Save', topDialog()));
  assert.deepEqual(puts.at(-1), { student_timezone: null });
  assert.match(bodyText(), /Kavya's timezone is no longer set\./);
  assert.equal(fields()['Student timezone'], 'Not setChange');
  assert.ok(!headers().includes('Student Time'));
  assert.ok(!globalThis.__leadsApi.calls.some((entry) => entry.url.startsWith('/api/bde/')), "the BDE's routes are never called");
});

test('Lead page: a zone the API refuses, or a lead another change holds, is said in the dialog, which stays open', async () => {
  let answer = () => fail(400, { error: 'INVALID_TIMEZONE', message: 'Choose a valid time zone.' });
  serve({
    [`GET ${LEADS}lead-web/`]: detailOf(WEBSITE, { student_timezone: 'Asia/Dubai' }),
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
    [`PUT ${LEADS}lead-web/student-timezone/`]: () => answer(),
  });
  await open('/leads/lead-web', ADMIN_TZ);
  await click(button('Change student timezone'));
  await choose('Student timezone', 'US — Eastern');
  await click(button('Save', topDialog()));
  assert.deepEqual(calls('PUT', `${LEADS}lead-web/student-timezone/`)[0].data, { student_timezone: 'America/New_York' });
  assert.match(clean(topDialog().textContent), /Choose a valid time zone\./);
  // Busy: the API's own words when it gives them, the dialog's when it does not.
  answer = () => fail(503, { error: 'LEAD_BUSY', message: 'This lead is being changed right now. Try again in a moment.' });
  await click(button('Save', topDialog()));
  assert.match(clean(topDialog().textContent), /This lead is being changed right now\. Try again in a moment\./);
  answer = () => fail(503, { error: 'LEAD_BUSY' });
  await click(button('Save', topDialog()));
  assert.match(clean(topDialog().textContent), /Someone else is changing this student's details right now\. Try again in a moment\./);
  assert.equal(fields()['Student timezone'], 'United Arab Emirates (Asia/Dubai)Change', 'nothing changed');
});

test('Lead page: an older name opens on its listed zone, and Save without a change sends nothing; the dialog\'s own words where the API gives none', async () => {
  // Chrome gives India as Asia/Calcutta: the lead keeps it as given, and it reads as India.
  let answer = () => fail(400, { error: 'INVALID_TIMEZONE' });
  serve({
    [`GET ${LEADS}lead-web/`]: detailOf(WEBSITE, { student_timezone: 'Asia/Calcutta' }),
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
    [`PUT ${LEADS}lead-web/student-timezone/`]: () => answer(),
  });
  await open('/leads/lead-web', ADMIN_TZ);
  assert.equal(fields()['Student timezone'], 'India (Asia/Calcutta)Change');
  await click(button('Change student timezone'));
  assert.equal(clean(document.getElementById('student-timezone').textContent), 'India');
  assert.deepEqual(await optionsOf('Student timezone'), TIMEZONE_CHOICES, 'never the old name as an option of its own');
  await click(button('Save', topDialog()));
  assert.equal(calls('PUT', `${LEADS}lead-web/student-timezone/`).length, 0, 'saved as it was: nothing sent, nothing logged');
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0);

  // A refusal with no words of its own: the dialog's.
  await click(button('Change student timezone'));
  await choose('Student timezone', 'US — Eastern');
  await click(button('Save', topDialog()));
  assert.match(clean(topDialog().textContent), /Choose a valid time zone\./);
  answer = () => fail(500, { error: 'SOMETHING_ELSE' });
  await click(button('Save', topDialog()));
  assert.match(clean(topDialog().textContent), /Could not change the student timezone\./);
});

test("Lead page: a saved zone this browser does not know is shown as it is, never as Not set, and an untouched Save keeps it", async () => {
  serve({
    [`GET ${LEADS}lead-web/`]: detailOf(WEBSITE, { student_timezone: 'America/Nowhere_New' }),
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
  });
  await open('/leads/lead-web', ADMIN_TZ);
  assert.equal(fields()['Student timezone'], 'America/Nowhere_NewChange');
  await click(button('Change student timezone'));
  assert.equal(clean(document.getElementById('student-timezone').textContent), 'America/Nowhere_New');
  await click(button('Save', topDialog()));
  assert.equal(calls('PUT', `${LEADS}lead-web/student-timezone/`).length, 0);
});

test("Lead page: the next booking says the student's own time under its Indian time", async () => {
  const next = { id: 'b-1', booking_type: 'DEMO', date: '2026-11-07', time: '07:30', starts_at: SAT_7_NOV_0730 };
  serve({
    [`GET ${LEADS}lead-web/`]: detailOf({ ...WEBSITE, next_booking: next }, { student_timezone: 'America/New_York' }),
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
  });
  await open('/leads/lead-web', ADMIN_TZ);
  assert.equal(fields()['Next booking'], 'Sat, 7 Nov · 7:30 AM ISTStudent Time: Fri, 6 Nov · 9:00 PM New York');
  await mounted.pop().unmount();
  // India's clock, or no zone: the Indian time alone.
  for (const zone of ['Asia/Kolkata', null]) {
    serve({
      [`GET ${LEADS}lead-web/`]: detailOf({ ...WEBSITE, next_booking: next }, { student_timezone: zone }),
      [`GET ${BDES}`]: { results: BDE_OPTIONS },
    });
    await open('/leads/lead-web', ADMIN_TZ);
    assert.equal(fields()['Next booking'], 'Sat, 7 Nov · 7:30 AM IST', String(zone));
    await mounted.pop().unmount();
  }
});

test("My Enquiries: a BDE corrects their enquiry's student timezone from its Overview; the next booking's Student Time follows", async () => {
  const next = { id: 'b-1', booking_type: 'DEMO', date: '2026-11-07', time: '07:30', starts_at: SAT_7_NOV_0730 };
  const own = detailOf({ ...OWNED, owner: undefined, next_booking: next }, { student_timezone: 'Asia/Dubai',
    bookings: [entryAt('b-1', 'DEMO', '2026-11-07', '07:30', SAT_7_NOV_0730, 'Asia/Dubai')] });
  serve({
    [`GET ${ENQUIRIES}lead-own/`]: own,
    [`GET /api/bde/booking-links/`]: LINKS,
    [`PUT ${ENQUIRIES}lead-own/student-timezone/`]: (entry) => ok({ ...own, student_timezone: entry.data.student_timezone,
      bookings: own.bookings.map((booking) => ({ ...booking, student_timezone: entry.data.student_timezone })), changed: true }),
  });
  await open('/enquiries/lead-own', BDE_TZ);
  assert.equal(fields()['Student timezone'], 'United Arab Emirates (Asia/Dubai)Change');
  assert.equal(fields()['Next booking'], 'Sat, 7 Nov · 7:30 AM ISTStudent Time: 6:00 AM UAE');

  await click(button('Change student timezone'));
  assert.doesNotMatch(clean(topDialog().textContent), /\blead/i, "the BDE workspace's own words");
  assert.equal(clean(document.getElementById('student-timezone').textContent), 'United Arab Emirates');
  await choose('Student timezone', 'US — Eastern');
  await click(button('Save', topDialog()));
  assert.deepEqual(calls('PUT', `${ENQUIRIES}lead-own/student-timezone/`).map((entry) => entry.data),
    [{ student_timezone: 'America/New_York' }]);
  assert.match(bodyText(), /Riya's timezone is now US — Eastern \(America\/New_York\)\./);
  assert.equal(fields()['Student timezone'], 'US — Eastern (America/New_York)Change');
  assert.equal(fields()['Next booking'], 'Sat, 7 Nov · 7:30 AM ISTStudent Time: Fri, 6 Nov · 9:00 PM New York');
  assert.ok(!globalThis.__leadsApi.calls.some((entry) => entry.url.startsWith('/api/leads/')), "the administrators' routes are never called");
});

test('Lead page and an enquiry\'s page: without accounts.change_student_timezone the zone is shown, never offered to change', async () => {
  serve({ [`GET ${LEADS}lead-web/`]: detailOf(WEBSITE, { student_timezone: 'Europe/Berlin' }), [`GET ${BDES}`]: { results: BDE_OPTIONS } });
  await open('/leads/lead-web', ADMIN);
  assert.equal(fields()['Student timezone'], 'Europe/Berlin');
  assert.ok(!button('Change student timezone') && !button('Change'));
  await mounted.pop().unmount();

  serve({
    [`GET ${ENQUIRIES}lead-given/`]: detailOf({ ...WEBSITE, id: 'lead-given', owner: undefined }, { student_timezone: null }),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/enquiries/lead-given', BDE);
  assert.equal(fields()['Student timezone'], 'Not set');
  assert.ok(!button('Change student timezone') && !button('Change'));
});

test("Leads: a lead added with the student's timezone sends it; a zone the API refuses is said at its field", async () => {
  const posted = [];
  serve({
    [`GET ${LEADS}`]: list([WEBSITE]),
    [`GET ${BDES}`]: { results: BDE_OPTIONS },
    [`POST ${LEADS}`]: (entry) => {
      posted.push(entry.data);
      return posted.length === 1
        ? fail(400, { error: 'VALIDATION_ERROR', message: 'Check the fields.', fields: { student_timezone: ['Choose a valid time zone.'] } })
        : ok(detailOf({ ...WEBSITE, id: 'lead-new', student_name: 'Arjun' }, { student_timezone: 'Asia/Dubai' }));
    },
  });
  await open('/leads', ADMIN);
  await click(button('Add Lead'));
  // Optional, Not set until chosen; named by its own label, as the form's other fields are.
  assert.equal(clean(document.querySelector('label[for="enquiry-student-timezone"]').textContent), 'Student timezone (optional)');
  assert.equal(clean(document.getElementById('enquiry-student-timezone').textContent), 'Not set');
  assert.deepEqual(await optionsOf('enquiry-student-timezone'), TIMEZONE_CHOICES);
  await typeInto(document.getElementById('enquiry-parent-name'), 'Meera Menon');
  await typeInto(document.getElementById('enquiry-phone-number'), '98765 43210');
  await typeInto(document.getElementById('enquiry-student-name'), 'Arjun');
  await choose('enquiry-grade', 'Class 6');
  await choose('enquiry-source', 'Phone call');
  await choose('enquiry-student-timezone', 'United Arab Emirates');
  await click(button('Add lead', topDialog()));
  assert.equal(posted[0].student_timezone, 'Asia/Dubai');
  const field = document.querySelector('label[for="enquiry-student-timezone"]').parentElement;
  assert.match(clean(field.textContent), /^Student timezone \(optional\)United Arab Emirates.*Choose a valid time zone\.$/);
  assert.equal(document.getElementById('enquiry-student-timezone').getAttribute('aria-invalid'), 'true');
  await click(button('Add lead', topDialog()));
  assert.equal(posted.length, 2);
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0);
});

test("BDE dashboard: Upcoming Bookings give each student's own time beside the Indian one; today's agenda stays as it was", async () => {
  const upcoming = { total: 2, rows: [
    { id: 'b-1', booking_type: 'DEMO', date: '2026-11-08', time: '07:30', starts_at: SUN_8_NOV_0730, student_timezone: 'Asia/Dubai', enquiry: RIYA },
    { id: 'b-2', booking_type: 'DIAGNOSTIC', date: '2026-11-09', time: '19:30', starts_at: MON_9_NOV_1930, student_timezone: 'Asia/Kolkata',
      enquiry: KAVYA },
  ] };
  serve({
    [`GET ${DASHBOARD}`]: { ...dashboardOf({ date: TODAY, total: 1, rows: [{ ...EVENING_DEMO, student_timezone: 'Asia/Dubai' }] }), upcoming },
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/dashboard', BDE);
  assert.deepEqual(headers(), ['When', 'Student Time', 'Type', 'Student', 'Parent', 'Open']);
  assert.deepEqual(rows().map((row) => clean(row.querySelectorAll('td')[1].textContent)), ['6:00 AM UAE', 'Same as IST']);
  assert.match(clean(agendaItems()[0].textContent), /^7:30 PM\s*Demo class · Riya\s*Upcoming\s*Class 8 · Parent: Asha Nair · Tutor: Jack Sabastian$/);
  await mounted.pop().unmount();

  await onAPhone(async () => {
    await open('/dashboard', BDE);
    const cards = [...document.querySelectorAll('[aria-label="Upcoming bookings"] > li')].map((card) => clean(card.textContent));
    assert.match(cards[0], /Sun, 8 Nov · 7:30 AM IST\s*Student Time: 6:00 AM UAE\s*Parent: Asha Nair/);
    assert.match(cards[1], /Mon, 9 Nov · 7:30 PM IST\s*Student Time: Same as IST\s*Parent: Meera Menon/);
  });
});

// A booking in full for the administrators (backend coordination.booking_detail): the student's zone on it and
// on its lead's brief; and the lead in full (GET /api/leads/<id>/), its bookings each with their own instant.
const NOAH_LEAD = detailOf({ id: 'lead-noah', parent_name: 'Asha Nair', phone: '+1 2125550100', student_name: 'Noah',
  grade: 'Class 8', source: 'BOOKING_PAGE', source_label: 'Booking page', status: 'DEMO_BOOKED', status_label: 'Demo booked',
  next_booking: { id: 'b-noah', booking_type: 'DEMO', date: '2026-11-07', time: '07:30', starts_at: SAT_7_NOV_0730 },
  added_at: null, owner: null, created_at: '2026-11-01T05:00:00+00:00' }, {
  country: 'United States', student_timezone: 'America/New_York', bookings: [
    entryAt('b-noah', 'DEMO', '2026-11-07', '07:30', SAT_7_NOV_0730, 'America/New_York'),
    entryAt('b-noah-diag', 'DIAGNOSTIC', '2026-11-02', '19:30', MON_2_NOV_1930, 'America/New_York', { status: 'COMPLETED',
      ended: true, activity_state: 'COMPLETED', started_at: '2026-11-02T14:02:00+00:00', tutor: { full_name: 'Tutor A' } }),
  ] });
const bookingOf = (lead, entry, extra = {}) => ({ id: entry.id, booking_type: entry.booking_type, status: entry.status,
  slot: { id: `s-${entry.id}`, booking_type: entry.booking_type, date: entry.date, time: entry.time, starts_at: entry.starts_at,
    ends_at: new Date(Date.parse(entry.starts_at) + 3_600_000).toISOString(), started: false, ended: false },
  student_name: lead.student_name, grade: lead.grade, parent_name: lead.parent_name, phone: lead.phone, tutor: null, bde: null,
  redemo_for_id: null, booked_at: entry.booked_at, activity_state: entry.activity_state, started_at: null, has_report: false,
  report_version: null, report_due: false, student_timezone: lead.student_timezone, timezone: 'Asia/Kolkata', seat: 1,
  lead: { id: lead.id, phone_dial_code: lead.phone_dial_code, phone_number: lead.phone_number, school_name: lead.school_name,
    syllabus: lead.syllabus, country: lead.country, source: lead.source, owner_bde: null, student_timezone: lead.student_timezone },
  referral_status: 'NO_REF', channel: 'PUBLIC', created_by: null, invited_from: null, redemo_request: null, redemo_from: null,
  tutor_assigned_at: null, tutor_assigned_by: null, tutor_meet_link: null, tutor_changeable: true, tutor_change_refusal: null,
  cancelled_at: null, cancelled_by: null, cancel_reason: '', rescheduled_from: null, rescheduled_to: null, report: null,
  actions: { cancel: false, no_show: false, reschedule: false }, ...extra });

test("Booking workspace: Student Time under the slot's Indian time, the zone read-only, the child's bookings each at their own", async () => {
  serve({ [`GET /api/bookings/demo/b-noah/`]: bookingOf(NOAH_LEAD, NOAH_LEAD.bookings[0]), [`GET ${LEADS}lead-noah/`]: NOAH_LEAD });
  await open('/bookings/demo/b-noah', ADMIN_TZ);
  assert.match(bodyText(), /Sat, 7 Nov · 7:30 AM IST\s*Student Time: Fri, 6 Nov · 9:00 PM New York/);
  // The Parent panel names the zone the lead keeps, to read: it is corrected on the lead's own page.
  assert.equal(fields()['Student timezone'], 'US — Eastern (America/New_York)');
  assert.ok(!button('Change student timezone') && !button('Change'), 'nothing to change here, whatever the caller holds');
  const entries = [...document.querySelectorAll('[aria-label="All bookings"] > li')].map((entry) => clean(entry.textContent));
  assert.match(entries[0], /Sat, 7 Nov · 7:30 AM IST\s*Student Time: Fri, 6 Nov · 9:00 PM New York/);
  assert.match(entries[1], /Mon, 2 Nov · 7:30 PM IST\s*Student Time: 9:00 AM New York/);
  assert.ok(button('Open the diagnostic test on Mon, 2 Nov · 7:30 PM IST'), 'the Open button keeps its name');
  await mounted.pop().unmount();

  // The Bookings tab: a column of its own.
  await open('/bookings/demo/b-noah?tab=bookings', ADMIN_TZ);
  assert.deepEqual(headers(), ['When (IST)', 'Student Time', 'Type', 'Status', 'Tutor', 'Booked on']);
  assert.deepEqual(rows().map((row) => clean(row.querySelectorAll('td')[1].textContent)),
    ['Fri, 6 Nov · 9:00 PM New York', '9:00 AM New York']);
  assert.equal(clean(rows()[0].querySelector('td').textContent), 'Sat, 7 Nov · 7:30 AM IST (the booking you are viewing)');
});

test("Booking workspace: a student on India's clock, or with no zone, adds no line and no column", async () => {
  const india = { ...NOAH_LEAD, id: 'lead-isha', student_name: 'Isha', student_timezone: 'Asia/Calcutta', next_booking: null,
    bookings: [entryAt('b-isha', 'DEMO', '2026-11-09', '19:30', MON_9_NOV_1930, 'Asia/Calcutta')] };
  serve({ [`GET /api/bookings/demo/b-isha/`]: bookingOf(india, india.bookings[0]), [`GET ${LEADS}lead-isha/`]: india });
  await open('/bookings/demo/b-isha', ADMIN_TZ);
  assert.match(bodyText(), /Mon, 9 Nov · 7:30 PM IST/);
  assert.ok(!bodyText().includes('Student Time:'), "India's clock: nothing to add");
  assert.equal(fields()['Student timezone'], 'India (Asia/Calcutta)');
  await mounted.pop().unmount();
  await open('/bookings/demo/b-isha?tab=bookings', ADMIN_TZ);
  assert.ok(!headers().includes('Student Time'));
  await mounted.pop().unmount();

  const unknown = { ...india, id: 'lead-omar', student_name: 'Omar', student_timezone: null,
    bookings: [entryAt('b-omar', 'DEMO', '2026-11-09', '19:30', MON_9_NOV_1930, null)] };
  serve({ [`GET /api/bookings/demo/b-omar/`]: bookingOf(unknown, unknown.bookings[0]), [`GET ${LEADS}lead-omar/`]: unknown });
  await open('/bookings/demo/b-omar', ADMIN_TZ);
  assert.ok(!bodyText().includes('Student Time:'));
  assert.equal(fields()['Student timezone'], 'Not set');
});

// The Admissions Dashboard's answer (backend bookings.admissions): today's bookings nested as the administrators' rows are.
const todayRow = (id, student_name, date, time, starts_at, student_timezone) => ({ id, booking_type: 'DEMO', status: 'BOOKED',
  slot: { id: `s-${id}`, booking_type: 'DEMO', date, time, starts_at, ends_at: new Date(Date.parse(starts_at) + 3_600_000).toISOString(),
    started: false, ended: false }, student_name, grade: 'Class 8', tutor: null, activity_state: 'UPCOMING', started_at: null,
  student_timezone });
const admissionsOf = (rows) => ({ timezone: 'Asia/Kolkata', range: { from: '2026-11-02', to: TODAY }, leads: { received: 2, new: 1 },
  pipeline: [['NEW', 'New', 1], ['BOOKED', 'Booked', 1], ['COMPLETED', 'Completed', 0], ['NOT_STARTED', 'Not started', 0],
    ['CANCELLED', 'Cancelled', 0]].map(([stage, label, count]) => ({ stage, label, count })),
  bookings: { DEMO: { total: rows.length, upcoming: rows.length }, DIAGNOSTIC: { total: 0, upcoming: 0 } },
  today_bookings: { date: TODAY, total: rows.length, rows },
  pending: { unassigned_leads: 0, needs_tutor: { DEMO: 0, DIAGNOSTIC: 0 }, report_due: { DEMO: 0, DIAGNOSTIC: 0 },
    redemo_scheduling: 0, awaiting_confirmation: { DEMO: 0, DIAGNOSTIC: 0 } },
  recent_leads: [], activity: [] });

test("Admissions Dashboard: today's bookings give each student's own time beside the Indian one, only while one reads differently", async () => {
  serve({ 'GET /api/admissions/dashboard/': admissionsOf([
    todayRow('b-zara', 'Zara', TODAY, '07:30', SUN_8_NOV_0730, 'Asia/Dubai'),
    todayRow('b-riya', 'Riya', TODAY, '19:30', '2026-11-08T14:00:00+00:00', null),
  ]) });
  await open('/admissions', ADMIN);
  assert.deepEqual(headers(), ['Time (IST)', 'Student Time', 'Type', 'Student', 'Tutor', 'Status', 'Open']);
  assert.deepEqual(rows().map((row) => clean(row.querySelectorAll('td')[1].textContent)), ['6:00 AM UAE', '—']);
  assert.deepEqual(rows().map((row) => clean(row.querySelector('td').textContent)), ['7:30 AM', '7:30 PM']);
  await mounted.pop().unmount();

  serve({ 'GET /api/admissions/dashboard/': admissionsOf([todayRow('b-riya', 'Riya', TODAY, '19:30', '2026-11-08T14:00:00+00:00', 'Asia/Kolkata')]) });
  await open('/admissions', ADMIN);
  assert.deepEqual(headers(), ['Time (IST)', 'Type', 'Student', 'Tutor', 'Status', 'Open']);
});

// ------------------------------------------------------------------ run
let failed = 0;
for (const { name, fn } of tests) {
  globalThis.__leadsApi = { calls: [], handler: () => fail(404, { message: 'No handler' }) };
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
console.log(`${tests.length - failed}/${tests.length} lead tests passed.`);
window.close();
process.exit(failed ? 1 : 0);
