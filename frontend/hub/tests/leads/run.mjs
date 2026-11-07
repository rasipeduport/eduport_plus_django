// Lead management tests: the real Leads pages (src/pages/LeadsPage.jsx,
// LeadPage.jsx) and a BDE's My Leads (EnquiriesPage.jsx, EnquiryPage.jsx) in
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

/** The options the Radix Select labelled `label` offers, closed again afterwards. */
async function optionsOf(label) {
  const trigger = document.querySelector(`[aria-label="${label}"]`);
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
  assert.deepEqual(headers(),
    ['Received', 'Parent', 'Phone', 'Student', 'Class', 'Source', 'Status', 'Next booking', 'Owner', 'Assign', 'Open']);
  const [web, own] = rows();
  assert.match(clean(web.textContent), /6 Nov 2026.*Meera Menon.*\+91 9876543210.*Kavya.*Class 7.*Website.*New.*—.*Unassigned/);
  assert.match(clean(own.textContent), /Asha Nair.*Riya.*Demo link.*Demo booked.*Sun, 8 Nov.*7:30 PM IST.*Anil Kumar/);
  assert.ok(button('Assign', web) && !button('Reassign', web));
  assert.ok(button('Reassign', own) && !button('Assign', own));
  assert.equal(web.querySelector('a').getAttribute('href'), '/leads/lead-web');
  assert.ok(button('Add lead'));
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
  await click(button('Add lead'));
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
    source: 'PHONE_CALL', school_name: '', syllabus: '', country: '', parent_email: 'meera@example.com',
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
  await click(button('Add lead'));
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
  assert.ok(!button('Add lead') && !button('Assign') && !button('Reassign'));
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
  assert.equal(link('Open').getAttribute('href'), '/bookings?type=DIAGNOSTIC&when=all&booking=b-9');

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

test('My Leads: a BDE sees their own leads with the status their bookings give, and their booking links; no owner, no assigning', async () => {
  serve({
    [`GET /api/bde/enquiries/`]: list([{ ...OWNED, owner: undefined, created_at: undefined },
      { ...WEBSITE, id: 'lead-given', owner: undefined, added_at: '2026-11-06T06:00:00+00:00' }]),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/enquiries', BDE);
  assert.match(bodyText(), /My Leads.*the leads assigned to you/);
  assert.deepEqual(headers(), ['Parent', 'Phone', 'Student', 'Class', 'Source', 'Status', 'Next booking', 'Open']);
  const [own, given] = rows();
  assert.match(clean(own.textContent), /Riya.*Demo link.*Demo booked/);
  assert.match(clean(given.textContent), /Kavya.*Website.*New/);
  assert.equal(given.querySelector('a').getAttribute('href'), '/enquiries/lead-given');
  assert.ok(button('Copy Demo Link') && button('Copy Diagnostic Link'), 'the booking links are shared from My Leads');
  assert.ok(button('Add lead'));
  assert.ok(!button('Assign') && !button('Reassign'));
  assert.ok(!globalThis.__leadsApi.calls.some((entry) => entry.url.startsWith('/api/leads/')), "the administrators' API is never called");
  assert.ok((await optionsOf('Filter by status')).includes('Diagnostic completed'));
  // The dashboard's Upcoming Bookings tile lands here filtered to bookings of either type to come.
  await mounted.pop().unmount();
  await open('/enquiries?status=BOOKED', BDE);
  assert.equal(calls('GET', '/api/bde/enquiries/').at(-1).params.status, 'BOOKED');
  assert.equal(clean(document.querySelector('[aria-label="Filter by status"]').textContent), 'Booked (any type)');
});

test("My Leads: a lead's page calls or messages the parent, and sends the BDE's booking link to the parent's WhatsApp", async () => {
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

test('My Leads: a lead reassigned to another BDE is answered as one that does not exist', async () => {
  serve({
    [`GET /api/bde/enquiries/lead-moved/`]: () => fail(404, { error: 'NOT_FOUND', message: 'No such enquiry.' }),
    [`GET /api/bde/booking-links/`]: LINKS,
  });
  await open('/enquiries/lead-moved', BDE);
  assert.match(bodyText(), /Lead not found.*assigned to another BDE, or it is not one of your leads\./);
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

test('Access: Leads is for holders of accounts.view_all_leads; My Leads for BDEs only', () => {
  assert.equal(canOpenPage(ADMIN, '/leads'), true);
  assert.equal(canOpenPage(VIEWER, '/leads'), true);
  assert.equal(canOpenPage(BDE, '/leads'), false);
  assert.equal(canOpenPage({ role: 'TUTOR', permissions: ['accounts.view_assigned_bookings'] }, '/leads'), false);
  assert.equal(canOpenPage(BDE, '/enquiries'), true);
  // A superuser holds a BDE's permissions too (D1) but owns no leads.
  assert.equal(canOpenPage({ role: 'ADMIN', permissions: [...ADMIN.permissions, 'accounts.view_own_enquiries'] }, '/enquiries'), false);
  assert.equal(homePage(VIEWER), '/leads');
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
