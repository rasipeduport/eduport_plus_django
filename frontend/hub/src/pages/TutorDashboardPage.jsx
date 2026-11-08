import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertCircle,
  CalendarCheck,
  CalendarCheck2,
  CalendarClock,
  CalendarDays,
  CalendarOff,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  FileClock,
  PlayCircle,
  Sun,
  VideoOff,
} from 'lucide-react';

import api from '@/lib/api';
import { ACTIVITY_VIEW, HOMEWORK_VIEW, SESSION_VIEW, STUDENT_VIEW, canAny } from '@/lib/access';
import { indianToday } from '@/lib/bde-booking-filters';
import { TUTOR_BOOKINGS_URL, bookingError, isJoinable, tutorBookingPagePath, tutorBookingsPagePath } from '@/lib/bookings';
import { bookingTypeLabel, slotLabel, slotParts } from '@/lib/enquiries';
import { reportWords } from '@/lib/reports';
import { sessionsToday } from '@/lib/session-day';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { DashboardHeader } from '@/components/dashboard/dashboard-header';
import { Tile } from '@/components/dashboard/kpi-cards';
import { NeedsAttention, attentionItems } from '@/components/dashboard/needs-attention';
import { Panel, PanelEmpty, ScrollList } from '@/components/dashboard/dashboard-primitives';
import { RecentActivity } from '@/components/dashboard/recent-activity';
import { UpcomingSessions } from '@/components/dashboard/upcoming-sessions';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { FeedbackBadge, ReportStateBadge } from '@/components/bookings/booking-badges';
import { JoinMeetButton } from '@/components/bookings/meet-link';
import { TutorReportLink } from '@/components/reports/tutor-report-link';
import { Page } from '@/components/page/page';
import { AccessDeniedState, ErrorState } from '@/components/page/states';

// One page of each list is read: enough for a tutor's day and their reports due.
const LIST_ROWS = 50;
const ACTIVITY_ROWS = 25;
// Every booking opened from here comes back to the dashboard.
const FROM_DASHBOARD = { from: { to: '/dashboard', label: 'Dashboard' } };

const bookingPath = (booking) => tutorBookingPagePath(booking.booking_type, booking.id);
const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

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
      <div className="grid gap-4 xl:grid-cols-5">
        <Skeleton className="h-56 rounded-xl xl:col-span-3" />
        <Skeleton className="h-56 rounded-xl xl:col-span-2" />
      </div>
    </div>
  );
}

