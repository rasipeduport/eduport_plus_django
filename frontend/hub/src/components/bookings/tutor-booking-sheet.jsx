import { useEffect, useState } from 'react';
import { SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { bookingError, tutorBookingUrl } from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { BookingStateBadge } from './booking-badges';

function Section({ title, children }) {
  return (
    <section className="rounded-lg border p-4">
      <h3 className="mb-1 text-sm font-semibold">{title}</h3>
      <dl className="divide-y">{children}</dl>
    </section>
  );
}

function Detail({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

/**
 * One booking the tutor is assigned to teach (GET /api/tutor/bookings/<id>/):
 * the slot in Indian time and the child it is for. Read-only, and only the
 * fields below are read -- nothing of the parent, the BDE or the assignment.
 * A booking no longer assigned to the caller is answered 404, as one that does
 * not exist.
 */
export function TutorBookingSheet({ bookingId, open, onOpenChange, reloadKey }) {
  const [booking, setBooking] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!open || !bookingId) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(tutorBookingUrl(bookingId))
      .then((response) => {
        if (active) setBooking(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load this booking.'));
      });
    return () => {
      active = false;
    };
  }, [open, bookingId, reloadKey, retryKey]);

  // Nothing of another booking shows while this one loads.
  const shown = booking && booking.id === bookingId ? booking : null;

  let body;
  if (failure && failure.status === 404) {
    body = (
      <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
        <SearchXIcon className="text-muted-foreground size-8" />
        <p className="font-medium">Booking not found</p>
        <p className="text-muted-foreground text-sm">It may no longer be assigned to you, or the link may be mistyped.</p>
      </div>
    );
  } else if (failure) {
    body = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setRetryKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  } else if (!shown) {
    body = (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-32" />
        <Skeleton className="h-40" />
      </div>
    );
  } else {
    body = (
      <div className="flex flex-col gap-4">
        {shown.status === 'CANCELLED' ? (
          <p className="bg-muted text-muted-foreground rounded-md px-3 py-2 text-sm">
            This booking was cancelled. There is no class to teach.
          </p>
        ) : null}
        <Section title="Booking">
          <Detail label="Type">{bookingTypeLabel(shown.booking_type)}</Detail>
          <Detail label="When">{slotLabel(shown.slot)}</Detail>
          <Detail label="Status">
            <BookingStateBadge booking={shown} />
          </Detail>
        </Section>

        <Section title="Student">
          <Detail label="Name">{shown.student_name}</Detail>
          <Detail label="Class">{shown.grade}</Detail>
          <Detail label="Syllabus">{shown.syllabus}</Detail>
          <Detail label="School">{shown.school_name}</Detail>
          <Detail label="Country">{shown.country}</Detail>
        </Section>
      </div>
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{shown ? shown.student_name : 'Booking'}</SheetTitle>
          <SheetDescription>{shown ? `${slotLabel(shown.slot)} · ${shown.grade || 'Class not given'}` : 'Loading…'}</SheetDescription>
          {shown ? (
            <div className="flex flex-wrap gap-2 pt-1">
              <BookingTypeBadge type={shown.booking_type} />
              <BookingStateBadge booking={shown} />
            </div>
          ) : null}
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">{body}</div>
      </SheetContent>
    </Sheet>
  );
}
