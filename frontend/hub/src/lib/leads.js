// The administrators' Leads page: the /api/leads/ contract (backend
// bookings/lead_views.py) as the Hub uses it. Rows, statuses and sources read
// as a BDE's My Enquiries does (lib/enquiries.js); the API enforces every rule.
import { bookingPagePath } from '@/lib/bookings';

export const LEADS_URL = '/api/leads/';
export const LEAD_BDES_URL = '/api/leads/bdes/';
export const leadUrl = (id) => `${LEADS_URL}${id}/`;
export const leadOwnerUrl = (id) => `${LEADS_URL}${id}/owner/`;
// Staff's notes on a lead, shared with its owner BDE and its tutors (backend bookings/notes.py).
export const leadNotesUrl = (id) => `${LEADS_URL}${id}/notes/`;
// The student's time zone on any lead, set or corrected (PUT { student_timezone },
// backend bookings.student_timezones): it answers the lead in full.
export const leadTimezoneUrl = (id) => `${LEADS_URL}${id}/student-timezone/`;

// The owner filter's value for the leads nobody owns yet.
export const UNASSIGNED = 'unassigned';

/** The owner filter's options: nobody, then every BDE account the API lists (those who left marked as such). */
export function ownerOptions(bdes) {
  return [
    { value: UNASSIGNED, label: 'Unassigned' },
    ...(bdes ?? []).map((bde) => ({ value: bde.id, label: bde.assignable ? bde.full_name : `${bde.full_name} (inactive)` })),
  ];
}

/** Where a lead's booking opens: its workspace. */
export function bookingPageUrl(booking) {
  return bookingPagePath(booking.booking_type, booking.id);
}

// The utm_* parameters a lead form's page carried (backend Lead.source_details), as the lead page labels them.
export const CAMPAIGN_FIELDS = [
  ['utm_source', 'Campaign source'],
  ['utm_medium', 'Medium'],
  ['utm_campaign', 'Campaign'],
  ['utm_content', 'Content'],
  ['utm_term', 'Term'],
];
