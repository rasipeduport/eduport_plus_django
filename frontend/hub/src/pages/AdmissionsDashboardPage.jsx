import { useEffect, useId, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  CalendarCheck,
  CalendarDays,
  CalendarOff,
  ChevronRight,
  ClipboardCheck,
  FileWarning,
  Funnel,
  Hourglass,
  Inbox,
  ListTodo,
  RefreshCwIcon,
  RotateCcw,
  UserPlus,
  UserRoundX,
  Users,
} from 'lucide-react';

import api from '@/lib/api';
import {
  ADMISSIONS_DASHBOARD_URL,
  DEFAULT_RANGE,
  RANGE_OPTIONS,
  bookingsInRangePath,
  bookingsListPath,
  busierType,
  leadsPath,
  readRange,
  todaysBookingPath,
  totalOf,
} from '@/lib/admissions';
import { rangeLabel } from '@/lib/date-range';
import { enquiryError, slotParts } from '@/lib/enquiries';
import { cn, getInitials } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tile } from '@/components/dashboard/kpi-cards';
import { Panel, PanelEmpty, ScrollList } from '@/components/dashboard/dashboard-primitives';
import { RecentActivity } from '@/components/dashboard/recent-activity';
import { BookingTypeBadge, EnquiryStatusBadge } from '@/components/enquiries/enquiry-badges';
import { BookingStateBadge, TutorName } from '@/components/bookings/booking-badges';
import { DatePresets } from '@/components/page/date-presets';
import { Page, PageHeader } from '@/components/page/page';
import { ResponsiveList } from '@/components/page/responsive-list';
import { AccessDeniedState, ErrorState } from '@/components/page/states';

const plural = (count, one, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
const percent = (part, whole) => (whole > 0 ? Math.round((part / whole) * 100) : 0);

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-5">
        <Skeleton className="h-72 rounded-xl xl:col-span-3" />
        <Skeleton className="h-72 rounded-xl xl:col-span-2" />
      </div>
      <Skeleton className="h-56 rounded-xl" />
    </div>
  );
}

/** The span the dashboard counts: a preset, or a Custom range on a calendar. */
function RangeFilter({ range, onChange }) {
  const labelId = useId();
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:items-end">
      <span id={labelId} className="sr-only">
        Dates to count
      </span>
      <DatePresets
        options={RANGE_OPTIONS}
        value={range.range}
        from={range.from}
        to={range.to}
        anyLabel="Last 7 days"
        labelledBy={labelId}
        onPick={(preset) => onChange({ range: preset === DEFAULT_RANGE ? null : preset, from: null, to: null })}
        onCustom={(picked) =>
          onChange(picked.from ? { range: 'custom', ...picked } : { range: null, from: null, to: null })
        }
      />
      <p className="text-muted-foreground text-xs" aria-live="polite">
        {rangeLabel(range.from, range.to, '')} · Indian dates (IST)
      </p>
    </div>
  );
}

// Where five tiles share a row (xl) the longer labels take two lines: each label
// gets room for two there, so every value sits at the same height.
const KPI_LABEL = 'xl:min-h-8 2xl:min-h-0';

function KpiTiles({ data, range }) {
  const { leads, bookings, pending } = data;
  const awaiting = totalOf(pending?.awaiting_confirmation);
  const bookingHint = (counts) => (counts.upcoming > 0 ? `${counts.upcoming} still to come` : 'None still to come');
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
      <Tile
        labelClassName={KPI_LABEL}
        icon={Users}
        label="Total Leads"
        value={leads.received}
        hint="Came in on these dates"
        to={leadsPath(range)}
      />
      <Tile
        labelClassName={KPI_LABEL}
        icon={UserPlus}
        tone="info"
        label="New Leads"
        value={leads.new}
        hint={leads.received > 0 ? `${percent(leads.new, leads.received)}% not booked yet` : 'No booking yet'}
        to={leadsPath(range, 'NEW')}
      />
      {bookings ? (
        <>
          <Tile
            labelClassName={KPI_LABEL}
            icon={CalendarCheck}
            tone="demo"
            label="Demo Bookings"
            value={bookings.DEMO.total}
            hint={bookingHint(bookings.DEMO)}
            to={bookingsInRangePath('DEMO', range)}
          />
          <Tile
            labelClassName={KPI_LABEL}
            icon={ClipboardCheck}
            tone="diagnostic"
            label="Diagnostic Bookings"
            value={bookings.DIAGNOSTIC.total}
            hint={bookingHint(bookings.DIAGNOSTIC)}
            to={bookingsInRangePath('DIAGNOSTIC', range)}
          />
        </>
      ) : null}
      {awaiting != null ? (
        <Tile
          labelClassName={KPI_LABEL}
          icon={Hourglass}
          tone={awaiting > 0 ? 'warning' : 'default'}
          label="Pending Confirmations"
          value={awaiting}
          hint="Classes to come awaiting the parent"
        />
      ) : null}
    </div>
  );
}

