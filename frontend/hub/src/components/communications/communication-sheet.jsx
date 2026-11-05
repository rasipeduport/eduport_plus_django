import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { BookingStateBadge } from '@/components/bookings/booking-badges';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { useBookingCommunication } from '@/hooks/use-booking-communication';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { CommunicationPanel } from './communication-panel';

/**
 * One booking's parent communication for its lead's BDE, opened from the
 * enquiry's bookings: the parent's answer, the five steps and every WhatsApp
 * message (Phase 3.1), read from GET /api/communications/bookings/<type>/<id>/
 * for holders of accounts.view_own_lead_communications, with asking for
 * confirmation and recording the answer where the API offers them (3.2,
 * CommunicationPanel; `onChanged` after either). The API serves only the
 * caller's own leads' bookings and answers any other as one that does not exist.
 */
export function BookingCommunicationSheet({ bookingType, bookingId, open, onOpenChange, reloadKey, onChanged }) {
  const state = useBookingCommunication(open ? bookingType : null, open ? bookingId : null, reloadKey);
  const booking = state.communication?.booking;
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Communication</SheetTitle>
          <SheetDescription>
            {booking ? `${booking.student_name} · ${bookingTypeLabel(booking.booking_type)} · ${slotLabel(booking.slot)}` : 'Loading…'}
          </SheetDescription>
          {booking ? (
            <div className="flex flex-wrap gap-2 pt-1">
              <BookingTypeBadge type={booking.booking_type} />
              <BookingStateBadge booking={booking} />
            </div>
          ) : null}
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
          <CommunicationPanel key={`${bookingType}-${bookingId}`} state={state} onChanged={onChanged} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
