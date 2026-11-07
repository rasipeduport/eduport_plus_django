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
  // Shared for nobody in particular, a copy here ends no enquiry's reminder.
  await click(button('Copy Demo Link'));
  assert.ok(!globalThis.__leadsApi.calls.some((entry) => entry.method === 'POST'), 'nothing is told');
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
  const SHARED = '/api/bde/enquiries/lead-given/booking-link-shared/';
  serve({
    [`GET /api/bde/enquiries/lead-given/`]: detailOf({ ...WEBSITE, id: 'lead-given', owner: undefined }, { parent_email: 'meera@example.com' }),
    [`GET /api/bde/booking-links/`]: LINKS,
    [`POST ${SHARED}`]: { resolved: true },
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
  // Sending a link to this parent -- on WhatsApp or copied -- tells the API, which ends the reminder to call the new enquiry.
  await click(send);
  await click(button('Copy Diagnostic Link'));
  assert.deepEqual(calls('POST', SHARED).map((entry) => entry.data), [{ booking_type: 'DEMO' }, { booking_type: 'DIAGNOSTIC' }]);
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
