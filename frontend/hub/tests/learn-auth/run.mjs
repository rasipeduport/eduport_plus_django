import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
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
      for (const dep of ['react', 'react-dom', 'react-router-dom']) build.onResolve({ filter: new RegExp('^' + dep + '(/.*)?$') }, (args) => ({ path: require.resolve(args.path, { paths: [path.join(here, '../..')] }) }));
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
const { mount, act } = harness;
const tests = [];
let cleanup;
const test = (name, fn) => tests.push({ name, fn });
const settle = async () => { for (let i = 0; i < 6; i++) await act(async () => new Promise(resolve => setTimeout(resolve, 0))); };
const click = async el => { assert.ok(el); await act(async () => el.click()); await settle(); };
const text = () => document.body.textContent;
const button = label => [...document.querySelectorAll('button')].find(el => el.textContent === label);
const type = async (input, value) => { assert.ok(input); await act(async () => {
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, value);
  input.dispatchEvent(new window.Event('input', { bubbles: true }));
}); };
const submit = async () => { await act(async () => document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }))); await settle(); };
const open = async (kind, props) => { cleanup = await mount(kind, props); await settle(); };
const serve = fn => { globalThis.__salesApi = { calls: [], handler: async entry => ({ data: await fn(entry) }) }; };
const fail = data => Promise.reject({ response: { data } });
const pending = { user: { role: 'STUDENT', must_change_password: true }, must_change_password: true };
const admin = { role: 'ADMIN', permissions: ['accounts.view_invitations', 'accounts.change_invitation'] };
// An account still carrying the retired accounts.create_invitation (as before migration accounts.0028): it opens nothing more.
const formerInviter = { ...admin, permissions: [...admin.permissions, 'accounts.create_invitation'] };
const invitation = { id: 'invite', student_id: 'student', student_name: 'Enrolled Student', student_code: 'EDP12345', username: 'edp12345', role: 'STUDENT', status: 'PENDING', credentials_available: true, created_at: '2026-11-10T00:00:00Z' };