// What each stage of the pipeline means, read out under its name.
const STAGE_HINTS = {
  NEW: 'No booking yet',
  BOOKED: 'A class to come',
  COMPLETED: 'A class taught',
  NOT_STARTED: 'Slot ended, no start',
  CANCELLED: 'Booking cancelled',
};

/**
 * Where the leads that came in on the dashboard's dates stand now, stage by
 * stage: each a bar of its share, its count and the share spelt out, opening
 * the Leads page at that stage over the same dates.
 */
function Pipeline({ data, range, className }) {
  const { pipeline, leads } = data;
  const largest = Math.max(1, ...pipeline.map((stage) => stage.count));
  return (
    <Panel
      icon={Funnel}
      title="Admissions Pipeline"
      subtitle={`Where the ${plural(leads.received, 'lead')} from these dates stand now`}
      actionTo={leadsPath(range)}
      className={className}
    >
      {leads.received === 0 ? (
        <PanelEmpty icon={Funnel} message="No leads came in on these dates" hint="Try a longer span of dates." />
      ) : (
        <ol aria-label="Leads by stage" className="flex flex-col gap-1">
          {pipeline.map((stage) => {
            const share = percent(stage.count, leads.received);
            return (
              <li key={stage.stage}>
                <Link
                  to={leadsPath(range, stage.stage)}
                  aria-label={`${stage.label}: ${plural(stage.count, 'lead')}, ${share}%. Open them on the Leads page.`}
                  className="hover:bg-muted/40 -mx-2 grid grid-cols-[minmax(0,10rem)_1fr_auto] items-center gap-x-4 gap-y-1 rounded-md px-2 py-2 transition-colors"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{stage.label}</span>
                    <span className="text-muted-foreground block truncate text-xs">{STAGE_HINTS[stage.stage]}</span>
                  </span>
                  <span className="bg-muted h-2 overflow-hidden rounded-full" aria-hidden="true">
                    <span
                      className="bg-primary block h-full rounded-full"
                      style={{ width: stage.count > 0 ? `max(${(stage.count / largest) * 100}%, 0.5rem)` : 0 }}
                    />
                  </span>
                  <span className="flex items-baseline gap-2 text-right whitespace-nowrap tabular-nums">
                    <span className="text-sm font-semibold">{stage.count}</span>
                    <span className="text-muted-foreground w-9 text-xs">{share}%</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

function ActionRow({ icon: Icon, label, detail, count, to }) {
  const content = (
    <>
      <span
        className={cn(
          'flex size-7 shrink-0 items-center justify-center rounded-md',
          count > 0 ? 'bg-warning/10 text-warning' : 'bg-muted text-muted-foreground'
        )}
      >
        <Icon className="size-3.5" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm">{label}</span>
        {detail ? <span className="text-muted-foreground block truncate text-xs">{detail}</span> : null}
      </span>
      <span
        className={cn('shrink-0 text-sm font-semibold tabular-nums', count > 0 ? 'text-foreground' : 'text-muted-foreground')}
      >
        {count}
      </span>
      {to && count > 0 ? <ChevronRight className="text-muted-foreground size-4 shrink-0" aria-hidden="true" /> : null}
    </>
  );
  return (
    <li>
      {to && count > 0 ? (
        <Link to={to} className="hover:bg-muted/40 -mx-2 flex items-center gap-3 rounded-md px-2 py-2.5 transition-colors">
          {content}
        </Link>
      ) : (
        <div className="flex items-center gap-3 py-2.5">{content}</div>
      )}
    </li>
  );
}

/** Demo and Diagnostic counts in words, e.g. "2 demo · 1 diagnostic". */
function byType(counts) {
  return `${counts.DEMO} demo · ${counts.DIAGNOSTIC} diagnostic`;
}

/**
 * What awaits an administrator now, whatever the dates: each count opens the
 * list that shows exactly those -- the Leads page's unassigned leads, a
 * Bookings page's classes needing a tutor or with their report due, Demo's
 * Re-Demo requests to schedule. Parents' confirmations are the BDEs' to
 * chase, so they are counted only.
 */
function PendingActions({ pending, className }) {
  const items = [
    {
      key: 'unassigned',
      icon: UserRoundX,
      label: 'Leads without a BDE',
      count: pending.unassigned_leads,
      to: '/leads?owner=unassigned',
    },
  ];
  if (pending.needs_tutor) {
    items.push({
      key: 'tutor',
      icon: Users,
      label: 'Classes to come that need a tutor',
      detail: byType(pending.needs_tutor),
      count: totalOf(pending.needs_tutor),
      to: bookingsListPath(busierType(pending.needs_tutor), { assigned: 'false' }),
    });
  }
  if (pending.report_due) {
    items.push({
      key: 'report',
      icon: FileWarning,
      label: 'Tutor reports due',
      detail: byType(pending.report_due),
      count: totalOf(pending.report_due),
      to: bookingsListPath(busierType(pending.report_due), { report: 'due', when: 'past' }),
    });
  }
  if (pending.redemo_scheduling != null) {
    items.push({
      key: 'redemo',
      icon: RotateCcw,
      label: 'Re-Demo requests to schedule',
      count: pending.redemo_scheduling,
      to: bookingsListPath('DEMO', { tab: 'redemo', status: 'AWAITING_SCHEDULING' }),
    });
  }
  if (pending.awaiting_confirmation) {
    items.push({
      key: 'confirmation',
      icon: Hourglass,
      label: 'Awaiting parent confirmation',
      detail: byType(pending.awaiting_confirmation),
      count: totalOf(pending.awaiting_confirmation),
    });
  }
  return (
    <Panel icon={ListTodo} title="Pending Actions" subtitle="As things stand now" className={className}>
      <ul className="divide-y">
        {items.map(({ key, ...item }) => (
          <ActionRow key={key} {...item} />
        ))}
      </ul>
    </Panel>
  );
}

const TODAY_COLUMNS = [
  {
    key: 'time',
    header: 'Time (IST)',
    className: 'whitespace-nowrap font-medium tabular-nums',
    cell: (booking) => slotParts(booking.slot.date, booking.slot.time).time,
  },
  { key: 'type', header: 'Type', cell: (booking) => <BookingTypeBadge type={booking.booking_type} /> },
  {
    key: 'student',
    header: 'Student',
    cell: (booking) => (
      <>
        <p className="font-medium">{booking.student_name}</p>
        {booking.grade ? <p className="text-muted-foreground text-xs">{booking.grade}</p> : null}
      </>
    ),
  },
  { key: 'tutor', header: 'Tutor', cell: (booking) => <TutorName booking={booking} /> },
  { key: 'status', header: 'Status', cell: (booking) => <BookingStateBadge booking={booking} /> },
  {
    key: 'open',
    header: { srOnly: 'Open' },
    headerClassName: 'w-px',
    cell: (booking) => (
      <Button variant="outline" size="sm" asChild>
        <Link to={todaysBookingPath(booking)} aria-label={`View ${booking.student_name}'s booking`}>
          View
          <ChevronRight />
        </Link>
      </Button>
    ),
  },
];

function TodayCard({ booking }) {
  return (
    <article className="hover:bg-muted/40 relative flex items-center gap-3 rounded-lg border p-3 transition-colors has-[a:focus-visible]:ring-[3px] has-[a:focus-visible]:ring-ring/50">
      <span className="w-16 shrink-0 text-sm font-medium tabular-nums">{slotParts(booking.slot.date, booking.slot.time).time}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">
          <Link to={todaysBookingPath(booking)} className="outline-none after:absolute after:inset-0 after:rounded-lg">
            {booking.student_name}
          </Link>
        </p>
        <p className="text-muted-foreground truncate text-xs">
          {booking.tutor ? `Tutor: ${booking.tutor.full_name}` : 'No tutor yet'}
        </p>
      </div>
      <div className="flex flex-col items-end gap-1">
        <BookingTypeBadge type={booking.booking_type} />
        <BookingStateBadge booking={booking} />
      </div>
    </article>
  );
}

/** Today's Demo classes and Diagnostic tests, soonest first; "today" is the API's Indian date, named rather than assumed. */
function TodaysBookings({ today }) {
  const rows = today.rows ?? [];
  const day = slotParts(today.date, '00:00').day;
  const subtitle = today.total > rows.length ? `${day} · the first ${rows.length} of ${today.total} · IST` : `${day} · Indian time (IST)`;
  return (
    <Panel
      icon={CalendarDays}
      title="Today's Bookings"
      subtitle={subtitle}
      action={
        today.total > 0 ? (
          <Badge variant="secondary" className="tabular-nums">
            {plural(today.total, 'booking')}
          </Badge>
        ) : null
      }
    >
      {rows.length === 0 ? (
        <PanelEmpty icon={CalendarOff} message="Nothing booked for today" hint="Demo classes and diagnostic tests on today's date appear here." />
      ) : (
        <ResponsiveList
          label="Today's bookings"
          columns={TODAY_COLUMNS}
          rows={rows}
          minTableWidth={640}
          renderCard={(booking) => <TodayCard booking={booking} />}
        />
      )}
    </Panel>
  );
}

function RecentLeads({ rows }) {
  return (
    <Panel icon={Inbox} title="Recent Enquiries" subtitle="The latest leads to come in" actionTo="/leads">
      {rows.length === 0 ? (
        <PanelEmpty icon={Inbox} message="No leads yet" hint="Leads from the booking pages, the website and BDEs appear here." />
      ) : (
        <ScrollList total={rows.length} className="divide-y">
          {rows.map((lead) => (
            <li key={lead.id} className="py-2.5 first:pt-0 last:pb-0">
              <Link
                to={`/leads/${lead.id}`}
                className="hover:bg-muted/40 -mx-2 flex items-center gap-3 rounded-md px-2 py-1 transition-colors"
              >
                <Avatar className="size-8 rounded-full" aria-hidden="true">
                  <AvatarFallback className="rounded-full text-xs">{getInitials(lead.student_name, null)}</AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{lead.student_name}</p>
                  <p className="text-muted-foreground truncate text-xs">
                    {[lead.grade, lead.source_label, lead.owner ? lead.owner.full_name : 'Unassigned'].filter(Boolean).join(' · ')}
                  </p>
                </div>
                <EnquiryStatusBadge enquiry={lead} />
              </Link>
            </li>
          ))}
        </ScrollList>
      )}
    </Panel>
  );
}

/**
 * The Admissions Dashboard, for administrators: the admissions pipeline at a
 * glance, across every BDE. Over the dates picked (the last 7 days unless
 * chosen otherwise, kept in the URL) the leads that came in and where they
 * stand now, and the Demo and Diagnostic bookings for classes on those dates;
 * then, as things stand now, what awaits action, today's bookings, the latest
 * leads and the latest admissions activity -- all from one request
 * (GET /api/admissions/dashboard/). Each count opens the list it counts. The
 * booking parts show only for holders of accounts.view_all_bookings, the
 * activity only for readers of the activity log, as the API answers.
 */
export default function AdmissionsDashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const range = readRange(searchParams);
  const { from, to } = range;
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setPending(true);
    api
      .get(ADMISSIONS_DASHBOARD_URL, { params: { from, to } })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, 'Could not load the admissions dashboard.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [from, to, reloadKey]);

  const changeRange = (updates) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    setSearchParams(params, { replace: true });
  };
  const reload = () => setReloadKey((key) => key + 1);

  let content;
  if (failure && !data && failure.status === 403) {
    content = <AccessDeniedState title="You don't have access to the admissions dashboard." message={failure.message} />;
  } else if (failure && !data) {
    content = <ErrorState message={failure.message} onRetry={reload} pending={pending} />;
  } else if (!data) {
    content = <DashboardSkeleton />;
  } else {
    content = (
      <div className={cn('flex flex-col gap-4', pending && 'opacity-70 transition-opacity')} aria-busy={pending || undefined}>
        {failure ? <ErrorState message={failure.message} onRetry={reload} pending={pending} /> : null}
        <KpiTiles data={data} range={range} />
        <div className="grid min-w-0 gap-4 xl:grid-cols-5 xl:items-start">
          <Pipeline data={data} range={range} className="xl:col-span-3" />
          <PendingActions pending={data.pending} className="xl:col-span-2" />
        </div>
        {data.today_bookings ? <TodaysBookings today={data.today_bookings} /> : null}
        <div className={cn('grid min-w-0 gap-4 lg:items-start', data.activity && 'lg:grid-cols-2')}>
          <RecentLeads rows={data.recent_leads ?? []} />
          {data.activity ? <RecentActivity rows={data.activity} /> : null}
        </div>
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Admissions Dashboard"
        description="Leads, Demo and Diagnostic bookings and what awaits action, across every BDE."
        actionsClassName="w-full sm:w-auto"
        actions={
          <div className="flex w-full items-start gap-2">
            <RangeFilter range={range} onChange={changeRange} />
            <Button variant="ghost" size="icon" onClick={reload} disabled={pending} aria-label="Refresh">
              <RefreshCwIcon />
            </Button>
          </div>
        }
      />
      {content}
    </Page>
  );
}
