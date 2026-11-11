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
const admin = { role: 'ADMIN', permissions: ['accounts.view_invitations', 'accounts.change_invitation', 'accounts.create_invitation'] };
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
  await click(button('Reveal temporary password'));
  assert.equal(globalThis.__salesApi.calls[0].url, '/api/invitations/invite/credentials/');
  assert.ok([...document.querySelectorAll('input')].some(el => el.value === 'test-temporary-secret'));
  assert.equal(localStorage.length, 0); assert.equal(sessionStorage.length, 0);
  const dialog = document.querySelector('[role="dialog"]'); await click([...dialog.querySelectorAll('button')].find(el => el.textContent.includes('Close')));
  assert.ok(![...document.querySelectorAll('input')].some(el => el.value === 'test-temporary-secret'));
});
test('Activated accounts have no temporary credential action', async () => {
  serve(() => ({})); await open('invitations', { data: [{ ...invitation, status: 'ACCEPTED', credentials_available: false }], user: admin });
  assert.ok(text().includes('Activated')); assert.ok(!button('Reveal temporary password'));
});
test('Read-only staff cannot reveal credentials', async () => {
  serve(() => ({})); await open('invitations', { data: [invitation], user: { role: 'ADMIN', permissions: ['accounts.view_invitations'] } });
  assert.ok(!button('Reveal temporary password')); assert.ok(!button('Issue Learn credentials'));
});
test('Admin can explicitly transition an enrolled legacy student', async () => {
  let changed = false; serve(() => ({})); await open('invitations', { data: [{ ...invitation, legacy: true, credentials_available: false, username: null }], user: admin, onChanged: () => { changed = true; } });
  await click(button('Issue Learn credentials')); assert.equal(globalThis.__salesApi.calls[0].url, '/api/invitations/students/student/issue/'); assert.ok(changed);
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
