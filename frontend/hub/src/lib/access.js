// Which Hub pages each staff role may open -- one table for the No Access gate,
// the route guards and the sidebar, so they can never disagree. The API
// enforces the same rules on every request; this only decides what the Hub
// offers. Access is granted role by role: an account whose role is not listed
// here gets no pages at all, never the admin's.

import { canViewTeam } from './team';

export const HUB_ROLES = ['ADMIN', 'MENTOR', 'TUTOR'];

const PAGES_BY_ROLE = {
  ADMIN: new Set(['/dashboard', '/students', '/sessions', '/exams', '/homework', '/invitations', '/activity']),
  MENTOR: new Set(['/dashboard', '/students', '/sessions', '/exams', '/homework', '/activity']),
  // Exams are a mentor <-> student affair; tutors are not involved.
  TUTOR: new Set(['/dashboard', '/students', '/sessions', '/homework', '/activity']),
};

/**
 * The role the Hub treats `user` as, or null when the Hub has nothing for
 * them. A superuser keeps a MENTOR or TUTOR role's view, as the API scopes
 * them; with any other role (students aside) a superuser counts as ADMIN, as
 * the API's IsAdminUser does.
 */
export function hubRole(user) {
  if (!user) return null;
  if (HUB_ROLES.includes(user.role)) return user.role;
  return user.is_superuser && user.role !== 'STUDENT' ? 'ADMIN' : null;
}

/** Whether `user` may open the page at `path` (a top-level path such as '/exams'). */
export function canOpenPage(user, path) {
  const role = hubRole(user);
  if (!role) return false;
  // The Team directory follows its own rule: managers, and staff holding accounts.view_team.
  if (path === '/team') return canViewTeam(user);
  return PAGES_BY_ROLE[role].has(path);
}
