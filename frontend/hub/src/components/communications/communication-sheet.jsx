import { CalendarClockIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { BookingStateBadge } from '@/components/bookings/booking-badges';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { useBookingCommunication } from '@/hooks/use-booking-communication';
import { slotLabel } from '@/lib/enquiries';
import { CommunicationPanel } from './communication-panel';
import { CommunicationWorkspace } from './communication-workspace';

/** A booking's id as the header shows it: its first eight characters, upper-cased -- the whole id on hover. */
const shortId = (id) => String(id).slice(0, 8).toUpperCase();

/**
 * One booking's parent communication for its lead's BDE, opened from the
 * enquiry's bookings: the parent's answer, the five steps and every WhatsApp
 * message (Phase 3.1), read from GET /api/communications/bookings/<type>/<id>/
 * for holders of accounts.view_own_lead_communications, with asking for
 * confirmation and recording the answer where the API offers them (3.2,
 * CommunicationPanel; `onChanged` after either). A wide side sheet: the
 * booking in its header, then CommunicationWorkspace. The API serves only the
 * caller's own leads' bookings and answers any other as one that does not exist.
 */
export function BookingCommunicationSheet({ bookingType, bookingId, open, onOpenChange, reloadKey, onChanged }) {
  const state = useBookingCommunication(open ? bookingType : null, open ? bookingId : null, reloadKey);
  const booking = state.communication?.booking;
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" showCloseButton={false} className="w-full gap-0 sm:w-11/12 sm:max-w-2xl lg:max-w-5xl">
        <SheetHeader className="gap-1 border-b py-4 pr-16 pl-4 sm:pl-6">
          <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">Communication</p>
          <SheetTitle className="text-lg leading-snug">{booking ? booking.student_name : 'Booking communication'}</SheetTitle>
          <SheetDescription asChild>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-1">
              {booking ? (
                <>
                  <BookingTypeBadge type={booking.booking_type} />
                  <span className="text-foreground inline-flex items-center gap-1.5">
                    <CalendarClockIcon className="text-muted-foreground size-4" aria-hidden="true" />
                    {slotLabel(booking.slot)}
                  </span>
                  <BookingStateBadge booking={booking} />
                  <span title={booking.id}>
                    Booking ID <span className="text-foreground font-mono text-xs">{shortId(booking.id)}</span>
                  </span>
                </>
              ) : state.failure ? null : (
                'Loading…'
              )}
            </div>
          </SheetDescription>
          <SheetClose asChild>
            <Button variant="ghost" size="icon" className="absolute top-3 right-3" aria-label="Close">
              <XIcon />
            </Button>
          </SheetClose>
        </SheetHeader>
        <CommunicationPanel key={`${bookingType}-${bookingId}`} state={state} onChanged={onChanged}>
          {(panel) => <CommunicationWorkspace {...panel} />}
        </CommunicationPanel>
      </SheetContent>
    </Sheet>
  );
}
