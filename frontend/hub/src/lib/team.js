// Team Management: the /api/team/ contract (backend accounts/team.py) as the
// Hub uses it. The backend enforces every rule; the checks here only decide
// which controls to offer, so a refusal from the API is always shown as-is.

import { PERMISSIONS, can, canAny } from './access';
import { passwordPolicyError } from './password-policy';
import { EMAIL_RE } from './utils';

export const TEAM_URL = '/api/team/';
export const TEAM_PERMISSIONS_URL = '/api/team/permissions/';
export const VIEW_TEAM = PERMISSIONS.viewTeam;

// The staff roles Team manages (backend accounts.models HUB_ROLES). BDE and
// Sales TL sign in to the Hub but hold no permission yet, so they see the
// No Access page until their modules exist.
export const TEAM_ROLES = [
  { value: 'ADMIN', label: 'Admin' },
  { value: 'MENTOR', label: 'Mentor' },
  { value: 'TUTOR', label: 'Tutor' },
  { value: 'BDE', label: 'BDE' },
  { value: 'SALES_TL', label: 'Sales TL' },
];

const STAFF_ROLES = new Set(TEAM_ROLES.map((role) => role.value));

// Handing a departing mentor's or tutor's ACTIVE students to a colleague of
// the same role (POST /api/users/<id>/reassign/, admin-only). The API refuses
// to deactivate them, or change their role, until this is done. `list` is the
// active staff of that role; `field` is the reassign body's key.
export const HANDOVER_ROLES = {
  MENTOR: { list: '/api/mentors/', key: 'mentors', field: 'new_mentor', noun: 'mentor' },
  TUTOR: { list: '/api/tutors/', key: 'tutors', field: 'new_tutor', noun: 'tutor' },
};
export const reassignUrl = (id) => `/api/users/${id}/reassign/`;

export const memberUrl = (id, action = '') => `${TEAM_URL}${id}/${action}`;

export function roleLabel(role) {
  return TEAM_ROLES.find((option) => option.value === role)?.label ?? role;
}

/** Holders of accounts.manage_team manage the team (backend: is_team_manager). */
export function canManageTeam(user) {
  return can(user, PERMISSIONS.manageTeam);
}

/** Managers, and staff granted accounts.view_team, may read the directory. */
export function canViewTeam(user) {
  return canAny(user, [PERMISSIONS.manageTeam, PERMISSIONS.viewTeam]);
}

/**
 * Why `viewer` may not change `member`, or null when they may -- the same
 * order of checks as the backend's check_may_change.
 */
export function changeRestriction(viewer, member) {
  if (!viewer || !member) return 'Not available.';
  if (member.id === viewer.id) return 'You cannot change your own account here.';
  if (!viewer.is_superuser && (member.role === 'ADMIN' || member.is_superuser)) {
    return 'Only a superuser can change an administrator account.';
  }
  return null;
}

/** Roles the viewer may give someone: only a superuser grants Admin. */
export function assignableRoles(viewer) {
  return TEAM_ROLES.filter((role) => role.value !== 'ADMIN' || viewer?.is_superuser);
}

export function isActiveMember(member) {
  return Boolean(member?.is_active && !member?.deactivated_at);
}

export function isLocked(member) {
  return Boolean(member?.locked_until && new Date(member.locked_until) > new Date());
}

// The fields PATCH /api/team/<id>/ accepts. Staff sign in by username, so a
// changed email leaves sign-in alone; the API keeps it unique and clear of
// student invitations.
export const EDITABLE_FIELDS = ['username', 'full_name', 'email', 'mobile_number', 'role'];

/** The details form's starting values for `member`. */
export function memberFormValues(member) {
  return {
    username: member?.username ?? '',
    full_name: member?.full_name ?? '',
    email: member?.email ?? '',
    mobile_number: member?.mobile_number ?? '',
    role: member?.role ?? '',
    permissions: [...(member?.permissions ?? [])].sort(),
    password: '',
  };
}

/** Field errors for the details form, or null when it may be submitted. */
export function validateMemberForm(values) {
  const errors = {};
  if (!values.username.trim()) errors.username = 'Username is required.';
  if (!values.full_name.trim()) errors.full_name = 'Full name is required.';
  if (!values.email.trim()) errors.email = 'Email is required.';
  else if (!EMAIL_RE.test(values.email.trim())) errors.email = 'Enter a valid email address.';
  if (values.mobile_number.trim().length > 20) errors.mobile_number = 'At most 20 characters.';
  if (!STAFF_ROLES.has(values.role)) errors.role = 'Choose a role.';
  // The reset password is optional; one that was typed must meet the rule.
  if (values.password && passwordPolicyError(values.password)) errors.password = passwordPolicyError(values.password);
  return Object.keys(errors).length ? errors : null;
}

/**
 * What saving the form would send, relative to `baseline` (the member as the
 * API last returned it): `details` for PATCH (changed fields only), the full
 * `permissions` set for PUT when it changed, and the reset `password` when one
 * was typed. Each part is null when there is nothing to send.
 */
export function planMemberSave(baseline, values) {
  const before = memberFormValues(baseline);
  const details = {};
  if (values.username.trim() !== before.username) details.username = values.username.trim();
  if (values.full_name.trim() !== before.full_name) details.full_name = values.full_name.trim();
  // Stored in lower case by the API, so a change of letter case alone is none.
  const email = values.email.trim().toLowerCase();
  if (email !== before.email.toLowerCase()) details.email = email;
  if (values.mobile_number.trim() !== before.mobile_number) details.mobile_number = values.mobile_number.trim() || null;
  if (values.role !== before.role) details.role = values.role;
  const permissions = [...values.permissions].sort();
  const permissionsChanged =
    permissions.length !== before.permissions.length || permissions.some((name, i) => name !== before.permissions[i]);
  return {
    details: Object.keys(details).length ? details : null,
    permissions: permissionsChanged ? permissions : null,
    password: values.password ? values.password : null,
  };
}

/**
 * `{ status, code, message, details, fields, permissions }` from a Team API
 * failure. The API puts a machine code in `error` and the sentence to show in
 * `message`; a password-policy refusal adds `details`, missing or unknown
 * fields `fields`, and a refused permission change the codes in `permissions`.
 */
export function teamError(err, fallback) {
  const response = err?.response;
  const data = response?.data ?? {};
  return {
    status: response?.status ?? null,
    code: typeof data.error === 'string' ? data.error : null,
    message: response
      ? data.message || data.detail || fallback
      : 'Could not reach the server. Check your connection and try again.',
    details: Array.isArray(data.details) ? data.details : [],
    fields: Array.isArray(data.fields) ? data.fields : [],
    permissions: Array.isArray(data.permissions) ? data.permissions : [],
  };
}
