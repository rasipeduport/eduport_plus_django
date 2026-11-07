// The Hub's refreshed design language is rolled out role by role. An account
// whose role is listed here gets it: the layout marks <html data-design="refresh">
// while they are signed in, which lays Eduport's colours over the Admin theme
// (index.css: blue actions and Demo, green Diagnostic and success, a white light
// page). Every other role keeps the current look until its own redesign adds it
// here; once every role is listed, the refreshed values become the defaults and
// this switch goes.
export const REFRESHED_ROLES = new Set(['BDE']);

export const REFRESH_ATTRIBUTE_VALUE = 'refresh';

/** Whether `user` sees the Hub in the refreshed design. */
export function usesRefreshedDesign(user) {
  return REFRESHED_ROLES.has(user?.role);
}
