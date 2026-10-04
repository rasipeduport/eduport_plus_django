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
  '/exams': [{ label: 'Exams' }],
  '/homework': [{ label: 'Homework' }],
  '/admins': [{ label: 'Admins' }],
  '/mentors': [{ label: 'Mentors' }],
  '/tutors': [{ label: 'Tutors' }],
  '/invitations': [{ label: 'Invitations' }],
  // The Hub shows no breadcrumb on /activity -- the page carries its own
  // "Activity log" heading, so the crumb only repeated it.
};

// Routes whose trail cannot be a fixed string because the path carries an id.
// The page itself names the record (the student profile shows the student's
// name in its header), so the crumb stays generic rather than waiting on a
// fetch to render the chrome.
const breadcrumbPatterns = [
  { pattern: /^\/students\/[^/]+$/, trail: [{ label: 'Students', href: '/students' }, { label: 'Profile' }] },
];

export function getBreadcrumbs(pathname) {
  const exact = breadcrumbConfig[pathname];
  if (exact) return exact;
  return breadcrumbPatterns.find((entry) => entry.pattern.test(pathname))?.trail ?? [];
}
