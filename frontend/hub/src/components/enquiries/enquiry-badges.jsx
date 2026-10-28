import { Badge } from '@/components/ui/badge';
import { bookingTypeLabel, statusVariant } from '@/lib/enquiries';

/** An enquiry's status, as the API words it ("Demo booked", "New", ...). */
export function EnquiryStatusBadge({ enquiry }) {
  return <Badge variant={statusVariant(enquiry.status)}>{enquiry.status_label}</Badge>;
}

/** Demo class or diagnostic test. */
export function BookingTypeBadge({ type }) {
  return <Badge variant={type === 'DIAGNOSTIC' ? 'warning' : 'info'}>{bookingTypeLabel(type)}</Badge>;
}