test('Learn uses username/password inputs without Google', async () => {
  serve(() => ({})); await open('login');
  assert.ok(document.querySelector('input[autocomplete="username"]'));
  assert.equal(document.querySelector('input[name="password"]').type, 'password');
  assert.ok(!text().includes('Google')); assert.equal(document.querySelectorAll('script[src*="google"]').length, 0);
});
test('Learn submits credentials to the student endpoint and shows failures', async () => {
  serve(() => fail({ message: 'Invalid username or password.' })); await open('login');
  await type(document.querySelector('[name="username"]'), 'edp12345'); await type(document.querySelector('[name="password"]'), 'temporary-test-secret'); await submit();
  assert.deepEqual(globalThis.__salesApi.calls[0].data, { username: 'edp12345', password: 'temporary-test-secret' });
  assert.equal(globalThis.__salesApi.calls[0].url, '/api/auth/learn/login/');
  assert.ok(text().includes('Invalid username or password.'));
});
test('Password confirmation is required before sending', async () => {
  serve(() => pending); await open('change');
  const inputs = document.querySelectorAll('input'); await type(inputs[0], 'temporary'); await type(inputs[1], 'New-Personal-Password'); await type(inputs[2], 'different'); await submit();
  assert.ok(text().includes('do not match')); assert.equal(globalThis.__salesApi.calls.filter(e => e.method === 'POST').length, 0);
});
test('Backend password policy errors retain the change screen', async () => {
  serve(e => e.method === 'GET' ? pending : fail({ details: ['Choose a stronger password.'] })); await open('change');
  const inputs = document.querySelectorAll('input'); await type(inputs[0], 'temporary'); await type(inputs[1], 'weak'); await type(inputs[2], 'weak'); await submit();
  assert.ok(text().includes('Choose a stronger password.'));
  assert.equal(globalThis.__salesApi.calls.at(-1).url, '/api/auth/change-password/');
  assert.deepEqual(globalThis.__salesApi.calls.at(-1).data, { current_password: 'temporary', new_password: 'weak' });
});
test('Pending accounts are redirected before learning data is fetched', async () => {
  serve(() => pending); await open('guard');
  assert.ok(text().includes('Password change required')); assert.ok(!text().includes('Learning content'));
  assert.ok(!globalThis.__salesApi.calls.some(e => e.url === '/api/student/dashboard/'));
});
test('Invitation displays name EDP username lifecycle and date without fetching secrets', async () => {
  serve(() => ({})); await open('invitations', { data: [invitation], user: admin });
  for (const expected of ['Enrolled Student', 'EDP12345', 'edp12345', 'Pending', '2026']) assert.ok(text().includes(expected));
  assert.equal(globalThis.__salesApi.calls.length, 0);
});
test('Authorized explicit reveal does not save credentials in browser storage', async () => {
  serve(() => ({ username: 'edp12345', temporary_password: 'test-temporary-secret', student_code: 'EDP12345' })); await open('invitations', { data: [invitation], user: admin });
  await click(button('Reveal Password'));
  assert.equal(globalThis.__salesApi.calls[0].url, '/api/invitations/invite/credentials/');
  assert.ok([...document.querySelectorAll('input')].some(el => el.value === 'test-temporary-secret'));
  assert.equal(localStorage.length, 0); assert.equal(sessionStorage.length, 0);
  const dialog = document.querySelector('[role="dialog"]'); await click([...dialog.querySelectorAll('button')].find(el => el.textContent.includes('Close')));
  assert.ok(![...document.querySelectorAll('input')].some(el => el.value === 'test-temporary-secret'));
});
test('Activated accounts have no temporary credential action', async () => {
  serve(() => ({})); await open('invitations', { data: [{ ...invitation, status: 'ACCEPTED', credentials_available: false }], user: admin });
  assert.ok(text().includes('Activated')); assert.ok(!button('Reveal Password'));
});
test('Read-only staff cannot reveal credentials', async () => {
  serve(() => ({})); await open('invitations', { data: [invitation], user: { role: 'ADMIN', permissions: ['accounts.view_invitations'] } });
  assert.ok(!button('Reveal Password')); assert.ok(!button('Issue Learn credentials'));
});
test('A legacy row offers no manual credential issue: Learn accounts come from enrollment', async () => {
  serve(() => ({})); await open('invitations', { data: [{ ...invitation, legacy: true, credentials_available: false, username: null }], user: formerInviter });
  assert.ok(text().includes('Not issued')); assert.ok(!button('Issue Learn credentials'));
  assert.equal(globalThis.__salesApi.calls.length, 0);
});
// ---------------------------------------- Regenerate Temporary Password / Copy Login Details
const regenerable = { ...invitation, credentials_regenerable: true, last_password_reset_at: null };
const failWith = (status, data) => Promise.reject({ response: { status, data } });
const menuTrigger = () => document.querySelector('button[aria-haspopup="menu"]');
const menuItem = label => [...document.querySelectorAll('[role="menuitem"]')].find(el => el.textContent.trim() === label);
const openMenu = async () => {
  const trigger = menuTrigger(); assert.ok(trigger, 'a row menu');
  trigger.focus();
  await act(async () => trigger.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })));
  await settle();
};
const dialogText = () => [...document.querySelectorAll('[role="dialog"]')].map(el => el.textContent).join(' ');
const posts = () => globalThis.__salesApi.calls.filter(e => e.method === 'POST').map(e => e.url);
async function withClipboard(run, refuse = false) {
  const written = [];
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (value) => {
    if (refuse) throw new Error('blocked');
    written.push(value);
  } } });
  try { await run(written); } finally { delete navigator.clipboard; }
}

