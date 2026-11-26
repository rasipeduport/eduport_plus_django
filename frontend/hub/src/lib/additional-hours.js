// Additional hours with deferred payment (backend sales.additional_hours): an
// administrator adds hours to an enrolled student's class quota at once, for an
// agreed amount the administrator or the student's mentor collects later, in as
// many payments as it takes. Their own ledger: never part of the plan figures,
// payment history, AutoPay, refunds or the Sales Dashboard. Every figure and
// every rule is the API's; the Hub only shows them and offers what the API's
// flags allow (can_create, can_manage, can_record_payment, can_void_payments).
import { PAYMENT_METHODS, paymentToday } from '@/lib/payments';

export const ADDITIONAL_HOURS_URL = '/api/sales/additional-hours/';
export const studentAdditionalHoursUrl = (studentId) => `/api/sales/students/${studentId}/additional-hours/`;
export const additionalHoursEligibilityUrl = (studentId) => `${studentAdditionalHoursUrl(studentId)}eligibility/`;
export const allocationUrl = (id) => `${ADDITIONAL_HOURS_URL}${id}/`;
export const allocationPaymentsUrl = (id) => `${allocationUrl(id)}payments/`;
export const allocationVoidUrl = (id, paymentId) => `${allocationPaymentsUrl(id)}${paymentId}/void/`;
// Paid through Stripe: a Checkout link per attempt (backend sales.additional_hours_stripe); only Stripe's
// verified webhook records the payment, never the parent's return from Checkout.
export const allocationStripeLinksUrl = (id) => `${allocationUrl(id)}stripe-links/`;
export const allocationStripeExpireUrl = (id, checkoutId) => `${allocationStripeLinksUrl(id)}${checkoutId}/expire/`;
/** Where an allocation opens: its student's Finance tab, scrolled to it. */
export const allocationPath = (row) => `/students/${row.student.id}?tab=finance&hours=${row.id}`;

// Money received directly, with its receipt: the regular ledger's own methods, never Stripe.
export const DIRECT_METHODS = PAYMENT_METHODS.filter((method) => method.value !== 'STRIPE');
export const VOID_KINDS = [
  { value: 'ERROR', label: 'Recorded in error' },
  { value: 'REFUNDED', label: 'Refunded to the payer' },
  { value: 'REVERSED', label: 'Reversed or bounced' },
];

// Where an allocation's payment stands (sales.additional_hours.state); the hours count whatever it says.
const STATUSES = {
  PENDING: { label: 'Pending', variant: 'warning' },
  PARTIALLY_PAID: { label: 'Partially paid', variant: 'warning' },
  PAID: { label: 'Paid', variant: 'success' },
  WAIVED: { label: 'Waived', variant: 'outline' },
  CANCELLED: { label: 'Withdrawn', variant: 'outline' },
};
export const allocationStatus = (row) => STATUSES[row.status] ?? { label: row.status, variant: 'outline' };

// A Stripe link's state: still being created at Stripe, open, or closed one way or another.
export const CREATING_CHECKOUT = ['PREPARED', 'SUBMITTING', 'UNKNOWN'];
const CHECKOUT_STATUSES = {
  OPEN: { label: 'Open', variant: 'info' },
  PAID: { label: 'Paid', variant: 'success' },
  EXPIRED: { label: 'Expired', variant: 'outline' },
  FAILED: { label: 'Failed', variant: 'outline' },
  REQUIRES_REVIEW: { label: 'Needs review', variant: 'destructive' },
};
export const checkoutStatus = (row) =>
  CHECKOUT_STATUSES[row.status] ?? (CREATING_CHECKOUT.includes(row.status) ? { label: 'Awaiting Stripe', variant: 'warning' } : { label: row.status, variant: 'outline' });
export const OPEN_STATUSES = ['PENDING', 'PARTIALLY_PAID'];

// The pending list's views: open (pending or partly paid, the default), overdue, each status, or everything.
export const LIST_VIEWS = [
  { value: 'OPEN', label: 'Pending and partly paid' },
  { value: 'OVERDUE', label: 'Overdue' },
  { value: 'PENDING', label: 'Pending' },
  { value: 'PARTIALLY_PAID', label: 'Partially paid' },
  { value: 'PAID', label: 'Paid' },
  { value: 'WAIVED', label: 'Waived' },
  { value: 'CANCELLED', label: 'Withdrawn' },
  { value: 'ALL', label: 'All' },
];
/** The API's query for a list view: overdue is a flag of its own, All asks for every status. */
export function listQuery(view) {
  if (view === 'OVERDUE') return { overdue: 'true' };
  if (view === 'ALL') return {};
  return { status: view };
}

// Quota is counted in hours; a plan counts classes (1 plan class = 1 hour of quota).
export const hours = (value) => (value == null ? '—' : `${value} ${Number(value) === 1 ? 'hr' : 'hrs'}`);
export const classes = (value) => (value == null ? '—' : `${value} ${Number(value) === 1 ? 'class' : 'classes'}`);

/** A due date in words, with how overdue it is. */
export function dueLabel(row, formatDate) {
  const due = formatDate(row.due_date);
  return row.overdue ? `${due} · overdue ${row.days_overdue} ${row.days_overdue === 1 ? 'day' : 'days'}` : due;
}

/** The plan an allocation names, and its chapter for reference. */
export const planLabel = (plan) => `${plan.quote_reference} · ${plan.syllabus} · ${plan.plan_type_label}`;
export const chapterLabel = (chapter) => (chapter ? `${chapter.position}. ${chapter.name}` : 'Not chapter-specific');

/** A form's key for one request: a repeated submission is recorded once (the API's request_id). */
export function requestKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export const today = paymentToday;
