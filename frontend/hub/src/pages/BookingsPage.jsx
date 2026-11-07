import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CheckCircle2Icon, RefreshCwIcon, ShieldAlertIcon, XIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import {
  CLEARED_FILTERS,
  REDEMOS_URL,
  REDEMO_TAB,
  bookingError,
  bookingRedemoUrl,
  bookingsUrl,
  cancelReasonLabel,
  listParams,
  readFilters,
  readRedemoStatus,
} from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { AssignTutorDialog } from '@/components/bookings/assign-tutor-dialog';
import { BookingDetailSheet } from '@/components/bookings/booking-detail-sheet';
import { BookingList } from '@/components/bookings/booking-list';
import { CancelBookingDialog } from '@/components/bookings/cancel-booking-dialog';
import { RedemoDetailSheet } from '@/components/bookings/redemo-detail-sheet';
import { RedemoList } from '@/components/bookings/redemo-list';
import { RedemoScheduleDialog } from '@/components/bookings/redemo-schedule-dialog';
import { RequestRedemoDialog } from '@/components/bookings/request-redemo-dialog';
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

function PageHeader({ onRefresh, pending }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold">Demo &amp; Diagnostic bookings</h1>
        <p className="text-muted-foreground max-w-3xl text-sm">
          Every demo class and diagnostic test parents have booked. Give each booking its own tutor: a tutor teaches
          one student at a time, so the tutor list shows who is free for the slot. Times are Indian time (IST).
        </p>
      </div>
      <Button variant="ghost" size="sm" onClick={onRefresh} disabled={pending}>
        <RefreshCwIcon />
        Refresh
      </Button>
    </div>
  );
}

function Notice({ notice, onDismiss }) {
  if (!notice) return null;
  return (
    <div role="status" className="bg-success/10 text-success mb-4 flex items-start gap-2 rounded-md px-3 py-2 text-sm">
      <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" />
      <p className="flex-1">{notice}</p>
      <button type="button" onClick={onDismiss} className="shrink-0" aria-label="Dismiss">
        <XIcon className="size-4" />
      </button>
    </div>
  );
}

/** The page's URL with `updates` applied; any change but paging or the open item starts again at page 1. */
function nextParams(searchParams, updates) {
  const params = new URLSearchParams(searchParams);
  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === '') params.delete(key);
    else params.set(key, value);
  }
  if (!('page' in updates) && !('booking' in updates) && !('redemo' in updates)) params.delete('page');
  return params;
}

/**
 * The Bookings page for the Admin / Coordinator: the Demo and Diagnostic
 * bookings (BookingsView) and, in the Re-Demo tab (?type=REDEMO), the Re-Demo
 * requests (RedemosView).
 */
export default function BookingsPage({ user }) {
  const [searchParams] = useSearchParams();
  return searchParams.get('type') === REDEMO_TAB ? <RedemosView user={user} /> : <BookingsView user={user} />;
}

/**
 * Demo and Diagnostic bookings for the Admin / Coordinator: every booking
 * parents made, one tab per type (?type=DIAGNOSTIC; Demo by default) -- each
 * type is its own list (GET /api/bookings/<demo|diagnostic>/), filtered and
 * paged by the API. A completed Demo may be sent for a Re-Demo from its sheet
 * (actions.request_redemo, a reason required and shown back first), which the
 * Re-Demo tab then lists. A booking opens in a side sheet (?booking=<id>, of the
 * tab's type), is given its tutor in a dialog that shows who is free for the
 * slot, and may be moved to another slot or cancelled with a reason from the
 * list -- each offered only when the booking's `actions` from the API say so
 * (accounts.reschedule_booking, accounts.cancel_booking). Opens for holders of
 * accounts.view_all_bookings (lib/access); assigning needs
 * accounts.assign_booking_tutor. The API enforces both, and checks the tutor
 * again on every assignment.
 */
