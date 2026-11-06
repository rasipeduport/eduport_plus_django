// Booking management for administrators: the /api/bookings/<type>/ contract
// (backend bookings/management_views.py and bookings/coordination.py) as the
// Hub uses it. The API enforces every rule -- who may read or change a
// booking, and whether a tutor is free, checked again when assigning -- so
// this only builds its requests and labels what it returns.

export const BOOKING_TYPES = [
  { value: 'DEMO', label: 'Demo' },
  { value: 'DIAGNOSTIC', label: 'Diagnostic' },
];
// The Bookings page opens on the Demo bookings.
export const DEFAULT_TYPE = 'DEMO';

// Each type is a table and a list of its own (backend bookings.models.booking_model),
// so a booking is named by its type and its id: /api/bookings/<demo|diagnostic>/<id>/.
const TYPE_PATHS = { DEMO: 'demo', DIAGNOSTIC: 'diagnostic' };

export function typePath(type) {
  const segment = TYPE_PATHS[type];
  if (!segment) throw new Error(`Unknown booking type: ${type}`);
  return segment;
}

export const BOOKINGS_URL = '/api/bookings/';
export const bookingsUrl = (type) => `${BOOKINGS_URL}${typePath(type)}/`;
export const bookingUrl = (type, id) => `${bookingsUrl(type)}${id}/`;
export const bookingTutorsUrl = (type, id) => `${bookingUrl(type, id)}tutors/`;
export const bookingTutorUrl = (type, id) => `${bookingUrl(type, id)}tutor/`;
export const bookingHistoryUrl = (type, id) => `${bookingUrl(type, id)}history/`;
export const bookingRescheduleOptionsUrl = (type, id) => `${bookingUrl(type, id)}reschedule-options/`;
export const bookingRescheduleUrl = (type, id) => `${bookingUrl(type, id)}reschedule/`;
export const bookingCancelUrl = (type, id) => `${bookingUrl(type, id)}cancel/`;
// A Diagnostic's Demo invitation for its parent (backend bookings.demo_invites): the Admin's, and a BDE's for their own lead.
export const bookingDemoInviteUrl = (type, id) => `${bookingUrl(type, id)}demo-invite/`;
// A BDE's routes on a booking of their own lead; the API checks the lead is theirs on every request.
export const bdeBookingUrl = (type, id) => `/api/bde/bookings/${typePath(type)}/${id}/`;
// Cancelling it (Q22).
export const bdeBookingCancelUrl = (type, id) => `${bdeBookingUrl(type, id)}cancel/`;
export const bdeDemoInviteUrl = (type, id) => `${bdeBookingUrl(type, id)}demo-invite/`;

/** The Bookings page with one booking open in its detail sheet (?type=<TYPE>&booking=<id>). */
export function bookingPagePath(type, id) {
  typePath(type); // DEMO or DIAGNOSTIC only, as for the API paths
  return `/bookings?type=${type}&booking=${id}`;
}

// Why a booking was cancelled or moved: a code from a fixed list (backend
// bookings.models.CancelReason / RescheduleReason), never free text. No-show
// is offered only once the scheduled time has passed (the booking's actions.no_show).
export const CANCEL_REASONS = [
  { value: 'NO_SHOW', label: 'No-show' },
  { value: 'PARENT_REQUEST', label: 'Parent asked to cancel' },
  { value: 'DUPLICATE', label: 'Duplicate booking' },
  { value: 'BOOKED_BY_MISTAKE', label: 'Booked by mistake' },
  { value: 'OTHER', label: 'Other' },
];
export const RESCHEDULE_REASONS = [
  { value: 'PARENT_REQUEST', label: 'Parent asked to move' },
  { value: 'TUTOR_UNAVAILABLE', label: 'Tutor unavailable' },
  { value: 'OTHER', label: 'Other' },
];

const labelOf = (options, code) => options.find((option) => option.value === code)?.label ?? '';
export const cancelReasonLabel = (code) => labelOf(CANCEL_REASONS, code);
export const rescheduleReasonLabel = (code) => labelOf(RESCHEDULE_REASONS, code);

// The list filters the API accepts (backend coordination.parse_filters). The
// type is the list's own URL, never a filter.
export const BOOKING_STATUSES = [
  { value: 'BOOKED', label: 'Booked' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'RESCHEDULED', label: 'Rescheduled' },
  { value: 'CANCELLED', label: 'Cancelled' },
];
export const ASSIGNMENT_FILTERS = [
  { value: 'false', label: 'Needs a tutor' },
  { value: 'true', label: 'Tutor assigned' },
];
// Whether the booking has its report (backend coordination.parse_filters
// `report`, P8). Report due is a booked booking whose slot is over without
// one -- the rows' own report_due -- so it is only ever found among past slots.
export const REPORT_FILTERS = [
  { value: 'submitted', label: 'Report submitted' },
  { value: 'missing', label: 'No report yet' },
  { value: 'due', label: 'Report due' },
];
export const REPORT_DUE = 'due';
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
const REPORT_VALUES = values(REPORT_FILTERS);
const WHEN_VALUES = values(WHEN_FILTERS);

/** `value` if it is a booking type (DEMO or DIAGNOSTIC), else ''. */
export function readBookingType(value) {
  return TYPE_VALUES.has(value) ? value : '';
}

