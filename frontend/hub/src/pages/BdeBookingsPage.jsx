import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { CalendarCheck, ChevronRightIcon, ClipboardCheck, SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { BOOKING_STATUSES, DEFAULT_WHEN, WHEN_FILTERS, bdeBookingsUrl } from '@/lib/bookings';
import { enquiryBookingPath, enquiryError, slotLabel, slotParts } from '@/lib/enquiries';
import { useListParams } from '@/hooks/use-list-params';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { BookingStateBadge } from '@/components/bookings/booking-badges';
import { ParentConfirmationBadge } from '@/components/communications/communication-badges';
import { DateRangeFilter } from '@/components/page/date-range-filter';
import { FilterSelect, ListToolbar, SearchField } from '@/components/page/list-toolbar';
import { EmptyState, Page, PageHeader } from '@/components/page/page';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { AccessDeniedState, ErrorState } from '@/components/page/states';

const TYPES = {
  DEMO: {
    icon: CalendarCheck,
    title: 'Demo Bookings',
    description: 'Every demo class booked for your enquiries, in Indian time (IST). Open one to act on it in its enquiry.',
    noun: 'demo classes',
  },
  DIAGNOSTIC: {
    icon: ClipboardCheck,
    title: 'Diagnostic Bookings',
    description: 'Every diagnostic test booked for your enquiries, in Indian time (IST). Open one to act on it in its enquiry.',
    noun: 'diagnostic tests',
  },
};
const PAGE_SIZE = 25;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const WHEN_VALUES = new Set(WHEN_FILTERS.map((option) => option.value));
// The date filter's choices besides its default (Upcoming, shown as the select's empty value).
const OTHER_WHENS = WHEN_FILTERS.filter((option) => option.value !== DEFAULT_WHEN);
// A Re-Demo is only ever a Demo's.
const STATUSES = {
  DEMO: BOOKING_STATUSES,
  DIAGNOSTIC: BOOKING_STATUSES.filter((option) => option.value !== 'REDEMO_REQUIRED'),
};

function Tutor({ booking }) {
  if (booking.tutor) return <span className="font-medium">{booking.tutor.full_name}</span>;
  return <span className="text-muted-foreground">{booking.status === 'BOOKED' ? 'Not assigned yet' : '—'}</span>;
}

function State({ booking }) {
  return (
    <span className="flex flex-wrap gap-1">
      <BookingStateBadge booking={booking} />
      {booking.redemo ? <Badge variant="outline">Re-Demo</Badge> : null}
    </span>
  );
}

/**
 * A BDE's Demo or Diagnostic bookings (`type`): every booking of that type
 * made for their own enquiries, as GET /api/bde/bookings/<type>/ lists them --
 * searched and filtered by status, by upcoming or past, and by date, all kept
 * in the URL (q, status, when, from, to, page). Each opens its enquiry's
 * workspace on the Bookings tab with that booking highlighted, where the BDE
 * acts on it; the workspace's way back returns to this list as it was.
 */
export default function BdeBookingsPage({ user, type }) {
  const { icon, title, description, noun } = TYPES[type];
  const statuses = STATUSES[type];
  const location = useLocation();
  const canSeeConfirmation = can(user, PERMISSIONS.viewOwnLeadCommunications);
  const { searchParams, update, clear } = useListParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const q = (searchParams.get('q') ?? '').trim();
  const status = statuses.some((option) => option.value === searchParams.get('status')) ? searchParams.get('status') : '';
  const when = WHEN_VALUES.has(searchParams.get('when')) ? searchParams.get('when') : DEFAULT_WHEN;
  const from = DATE_RE.test(searchParams.get('from') ?? '') ? searchParams.get('from') : '';
  const to = DATE_RE.test(searchParams.get('to') ?? '') ? searchParams.get('to') : '';
  const filtered = Boolean(q || status || from || to || when !== DEFAULT_WHEN);

  useEffect(() => {
    let active = true;
    setPending(true);

    const params = { page, page_size: PAGE_SIZE };
    if (q) params.q = q;
    if (status) params.status = status;
    // "All dates" is the page's own word for no date filter.
    if (when !== 'all') params.when = when;
    if (from) params.from = from;
    if (to) params.to = to;

    api
      .get(bdeBookingsUrl(type), { params })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, `Could not load your ${noun}.`));
      })
      .finally(() => {
        if (active) setPending(false);
      });

    return () => {
      active = false;
    };
  }, [type, noun, page, q, status, when, from, to, reloadKey]);

  // Each booking opens in its enquiry's workspace; its way back is this list, filters and page included.
  const opening = (booking) => ({
    to: enquiryBookingPath(booking.enquiry.id, booking.id),
    state: { from: { to: `${location.pathname}${location.search}`, label: title } },
  });

  const columns = [
    {
      key: 'when',
      header: 'Date & Time',
      className: 'whitespace-nowrap',
      cell: (booking) => {
        const at = slotParts(booking.date, booking.time);
        return (
          <>
            <p className="font-medium">{at.day}</p>
            <p className="text-muted-foreground text-xs">{at.time} IST</p>
          </>
        );
      },
    },
    {
      key: 'student',
      header: 'Student',
      cell: (booking) => (
        <>
          <p className="font-medium">{booking.enquiry.student_name}</p>
          {booking.enquiry.grade ? <p className="text-muted-foreground text-xs">{booking.enquiry.grade}</p> : null}
        </>
      ),
    },
    { key: 'parent', header: 'Parent', cell: (booking) => booking.enquiry.parent_name },
    { key: 'tutor', header: 'Tutor', cell: (booking) => <Tutor booking={booking} /> },
    { key: 'status', header: 'Status', cell: (booking) => <State booking={booking} /> },
    ...(canSeeConfirmation
      ? [
          {
            key: 'confirmation',
            header: 'Confirmation',
            cell: (booking) => <ParentConfirmationBadge status={booking.parent_confirmation} booked={booking.status === 'BOOKED'} />,
          },
        ]
      : []),
    {
      key: 'open',
      header: { srOnly: 'Open' },
      headerClassName: 'w-px',
      cell: (booking) => (
        <Button variant="outline" size="sm" asChild>
          <Link {...opening(booking)} aria-label={`View ${booking.enquiry.student_name}'s booking on ${slotLabel(booking)}`}>
            View
            <ChevronRightIcon />
          </Link>
        </Button>
      ),
    },
  ];

  const renderCard = (booking) => (
    <article className="bg-card hover:bg-muted/40 relative flex h-full flex-col gap-3 rounded-xl border p-4 transition-colors has-[a:focus-visible]:ring-[3px] has-[a:focus-visible]:ring-ring/50">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-medium">
            <Link {...opening(booking)} className="outline-none after:absolute after:inset-0 after:rounded-xl">
              {booking.enquiry.student_name}
            </Link>
          </h2>
          <p className="text-muted-foreground truncate text-sm">
            {[booking.enquiry.grade, booking.enquiry.parent_name].filter(Boolean).join(' · ')}
          </p>
        </div>
        <State booking={booking} />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div className="col-span-2 min-w-0">
          <p className="text-muted-foreground text-xs">Date & Time</p>
          <p className="truncate">{slotLabel(booking)}</p>
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Tutor</p>
          <Tutor booking={booking} />
        </div>
        {canSeeConfirmation ? (
          <div className="min-w-0">
            <p className="text-muted-foreground text-xs">Confirmation</p>
            <ParentConfirmationBadge status={booking.parent_confirmation} booked={booking.status === 'BOOKED'} />
          </div>
        ) : null}
      </div>
    </article>
  );

  let content;
  if (failure?.status === 403) {
    content = (
      <AccessDeniedState
        title={failure.code === 'NOT_A_BDE' ? 'Bookings here belong to BDE accounts.' : `You don't have access to ${noun}.`}
        message={failure.message}
      />
    );
  } else {
    const rows = data?.results ?? [];
    const total = data?.count ?? 0;
    let list;
    if (!data && !failure) {
      list = <TableSkeleton columns={6} toolbar={false} />;
    } else if (!data) {
      list = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} pending={pending} />;
    } else {
      list = (
        <>
          {failure ? <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} pending={pending} /> : null}
          {rows.length ? (
            <ResponsiveList
              label={title}
              columns={columns}
              rows={rows}
              pending={pending}
              minTableWidth={980}
              renderCard={renderCard}
            />
          ) : total > 0 ? (
            <EmptyState
              icon={SearchXIcon}
              title="Nothing on this page"
              description="This page is past the last one."
              action={
                <Button variant="outline" onClick={() => update({ page: null })}>
                  Go to the first page
                </Button>
              }
            />
          ) : filtered ? (
            <EmptyState
              icon={SearchXIcon}
              title={`No ${noun} match these filters`}
              description={
                from || to || when !== DEFAULT_WHEN
                  ? 'Try another search, status or dates, or clear the filters.'
                  : 'Try another search or status, or clear the filters.'
              }
              action={
                <Button variant="outline" onClick={clear}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={icon}
              title={`No upcoming ${noun}`}
              description={`Upcoming ${noun} booked for your enquiries appear here. Earlier ones are under All dates.`}
              action={
                <Button variant="outline" onClick={() => update({ when: 'all' })}>
                  Show all dates
                </Button>
              }
            />
          )}
          {total > 0 ? (
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              pending={pending}
              onPageChange={(next) => update({ page: String(next) })}
            />
          ) : null}
        </>
      );
    }
    content = (
      <div className="flex flex-col gap-4">
        <ListToolbar active={filtered} onClear={clear}>
          <SearchField
            value={q}
            onSearch={(text) => update({ q: text || null })}
            label="Search bookings"
            placeholder="Search student, parent or phone…"
          />
          <FilterSelect
            label="Filter by status"
            placeholder="All statuses"
            value={status}
            onChange={(value) => update({ status: value || null })}
            options={statuses}
          />
          <FilterSelect
            label="Filter by upcoming or past"
            placeholder="Upcoming"
            value={when === DEFAULT_WHEN ? '' : when}
            onChange={(value) => update({ when: value || null })}
            options={OTHER_WHENS}
          />
          <DateRangeFilter from={from} to={to} onChange={(range) => update(range)} />
        </ListToolbar>
        {list}
      </div>
    );
  }

  return (
    <Page>
      <PageHeader title={title} description={description} />
      {content}
    </Page>
  );
}