/** Today's Demo classes and diagnostic tests (IST) on a timeline, each with its Meet room while it is to come. */
function TodaysSchedule({ rows, total, className }) {
  const day = slotParts(indianToday(), '00:00').day;
  const subtitle = total > rows.length ? `${day} · the first ${rows.length} of ${total} · IST` : `${day} · Indian time (IST)`;
  return (
    <Panel
      icon={CalendarDays}
      title="Today's Bookings"
      subtitle={subtitle}
      className={className}
      action={
        total > 0 ? (
          <Badge variant="secondary" className="tabular-nums">
            {plural(total, 'booking', 'bookings')}
          </Badge>
        ) : null
      }
    >
      {rows.length === 0 ? (
        <PanelEmpty icon={Sun} message="No Demo or Diagnostic bookings today" hint="The ones you are assigned for today appear here." />
      ) : (
        <ol aria-label="Today's bookings">
          {rows.map((booking) => {
            const at = slotParts(booking.slot.date, booking.slot.time);
            return (
              <li key={booking.id} className="group relative flex gap-3">
                <span className="w-16 shrink-0 pt-0.5 text-sm font-medium whitespace-nowrap tabular-nums">{at.time}</span>
                <span className="flex flex-col items-center" aria-hidden="true">
                  <span
                    className={cn(
                      'mt-1.5 size-2.5 shrink-0 rounded-full ring-4',
                      booking.booking_type === 'DIAGNOSTIC' ? 'bg-diagnostic ring-diagnostic/15' : 'bg-demo ring-demo/15'
                    )}
                  />
                  <span className="bg-border mt-1.5 w-px flex-1 group-last:hidden" />
                </span>
                <div className="flex min-w-0 flex-1 flex-wrap items-start justify-between gap-x-3 gap-y-2 pb-5 group-last:pb-0">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <Link
                        to={bookingPath(booking)}
                        state={FROM_DASHBOARD}
                        className="hover:underline focus-visible:underline focus-visible:outline-none"
                      >
                        <span className="font-medium">{bookingTypeLabel(booking.booking_type)}</span>
                        <span className="text-muted-foreground"> · </span>
                        <span className="font-medium">{booking.student_name}</span>
                      </Link>
                      <ReportStateBadge booking={booking} />
                    </div>
                    <p className="text-muted-foreground mt-0.5 text-xs">
                      {[booking.grade, booking.syllabus].filter(Boolean).join(' · ')}
                    </p>
                  </div>
                  {isJoinable(booking) ? (
                    <JoinMeetButton link={booking.tutor_meet_link} label={`Join the Google Meet for ${booking.student_name}`} />
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

/** The next bookings to teach, beyond the moment: when (IST), what, for whom, opening each. */
function UpcomingBookings({ rows, total, className }) {
  const subtitle = total > rows.length ? `The next ${rows.length} of ${total} · Indian time (IST)` : 'Indian time (IST)';
  return (
    <Panel
      icon={CalendarClock}
      title="Upcoming Bookings"
      subtitle={subtitle}
      className={className}
    >
      {rows.length === 0 ? (
        <PanelEmpty icon={CalendarOff} message="No upcoming bookings" hint="Demo classes and diagnostic tests assigned to you appear here." />
      ) : (
        <ScrollList total={rows.length} className="divide-y">
          {rows.map((booking) => (
            <li key={booking.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1 basis-48">
                <Link
                  to={bookingPath(booking)}
                  state={FROM_DASHBOARD}
                  className="text-sm font-medium hover:underline"
                >
                  {booking.student_name}
                </Link>
                <p className="text-muted-foreground text-xs">
                  {slotLabel(booking.slot)}
                  {booking.grade ? ` · ${booking.grade}` : ''}
                </p>
              </div>
              <BookingTypeBadge type={booking.booking_type} />
              <ChevronRight className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
            </li>
          ))}
        </ScrollList>
      )}
    </Panel>
  );
}

/** The classes taught whose feedback (Demo) or results (Diagnostic) are still due, each with its way to write them. */
function PendingReports({ rows, total, className }) {
  return (
    <Panel
      icon={FileClock}
      title="Pending Feedback & Results"
      subtitle={total > 0 ? 'Classes you taught, their report not in yet' : 'Classes you taught, their report not in'}
      className={className}
      action={
        total > 0 ? (
          <Badge variant="warning" className="tabular-nums">
            {total} pending
          </Badge>
        ) : null
      }
    >
      {rows.length === 0 ? (
        <div className="bg-success/10 border-success/20 flex items-start gap-3 rounded-lg border px-3 py-2.5">
          <CheckCircle2 className="text-success mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-success text-sm font-medium">All caught up</p>
            <p className="text-muted-foreground text-xs">Every class you taught has its feedback or results in.</p>
          </div>
        </div>
      ) : (
        <ScrollList total={rows.length} className="divide-y">
          {rows.map((booking) => (
            <li key={booking.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1 basis-40">
                <Link
                  to={bookingPath(booking)}
                  state={FROM_DASHBOARD}
                  className="text-sm font-medium hover:underline"
                >
                  {booking.student_name}
                </Link>
                <p className="text-muted-foreground text-xs">
                  {reportWords(booking.booking_type).tab} · {slotLabel(booking.slot)}
                </p>
              </div>
              <FeedbackBadge booking={booking} />
              <TutorReportLink booking={booking} state={FROM_DASHBOARD} />
            </li>
          ))}
        </ScrollList>
      )}
    </Panel>
  );
}

/**
 * The tutor dashboard: the Demo and Diagnostic bookings the signed-in tutor is
 * assigned and their regular classes at a glance -- the headline numbers,
 * today's bookings, what needs their hand, what is booked next, the feedback
 * and results still due, today's regular classes and their latest activity.
 * Everything is read from APIs the Hub already serves a tutor: their bookings
 * (GET /api/tutor/bookings/, filtered by the API -- only ever their own),
 * sessions, students, homework and activity. Each request fails on its own,
 * so one refused list only blanks its own panel. Booking times are Indian
 * time, as the booking pages show them; regular classes keep the Sessions
 * page's local times.
 */
export default function TutorDashboardPage({ user }) {
  const canSeeSessions = canAny(user, SESSION_VIEW);
  const canSeeStudents = canAny(user, STUDENT_VIEW);
  const canSeeHomework = canAny(user, HOMEWORK_VIEW);
  const canSeeActivity = canAny(user, ACTIVITY_VIEW);
  const [data, setData] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    const today = indianToday();
    const bookings = (params) => api.get(TUTOR_BOOKINGS_URL, { params: { page: 1, page_size: 1, ...params } });
    const optional = (allowed, request) => (allowed ? request() : Promise.resolve(null));

    (async () => {
      const results = await Promise.allSettled([
        bookings({ type: 'DEMO', when: 'all' }),
        bookings({ type: 'DIAGNOSTIC', when: 'all' }),
        bookings({ when: 'all', from: today, to: today, page_size: LIST_ROWS }),
        bookings({ when: 'completed', report: 'due', page_size: LIST_ROWS }),
        bookings({ when: 'all', status: 'COMPLETED' }),
        bookings({ when: 'upcoming', status: 'BOOKED', page_size: LIST_ROWS }),
        optional(canSeeSessions, () => api.get('/api/sessions/')),
        optional(canSeeStudents, () => api.get('/api/students/')),
        optional(canSeeHomework, () => api.get('/api/homework/')),
        optional(canSeeActivity, () => api.get('/api/activity/', { params: { page: 1, page_size: ACTIVITY_ROWS } })),
      ]);
      if (!active) return;
      const [demo, diagnostic, todays, pending, completed, upcoming, sessions, students, homework, activity] = results;
      const list = (result) => (result.status === 'fulfilled' ? result.value.data : null);
      const value = (result, pick) => (result.status === 'fulfilled' && result.value ? pick(result.value.data) : null);
      const bookingResults = [demo, diagnostic, todays, pending, completed, upcoming];
      const refused = bookingResults.find((result) => result.status === 'rejected');
      setData({
        bookingsFailure: refused ? bookingError(refused.reason, 'Some of your bookings could not be loaded.') : null,
        demo: list(demo),
        diagnostic: list(diagnostic),
        today: list(todays),
        pending: list(pending),
        completed: list(completed),
        upcoming: list(upcoming),
        sessions: value(sessions, (d) => d.sessions ?? []),
        students: value(students, (d) => (Array.isArray(d) ? d : [])) ?? [],
        homework: value(homework, (d) => d.homework ?? []),
        activity: value(activity, (d) => d.results ?? []),
      });
    })();

    return () => {
      active = false;
    };
  }, [canSeeSessions, canSeeStudents, canSeeHomework, canSeeActivity, reloadKey]);

  let content;
  if (!data) {
    content = <DashboardSkeleton />;
  } else if (data.bookingsFailure?.status === 403) {
    content = <AccessDeniedState title="This dashboard belongs to tutor accounts." message={data.bookingsFailure.message} />;
  } else {
    const count = (page) => page?.count ?? 0;
    const todayRows = data.today?.results ?? [];
    const pendingRows = data.pending?.results ?? [];
    const upcomingRows = data.upcoming?.results ?? [];
    const classesToday = data.sessions ? sessionsToday(data.sessions).length : 0;
    const bookingsToday = count(data.today);
    const late = todayRows.filter((booking) => booking.status === 'BOOKED' && booking.activity_state === 'LATE');
    const noMeet = upcomingRows.filter((booking) => !booking.tutor_meet_link);
    const pendingTotal = count(data.pending);

    // What needs the tutor's hand: their bookings first, then their regular classes' (the staff dashboard's own rows).
    const attention = [
      {
        key: 'late',
        icon: PlayCircle,
        label: 'Classes to start now',
        count: late.length,
        to: late[0] ? bookingPath(late[0]) : '/dashboard',
      },
      {
        key: 'reports',
        icon: FileClock,
        label: 'Feedback & results due',
        count: pendingTotal,
        to: pendingRows[0] ? `${tutorBookingsPagePath(pendingRows[0].booking_type)}?view=completed&feedback=due` : '/dashboard',
      },
      {
        key: 'meet',
        icon: VideoOff,
        label: 'Upcoming bookings without a Meet link',
        count: noMeet.length,
        to: noMeet[0] ? bookingPath(noMeet[0]) : '/dashboard',
      },
      ...attentionItems({
        homework: data.homework ?? [],
        sessions: data.sessions ?? [],
        additionalExams: null,
        stats: null,
        canSeeInvitations: false,
      }).filter((item) => (item.key === 'homework' ? data.homework : data.sessions)),
    ];
    const attentionTotal = attention.reduce((sum, item) => sum + item.count, 0);

    content = (
      <>
        {data.bookingsFailure ? (
          <ErrorState message={data.bookingsFailure.message} onRetry={() => setReloadKey((key) => key + 1)} />
        ) : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <Tile
            icon={CalendarCheck2}
            tone="default"
            label="Assigned Bookings"
            value={count(data.demo) + count(data.diagnostic)}
            hint={`${count(data.demo)} Demo · ${count(data.diagnostic)} Diagnostic`}
          />
          <Tile
            icon={CalendarDays}
            tone="info"
            label="Today's Sessions"
            value={bookingsToday + classesToday}
            hint={
              data.sessions
                ? `${bookingsToday} Demo/Diagnostic · ${plural(classesToday, 'regular class', 'regular classes')}`
                : `${bookingsToday} Demo/Diagnostic`
            }
          />
          <Tile
            icon={FileClock}
            tone={pendingTotal > 0 ? 'warning' : 'default'}
            label="Pending Feedback"
            value={pendingTotal}
            hint={pendingTotal > 0 ? 'Classes taught, report not in' : 'All caught up'}
            hintTone={pendingTotal > 0 ? 'warning' : 'muted'}
          />
          <Tile
            icon={CalendarCheck}
            tone="success"
            label="Completed Sessions"
            value={count(data.completed)}
            hint="Demo and Diagnostic, report in"
          />
          <Tile
            icon={AlertCircle}
            tone={attentionTotal > 0 ? 'destructive' : 'default'}
            label="Needs Attention"
            value={attentionTotal}
            hint={attentionTotal > 0 ? plural(attentionTotal, 'item needs you', 'items need you') : 'All clear'}
            hintTone={attentionTotal > 0 ? 'warning' : 'muted'}
          />
        </div>

        <div className="grid min-w-0 gap-4 xl:grid-cols-5 xl:items-start">
          <TodaysSchedule rows={todayRows} total={bookingsToday} className="xl:col-span-3" />
          <div className="min-w-0 xl:col-span-2">
            <NeedsAttention items={attention} />
          </div>
        </div>

        <div className="grid min-w-0 gap-4 xl:grid-cols-5 xl:items-start">
          <UpcomingBookings rows={upcomingRows} total={count(data.upcoming)} className="xl:col-span-3" />
          <PendingReports rows={pendingRows} total={pendingTotal} className="xl:col-span-2" />
        </div>

        {data.sessions?.length || data.activity ? (
          <div className="grid min-w-0 gap-4 xl:grid-cols-5 xl:items-start">
            {/* Regular classes, only for a tutor who has any: their Sessions page's own panel. */}
            {data.sessions?.length ? (
              <div className="min-w-0 xl:col-span-3">
                <UpcomingSessions sessions={data.sessions} students={data.students} />
              </div>
            ) : null}
            {data.activity ? (
              <div className={cn('min-w-0', data.sessions?.length ? 'xl:col-span-2' : 'xl:col-span-5')}>
                <RecentActivity rows={data.activity} />
              </div>
            ) : null}
          </div>
        ) : null}
      </>
    );
  }

  return (
    <Page>
      <DashboardHeader user={user} subtitle="Your Demo and Diagnostic bookings and your classes at a glance." />
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" asChild>
          <Link to={tutorBookingsPagePath('DEMO')}>
            <CalendarCheck />
            Demo Bookings
          </Link>
        </Button>
        <Button variant="outline" asChild>
          <Link to={tutorBookingsPagePath('DIAGNOSTIC')}>
            <ClipboardCheck />
            Diagnostic Bookings
          </Link>
        </Button>
      </div>
      {content}
    </Page>
  );
}
