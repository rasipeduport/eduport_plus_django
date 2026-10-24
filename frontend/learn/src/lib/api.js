import axios from 'axios';

const SAFE_METHODS = new Set(['get', 'head', 'options']);
const CSRF_HEADER = 'X-CSRFToken';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  withCredentials: true,
  // The CSRF token is NOT read from document.cookie. The API is another origin
  // (another port locally, possibly another host in production), whose cookie
  // this page may be unable to read, and another app on the same parent domain
  // could set a cookie with the same name. The API returns the token in the
  // body of /api/auth/csrf/, /api/auth/me/ and both login endpoints instead;
  // it is kept in memory below. axios' own cookie-based XSRF header is off.
  xsrfCookieName: null,
  withXSRFToken: false,
});

let csrfToken = null;
let csrfFetch = null;

function rememberCsrfToken(data) {
  if (data && typeof data.csrf_token === 'string' && data.csrf_token) {
    csrfToken = data.csrf_token;
  }
}

/**
 * The current CSRF token, fetched from GET /api/auth/csrf/ when none is known
 * yet (a fresh login page) or when `refresh` is set (the last one was refused).
 */
export function ensureCsrfToken(refresh = false) {
  if (csrfToken && !refresh) return Promise.resolve(csrfToken);
  if (!csrfFetch) {
    csrfFetch = api
      .get('/api/auth/csrf/')
      .then(() => csrfToken)
      .finally(() => {
        csrfFetch = null;
      });
  }
  return csrfFetch;
}

api.interceptors.request.use(async (config) => {
  if (!SAFE_METHODS.has((config.method || 'get').toLowerCase())) {
    const token = await ensureCsrfToken();
    if (token) config.headers.set(CSRF_HEADER, token);
  }
  return config;
});

api.interceptors.response.use(
  (response) => {
    rememberCsrfToken(response.data);
    return response;
  },
  async (error) => {
    const { response, config } = error;

    // A stale token (e.g. a login in another tab rotated the CSRF secret):
    // fetch a fresh one and retry the request exactly once.
    const csrfFailed =
      response?.status === 403 &&
      (response.data?.error === 'CSRF_FAILED' || String(response.data?.detail || '').startsWith('CSRF Failed'));
    if (csrfFailed && config && !config._csrfRetried) {
      config._csrfRetried = true;
      await ensureCsrfToken(true);
      return api(config);
    }

    // Not logged in (or the session expired): back to the login page.
    if (response && response.status === 401 && !window.location.pathname.endsWith('/login')) {
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;
