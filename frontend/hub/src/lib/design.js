// The Hub's refreshed design language is rolled out role by role. An account
// whose role is listed here gets it: the layout marks <html data-design="refresh">
// while they are signed in, which lays Eduport's colours over the Admin theme
// (index.css: blue actions and Demo, green Diagnostic and success, a white light
// page). Every other role keeps the current look until its own redesign adds it
// here; once every role is listed, the refreshed values become the defaults and
// this switch goes.
export const REFRESHED_ROLES = new Set(['BDE', 'ADMIN', 'TUTOR']);

export const REFRESH_ATTRIBUTE_VALUE = 'refresh';

// Pages a refreshed role still sees in the current look, because their own
// redesign has not come yet: the Admin's and the tutor's Academics & Learning
// -- their Academics Dashboard (the staff dashboard), and each page with
// everything under it, such as one student's profile under /students. The
// sidebar and header look the same either way: the refreshed tokens leave the
// sidebar's alone.
const CURRENT_LOOK_PAGES = {
  ADMIN: ['/academics-dashboard', '/students', '/sessions', '/exams', '/homework'],
  TUTOR: ['/academics-dashboard', '/students', '/sessions', '/exams', '/homework'],
};

/** Whether `user` works in the refreshed design (its sidebar and pages), whichever page is open. */
export function usesRefreshedDesign(user) {
  return REFRESHED_ROLES.has(user?.role);
}

/** Whether the page at `pathname` shows `user` the refreshed design's colours. */
export function refreshedAt(user, pathname) {
  if (!usesRefreshedDesign(user)) return false;
  const kept = CURRENT_LOOK_PAGES[user.role] ?? [];
  return !kept.some((page) => pathname === page || pathname.startsWith(`${page}/`));
}
