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
  '/academics-dashboard': [{ label: 'Academics Dashboard' }],
  '/students': [{ label: 'Students' }],
  '/sessions': [{ label: 'Sessions' }],
  '/exams': [{ label: 'Exams' }],
  '/homework': [{ label: 'Homework' }],
  '/invitations': [{ label: 'Invitations' }],
  '/enquiries': [{ label: 'My Enquiries' }],
  '/demo-bookings': [{ label: 'Demo Bookings' }],
  '/diagnostic-bookings': [{ label: 'Diagnostic Bookings' }],
  '/follow-ups': [{ label: 'Follow-ups' }],
  '/sales': [{ label: 'My Sales' }],
  '/plans': [{ label: 'Plans & Pricing' }],
  '/leads': [{ label: 'Leads' }],
  '/admissions': [{ label: 'Admissions Dashboard' }],
  '/bookings': [{ label: 'Bookings' }],
  '/bookings/demo': [{ label: 'Demo Bookings' }],
  '/bookings/diagnostic': [{ label: 'Diagnostic Bookings' }],
  '/booking-slots': [{ label: 'Booking Slots' }],
  '/my-bookings': [{ label: 'My Bookings' }],
  '/my-bookings/demo': [{ label: 'Demo Bookings' }],
  '/my-bookings/diagnostic': [{ label: 'Diagnostic Bookings' }],
  '/hourly-earnings': [{ label: 'Hourly Earnings' }],
  '/team': [{ label: 'Team' }],
  '/sales-dashboard': [{ label: 'Sales Dashboard' }],
  '/sales-module': [{ label: 'Sales Module' }],
  '/sales-punching': [{ label: 'Sales Punching' }],
  '/sales-syllabus': [{ label: 'Sales Syllabus' }],
  '/tutor-earnings': [{ label: 'Tutor Earnings' }],
  // The Hub shows no breadcrumb on /activity -- the page carries its own
  // heading (the activity log's, or a BDE's Activity), so the crumb only repeated it.
};

// Routes whose trail cannot be a fixed string because the path carries an id.
// The page itself names the record (the student profile shows the student's
// name in its header), so the crumb stays generic rather than waiting on a
// fetch to render the chrome. A trail may be worked out from the path's match
// (a tutor's report links back to its own booking).
const breadcrumbPatterns = [
  { pattern: /^\/students\/[^/]+$/, trail: [{ label: 'Students', href: '/students' }, { label: 'Profile' }] },
  { pattern: /^\/team\/[^/]+$/, trail: [{ label: 'Team', href: '/team' }, { label: 'Staff member' }] },
  { pattern: /^\/enquiries\/[^/]+$/, trail: [{ label: 'My Enquiries', href: '/enquiries' }, { label: 'Enquiry' }] },
  { pattern: /^\/leads\/[^/]+$/, trail: [{ label: 'Leads', href: '/leads' }, { label: 'Lead' }] },
  { pattern: /^\/bookings\/demo\/[^/]+$/, trail: [{ label: 'Demo Bookings', href: '/bookings/demo' }, { label: 'Booking' }] },
  {
    pattern: /^\/bookings\/diagnostic\/[^/]+$/,
    trail: [{ label: 'Diagnostic Bookings', href: '/bookings/diagnostic' }, { label: 'Booking' }],
  },
  {
    pattern: /^\/my-bookings\/demo\/[^/]+$/,
    trail: [{ label: 'Demo Bookings', href: '/my-bookings/demo' }, { label: 'Booking' }],
  },
  {
    pattern: /^\/my-bookings\/diagnostic\/[^/]+$/,
    trail: [{ label: 'Diagnostic Bookings', href: '/my-bookings/diagnostic' }, { label: 'Booking' }],
  },
  {
    pattern: /^\/my-bookings\/(demo|diagnostic)\/([^/]+)\/report$/,
    trail: ([, segment, id]) => [
      { label: segment === 'demo' ? 'Demo Bookings' : 'Diagnostic Bookings', href: `/my-bookings/${segment}` },
      { label: 'Booking', href: `/my-bookings/${segment}/${id}` },
      { label: segment === 'demo' ? 'Feedback' : 'Results' },
    ],
  },
];

export function getBreadcrumbs(pathname) {
  const exact = breadcrumbConfig[pathname];
  if (exact) return exact;
  for (const entry of breadcrumbPatterns) {
    const match = entry.pattern.exec(pathname);
    if (match) return typeof entry.trail === 'function' ? entry.trail(match) : entry.trail;
  }
  return [];
}
