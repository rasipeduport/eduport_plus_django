import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CheckCircle2Icon, RefreshCwIcon, ShieldAlertIcon, XIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { bookingError, bookingsUrl, cancelReasonLabel, listParams, readFilters } from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { AssignTutorDialog } from '@/components/bookings/assign-tutor-dialog';
import { BookingDetailSheet } from '@/components/bookings/booking-detail-sheet';
import { BookingList } from '@/components/bookings/booking-list';
import { CancelBookingDialog } from '@/components/bookings/cancel-booking-dialog';
import { RescheduleBookingDialog } from '@/components/bookings/reschedule-booking-dialog';

const PAGE_SIZE = 25;

function AccessDenied({ failure }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
      <ShieldAlertIcon className="text-muted-foreground size-8" />
      <p className="font-medium">You don&apos;t have access to bookings.</p>
      <p className="text-muted-foreground max-w-md text-sm">{failure.message}</p>
    </div>
  );
}

/**
 * Demo and Diagnostic bookings for the Admin / Coordinator: every booking
 * parents made, one tab per type (?type=DIAGNOSTIC; Demo by default) -- each
 * type is its own list (GET /api/bookings/<demo|diagnostic>/), filtered and
 * paged by the API. A booking opens in a side sheet (?booking=<id>, of the
 * tab's type), is given its tutor in a dialog that shows who is free for the
 * slot, and may be moved to another slot or cancelled with a reason from the
 * list -- each offered only when the booking's `actions` from the API say so
 * (accounts.reschedule_booking, accounts.cancel_booking). Opens for holders of
 * accounts.view_all_bookings (lib/access); assigning needs
 * accounts.assign_booking_tutor. The API enforces both, and checks the tutor
 * again on every assignment.
 */
export default function BookingsPage({ user }) {
  const canAssign = can(user, PERMISSIONS.assignBookingTutor);
  // A tutor's permanent Meet link belongs to their account: team managers set it (backend accounts.team).
  const canEditMeetLink = can(user, PERMISSIONS.manageTeam);
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [assigning, setAssigning] = useState(null);
  const [cancelling, setCancelling] = useState(null);
  const [rescheduling, setRescheduling] = useState(null);
  const [notice, setNotice] = useState(null);

  const filters = readFilters(searchParams);
  const { q, type, status, assigned, report, from, to, when } = filters;
  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const openId = searchParams.get('booking');

  useEffect(() => {
    let active = true;
    setPending(true);
    api
      .get(bookingsUrl(type), { params: listParams({ q, status, assigned, report, from, to, when }, page, PAGE_SIZE) })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load the bookings.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [q, type, status, assigned, report, from, to, when, page, reloadKey]);

  const reload = () => setReloadKey((key) => key + 1);

  const update = (updates) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === '') params.delete(key);
      else params.set(key, value);
    }
    // Any filter change (anything but paging or the open booking) starts again at page 1.
    if (!('page' in updates) && !('booking' in updates)) params.delete('page');
    setSearchParams(params);
  };

  // After a change: say what happened, and read the list (and the open booking) again.
  const changed = (message) => {
    setNotice(message);
    reload();
  };

  const typeOf = (booking) => bookingTypeLabel(booking.booking_type).toLowerCase();

  // A move answers the replacement booking, which the sheet then shows (Q24: whether the tutor came too).
  const moved = ({ booking, tutor }) => {
    let tutorNote = '';
    if (tutor?.carried_over) tutorNote = ` ${tutor.tutor.full_name} still teaches it.`;
    else if (tutor?.tutor) tutorNote = ` ${tutor.tutor.full_name} isn't free then, so it needs a tutor.`;
    changed(`Moved ${booking.student_name}'s ${typeOf(booking)} to ${slotLabel(booking.slot)}.${tutorNote}`);
    update({ booking: booking.id });
  };

  let content;
  if (failure?.status === 403) {
    content = <AccessDenied failure={failure} />;
  } else if (!data && !failure) {
    content = <TableSkeleton columns={6} />;
  } else if (!data) {
    content = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={reload} disabled={pending}>
          Try again
        </Button>
      </div>
    );
  } else {
    content = (
      <>
        {failure ? (
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <p className="text-destructive text-sm">{failure.message}</p>
            <Button variant="outline" size="sm" onClick={reload} disabled={pending}>
              Try again
            </Button>
          </div>
        ) : null}
        <BookingList
          rows={data.results ?? []}
          total={data.count ?? 0}
          page={page}
          pageSize={PAGE_SIZE}
          filters={filters}
          pending={pending}
          canAssign={canAssign}
          onChange={update}
          onOpen={(id) => update({ booking: id })}
          onAssign={setAssigning}
        />
      </>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">Demo &amp; Diagnostic bookings</h1>
          <p className="text-muted-foreground max-w-3xl text-sm">
            Every demo class and diagnostic test parents have booked. Give each booking its own tutor: a tutor teaches
            one student at a time, so the tutor list shows who is free for the slot. Times are Indian time (IST).
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={reload} disabled={pending}>
          <RefreshCwIcon />
          Refresh
        </Button>
      </div>

      {notice ? (
        <div role="status" className="bg-success/10 text-success mb-4 flex items-start gap-2 rounded-md px-3 py-2 text-sm">
          <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" />
          <p className="flex-1">{notice}</p>
          <button type="button" onClick={() => setNotice(null)} className="shrink-0" aria-label="Dismiss">
            <XIcon className="size-4" />
          </button>
        </div>
      ) : null}

      {content}

      <BookingDetailSheet
        bookingType={type}
        bookingId={openId}
        open={Boolean(openId)}
        onOpenChange={(open) => {
          if (!open) update({ booking: null });
        }}
        canAssign={canAssign}
        canEditMeetLink={canEditMeetLink}
        reloadKey={reloadKey}
        onAssign={setAssigning}
        onChanged={(booking) => changed(`Unassigned the tutor from ${booking.student_name}'s booking.`)}
        onReschedule={setRescheduling}
        onCancel={setCancelling}
        onOpenBooking={(id) => update({ booking: id })}
      />

      <CancelBookingDialog
        booking={cancelling}
        open={Boolean(cancelling)}
        onOpenChange={(open) => {
          if (!open) setCancelling(null);
        }}
        onCancelled={(booking) =>
          changed(`Cancelled ${booking.student_name}'s ${typeOf(booking)} (${cancelReasonLabel(booking.cancel_reason_code)}).`)
        }
      />

      <RescheduleBookingDialog
        booking={rescheduling}
        open={Boolean(rescheduling)}
        onOpenChange={(open) => {
          if (!open) setRescheduling(null);
        }}
        onRescheduled={moved}
      />

      {canAssign ? (
        <AssignTutorDialog
          booking={assigning}
          open={Boolean(assigning)}
          onOpenChange={(open) => {
            if (!open) setAssigning(null);
          }}
          onAssigned={(booking) => changed(`${booking.tutor?.full_name} now teaches ${booking.student_name}'s ${typeOf(booking)}.`)}
        />
      ) : null}
    </div>
  );
}
