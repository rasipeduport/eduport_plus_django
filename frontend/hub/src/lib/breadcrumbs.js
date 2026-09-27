/**
 * Map of route paths to their breadcrumb trail.
 *
 * Each entry is an array so multi-level breadcrumbs work out of the box:
 *   '/students/123': [{ label: 'Students', href: '/students' }, { label: 'Jane Doe' }]
 *
 * The last item in the array is always rendered as the current (non-link) page.
 */
const breadcrumbConfig = {
  '/dashboard': [{ label: 'Dashboard' }],
  '/students': [{ label: 'Students' }],
  '/sessions': [{ label: 'Sessions' }],
  '/admins': [{ label: 'Admins' }],
  '/mentors': [{ label: 'Mentors' }],
  '/tutors': [{ label: 'Tutors' }],
  '/invitations': [{ label: 'Invitations' }],
  // The Hub shows no breadcrumb on /activity -- the page carries its own
  // "Activity log" heading, so the crumb only repeated it.
};

export function getBreadcrumbs(pathname) {
  return breadcrumbConfig[pathname] ?? [];
}
