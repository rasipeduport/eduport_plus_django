import { useEffect, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeftIcon, RefreshCwIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { ADMIN_BOOKING_STATUSES, CLEARED_ADMIN_FILTERS, readAdminBookingFilters } from '@/lib/admin-booking-filters';
import {
  REDEMOS_URL,
  REDEMO_VIEW,
  bookingError,
  bookingPagePath,
  bookingUrl,
  bookingsUrl,
  cancelReasonLabel,
  listParams,
  readRedemoStatus,
  redemoCloseUrl,
  redemoReopenUrl,
  redemoUrl,
} from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TableSkeleton } from '@/components/table-skeleton';
import { AssignTutorDialog } from '@/components/bookings/assign-tutor-dialog';
import { AdminBookingFilters, BookingList } from '@/components/bookings/booking-list';
import { CancelBookingDialog } from '@/components/bookings/cancel-booking-dialog';
import { RedemoCloseDialog } from '@/components/bookings/redemo-close-dialog';
import { RedemoDetailSheet } from '@/components/bookings/redemo-detail-sheet';
import { RedemoList } from '@/components/bookings/redemo-list';
import { RedemoScheduleDialog } from '@/components/bookings/redemo-schedule-dialog';
import { RescheduleBookingDialog } from '@/components/bookings/reschedule-booking-dialog';
import { Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';

const PAGE_SIZE = 25;
const TYPES = {
  DEMO: {
    title: 'Demo Bookings',
    description:
      'Every demo class parents have booked, across every BDE. Give each its own tutor (the tutor list shows who is free for the slot) and schedule the Re-Demos asked for. Times are Indian time (IST).',
    noun: 'demo classes',
  },
  DIAGNOSTIC: {
    title: 'Diagnostic Bookings',
    description:
      'Every diagnostic test parents have booked, across every BDE. Give each its own tutor: the tutor list shows who is free for the slot. Times are Indian time (IST).',
    noun: 'diagnostic tests',
  },
};
// Demo Bookings' two lists: the bookings, and the Re-Demo requests (?tab=redemo).
const BOOKINGS_VIEW = 'bookings';

/** The page's title and what it is for, with Refresh on the right. */
function BookingsHeader({ type, onRefresh, pending }) {
  const { title, description } = TYPES[type];
  return (
    <PageHeader
      title={title}
      description={description}
      actions={
        <Button variant="outline" onClick={onRefresh} disabled={pending}>
          <RefreshCwIcon />
          Refresh
        </Button>
      }
    />
  );
}

/**
 * Demo Bookings' tabs: its bookings, and the Re-Demo requests. Each is a list
 * of its own, so moving between them clears the filters and the open item.
 */
function DemoTabs({ value }) {
  const [, setSearchParams] = useSearchParams();
  const show = (next) => setSearchParams(new URLSearchParams(next === REDEMO_VIEW ? { tab: REDEMO_VIEW } : {}));
  return (
    <Tabs value={value} onValueChange={show}>
      <TabsList>
        <TabsTrigger value={BOOKINGS_VIEW}>Bookings</TabsTrigger>
        <TabsTrigger value={REDEMO_VIEW}>Re-Demo requests</TabsTrigger>
      </TabsList>
    </Tabs>
  );
}

/** Where a list's load stands: the skeleton, an error with Try again, or the list (with any later error above it). */
function Loaded({ data, failure, pending, onRetry, children }) {
  if (!data && !failure) return <TableSkeleton columns={6} toolbar={false} />;
  if (!data) return <ErrorState message={failure.message} onRetry={onRetry} pending={pending} />;
  return (
    <>
      {failure ? <ErrorState message={failure.message} onRetry={onRetry} pending={pending} /> : null}
      {children}
    </>
  );
}

/** The page's URL with `updates` applied; any change but paging, the open Re-Demo request or ?schedule starts again at page 1. */
function nextParams(searchParams, updates) {
  const params = new URLSearchParams(searchParams);
  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === '') params.delete(key);
    else params.set(key, value);
  }
  if (!('page' in updates) && !('redemo' in updates) && !('schedule' in updates)) params.delete('page');
  return params;
}

/** A booking's workspace, with the list it is opened from (`back`, that list's URL) as its way back. */
function workspaceLink(type, id, back) {
  return { to: bookingPagePath(type, id), state: { from: { to: back, label: TYPES[type].title } } };
}

