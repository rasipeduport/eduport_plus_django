// Booking management for administrators: the /api/bookings/ contract (backend
// bookings/management_views.py and bookings/coordination.py) as the Hub uses
// it. The API enforces every rule -- who may read or change a booking, and
// whether a tutor is free, checked again when assigning -- so this only builds
// its requests and labels what it returns.

export const BOOKINGS_URL = '/api/bookings/';
export const bookingUrl = (id) => `${BOOKINGS_URL}${id}/`;
export const bookingTutorsUrl = (id) => `${BOOKINGS_URL}${id}/tutors/`;
export const bookingTutorUrl = (id) => `${BOOKINGS_URL}${id}/tutor/`;

// The list filters the API accepts (backend coordination.parse_filters).
export const BOOKING_TYPES = [
  { value: 'DEMO', label: 'Demo' },
  { value: 'DIAGNOSTIC', label: 'Diagnostic' },
];
export const BOOKING_STATUSES = [
  { value: 'BOOKED', label: 'Booked' },
  { value: 'CANCELLED', label: 'Cancelled' },
];
export const ASSIGNMENT_FILTERS = [
  { value: 'false', label: 'Needs a tutor' },
  { value: 'true', label: 'Tutor assigned' },
];
// Upcoming is the page's default; "all" is the page's own word for no date filter.
export const WHEN_FILTERS = [
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'past', label: 'Past' },
  { value: 'all', label: 'All dates' },
];
export const DEFAULT_WHEN = 'upcoming';

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

const values = (options) => new Set(options.map((option) => option.value));
const TYPE_VALUES = values(BOOKING_TYPES);
const STATUS_VALUES = values(BOOKING_STATUSES);
const ASSIGNMENT_VALUES = values(ASSIGNMENT_FILTERS);
const WHEN_VALUES = values(WHEN_FILTERS);

/**
 * The list's filters from the page URL. A value the API would refuse is
 * dropped here, so a hand-edited link shows the unfiltered list rather than
 * an error.
 */
export function readFilters(searchParams) {
  const pick = (name, allowed) => (allowed.has(searchParams.get(name)) ? searchParams.get(name) : '');
  const date = (name) => (DATE_RE.test(searchParams.get(name) ?? '') ? searchParams.get(name) : '');
  return {
    q: (searchParams.get('q') ?? '').trim(),
    type: pick('type', TYPE_VALUES),
    status: pick('status', STATUS_VALUES),
    assigned: pick('assigned', ASSIGNMENT_VALUES),
    from: date('from'),
    to: date('to'),
    when: pick('when', WHEN_VALUES) || DEFAULT_WHEN,
  };
}

/** The query the list endpoint takes for `filters` and `page`. */
export function listParams(filters, page, pageSize) {
  const params = { page, page_size: pageSize };
  for (const name of ['q', 'type', 'status', 'assigned', 'from', 'to']) {
    if (filters[name]) params[name] = filters[name];
  }
  if (filters.when !== 'all') params.when = filters.when;
  return params;
}

// My Bookings for tutors: the /api/tutor/bookings/ contract (backend
// bookings/tutor_views.py and bookings/tutor_bookings.py). The API serves the
// caller only the bookings assigned to them, each with the child and the slot
// and nothing of the parent, the BDE or the assignment.
export const TUTOR_BOOKINGS_URL = '/api/tutor/bookings/';
export const tutorBookingUrl = (id) => `${TUTOR_BOOKINGS_URL}${id}/`;

/** The tutor list's filters from the page URL; a value the API would refuse is dropped, as in readFilters. */
export function readTutorFilters(searchParams) {
  const pick = (name, allowed) => (allowed.has(searchParams.get(name)) ? searchParams.get(name) : '');
  return { type: pick('type', TYPE_VALUES), when: pick('when', WHEN_VALUES) || DEFAULT_WHEN };
}

/** The query the tutor list endpoint takes. It reads "all" itself (backend tutor_bookings.parse_filters). */
export function tutorListParams(filters, page, pageSize) {
  const params = { page, page_size: pageSize, when: filters.when };
  if (filters.type) params.type = filters.type;
  return params;
}

/** Where a booking stands: cancelled, or by its slot's clock -- upcoming, in progress, done. */
export function bookingState(booking) {
  if (booking.status === 'CANCELLED') return { label: 'Cancelled', variant: 'outline' };
  if (booking.slot?.ended) return { label: 'Done', variant: 'secondary' };
  if (booking.slot?.started) return { label: 'In progress', variant: 'info' };
  return { label: 'Upcoming', variant: 'success' };
}

/** Whether the booking's tutor may still change: booked, and its slot not started (backend tutor_change_refusal). */
export function tutorChangeable(booking) {
  if ('tutor_changeable' in booking) return Boolean(booking.tutor_changeable);
  return booking.status === 'BOOKED' && !booking.slot?.started;
}

// How the booking came in (backend bookings.models.ReferralStatus).
const REFERRAL_LABELS = {
  ATTRIBUTED: "Through a BDE's link",
  NO_REF: 'Booking page, no link',
  INVALID_REF: 'Unreadable link',
  UNKNOWN_REF: 'Unknown link',
  REVOKED_LINK: 'Revoked link',
  INACTIVE_BDE: 'Link of a BDE who has left',
  WRONG_TYPE: 'Link for the other booking type',
};

export function referralLabel(status) {
  return REFERRAL_LABELS[status] ?? status ?? '—';
}

/**
 * `{ status, code, message, fields, conflict }` from an axios error. The
 * booking API answers `{ error: CODE, message, fields?, conflict? }`; a
 * refused tutor carries the class or booking that holds them in `conflict`.
 */
export function bookingError(err, fallback) {
  const response = err?.response;
  const data = response?.data ?? {};
  const fields = Array.isArray(data.fields)
    ? data.fields
    : data.fields && typeof data.fields === 'object'
      ? Object.keys(data.fields)
      : [];
  return {
    status: response?.status ?? null,
    code: typeof data.error === 'string' ? data.error : null,
    message: response
      ? data.message || data.detail || fallback
      : 'Could not reach the server. Check your connection and try again.',
    fields,
    conflict: data.conflict && typeof data.conflict === 'object' ? data.conflict : null,
  };
}
