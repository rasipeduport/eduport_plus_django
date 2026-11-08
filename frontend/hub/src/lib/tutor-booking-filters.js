// A tutor's Demo and Diagnostic Bookings filters (pages/TutorBookingsPage):
// the view -- Upcoming, Completed or All -- then the class date (Today, This
// Week, This Month, All Time or a Custom range, in Indian dates, as a BDE's and
// the administrators' booking lists offer it), the student's name, the booking
// status and whether the feedback (a Demo's) or the results (a Diagnostic's)
// are in, every value kept in the URL. The booking type is the page's own
// address, never a filter. A value the API would refuse is dropped, so a
// hand-edited link shows the unfiltered list rather than an error.
import { DEFAULT_CLASS_DATES, readBdeBookingFilters } from '@/lib/bde-booking-filters';

// Upcoming: the slot has not ended. Completed: the classes taught -- the
// report in, or due (backend tutor_bookings.taught). All: every booking.
export const TUTOR_VIEWS = [
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'completed', label: 'Completed' },
  { value: 'all', label: 'All' },
];
export const DEFAULT_VIEW = 'upcoming';

// The statuses a tutor's rows show (backend tutor_bookings.STATUS_FILTERS): a
// Demo sent for a Re-Demo reads Completed to the tutor who taught it.
export const TUTOR_STATUSES = [
  { value: 'BOOKED', label: 'Booked' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'RESCHEDULED', label: 'Rescheduled' },
  { value: 'CANCELLED', label: 'Cancelled' },
];

// The report filter (the API's `report`): Pending is a class the tutor taught
// whose report is still due; Submitted, one whose report is in.
export const FEEDBACK_FILTERS = [
  { value: 'due', label: 'Pending' },
  { value: 'submitted', label: 'Submitted' },
];

const known = (options, value) => options.some((option) => option.value === value);

/**
 * The list's filters from its URL: `view` (Upcoming when absent), the class
 * date as lib/bde-booking-filters reads it (`dates`, `from`, `to`), `q` (the
 * student's name), `status` -- Upcoming and All only: Completed lists only
 * the classes taught -- `feedback` (Completed and All only: a class still to
 * come has nothing to report) and `page`. `filtered` says whether any filter
 * is off its default; the view is the page's tab, not a filter.
 */
export function readTutorBookingFilters(searchParams, now = new Date()) {
  const { page, q, status, dates, from, to } = readBdeBookingFilters(searchParams, TUTOR_STATUSES, now);
  const view = known(TUTOR_VIEWS, searchParams.get('view')) ? searchParams.get('view') : DEFAULT_VIEW;
  const asked = known(FEEDBACK_FILTERS, searchParams.get('feedback')) ? searchParams.get('feedback') : '';
  const shownStatus = view === 'completed' ? '' : status;
  const feedback = view === 'upcoming' ? '' : asked;
  return {
    page,
    view,
    q,
    status: shownStatus,
    feedback,
    dates,
    from,
    to,
    filtered: Boolean(q || shownStatus || feedback || dates !== DEFAULT_CLASS_DATES),
  };
}

/** What GET /api/tutor/bookings/ is asked for the bookings of `type` under `filters` (readTutorBookingFilters'). */
export function tutorBookingParams(type, filters, pageSize) {
  const params = { type, when: filters.view, page: filters.page, page_size: pageSize };
  if (filters.q) params.q = filters.q;
  if (filters.status) params.status = filters.status;
  if (filters.feedback) params.report = filters.feedback;
  if (filters.from) params.from = filters.from;
  if (filters.to) params.to = filters.to;
  return params;
}

// What going back to the unfiltered list of the same view clears.
export const CLEARED_TUTOR_FILTERS = { dates: null, from: null, to: null, q: null, status: null, feedback: null, page: null };