/**
 * The Demo or Diagnostic Bookings page (`type`) for the Admin / Coordinator:
 * the type's bookings (BookingsView) and, for Demo in its Re-Demo tab
 * (?tab=redemo), the Re-Demo requests (RedemosView). A link that opened a
 * booking on this page (?booking=<id>, from before bookings had a workspace)
 * opens its workspace instead, the list it named as the way back.
 */
export default function BookingsPage({ user, type }) {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const openId = searchParams.get('booking');
  if (openId) {
    const params = new URLSearchParams(searchParams);
    params.delete('booking');
    const { to, state } = workspaceLink(type, openId, `${location.pathname}${params.size ? `?${params}` : ''}`);
    return <Navigate to={to} replace state={state} />;
  }
  return type === 'DEMO' && searchParams.get('tab') === REDEMO_VIEW ? (
    <RedemosView user={user} />
  ) : (
    <BookingsView user={user} type={type} />
  );
}

/**
 * One type's bookings for the Admin / Coordinator: every booking of `type`
 * parents made (GET /api/bookings/<demo|diagnostic>/), filtered by class date,
 * search, status, tutor, report and schedule (lib/admin-booking-filters) and
 * paged by the API. Each booking opens in its own workspace
 * (pages/BookingWorkspacePage: /bookings/<type>/<id>), where it is moved,
 * cancelled or sent for a Re-Demo; from the list its tutor is given in a
 * dialog that shows who is free for the slot. Opens for holders of
 * accounts.view_all_bookings (lib/access); assigning needs
 * accounts.assign_booking_tutor. The API enforces both, and checks the tutor
 * again on every assignment.
 */
function BookingsView({ user, type }) {
  const canAssign = can(user, PERMISSIONS.assignBookingTutor);
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [assigning, setAssigning] = useState(null);
  const [notice, setNotice] = useState(null);

  const filters = readAdminBookingFilters(searchParams, type);
  const { page, q, status, assigned, report, from, to, when } = filters;

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

  // Any filter change (anything but paging) starts again at page 1.
  const update = (updates) => setSearchParams(nextParams(searchParams, updates));
  const clear = () => update(CLEARED_ADMIN_FILTERS);

  // After a change: say what happened, and read the list again.
  const changed = (message) => {
    setNotice(message);
    reload();
  };

  const typeOf = (booking) => bookingTypeLabel(booking.booking_type).toLowerCase();

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to bookings." message={failure.message} />;
  } else {
    content = (
      <div className="flex flex-col gap-4">
        {type === 'DEMO' ? <DemoTabs value={BOOKINGS_VIEW} /> : null}
        <AdminBookingFilters filters={filters} statuses={ADMIN_BOOKING_STATUSES[type]} onChange={update} onClear={clear} />
        <Loaded data={data} failure={failure} pending={pending} onRetry={reload}>
          <BookingList
            rows={data?.results ?? []}
            total={data?.count ?? 0}
            page={page}
            pageSize={PAGE_SIZE}
            filters={filters}
            pending={pending}
            canAssign={canAssign}
            noun={TYPES[type].noun}
            onChange={update}
            onClear={clear}
            onOpen={(id) => {
              const { to, state } = workspaceLink(type, id, `${location.pathname}${location.search}`);
              navigate(to, { state });
            }}
            onAssign={setAssigning}
          />
        </Loaded>
      </div>
    );
  }

  return (
    <Page>
      <BookingsHeader type={type} onRefresh={reload} pending={pending} />
      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}

      {content}

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
    </Page>
  );
}