test('The list shows EDP ID, the last credential update, and a pending row offers Reveal Password and its menu', async () => {
  serve(() => ({})); await open('invitations', { data: [{ ...regenerable, last_password_reset_at: '2026-11-12T09:30:00Z' }], user: admin });
  const headers = [...document.querySelectorAll('th')].map(th => th.textContent.trim());
  assert.deepEqual(headers, ['Student', 'EDP ID', 'Username', 'Status', 'Invited At', 'Last Credential Update', 'Actions']);
  assert.ok(text().includes('Nov 12, 2026'));
  assert.ok(button('Reveal Password'));
  await openMenu();
  assert.deepEqual([...document.querySelectorAll('[role="menuitem"]')].map(el => el.textContent.trim()),
    ['Regenerate Temporary Password', 'Copy Login Details']);
  for (const unsupported of ['Resend Invitation', 'Reset Password', 'Send Reset Link']) assert.ok(!text().includes(unsupported), unsupported);
  assert.equal(globalThis.__salesApi.calls.length, 0, 'nothing is read until an action is chosen');
});
test('Regenerate asks first; Cancel sends nothing', async () => {
  serve(() => ({})); await open('invitations', { data: [regenerable], user: admin });
  await openMenu(); await click(menuItem('Regenerate Temporary Password'));
  for (const expected of ['Regenerate Temporary Password', 'A new temporary password will be generated for Enrolled Student (EDP12345).',
    'The old temporary password will no longer work.', 'Share the new credentials securely with the student/parent.',
    'The student must set a new password on first login.']) assert.ok(dialogText().includes(expected), expected);
  await click(button('Cancel'));
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0);
  assert.equal(globalThis.__salesApi.calls.length, 0);
});
test('Generate New Password sends the listed last reset, then shows the new password and reads the list again', async () => {
  let changed = 0;
  serve(e => e.url.endsWith('/regenerate/') ? { status: 'regenerated', last_password_reset_at: '2026-11-17T08:00:00Z' }
    : { username: 'edp12345', temporary_password: 'regenerated-secret', student_code: 'EDP12345' });
  await open('invitations', { data: [regenerable], user: admin, onChanged: () => { changed++; } });
  await openMenu(); await click(menuItem('Regenerate Temporary Password')); await click(button('Generate New Password'));
  assert.deepEqual(posts(), ['/api/invitations/invite/credentials/regenerate/', '/api/invitations/invite/credentials/']);
  assert.deepEqual(globalThis.__salesApi.calls[0].data, { last_password_reset_at: null });
  assert.ok(dialogText().includes('New temporary password')); assert.ok(dialogText().includes('The old temporary password no longer works.'));
  assert.ok([...document.querySelectorAll('input')].some(el => el.value === 'regenerated-secret'));
  assert.equal(changed, 1);
  assert.equal(localStorage.length, 0); assert.equal(sessionStorage.length, 0);
});
test('A regeneration refused as stale says so, reveals nothing and reads the list again', async () => {
  let changed = 0;
  serve(e => e.url.endsWith('/regenerate/')
    ? failWith(409, { error: 'CREDENTIALS_CHANGED', message: 'The temporary password was replaced moments ago. Reveal the current one instead of generating another.' })
    : {});
  await open('invitations', { data: [{ ...regenerable, last_password_reset_at: '2026-11-12T09:30:00Z' }], user: admin, onChanged: () => { changed++; } });
  await openMenu(); await click(menuItem('Regenerate Temporary Password')); await click(button('Generate New Password'));
  assert.deepEqual(globalThis.__salesApi.calls[0].data, { last_password_reset_at: '2026-11-12T09:30:00Z' });
  assert.deepEqual(posts(), ['/api/invitations/invite/credentials/regenerate/']);
  assert.ok(dialogText().includes('replaced moments ago'));
  assert.ok(![...document.querySelectorAll('input')].some(el => el.value));
  assert.equal(changed, 1);
});
test('Copy Login Details reveals through the audited endpoint and copies; a refused clipboard shows them to copy by hand', async () => {
  const secret = { username: 'edp12345', temporary_password: 'copied-secret', student_code: 'EDP12345' };
  await withClipboard(async (written) => {
    serve(() => secret); await open('invitations', { data: [regenerable], user: admin });
    await openMenu(); await click(menuItem('Copy Login Details'));
    assert.deepEqual(posts(), ['/api/invitations/invite/credentials/']);
    assert.deepEqual(globalThis.__salesApi.calls[0].data, { purpose: 'copy' }, 'logged as a copy');
    assert.equal(written.length, 1);
    assert.match(written[0], /Username: edp12345\nTemporary password: copied-secret\n/);
    assert.ok(text().includes('Login details copied.'));
    assert.equal(document.querySelectorAll('[role="dialog"]').length, 0);
  });
  await cleanup(); cleanup = null;
  await withClipboard(async (written) => {
    serve(() => secret); await open('invitations', { data: [regenerable], user: admin });
    await openMenu(); await click(menuItem('Copy Login Details'));
    assert.equal(written.length, 0);
    assert.ok(dialogText().includes('Clipboard unavailable. Copy the credentials manually.'));
    assert.ok([...document.querySelectorAll('input')].some(el => el.value === 'copied-secret'));
  }, true);
});
test('An activated row the API offers no reset for has no password action and keeps its last update date', async () => {
  serve(() => ({}));
  await open('invitations', { data: [{ ...regenerable, status: 'ACCEPTED', credentials_available: false, credentials_regenerable: false,
    last_password_reset_at: '2026-10-10T05:50:00Z' }], user: admin });
  assert.ok(text().includes('Activated')); assert.ok(text().includes('Oct 10, 2026'));
  assert.ok(!menuTrigger()); assert.ok(!button('Reveal Password'));
  for (const unsupported of ['Reset Password', 'Send Reset Link']) assert.ok(!text().includes(unsupported), unsupported);
});
test('A pending account whose stored credentials are unreadable can still be regenerated, but not revealed', async () => {
  serve(() => ({})); await open('invitations', { data: [{ ...regenerable, credentials_available: false }], user: admin });
  assert.ok(!button('Reveal Password'));
  await openMenu();
  assert.deepEqual([...document.querySelectorAll('[role="menuitem"]')].map(el => el.textContent.trim()), ['Regenerate Temporary Password']);
});
test('Without permission to reveal there is no menu and nothing to regenerate', async () => {
  serve(() => ({})); await open('invitations', { data: [regenerable], user: { role: 'ADMIN', permissions: ['accounts.view_invitations'] } });
  assert.ok(!menuTrigger()); assert.ok(!button('Reveal Password'));
  assert.equal(globalThis.__salesApi.calls.length, 0);
});
// ---------------------------------------------------------------- Reset Password (activated)
const activated = { ...invitation, status: 'ACCEPTED', credentials_available: false, credentials_regenerable: false,
  password_resettable: true, last_password_reset_at: null };

