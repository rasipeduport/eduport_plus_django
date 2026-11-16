// Messages for the staff sign-in and forced password-change pages, from the
// answers of POST /api/auth/login/ and POST /api/auth/change-password/.

/**
 * The API gives every failed password sign-in the same answer -- wrong
 * password, unknown username, locked or inactive account -- so the page never
 * says which. The lockout hint goes with every failure for the same reason.
 */
export function passwordLoginError(err) {
  const response = err?.response;
  if (!response) return 'Could not reach the server. Check your connection and try again.';
  if (response.status === 429) return 'Too many sign-in attempts. Wait a minute, then try again.';
  if (response.data?.error === 'INVALID_CREDENTIALS') {
    return `${response.data.message}\nRepeated failed attempts lock an account for a while.`;
  }
  return response.data?.message || 'Sign-in failed. Please try again.';
}

// The form field each refusal from POST /api/auth/change-password/ belongs to.
const CHANGE_FIELD_FOR_CODE = {
  INVALID_CURRENT_PASSWORD: 'current',
  PASSWORD_REUSED: 'next',
  PASSWORD_POLICY: 'next',
};

/** `{ field, message, details, sessionEnded }` for a refused password change. */
export function passwordChangeFailure(err) {
  const response = err?.response;
  const data = response?.data ?? {};
  if (!response) return { message: 'Could not reach the server. Check your connection and try again.' };
  // The endpoint refuses only an anonymous request with 403: the session ended.
  if (response.status === 403 && data.error !== 'CSRF_FAILED') {
    return { sessionEnded: true, message: 'Your session has ended. Sign in again to change your password.' };
  }
  if (response.status === 429) return { message: 'Too many attempts. Wait a while, then try again.' };
  return {
    field: CHANGE_FIELD_FOR_CODE[data.error] ?? null,
    message: data.message || 'Could not change your password. Please try again.',
    details: Array.isArray(data.details) ? data.details : [],
  };
}