/**
 * Demo Bookings' Re-Demo tab (?tab=redemo): every Re-Demo request in the
 * API's order -- an administrator's steps first -- (GET /api/bookings/redemos/),
 * filtered by status chip (?status=), search (?q=), the lead's BDE (?owner=),
 * the dates requested (?from=, ?to=) and one student (?lead=, how a booking's
 * workspace opens its request), and paged by the API. A request opens in a
 * side sheet (?redemo=<id>, its row highlighted) with everything about it and
 * what may be done with it now: Schedule Re-Demo (a dialog of the time and
 * the tutor free then, or the tutor and their times, on the student's own
 * clock beside IST, and remarks for them, which books it at once; ?schedule=1
 * opens it straight away), close or reopen the request, and reschedule,
 * change the tutor of or cancel the Re-Demo booked for it -- each Demo also
 * opening in its own workspace. Arriving from a workspace
 * (location.state.from), the page leads back to it. Nothing is sent to the
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
  const [closing, setClosing] = useState(null);
  // The request the close / reopen dialog was last opened for: kept while it animates closed, so it never
  // turns into the other dialog on its way out.
  const [lastClosing, setLastClosing] = useState(null);
  const [acting, setActing] = useState(null);
  const [notice, setNotice] = useState(null);

  const navigate = useNavigate();
  const location = useLocation();
  const back = location.state?.from ?? null;
  const filters = readRedemoFilters(searchParams);
  const { q, status, owner, from, to, lead, page } = filters;
  const openId = searchParams.get('redemo');
  const scheduleNow = searchParams.get('schedule') === '1';

  useEffect(() => {
    let active = true;
    setPending(true);
    const params = { page, page_size: PAGE_SIZE };
    for (const [name, value] of Object.entries({ q, status, owner, from, to, lead })) if (value) params[name] = value;
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
  }, [q, status, owner, from, to, lead, page, reloadKey]);

  // A link that asks to schedule (?schedule=1, Request Re-Demo's "Schedule now") opens the dialog once the request is read.
  useEffect(() => {
    if (!scheduleNow || !openId || !canSchedule) return undefined;
    let active = true;
    api
      .get(redemoUrl(openId))
      .then((response) => {
        if (active && response.data.actions?.schedule) setScheduling(response.data);
      })
      .catch(() => {})
      .finally(() => {
        // From the URL as it is by then: whatever the administrator changed meanwhile stays.
        if (!active) return;
        setSearchParams(
          (current) => {
            const params = new URLSearchParams(current);
            params.delete('schedule');
            return params;
          },
          { replace: true, state: location.state }
        );
      });
    return () => {
      active = false;
    };
    // Only when a link asks for it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scheduleNow, openId, canSchedule]);

  const reload = () => setReloadKey((key) => key + 1);
  // Filters change the URL; the way back to a workspace stays with it.
  const update = (updates) => setSearchParams(nextParams(searchParams, updates), { state: location.state });
  const changed = (message) => {
    setNotice(message);
    reload();
  };
  const leadLabel = lead ? (data?.results?.[0]?.student_name ?? null) : null;
  const openClosing = (next) => {
    setClosing(next);
    setLastClosing(next);
  };
  const shownClosing = closing ?? lastClosing;
  // Scheduling straight from a list row: the request read in full first, so its remarks are shown -- and kept.
  const scheduleRow = (row) => {
    update({ redemo: row.id });
    api
      .get(redemoUrl(row.id))
      .then((response) => {
        if (response.data.actions?.schedule) setScheduling(response.data);
      })
      .catch((err) => setNotice(bookingError(err, 'Could not load this Re-Demo request.').message));
  };

  // A Re-Demo booked for the request: its full booking for the dialog that changes it.
  const actOn = (action, bookingId) => {
    api
      .get(bookingUrl('DEMO', bookingId))
      .then((response) => setActing({ action, booking: response.data }))
      .catch((err) => setNotice(bookingError(err, 'Could not load the Re-Demo booking.').message));
  };
  const closeActing = (open) => {
    if (!open) setActing(null);
  };

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to bookings." message={failure.message} />;
  } else {
    content = (
      <div className="flex flex-col gap-4">
        <DemoTabs value={REDEMO_VIEW} />
        <Loaded data={data} failure={failure} pending={pending} onRetry={reload}>
          <RedemoList
            rows={data?.results ?? []}
            total={data?.count ?? 0}
            page={page}
            pageSize={PAGE_SIZE}
            filters={{ ...filters, leadLabel }}
            counts={data?.counts}
            owners={data?.owners}
            pending={pending}
            canSchedule={canSchedule}
            highlightedId={openId}
            onChange={update}
            onOpen={(id) => update({ redemo: id })}
            onSchedule={scheduleRow}
          />
        </Loaded>
      </div>
    );
  }

  return (
    <Page>
      {back ? (
        <Button variant="ghost" size="sm" className="text-muted-foreground -ml-2 self-start" asChild>
          <Link to={back.to}>
            <ArrowLeftIcon className="size-4" />
            {back.label}
          </Link>
        </Button>
      ) : null}
      <BookingsHeader type="DEMO" onRefresh={reload} pending={pending} />
      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}

      {content}

      <RedemoDetailSheet
        redemoId={openId}
        open={Boolean(openId)}
        onOpenChange={(open) => {
          if (!open) update({ redemo: null });
        }}
        reloadKey={reloadKey}
        onSchedule={setScheduling}
        onClose={(redemo) => openClosing({ mode: 'close', redemo })}
        onReopen={(redemo) => openClosing({ mode: 'reopen', redemo })}
        onBookingAction={actOn}
        // A Demo of the chain opens in its own workspace, with its own report; back comes here, as filtered.
        onOpenBooking={(id) =>
          navigate(bookingPagePath('DEMO', id), {
            state: { from: { to: `${location.pathname}${location.search}`, label: 'Re-Demo requests' } },
          })
        }
        onOpenRedemo={(id) => update({ redemo: id })}
      />

      {canSchedule ? (
        <RedemoScheduleDialog
          redemo={scheduling}
          open={Boolean(scheduling)}
          onOpenChange={(open) => {
            if (!open) setScheduling(null);
          }}
          onScheduled={(redemo) =>
            changed(
              `${redemo.student_name}'s Re-Demo is booked with ${redemo.tutor?.full_name} on ${slotLabel(redemo.booking?.slot)}. The BDE tells the parent.`
            )
          }
        />
      ) : null}

      <RedemoCloseDialog
        mode={shownClosing?.mode}
        subject={
          shownClosing
            ? `${shownClosing.redemo.student_name} · Re-Demo of the Demo on ${slotLabel(shownClosing.redemo.original?.slot)}`
            : null
        }
        open={Boolean(closing)}
        onOpenChange={(open) => {
          if (!open) setClosing(null);
        }}
        url={shownClosing ? (shownClosing.mode === 'close' ? redemoCloseUrl : redemoReopenUrl)(shownClosing.redemo.id) : ''}
        // Refused (booked or closed meanwhile): read the list and the request again, as they are now.
        onRefused={reload}
        onDone={(redemo) =>
          changed(
            redemo.status === 'CLOSED'
              ? `Closed ${redemo.student_name}'s Re-Demo request (${redemo.closed?.reason?.label}). Its Demo reads Completed again.`
              : `Reopened ${redemo.student_name}'s Re-Demo request. It is waiting to be scheduled.`
          )
        }
      />

      <RescheduleBookingDialog
        booking={acting?.action === 'reschedule' ? acting.booking : null}
        open={acting?.action === 'reschedule'}
        onOpenChange={closeActing}
        onRescheduled={({ booking: replacement }) =>
          changed(`Moved ${replacement.student_name}'s Re-Demo to ${slotLabel(replacement.slot)}.`)
        }
      />
      {canSchedule ? (
        <AssignTutorDialog
          booking={acting?.action === 'change_tutor' ? acting.booking : null}
          open={acting?.action === 'change_tutor'}
          onOpenChange={closeActing}
          onAssigned={(updated) => changed(`${updated.tutor?.full_name} now teaches ${updated.student_name}'s Re-Demo.`)}
        />
      ) : null}
      <CancelBookingDialog
        booking={acting?.action === 'cancel' ? acting.booking : null}
        open={acting?.action === 'cancel'}
        onOpenChange={closeActing}
        onCancelled={(updated) =>
          changed(
            `Cancelled ${updated.student_name}'s Re-Demo (${cancelReasonLabel(updated.cancel_reason_code)}). The request waits to be scheduled again.`
          )
        }
      />
    </Page>
  );
}

/** Whether `value` is a real YYYY-MM-DD date (not 2026-02-31). */
function isDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value ?? '')) return false;
  const day = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(day.getTime()) && day.toISOString().slice(0, 10) === value;
}

/**
 * The Re-Demo tab's filters from its URL; a value the API would refuse is
 * dropped -- an impossible date, and a range that ends before it begins
 * keeps its start -- so a hand-edited link shows a list, never an error.
 */
function readRedemoFilters(searchParams) {
  const date = (name) => (isDate(searchParams.get(name)) ? searchParams.get(name) : '');
  const id = (name) => (/^[0-9a-f-]{36}$/i.test(searchParams.get(name) ?? '') ? searchParams.get(name) : '');
  const owner = searchParams.get('owner') === 'none' ? 'none' : id('owner');
  const from = date('from');
  const to = date('to');
  return {
    q: (searchParams.get('q') ?? '').trim(),
    status: readRedemoStatus(searchParams.get('status')),
    owner,
    from,
    to: from && to && to < from ? '' : to,
    lead: id('lead'),
    page: Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1),
  };
}
