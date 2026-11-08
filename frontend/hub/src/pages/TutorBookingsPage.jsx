import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { CalendarCheck, ChevronRightIcon, ClipboardCheck, RefreshCwIcon, SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { TUTOR_BOOKINGS_URL, bookingError, isJoinable, tutorBookingPagePath } from '@/lib/bookings';
import { slotLabel, slotParts } from '@/lib/enquiries';
import { reportWords } from '@/lib/reports';
import { showsStudentTime } from '@/lib/timezone';
import {
  CLEARED_TUTOR_FILTERS,
  DEFAULT_VIEW,
  TUTOR_VIEWS,
  readTutorBookingFilters,
  tutorBookingParams,
} from '@/lib/tutor-booking-filters';
import { useListParams } from '@/hooks/use-list-params';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TableSkeleton } from '@/components/table-skeleton';
import { FeedbackBadge, RedemoBadge, ReportStateBadge } from '@/components/bookings/booking-badges';
import { JoinMeetButton } from '@/components/bookings/meet-link';
import { StartBookingButton } from '@/components/bookings/start-booking-button';
import { StudentTimeCell } from '@/components/bookings/student-time';
import { TutorBookingFilters } from '@/components/bookings/tutor-booking-filters';
import { EmptyState, Page, PageHeader } from '@/components/page/page';
import { Pagination } from '@/components/page/pagination';
import { ResponsiveList } from '@/components/page/responsive-list';
import { AccessDeniedState, ErrorState } from '@/components/page/states';
import { TutorReportLink } from '@/components/reports/tutor-report-link';

const TYPES = {
  DEMO: {
    icon: CalendarCheck,
    title: 'Demo Bookings',
    description:
      'The demo classes you are assigned to teach, in Indian time (IST). Open one to join its Meet, start it and write its feedback.',
    noun: 'demo classes',
  },
  DIAGNOSTIC: {
    icon: ClipboardCheck,
    title: 'Diagnostic Bookings',
    description:
      'The diagnostic tests you are assigned to conduct, in Indian time (IST). Open one to join its Meet, start it and enter its results.',
    noun: 'diagnostic tests',
  },
};
const PAGE_SIZE = 25;

function Status({ booking }) {
  return (
    <span className="flex flex-wrap gap-1">
      <ReportStateBadge booking={booking} />
      {booking.redemo ? <RedemoBadge number={booking.redemo.number} /> : null}
    </span>
  );
}

function Meeting({ booking }) {
  if (!isJoinable(booking)) return <span className="text-muted-foreground">—</span>;
  return <JoinMeetButton link={booking.tutor_meet_link} label={`Join the Google Meet for ${booking.student_name}`} />;
}

/**
 * What a row offers first: Start Demo / Start Diagnostic while the API allows
 * it, else Submit Feedback / Enter Results once the class is started and its
 * report is not in -- nothing more, the rest is on the booking's own page.
 */
function MainAction({ booking, onStarted, from }) {
  if (booking.actions?.start) return <StartBookingButton booking={booking} onStarted={onStarted} onRefresh={onStarted} />;
  if (booking.status === 'BOOKED' && booking.started_at && !booking.has_report) {
    return <TutorReportLink booking={booking} state={{ from }} />;
  }
  return null;
}

/**
 * A tutor's Demo or Diagnostic bookings (`type`): every booking of that type
 * assigned to them, as GET /api/tutor/bookings/ lists them -- by view
 * (Upcoming, the default; Completed, the classes they taught, the report in
 * or pending; All), class date (Today, This Week, This Month, All Time or
 * Custom, in Indian dates), the student's name, status and feedback, all kept
 * in the URL (view, dates, from, to, q, status, feedback, page) and read by
 * lib/tutor-booking-filters. Each row offers its Meet room, Start while the
 * API allows it and the report once it can be written, and opens the
 * booking's workspace, whose way back returns here as the list was. The API
 * serves only the caller's own bookings, with the child and nothing of the
 * parent; opens for the TUTOR role holding accounts.view_assigned_bookings
 * (lib/access).
 */
