// Stands in for src/lib/api.js in the Tutor Earnings tests (run.mjs). Every
// call is recorded as { method, url, params, data } and answered by the
// running test's handler, so each test decides what the API says.
const state = () => globalThis.__earningsApi;

function call(method, url, data, config) {
  const entry = { method: method.toUpperCase(), url, params: config?.params ? { ...config.params } : null, data: data ?? null };
  state().calls.push(entry);
  return state().handler(entry);
}

const api = { interceptors: { request: { use() {} }, response: { use() {} } }, defaults: { headers: { common: {} } } };
api.get = (url, config) => call('get', url, undefined, config);
api.delete = (url, config) => call('delete', url, config?.data, config);
for (const method of ['post', 'put', 'patch']) {
  api[method] = (url, data, config) => call(method, url, data, config);
}

export function ensureCsrfToken() {
  return Promise.resolve('stub');
}

export default api;