/**
 * The list's filters from the page URL, and the type tab it shows (Demo
 * unless the URL says Diagnostic). A value the API would refuse is dropped
 * here, so a hand-edited link shows the unfiltered list rather than an error.
 * Reports are due only on slots that are over, so Report due reads Upcoming
 * (the default) as Past: a link to the reports due never shows an empty list.
 */
export function readFilters(searchParams) {
  const pick = (name, allowed) => (allowed.has(searchParams.get(name)) ? searchParams.get(name) : '');
  const date = (name) => (DATE_RE.test(searchParams.get(name) ?? '') ? searchParams.get(name) : '');
  const report = pick('report', REPORT_VALUES);
  const when = pick('when', WHEN_VALUES) || DEFAULT_WHEN;
  return {
    q: (searchParams.get('q') ?? '').trim(),
    type: pick('type', TYPE_VALUES) || DEFAULT_TYPE,
    status: pick('status', STATUS_VALUES),
    assigned: pick('assigned', ASSIGNMENT_VALUES),
    report,
    from: date('from'),
    to: date('to'),
    when: report === REPORT_DUE && when === 'upcoming' ? 'past' : when,
  };
}

/** The query the list endpoint (bookingsUrl(filters.type)) takes for `filters` and `page`. */
export function listParams(filters, page, pageSize) {
  const params = { page, page_size: pageSize };
  for (const name of ['q', 'status', 'assigned', 'report', 'from', 'to']) {
    if (filters[name]) params[name] = filters[name];
  }
  if (filters.when !== 'all') params.when = filters.when;
  return params;
}

// My Bookings for tutors: the /api/tutor/bookings/ contract (backend
// bookings/tutor_views.py and bookings/tutor_bookings.py). The API serves the
// caller only the bookings assigned to them, each with the child and the slot
// and nothing of the parent, the BDE or the assignment. The list holds both
// types (filtered by `type`); one booking is named by its type and its id.
export const TUTOR_BOOKINGS_URL = '/api/tutor/bookings/';
export const tutorBookingUrl = (type, id) => `${TUTOR_BOOKINGS_URL}${typePath(type)}/${id}/`;
// Start Demo / Start Diagnostic: the tutor's own explicit start (backend booking_service.start_booking).
export const tutorBookingStartUrl = (type, id) => `${tutorBookingUrl(type, id)}start/`;

/** "Start Demo" or "Start Diagnostic". */
export function startLabel(type) {
  return type === 'DIAGNOSTIC' ? 'Start Diagnostic' : 'Start Demo';
}

// What a refused Start says to the tutor (backend booking_service), by its code.
const START_REFUSALS = {
  START_TOO_EARLY: 'It is too early to start. You can start from 5 minutes before the scheduled time.',
  START_WINDOW_CLOSED: 'The slot has ended, so this booking can no longer be started.',
  BOOKING_CANCELLED: 'This booking was cancelled, so it cannot be started.',
  BOOKING_RESCHEDULED: 'This booking was moved to another slot. Start the new booking instead.',
  BOOKING_COMPLETED: 'This booking is already completed.',
  NOT_FOUND: 'This booking is no longer assigned to you.',
};

/** A failed Start as `bookingError` reads it, with the tutor's own wording for each refusal. */
export function startError(err) {
  const failure = bookingError(err, 'Could not start this booking. Please try again.');
  return { ...failure, message: START_REFUSALS[failure.code] ?? failure.message };
}

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

// Where a booking stands as a class (backend bookings.lifecycle ActivityState).
const ACTIVITY_STATES = {
  UPCOMING: { label: 'Upcoming', variant: 'success' },
  READY: { label: 'Ready to start', variant: 'success' },
  LATE: { label: 'Not started yet', variant: 'warning' },
  IN_PROGRESS: { label: 'In progress', variant: 'info' },
  NOT_STARTED: { label: 'Not started', variant: 'warning' },
  COMPLETED: { label: 'Completed', variant: 'secondary' },
  CANCELLED: { label: 'Cancelled', variant: 'outline' },
  RESCHEDULED: { label: 'Rescheduled', variant: 'outline' },
};
const BOOKED_STATE = { label: 'Booked', variant: 'success' };

/**
 * Where a booking stands: cancelled, moved or completed by its status; a
 * booked one by the API's own `activity_state`, never the slot's clock -- a
 * booking starts only when its tutor starts it, so a scheduled time that has
 * passed means Not started yet (or Not started, once the slot is over), never
 * In progress or Done. A booked one given without it (a link in a reschedule
 * chain) is just Booked.
 */
export function bookingState(booking) {
  if (booking.status !== 'BOOKED' && booking.status in ACTIVITY_STATES) return ACTIVITY_STATES[booking.status];
  return ACTIVITY_STATES[booking.activity_state] ?? BOOKED_STATE;
}

/**
 * Whether the booking's tutor may still change: booked, not started by its
 * tutor, and its slot not over (backend tutor_change_refusal).
 */
export function tutorChangeable(booking) {
  if ('tutor_changeable' in booking) return Boolean(booking.tutor_changeable);
  return booking.status === 'BOOKED' && !booking.started_at && !booking.slot?.ended;
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
 * How a booking came in, as its detail names it: a Demo booked with a Demo
 * invitation (a BDE handoff, backend bookings.demo_invites), or the booking
 * page's link as referralLabel reads it.
 */
export function cameInLabel(booking) {
  return booking?.channel === 'BDE_HANDOFF' ? 'Demo invitation' : referralLabel(booking?.referral_status);
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
