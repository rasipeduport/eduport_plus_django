// Stands in for src/lib/api.js in the access-test bundle. Answers GETs from
// fixtures.json -- the real API's responses for the scenario's caller, keyed
// by path plus the student_id / subject query (other query parameters do not
// change what a caller may see) -- and refuses everything else with a 403.
// Every call is recorded as "METHOD path".
const state = () => globalThis.__hubAccess;
const KEPT_QUERY = ['student_id', 'subject'];

function fixtureKey(url, params) {
  const parsed = new URL(url, 'http://hub.test');
  for (const [name, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== '') parsed.searchParams.set(name, value);
  }
  const kept = KEPT_QUERY.filter((name) => parsed.searchParams.has(name)).map((name) => `${name}=${parsed.searchParams.get(name)}`);
  return parsed.pathname + (kept.length ? `?${kept.join('&')}` : '');
}

function refuse(status, body) {
  const error = new Error(`stub answered ${status}`);
  error.response = { status, data: body };
  return Promise.reject(error);
}

function answer(method, url, config) {
  const { answers } = state();
  const key = fixtureKey(url, config?.params);
  state().calls.push(`${method.toUpperCase()} ${key}`);
  if (method !== 'get') return refuse(403, { error: 'FORBIDDEN', message: 'Writes are not exercised by the access tests.' });
  if (method === 'get' && key === '/api/auth/me/' && state().me) return Promise.resolve({ status: 200, data: state().me });
  const fixture = answers[key];
  if (!fixture) return refuse(404, { error: 'NOT_FOUND', message: `No fixture for ${key}` });
  if (fixture.status >= 400) return refuse(fixture.status, fixture.body);
  return Promise.resolve({ status: fixture.status, data: fixture.body });
}

const api = { interceptors: { request: { use() {} }, response: { use() {} } }, defaults: { headers: { common: {} } } };
api.get = (url, config) => answer('get', url, config);
for (const method of ['post', 'put', 'patch', 'delete']) {
  api[method] = (url, _data, config) => answer(method, url, config);
}

export function ensureCsrfToken() {
  return Promise.resolve('stub');
}

export default api;
