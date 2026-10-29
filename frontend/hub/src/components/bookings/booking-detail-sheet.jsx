import { useEffect, useState } from 'react';
import { SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { bookingError, bookingTutorUrl, bookingUrl, referralLabel, tutorChangeable } from '@/lib/bookings';
import { bookingTypeLabel, formatDay, slotLabel, sourceLabel } from '@/lib/enquiries';
import { BookingStateBadge, TutorName } from './booking-badges';

function Section({ title, action, children }) {
  return (
    <section className="rounded-lg border p-4">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {action}
      </div>
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

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <Skeleton className="h-32" />
      <Skeleton className="h-40" />
      <Skeleton className="h-32" />
    </div>
  );
}

/**
 * One booking in full (GET /api/bookings/<id>/): its tutor first -- with
 * Assign / Change and Unassign for holders of accounts.assign_booking_tutor
 * while the booking is booked and its slot has not started -- then the slot,
 * the child, the parent and any cancellation. Only what the API returns is
 * shown. Assigning opens the page's tutor dialog (`onAssign`); unassigning
 * happens here, confirmed first (DELETE /api/bookings/<id>/tutor/).
 */
export function BookingDetailSheet({ bookingId, open, onOpenChange, canAssign, reloadKey, onAssign, onChanged }) {
  const [booking, setBooking] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  const [unassignOpen, setUnassignOpen] = useState(false);
  const [unassignError, setUnassignError] = useState(null);
  const [unassigning, setUnassigning] = useState(false);

  useEffect(() => {
    if (!open || !bookingId) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(bookingUrl(bookingId))
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

  async function unassign() {
    setUnassigning(true);
    setUnassignError(null);
    try {
      const response = await api.delete(bookingTutorUrl(bookingId));
      setBooking(response.data);
      setUnassignOpen(false);
      onChanged?.(response.data);
    } catch (err) {
      setUnassignError(bookingError(err, 'Could not unassign the tutor.').message);
    } finally {
      setUnassigning(false);
    }
  }

  let body;
  if (failure && failure.status === 404) {
    body = (
      <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
        <SearchXIcon className="text-muted-foreground size-8" />
        <p className="font-medium">Booking not found</p>
        <p className="text-muted-foreground text-sm">It may be a mistyped link.</p>
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
    body = <DetailSkeleton />;
  } else {
    const changeable = canAssign && tutorChangeable(shown);
    const lead = shown.lead ?? {};
    body = (
      <div className="flex flex-col gap-4">
        <Section
          title="Tutor"
          action={
            changeable ? (
              <div className="flex gap-2">
                {shown.tutor ? (
                  <Button variant="outline" size="sm" onClick={() => setUnassignOpen(true)}>
                    Unassign
                  </Button>
                ) : null}
                <Button size="sm" onClick={() => onAssign(shown)}>
                  {shown.tutor ? 'Change tutor' : 'Assign tutor'}
                </Button>
              </div>
            ) : null
          }
        >
          <Detail label="Teaching">
            <TutorName booking={shown} />
          </Detail>
          {shown.tutor ? (
            <>
              <Detail label="Assigned by">{shown.tutor_assigned_by?.full_name}</Detail>
              <Detail label="Assigned on">{formatDay(shown.tutor_assigned_at)}</Detail>
            </>
          ) : null}
          {!tutorChangeable(shown) && shown.tutor_change_refusal ? (
            <p className="text-muted-foreground pt-2 text-xs">{shown.tutor_change_refusal.message}</p>
          ) : null}
        </Section>

        <Section title="Booking">
          <Detail label="Type">{bookingTypeLabel(shown.booking_type)}</Detail>
          <Detail label="When">{slotLabel(shown.slot)}</Detail>
          <Detail label="Seat">{shown.seat ? String(shown.seat) : null}</Detail>
          <Detail label="Booked on">{formatDay(shown.booked_at)}</Detail>
          <Detail label="Came in">{referralLabel(shown.referral_status)}</Detail>
          <Detail label="Credited BDE">{shown.bde?.full_name}</Detail>
        </Section>

        <Section title="Student">
          <Detail label="Name">{shown.student_name}</Detail>
          <Detail label="Class">{shown.grade}</Detail>
          <Detail label="School">{lead.school_name}</Detail>
          <Detail label="Syllabus">{lead.syllabus}</Detail>
          <Detail label="Country">{lead.country}</Detail>
        </Section>

        <Section title="Parent">
          <Detail label="Name">{shown.parent_name}</Detail>
          <Detail label="Phone">
            <span className="tabular-nums">{shown.phone}</span>
          </Detail>
          <Detail label="Enquiry source">{sourceLabel(lead.source)}</Detail>
          <Detail label="Enquiry BDE">{lead.owner_bde?.full_name}</Detail>
        </Section>

        {shown.status === 'CANCELLED' ? (
          <Section title="Cancellation">
            <Detail label="Cancelled on">{formatDay(shown.cancelled_at)}</Detail>
            <Detail label="By">{shown.cancelled_by?.full_name}</Detail>
            <Detail label="Reason">{shown.cancel_reason}</Detail>
          </Section>
        ) : null}
      </div>
    );
  }

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="w-full sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>{shown ? shown.student_name : 'Booking'}</SheetTitle>
            <SheetDescription>{shown ? `${slotLabel(shown.slot)} · ${shown.grade || 'Class not given'}` : 'Loading…'}</SheetDescription>
            {shown ? (
              <div className="flex flex-wrap gap-2 pt-1">
                <BookingTypeBadge type={shown.booking_type} />
                <BookingStateBadge booking={shown} />
                {!shown.tutor && shown.status === 'BOOKED' && !shown.slot?.ended ? (
                  <Badge variant="warning">Needs a tutor</Badge>
                ) : null}
              </div>
            ) : null}
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">{body}</div>
        </SheetContent>
      </Sheet>

      <FormDialog
        open={unassignOpen}
        onOpenChange={(next) => {
          setUnassignOpen(next);
          if (!next) setUnassignError(null);
        }}
        title="Unassign tutor"
        description={
          shown?.tutor
            ? `${shown.tutor.full_name} will no longer teach ${shown.student_name}'s booking. You can assign a tutor again later.`
            : null
        }
        error={unassignError}
        onConfirm={unassign}
        confirmLabel="Unassign"
        pendingLabel="Unassigning…"
        confirmVariant="destructive"
        pending={unassigning}
      />
    </>
  );
}
