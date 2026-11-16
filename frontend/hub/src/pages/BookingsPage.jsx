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
  bookingsUrl,
  listParams,
  readRedemoStatus,
  redemoPagePath,
} from '@/lib/bookings';
import { bookingTypeLabel } from '@/lib/enquiries';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TableSkeleton } from '@/components/table-skeleton';
import { AssignTutorDialog } from '@/components/bookings/assign-tutor-dialog';
import { AdminBookingFilters, BookingList } from '@/components/bookings/booking-list';
import { RedemoList } from '@/components/bookings/redemo-list';
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

/** The page's URL with `updates` applied; any change but paging starts again at page 1. */
function nextParams(searchParams, updates) {
  const params = new URLSearchParams(searchParams);
  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === '') params.delete(key);
    else params.set(key, value);
  }
  if (!('page' in updates)) params.delete('page');
  return params;
}

/** The way back from a Re-Demo request's workspace: the Re-Demo list at `pathname` with `params` as filtered, the request highlighted. */
function redemoBack(pathname, params, id) {
  const next = new URLSearchParams(params);
  next.set('highlight', id);
  return { to: `${pathname}?${next}`, label: 'Re-Demo requests' };
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
 * opens its workspace instead, the list it named as the way back; so does
 * one that opened a Re-Demo request in the former side sheet (?redemo=<id>,
 * ?schedule=1 on its Scheduling tab), back to the list with it highlighted.
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
  const redemoId = type === 'DEMO' ? searchParams.get('redemo') : null;
  if (redemoId) {
    const params = new URLSearchParams(searchParams);
    const schedule = params.get('schedule') === '1';
    params.delete('redemo');
    params.delete('schedule');
    params.set('tab', REDEMO_VIEW);
    const to = redemoPagePath(redemoId, schedule ? 'scheduling' : '');
    return <Navigate to={to} replace state={{ from: redemoBack(location.pathname, params, redemoId) }} />;
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
 * workspace lists its requests), and paged by the API. A request opens in its
 * own workspace (pages/RedemoWorkspacePage) -- Schedule straight onto its
 * Scheduling tab -- with this list, as filtered and the request highlighted
 * (?highlight=<id>), as its way back. Arriving from a workspace
 * (location.state.from), the page leads back to it.
 */
function RedemosView({ user }) {
  const canSchedule = can(user, PERMISSIONS.assignBookingTutor);
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const navigate = useNavigate();
  const location = useLocation();
  const back = location.state?.from ?? null;
  const filters = readRedemoFilters(searchParams);
  const { q, status, owner, from, to, lead, page } = filters;
  const highlightedId = searchParams.get('highlight');

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

  const reload = () => setReloadKey((key) => key + 1);
  // Filters change the URL; the way back to a workspace stays with it.
  const update = (updates) => setSearchParams(nextParams(searchParams, updates), { state: location.state });
  const leadLabel = lead ? (data?.results?.[0]?.student_name ?? null) : null;
  // A request in its workspace (`tab`: the one it opens on), back to this list as it is now.
  const openRequest = (id, tab = '') =>
    navigate(redemoPagePath(id, tab), { state: { from: redemoBack(location.pathname, searchParams, id) } });

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
            highlightedId={highlightedId}
            onChange={update}
            onOpen={(id) => openRequest(id)}
            onSchedule={(row) => openRequest(row.id, 'scheduling')}
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

      {content}
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
