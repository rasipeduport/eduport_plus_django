// The BDE workspace's enquiries -- their My Enquiries: the /api/bde/ contract
// (backend bookings/enquiries.py) as the Hub uses it, and the labels the
// administrators' Leads page shares (lib/leads.js). The API scopes every answer
// to the signed-in BDE and enforces every rule; this only labels what it returns.

export const BDE_DASHBOARD_URL = '/api/bde/dashboard/';
export const ENQUIRIES_URL = '/api/bde/enquiries/';
export const enquiryUrl = (id) => `${ENQUIRIES_URL}${id}/`;
// Staff's notes on one of the BDE's enquiries, shared with its tutors and the
// administrators (backend bookings/notes.py): read and added, never edited.
export const enquiryNotesUrl = (id) => `${enquiryUrl(id)}notes/`;
export const NOTE_MAX_LENGTH = 2000;

/**
 * An enquiry's workspace opened on its Bookings tab with `bookingId`
 * highlighted -- how the dashboard and the booking lists open one booking in
 * context (pages/EnquiryPage.jsx reads `tab` and `highlight`).
 */
export const enquiryBookingPath = (enquiryId, bookingId) => `/enquiries/${enquiryId}?tab=bookings&highlight=${bookingId}`;

// A lead's status follows its bookings (backend bookings.lead_status): nobody
// sets it. A booking to come shows first, then a class that happened, then a
// slot that ended with no start (the class never happened), then a cancellation.
// The status filter also takes each stage of either type (backend STAGES):
// the dashboard's Upcoming Bookings opens My Enquiries at ?status=BOOKED.
export const LEAD_STATUSES = [
  { value: 'NEW', label: 'New' },
  { value: 'BOOKED', label: 'Booked (any type)' },
  { value: 'DIAGNOSTIC_BOOKED', label: 'Diagnostic booked' },
  { value: 'DEMO_BOOKED', label: 'Demo booked' },
  { value: 'COMPLETED', label: 'Completed (any type)' },
  { value: 'DIAGNOSTIC_COMPLETED', label: 'Diagnostic completed' },
  { value: 'DEMO_COMPLETED', label: 'Demo completed' },
  // A completed Demo sent for a Re-Demo (backend bookings.redemos); Completed (any type) includes it.
  { value: 'DEMO_REDEMO_REQUIRED', label: 'Re-Demo required' },
  { value: 'NOT_STARTED', label: 'Not started (any type)' },
  { value: 'DIAGNOSTIC_NOT_STARTED', label: 'Diagnostic not started' },
  { value: 'DEMO_NOT_STARTED', label: 'Demo not started' },
  { value: 'CANCELLED', label: 'Cancelled (any type)' },
  { value: 'DIAGNOSTIC_CANCELLED', label: 'Diagnostic cancelled' },
  { value: 'DEMO_CANCELLED', label: 'Demo cancelled' },
];

const STATUS_VARIANT = {
  BOOKED: 'success',
  COMPLETED: 'secondary',
  REDEMO_REQUIRED: 'warning',
  NOT_STARTED: 'warning',
  CANCELLED: 'outline',
};

export function statusVariant(status) {
  if (status === 'NEW') return 'info';
  return STATUS_VARIANT[String(status ?? '').replace(/^(DEMO|DIAGNOSTIC)_/, '')] ?? 'outline';
}

// What a BDE or an administrator picks when adding a lead by hand (backend MANUAL_LEAD_SOURCES).
export const MANUAL_SOURCES = [
  { value: 'PHONE_CALL', label: 'Phone call' },
  { value: 'WHATSAPP', label: 'WhatsApp' },
  { value: 'WALK_IN', label: 'Walk-in' },
  { value: 'REFERRAL', label: 'Referral' },
  { value: 'SOCIAL_MEDIA', label: 'Social media' },
  { value: 'OTHER', label: 'Other' },
];

// The list filters also offer the two booking links, a booking page's lead no
// link brought, and the marketing site's two lead forms (backend SOURCE_FILTERS).
export const SOURCE_FILTERS = [
  { value: 'DEMO_LINK', label: 'Demo link' },
  { value: 'DIAGNOSTIC_LINK', label: 'Diagnostic link' },
  { value: 'BOOKING_PAGE', label: 'Booking page' },
  { value: 'WEBSITE', label: 'Website' },
  { value: 'LANDING_PAGE', label: 'Landing page' },
  ...MANUAL_SOURCES,
];

export function sourceLabel(source) {
  return SOURCE_FILTERS.find((option) => option.value === source)?.label ?? 'Booking page';
}

// The booking pages' classes and syllabi (backend public_serializers), so an
// enquiry added by hand reads like one that came through them.
export const CLASSES = ['Class 5', 'Class 6', 'Class 7', 'Class 8', 'Class 9', 'Class 10'];
export const SYLLABI = ['CBSE', 'IB', 'IGCSE', 'ICSE', 'Others'];

export const BOOKING_TYPE_LABELS = { DEMO: 'Demo class', DIAGNOSTIC: 'Diagnostic test' };

export function bookingTypeLabel(type) {
  return BOOKING_TYPE_LABELS[type] ?? type;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/**
 * A booking's slot as "Thu, 30 Oct" and "7:30 PM". Slots are Indian dates and
 * times (backend bookings.scheduling) and are shown as such, labelled IST,
 * whatever zone this device is in -- so nothing here reads the device clock.
 */
export function slotParts(date, time) {
  const [year, month, day] = String(date).split('-').map(Number);
  const [hour, minute] = String(time).split(':').map(Number);
  if (!year || !month || !day || Number.isNaN(hour) || Number.isNaN(minute)) return { day: date, time };
  const weekday = WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
  const clock = `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'AM' : 'PM'}`;
  return { day: `${weekday}, ${day} ${MONTHS[month - 1]}`, time: clock };
}

export function slotLabel(booking) {
  if (!booking) return '';
  const parts = slotParts(booking.date, booking.time);
  return `${parts.day} · ${parts.time} IST`;
}

/** A timestamp from the API as "28 Oct 2026" in this device's zone. */
export function formatDay(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

/** A phone number from the API ("+971 501234567") as a tel: and a wa.me link. */
export function phoneLinks(dialCode, number) {
  const digits = `${dialCode ?? ''}${number ?? ''}`.replace(/\D/g, '');
  return digits ? { tel: `tel:+${digits}`, whatsapp: `https://wa.me/${digits}` } : null;
}

/**
 * The wa.me link that opens a chat with this number with ``text`` filled in,
 * or null without a number. WhatsApp sends nothing until its user does, and a
 * link can carry no file.
 */
export function whatsAppUrl(dialCode, number, text) {
  const links = phoneLinks(dialCode, number);
  return links ? `${links.whatsapp}?text=${encodeURIComponent(text)}` : null;
}

/**
 * `{ status, code, message, fields, enquiryId }` from an axios error. The
 * workspace and the Leads API answer `{ error: CODE, message, fields? }`; a
 * duplicate of the BDE's own enquiry also carries `enquiry_id`, and any
 * duplicate an administrator adds `lead_id`.
 */
export function enquiryError(err, fallback) {
  const response = err?.response;
  const data = response?.data ?? {};
  return {
    status: response?.status ?? null,
    code: typeof data.error === 'string' ? data.error : null,
    message: response
      ? data.message || data.detail || fallback
      : 'Could not reach the server. Check your connection and try again.',
    fields: data.fields && typeof data.fields === 'object' && !Array.isArray(data.fields) ? data.fields : {},
    enquiryId: [data.enquiry_id, data.lead_id].find((id) => typeof id === 'string') ?? null,
  };
}