function BookingsView({ user }) {
  const canAssign = can(user, PERMISSIONS.assignBookingTutor);
  // A tutor's permanent Meet link belongs to their account: team managers set it (backend accounts.team).
  const canEditMeetLink = can(user, PERMISSIONS.manageTeam);
  // Each booking's parent communication, in its sheet (Phase 3.1).
  const canViewCommunication = can(user, PERMISSIONS.viewAllCommunications);
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [assigning, setAssigning] = useState(null);
  const [cancelling, setCancelling] = useState(null);
  const [rescheduling, setRescheduling] = useState(null);
  const [requestingRedemo, setRequestingRedemo] = useState(null);
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

  // Any filter change (anything but paging or the open booking) starts again at page 1.
  const update = (updates) => setSearchParams(nextParams(searchParams, updates));

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
      <PageHeader onRefresh={reload} pending={pending} />
      <Notice notice={notice} onDismiss={() => setNotice(null)} />

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
        canViewCommunication={canViewCommunication}
        reloadKey={reloadKey}
        // The parent's answer may cancel the booking: the list, the booking and its timeline are read again.
        onCommunicationChanged={() => setReloadKey((key) => key + 1)}
        onAssign={setAssigning}
        onChanged={(booking) => changed(`Unassigned the tutor from ${booking.student_name}'s booking.`)}
        onReschedule={setRescheduling}
        onCancel={setCancelling}
        onOpenBooking={(id) => update({ booking: id })}
        onRequestRedemo={setRequestingRedemo}
        onOpenRedemo={(id) => update({ ...CLEARED_FILTERS, type: REDEMO_TAB, booking: null, redemo: id })}
      />

      <RequestRedemoDialog
        booking={requestingRedemo}
        open={Boolean(requestingRedemo)}
        onOpenChange={(open) => {
          if (!open) setRequestingRedemo(null);
        }}
        requestUrl={requestingRedemo ? bookingRedemoUrl(requestingRedemo.booking_type, requestingRedemo.id) : ''}
        onRequested={() =>
          changed(
            `Asked for a Re-Demo of ${requestingRedemo.student_name}'s demo. It is now Re-Demo required; schedule it in the Re-Demo tab.`
          )
        }
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

/**
 * The Re-Demo tab (?type=REDEMO): every Re-Demo request, newest first
 * (GET /api/bookings/redemos/), searched (?q=), filtered by where it stands
 * (?status=) and paged by the API. A request opens in a side sheet
 * (?redemo=<id>) with its original Demo, its reason and the Re-Demo
 * scheduled for it -- each Demo opening in the Demo tab with its own report
 * -- and, for holders of accounts.assign_booking_tutor, Schedule Re-Demo (a
 * dialog of the tutor, the date and time they are free, and remarks for
 * them, which books it at once) and those remarks. Nothing is sent to the
 * parent: the BDE tells them the time.
 */
function RedemosView({ user }) {
  const canSchedule = can(user, PERMISSIONS.assignBookingTutor);
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [scheduling, setScheduling] = useState(null);
  const [notice, setNotice] = useState(null);

  const q = (searchParams.get('q') ?? '').trim();
  const status = readRedemoStatus(searchParams.get('status'));
  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const openId = searchParams.get('redemo');

  useEffect(() => {
    let active = true;
    setPending(true);
    const params = { page, page_size: PAGE_SIZE };
    if (q) params.q = q;
    if (status) params.status = status;
    api
      .get(REDEMOS_URL, { params })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load the Re-Demo requests.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [q, status, page, reloadKey]);

  const reload = () => setReloadKey((key) => key + 1);
  const update = (updates) => setSearchParams(nextParams(searchParams, updates));

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
        <RedemoList
          rows={data.results ?? []}
          total={data.count ?? 0}
          page={page}
          pageSize={PAGE_SIZE}
          filters={{ q, status }}
          pending={pending}
          onChange={update}
          onOpen={(id) => update({ redemo: id })}
        />
      </>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      <PageHeader onRefresh={reload} pending={pending} />
      <Notice notice={notice} onDismiss={() => setNotice(null)} />

      {content}

      <RedemoDetailSheet
        redemoId={openId}
        open={Boolean(openId)}
        onOpenChange={(open) => {
          if (!open) update({ redemo: null });
        }}
        reloadKey={reloadKey}
        onSchedule={setScheduling}
        // A Demo of the chain opens in the Demo tab, with its own report.
        onOpenBooking={(id) => update({ ...CLEARED_FILTERS, type: null, redemo: null, booking: id })}
        onOpenRedemo={(id) => update({ redemo: id })}
      />

      {canSchedule ? (
        <RedemoScheduleDialog
          redemo={scheduling}
          open={Boolean(scheduling)}
          onOpenChange={(open) => {
            if (!open) setScheduling(null);
          }}
          onScheduled={(redemo) => {
            setNotice(
              `${redemo.student_name}'s Re-Demo is booked with ${redemo.tutor?.full_name} on ${slotLabel(redemo.booking?.slot)}. The BDE tells the parent.`
            );
            reload();
          }}
        />
      ) : null}
    </div>
  );
}
