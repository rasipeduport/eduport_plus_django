// The password rule, as the API applies it (AUTH_PASSWORD_VALIDATORS in
// backend/config/settings.py): at least 8 characters, nothing else. The API
// stays the authority; checking here only saves a round trip.

export const PASSWORD_MIN_LENGTH = 8;

export const PASSWORD_RULE = `At least ${PASSWORD_MIN_LENGTH} characters.`;

/** Why `password` breaks the rule, or null when it is fine. */
export function passwordPolicyError(password) {
  // Characters as the API counts them: an emoji is one, not two UTF-16 units.
  return [...password].length < PASSWORD_MIN_LENGTH ? `Use at least ${PASSWORD_MIN_LENGTH} characters.` : null;
}
