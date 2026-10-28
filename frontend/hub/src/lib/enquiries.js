// The BDE workspace's enquiries: the /api/bde/ contract (backend
// bookings/enquiries.py) as the Hub uses it. The API scopes every answer to
// the signed-in BDE and enforces every rule; this only labels what it returns.

export const BDE_DASHBOARD_URL = '/api/bde/dashboard/';
export const ENQUIRIES_URL = '/api/bde/enquiries/';
export const enquiryUrl = (id) => `${ENQUIRIES_URL}${id}/`;

// Statuses follow the bookings (backend EnquiryStatus); a BDE does not set them.
export const ENQUIRY_STATUSES = [
  { value: 'NEW', label: 'New' },
  { value: 'BOOKED', label: 'Booked' },
  { value: 'DONE', label: 'Booking done' },
  { value: 'CANCELLED', label: 'Cancelled' },
];

const STATUS_VARIANT = { NEW: 'info', BOOKED: 'success', DONE: 'secondary', CANCELLED: 'outline' };

export function statusVariant(status) {
  return STATUS_VARIANT[status] ?? 'outline';
}

// What a BDE picks when adding an enquiry by hand (backend MANUAL_LEAD_SOURCES).
export const MANUAL_SOURCES = [
  { value: 'PHONE_CALL', label: 'Phone call' },
  { value: 'WHATSAPP', label: 'WhatsApp' },
  { value: 'WALK_IN', label: 'Walk-in' },
  { value: 'REFERRAL', label: 'Referral' },
  { value: 'SOCIAL_MEDIA', label: 'Social media' },
  { value: 'OTHER', label: 'Other' },
];

// The list filter also offers the two booking links (backend SOURCE_FILTERS).
export const SOURCE_FILTERS = [
  { value: 'DEMO_LINK', label: 'Demo link' },
  { value: 'DIAGNOSTIC_LINK', label: 'Diagnostic link' },
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
 * `{ status, code, message, fields, enquiryId }` from an axios error. The
 * workspace answers `{ error: CODE, message, fields? }`; a duplicate of the
 * BDE's own enquiry also carries `enquiry_id`.
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
    enquiryId: typeof data.enquiry_id === 'string' ? data.enquiry_id : null,
  };
}