test('An activated row offers Reset Password, no menu and no email reset link', async () => {
  serve(() => ({})); await open('invitations', { data: [activated], user: admin });
  assert.ok(text().includes('Activated')); assert.ok(button('Reset Password'));
  assert.ok(!menuTrigger()); assert.ok(!button('Reveal Password'));
  for (const unsupported of ['Send Reset Link', 'Resend Invitation', 'Must change password']) assert.ok(!text().includes(unsupported), unsupported);
  assert.equal(globalThis.__salesApi.calls.length, 0);
});
test('Reset Password asks first and explains the consequences; Cancel sends nothing', async () => {
  serve(() => ({})); await open('invitations', { data: [activated], user: admin });
  await click(button('Reset Password'));
  for (const expected of ['A temporary password will replace the Learn password of Enrolled Student (EDP12345).',
    "The student's current password stops working immediately and is never shown.", 'They are signed out of Learn on every device.',
    'The account stays Activated; they must set a new password at their next login.',
    'Share the new temporary password securely with the student/parent.']) assert.ok(dialogText().includes(expected), expected);
  await click(button('Cancel'));
  assert.equal(document.querySelectorAll('[role="dialog"]').length, 0);
  assert.equal(globalThis.__salesApi.calls.length, 0);
});
test('Confirming a reset sends the listed last update, then shows the new temporary password and reads the list again', async () => {
  let changed = 0;
  serve(e => e.url.endsWith('/reset/') ? { status: 'reset', last_password_reset_at: '2026-11-17T08:00:00Z' }
    : { username: 'edp12345', temporary_password: 'reset-secret', student_code: 'EDP12345' });
  await open('invitations', { data: [{ ...activated, last_password_reset_at: '2026-11-01T08:00:00Z' }], user: admin, onChanged: () => { changed++; } });
  await click(button('Reset Password'));
  const dialog = document.querySelector('[role="dialog"]');
  await click([...dialog.querySelectorAll('button')].find(el => el.textContent === 'Reset Password'));
  assert.deepEqual(posts(), ['/api/invitations/invite/credentials/reset/', '/api/invitations/invite/credentials/']);
  assert.deepEqual(globalThis.__salesApi.calls[0].data, { last_password_reset_at: '2026-11-01T08:00:00Z' });
  assert.ok(dialogText().includes('New temporary password'));
  assert.ok(dialogText().includes('the student has been signed out'));
  assert.ok([...document.querySelectorAll('input')].some(el => el.value === 'reset-secret'));
  assert.equal(changed, 1);
  assert.equal(localStorage.length, 0); assert.equal(sessionStorage.length, 0);
});
test('A stale reset says so, reveals nothing and reads the list again', async () => {
  let changed = 0;
  serve(e => e.url.endsWith('/reset/')
    ? failWith(409, { error: 'CREDENTIALS_CHANGED', message: 'This password was reset moments ago. Reveal the temporary password instead of resetting it again.' })
    : {});
  await open('invitations', { data: [activated], user: admin, onChanged: () => { changed++; } });
  await click(button('Reset Password'));
  const dialog = document.querySelector('[role="dialog"]');
  await click([...dialog.querySelectorAll('button')].find(el => el.textContent === 'Reset Password'));
  assert.deepEqual(posts(), ['/api/invitations/invite/credentials/reset/']);
  assert.ok(dialogText().includes('reset moments ago'));
  assert.ok(![...document.querySelectorAll('input')].some(el => el.value));
  assert.equal(changed, 1);
});
test('While a reset password waits for the student, the row says so and its menu reveals or copies it', async () => {
  serve(() => ({ username: 'edp12345', temporary_password: 'waiting-secret', student_code: 'EDP12345' }));
  await open('invitations', { data: [{ ...activated, credentials_available: true, last_password_reset_at: '2026-11-17T08:00:00Z' }], user: admin });
  assert.ok(text().includes('Activated')); assert.ok(text().includes('Must change password'));
  assert.ok(button('Reset Password')); assert.ok(!button('Reveal Password'));
  await openMenu();
  assert.deepEqual([...document.querySelectorAll('[role="menuitem"]')].map(el => el.textContent.trim()), ['Reveal Password', 'Copy Login Details']);
  await click(menuItem('Reveal Password'));
  assert.deepEqual(posts(), ['/api/invitations/invite/credentials/']);
  assert.ok(dialogText().includes('Temporary Learn credentials'));
  assert.ok([...document.querySelectorAll('input')].some(el => el.value === 'waiting-secret'));
});
test('Without permission to reveal there is no Reset Password', async () => {
  serve(() => ({})); await open('invitations', { data: [activated], user: { role: 'ADMIN', permissions: ['accounts.view_invitations'] } });
  assert.ok(!button('Reset Password')); assert.ok(!menuTrigger());
  assert.equal(globalThis.__salesApi.calls.length, 0);
});
test('The Activity Log names credential events and never shows a password', async () => {
  const { actionLabel, describeActivity } = harness;
  assert.equal(actionLabel('invitation.password_reset'), 'Learn password reset');
  assert.equal(actionLabel('invitation.credentials_copied'), 'Login details copied');
  assert.equal(describeActivity({ action: 'invitation.password_reset', context: { unlocked: false } }), 'Reset the Learn password to a temporary one');
  assert.equal(describeActivity({ action: 'invitation.password_reset', context: { unlocked: true } }),
    'Reset the Learn password to a temporary one and cleared a sign-in lockout');
  assert.equal(actionLabel('invitation.credentials_regenerated'), 'Temporary password regenerated');
  assert.equal(actionLabel('invitation.credentials_revealed'), 'Temporary password revealed');
  assert.equal(actionLabel('invitation.credentials_created'), 'Learn credentials issued');
  assert.equal(describeActivity({ action: 'invitation.credentials_regenerated', context: { unlocked: false } }), 'Regenerated the temporary Learn password');
  assert.equal(describeActivity({ action: 'invitation.credentials_regenerated', context: { unlocked: true } }),
    'Regenerated the temporary Learn password and cleared a sign-in lockout');
});
test('New Invitation stays where it was but only says invitations come from enrollment', async () => {
  serve((entry) => (entry.method === 'GET' && entry.url === '/api/invitations/' ? [invitation] : {}));
  await open('invitations-page', { user: formerInviter });
  assert.ok(text().includes('Enrolled Student'), 'the list still loads');
  await click(button('New Invitation'));
  assert.ok(text().includes('Student invitations are now created automatically during enrollment.'));
  for (const gone of ['Student ID', 'Verify', 'Create Invitation']) assert.ok(!text().includes(gone), gone);
  assert.equal(document.querySelectorAll('[role="dialog"] input').length, 0, 'no form');
  assert.deepEqual(globalThis.__salesApi.calls.map((e) => `${e.method} ${e.url}`), ['GET /api/invitations/'], 'nothing is looked up or created');
});
test('The Students page has no New Student action', async () => {
  serve(() => ({}));
  await open('students', { students: [], user: { role: 'ADMIN', permissions: ['accounts.view_all_students', 'accounts.view_full_student_record', 'accounts.change_student_details', 'accounts.create_invitation'] }, onChanged: () => {} });
  assert.ok(!text().includes('New Student')); assert.ok(![...document.querySelectorAll('a[href]')].some((a) => a.getAttribute('href').includes('/invitations')));
});
let failures = 0;
for (const { name, fn } of tests) {
  try { await fn(); console.log(`PASS ${name}`); }
  catch (err) { failures++; console.log(`FAIL ${name}: ${err.stack}`); }
  finally { if (cleanup) await cleanup(); cleanup = null; await settle(); }
}
console.error = quiet;
console.log(`${tests.length - failures}/${tests.length} Learn and invitation frontend tests passed.`);
window.close(); process.exit(failures ? 1 : 0);