export default function TutorBookingsPage({ type }) {
  const { icon, title, description, noun } = TYPES[type];
  const words = reportWords(type);
  const location = useLocation();
  const { searchParams, update } = useListParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [pendingCount, setPendingCount] = useState(null);

  const filters = readTutorBookingFilters(searchParams);
  const { page, view, q, status, feedback, from, to } = filters;
  const reload = () => setReloadKey((key) => key + 1);
  // The student's own time beside the slot's Indian time, where a booking shown reads differently (lib/timezone).
  const showStudentTime = showsStudentTime(data?.results, (booking) => booking.slot?.starts_at, (booking) => booking.student_timezone);

  useEffect(() => {
    let active = true;
    setPending(true);
    api
      .get(TUTOR_BOOKINGS_URL, { params: tutorBookingParams(type, { page, view, q, status, feedback, from, to }, PAGE_SIZE) })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, `Could not load your ${noun}.`));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [type, noun, page, view, q, status, feedback, from, to, reloadKey]);

  // How many classes taught still wait for their report, beside the Completed tab; a failure leaves it out.
  useEffect(() => {
    let active = true;
    api
      .get(TUTOR_BOOKINGS_URL, { params: { type, when: 'completed', report: 'due', page: 1, page_size: 1 } })
      .then((response) => {
        if (active) setPendingCount(response.data.count ?? null);
      })
      .catch(() => {
        if (active) setPendingCount(null);
      });
    return () => {
      active = false;
    };
  }, [type, reloadKey]);

  // Another view keeps the search and the dates; a filter the new view has no use for goes.
  const changeView = (next) => {
    const updates = { view: next === DEFAULT_VIEW ? null : next };
    if (next === 'completed') updates.status = null;
    if (next === 'upcoming') updates.feedback = null;
    update(updates);
  };

  // The way back from a booking's page: this list, its view, filters and page included.
  const backTo = { to: `${location.pathname}${location.search}`, label: title };
  const opening = (booking) => ({ to: tutorBookingPagePath(type, booking.id), state: { from: backTo } });
  const viewLink = (booking) => (
    <Button variant="outline" size="sm" asChild>
      <Link {...opening(booking)} aria-label={`View ${booking.student_name}'s booking on ${slotLabel(booking.slot)}`}>
        View
        <ChevronRightIcon />
      </Link>
    </Button>
  );

  const columns = [
    {
      key: 'when',
      header: 'Date & Time (IST)',
      className: 'whitespace-nowrap',
      cell: (booking) => {
        const at = slotParts(booking.slot.date, booking.slot.time);
        return (
          <>
            <p className="font-medium">{at.day}</p>
            <p className="text-muted-foreground text-xs">{at.time} IST</p>
          </>
        );
      },
    },
    ...(showStudentTime
      ? [
          {
            key: 'student_time',
            header: 'Student Time',
            className: 'whitespace-nowrap',
            cell: (booking) => <StudentTimeCell startsAt={booking.slot?.starts_at} timezone={booking.student_timezone} />,
          },
        ]
      : []),
    {
      key: 'student',
      header: 'Student',
      className: 'min-w-36 whitespace-normal',
      cell: (booking) => (
        <>
          <p className="font-medium break-words">{booking.student_name}</p>
          {booking.syllabus ? <p className="text-muted-foreground text-xs">{booking.syllabus}</p> : null}
        </>
      ),
    },
    { key: 'class', header: 'Class', className: 'whitespace-nowrap', cell: (booking) => booking.grade || '—' },
    { key: 'status', header: 'Status', cell: (booking) => <Status booking={booking} /> },
    { key: 'feedback', header: words.tab, cell: (booking) => <FeedbackBadge booking={booking} /> },
    { key: 'meeting', header: 'Meeting', cell: (booking) => <Meeting booking={booking} /> },
    {
      key: 'action',
      header: { srOnly: 'Actions' },
      headerClassName: 'w-px',
      cell: (booking) => (
        <div className="flex justify-end gap-2">
          <MainAction booking={booking} onStarted={reload} from={backTo} />
          {viewLink(booking)}
        </div>
      ),
    },
  ];

  const renderCard = (booking) => (
    <article className="bg-card hover:bg-muted/40 relative flex h-full flex-col gap-3 rounded-xl border p-4 transition-colors has-[a:focus-visible]:ring-[3px] has-[a:focus-visible]:ring-ring/50">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-medium">
            <Link {...opening(booking)} className="outline-none after:absolute after:inset-0 after:rounded-xl">
              {booking.student_name}
            </Link>
          </h2>
          <p className="text-muted-foreground truncate text-sm">
            {[booking.grade, booking.syllabus].filter(Boolean).join(' · ') || '—'}
          </p>
        </div>
        <Status booking={booking} />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div className="col-span-2 min-w-0">
          <p className="text-muted-foreground text-xs">Date & Time</p>
          <p className="truncate">{slotLabel(booking.slot)}</p>
        </div>
        {showStudentTime ? (
          <div className="col-span-2 min-w-0">
            <p className="text-muted-foreground text-xs">Student Time</p>
            <p className="truncate">
              <StudentTimeCell startsAt={booking.slot?.starts_at} timezone={booking.student_timezone} />
            </p>
          </div>
        ) : null}
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">{words.tab}</p>
          <FeedbackBadge booking={booking} />
        </div>
        {isJoinable(booking) ? (
          <div className="relative z-10 min-w-0">
            <p className="text-muted-foreground text-xs">Meeting</p>
            <Meeting booking={booking} />
          </div>
        ) : null}
      </div>
      {/* Above the card's own link, so each button is its own. */}
      <div className="relative z-10 mt-auto flex flex-wrap gap-2 empty:hidden">
        <MainAction booking={booking} onStarted={reload} from={backTo} />
      </div>
    </article>
  );

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title={`You don't have access to ${noun}.`} message={failure.message} />;
  } else {
    const rows = data?.results ?? [];
    const total = data?.count ?? 0;
    let list;
    if (!data && !failure) {
      list = <TableSkeleton columns={6} toolbar={false} />;
    } else if (!data) {
      list = <ErrorState message={failure.message} onRetry={reload} pending={pending} />;
    } else {
      let empty = null;
      if (total > 0) {
        empty = (
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
        );
      } else if (filters.filtered) {
        empty = (
          <EmptyState
            icon={SearchXIcon}
            title={`No ${noun} match these filters`}
            description="Try another name, status or dates, or clear the filters."
            action={
              <Button variant="outline" onClick={() => update(CLEARED_TUTOR_FILTERS)}>
                Clear all filters
              </Button>
            }
          />
        );
      } else if (view === 'upcoming') {
        empty = (
          <EmptyState
            icon={icon}
            title={`No upcoming ${noun}`}
            description={`When an administrator assigns you one of the ${noun}, it appears here. Earlier ones are under Completed and All.`}
            action={
              <Button variant="outline" onClick={() => changeView('all')}>
                Show all
              </Button>
            }
          />
        );
      } else {
        empty = (
          <EmptyState
            icon={icon}
            title={view === 'completed' ? `No completed ${noun} yet` : `No ${noun} assigned to you yet`}
            description={
              view === 'completed'
                ? `The ${noun} you start appear here once taught, with their ${words.noun} pending or submitted.`
                : `${title} an administrator assigns you appear here.`
            }
          />
        );
      }
      list = (
        <>
          {failure ? <ErrorState message={failure.message} onRetry={reload} pending={pending} /> : null}
          {rows.length ? (
            <ResponsiveList
              label={title}
              columns={columns}
              rows={rows}
              pending={pending}
              minTableWidth={1040}
              renderCard={renderCard}
            />
          ) : (
            empty
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
        <Tabs value={view} onValueChange={changeView}>
          <TabsList>
            {TUTOR_VIEWS.map((option) => (
              <TabsTrigger key={option.value} value={option.value}>
                {option.label}
                {option.value === 'completed' && pendingCount > 0 ? (
                  <Badge variant="warning" className="px-1.5 tabular-nums">
                    {pendingCount}
                    <span className="sr-only"> {words.noun} pending</span>
                  </Badge>
                ) : null}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <TutorBookingFilters type={type} filters={filters} onChange={update} onClear={() => update(CLEARED_TUTOR_FILTERS)} />
        {list}
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title={title}
        description={description}
        actions={
          <Button variant="ghost" size="sm" onClick={reload} disabled={pending}>
            <RefreshCwIcon />
            Refresh
          </Button>
        }
      />
      {content}
    </Page>
  );
}
