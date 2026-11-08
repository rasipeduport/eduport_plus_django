import { useEffect, useState } from 'react';
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { RefreshCwIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { ADMIN_BOOKING_STATUSES, CLEARED_ADMIN_FILTERS, readAdminBookingFilters } from '@/lib/admin-booking-filters';
import {
  REDEMOS_URL,
  REDEMO_VIEW,
  bookingError,
  bookingPagePath,
  bookingsUrl,
  listParams,
  readRedemoStatus,
} from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TableSkeleton } from '@/components/table-skeleton';
import { AssignTutorDialog } from '@/components/bookings/assign-tutor-dialog';
import { AdminBookingFilters, BookingList } from '@/components/bookings/booking-list';
import { RedemoDetailSheet } from '@/components/bookings/redemo-detail-sheet';
import { RedemoList } from '@/components/bookings/redemo-list';
import { RedemoScheduleDialog } from '@/components/bookings/redemo-schedule-dialog';
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

/** The page's URL with `updates` applied; any change but paging or the open Re-Demo request starts again at page 1. */
function nextParams(searchParams, updates) {
  const params = new URLSearchParams(searchParams);
  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === '') params.delete(key);
    else params.set(key, value);
  }
  if (!('page' in updates) && !('redemo' in updates)) params.delete('page');
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
 * Demo Bookings' Re-Demo tab (?tab=redemo): every Re-Demo request, newest first
 * (GET /api/bookings/redemos/), searched (?q=), filtered by where it stands
 * (?status=) and paged by the API. A request opens in a side sheet
 * (?redemo=<id>) with its original Demo, its reason and the Re-Demo
 * scheduled for it -- each Demo opening in its own workspace with its report
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

  const navigate = useNavigate();
  const location = useLocation();
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
            filters={{ q, status }}
            pending={pending}
            onChange={update}
            onOpen={(id) => update({ redemo: id })}
          />
        </Loaded>
      </div>
    );
  }

  return (
    <Page>
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
        // A Demo of the chain opens in its own workspace, with its own report.
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
          onScheduled={(redemo) => {
            setNotice(
              `${redemo.student_name}'s Re-Demo is booked with ${redemo.tutor?.full_name} on ${slotLabel(redemo.booking?.slot)}. The BDE tells the parent.`
            );
            reload();
          }}
        />
      ) : null}
    </Page>
  );
}
