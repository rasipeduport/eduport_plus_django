import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertCircle,
  CalendarCheck,
  CalendarCheck2,
  CalendarClock,
  CalendarDays,
  ClipboardCheck,
  FileClock,
  MessageSquareText,
  RefreshCwIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { ACTIVITY_VIEW, canAny } from '@/lib/access';
import { indianToday } from '@/lib/bde-booking-filters';
import { bookingError, tutorBookingsPagePath } from '@/lib/bookings';
import {
  ADMISSIONS_ENTITIES,
  LIST_ROWS,
  TUTOR_DASHBOARDS,
  allBookingsPath,
  bookingAttention,
  countByType,
  indianTomorrow,
  pendingReportsPath,
  settledData,
  tutorBookings,
} from '@/lib/tutor-dashboards';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tile } from '@/components/dashboard/kpi-cards';
import { NeedsAttention } from '@/components/dashboard/needs-attention';
import { RecentActivity } from '@/components/dashboard/recent-activity';
import { PendingReports, RecentlyCompleted } from '@/components/dashboard/tutor-reports';
import { TodaysBookings, UpcomingBookings } from '@/components/dashboard/tutor-work';
import { Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState } from '@/components/page/states';

// The latest completed bookings and admissions activity entries listed; the
// rest are on each type's list and in the activity log.
const COMPLETED_ROWS = 10;
const ACTIVITY_ROWS = 10;
const FROM = TUTOR_DASHBOARDS.admissions;
const TYPE_LINKS = [
  { to: tutorBookingsPagePath('DEMO'), label: 'Demo' },
  { to: tutorBookingsPagePath('DIAGNOSTIC'), label: 'Diagnostic' },
];
const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-5">
        <Skeleton className="h-72 rounded-xl xl:col-span-3" />
        <Skeleton className="h-72 rounded-xl xl:col-span-2" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-56 rounded-xl" />
        <Skeleton className="h-56 rounded-xl" />
      </div>
    </div>
  );
}

/**
 * The Tutor Hub's Admissions Dashboard: the Demo classes and diagnostic tests
 * the signed-in tutor is assigned, and nothing of their regular teaching. The
 * headline numbers for each type, today's bookings, what needs their hand,
 * the Demo feedback and the Diagnostic results still due, what comes after
 * today, the bookings completed lately and their latest Demo and Diagnostic
 * activity -- every row opening its booking's workspace or report, the counts
 * their type's list. All of it is read from the tutor's own bookings (GET
 * /api/tutor/bookings/, filtered by the API -- only ever theirs), in Indian
 * time as the booking pages show it, and from their own booking and report
 * entries in the activity log, for a tutor who may read it.
 */
export default function TutorAdmissionsDashboardPage({ user }) {
  const canSeeActivity = canAny(user, ACTIVITY_VIEW);
  const [data, setData] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    const today = indianToday();
    const activity = (entity) =>
      canSeeActivity ? api.get('/api/activity/', { params: { entity, page: 1, page_size: ACTIVITY_ROWS } }) : Promise.resolve(null);
    setPending(true);

    (async () => {
      const results = await Promise.allSettled([
        tutorBookings({ type: 'DEMO', when: 'all' }),
        tutorBookings({ type: 'DIAGNOSTIC', when: 'all' }),
        tutorBookings({ when: 'all', from: today, to: today, page_size: LIST_ROWS }),
        tutorBookings({ when: 'upcoming', status: 'BOOKED', from: indianTomorrow(), page_size: LIST_ROWS }),
        tutorBookings({ type: 'DEMO', when: 'completed', report: 'due', page_size: LIST_ROWS }),
        tutorBookings({ type: 'DIAGNOSTIC', when: 'completed', report: 'due', page_size: LIST_ROWS }),
        tutorBookings({ when: 'completed', status: 'COMPLETED', page_size: COMPLETED_ROWS }),
        ...ADMISSIONS_ENTITIES.map(activity),
      ]);
      if (!active) return;
      const [demo, diagnostic, todays, later, demoDue, diagnosticDue, completed, ...entries] = results;
      const refused = results.slice(0, 7).find((result) => result.status === 'rejected');
      const entryPages = entries.map(settledData);
      setData({
        failure: refused ? bookingError(refused.reason, 'Some of your bookings could not be loaded.') : null,
        demo: settledData(demo),
        diagnostic: settledData(diagnostic),
        todays: settledData(todays),
        later: settledData(later),
        demoDue: settledData(demoDue),
        diagnosticDue: settledData(diagnosticDue),
        completed: settledData(completed),
        // Both kinds of entry, newest first, while either was read.
        activity: entryPages.some(Boolean)
          ? entryPages
              .flatMap((page) => page?.results ?? [])
              .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
              .slice(0, ACTIVITY_ROWS)
          : null,
      });
      setPending(false);
    })();

    return () => {
      active = false;
    };
  }, [canSeeActivity, reloadKey]);

  const reload = () => setReloadKey((key) => key + 1);

  let content;
  if (!data) {
    content = <DashboardSkeleton />;
  } else if (data.failure?.status === 403) {
    content = <AccessDeniedState title="This dashboard belongs to tutor accounts." message={data.failure.message} />;
  } else {
    const count = (page) => page?.count ?? 0;
    const todayRows = data.todays?.results ?? [];
    const laterRows = data.later?.results ?? [];
    const demoDue = count(data.demoDue);
    const diagnosticDue = count(data.diagnosticDue);
    const todayTotal = count(data.todays);
    // Split by type only while every one of today's bookings was read.
    const todayByType = todayTotal === todayRows.length ? countByType(todayRows) : null;
    const attention = bookingAttention({
      today: todayRows,
      later: laterRows,
      demoFeedbackDue: demoDue,
      diagnosticResultsDue: diagnosticDue,
      home: FROM.to,
    });
    const attentionTotal = attention.reduce((sum, item) => sum + item.count, 0);

    content = (
      <div className={cn('flex flex-col gap-4', pending && 'opacity-70 transition-opacity')} aria-busy={pending || undefined}>
        {data.failure ? <ErrorState message={data.failure.message} onRetry={reload} pending={pending} /> : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile
            icon={CalendarCheck}
            tone="demo"
            label="Demo Bookings"
            value={count(data.demo)}
            hint="Assigned to you"
            to={allBookingsPath('DEMO')}
          />
          <Tile
            icon={ClipboardCheck}
            tone="diagnostic"
            label="Diagnostic Bookings"
            value={count(data.diagnostic)}
            hint="Assigned to you"
            to={allBookingsPath('DIAGNOSTIC')}
          />
          <Tile
            icon={CalendarDays}
            tone="info"
            label="Today's Bookings"
            value={todayTotal}
            hint={
              todayTotal === 0
                ? 'Nothing booked today'
                : todayByType
                  ? `${todayByType.DEMO} Demo · ${todayByType.DIAGNOSTIC} Diagnostic`
                  : 'Indian time (IST)'
            }
          />
          <Tile icon={CalendarClock} tone="default" label="Upcoming Bookings" value={count(data.later)} hint="Booked after today" />
          <Tile
            icon={CalendarCheck2}
            tone="success"
            label="Completed Bookings"
            value={count(data.completed)}
            hint="Taught, the report in"
          />
          <Tile
            icon={MessageSquareText}
            tone={demoDue > 0 ? 'warning' : 'default'}
            label="Pending Demo Feedback"
            value={demoDue}
            hint={demoDue > 0 ? plural(demoDue, 'Demo class taught', 'Demo classes taught') : 'All caught up'}
            hintTone={demoDue > 0 ? 'warning' : 'muted'}
            to={demoDue > 0 ? pendingReportsPath('DEMO') : undefined}
          />
          <Tile
            icon={FileClock}
            tone={diagnosticDue > 0 ? 'warning' : 'default'}
            label="Pending Diagnostic Results"
            value={diagnosticDue}
            hint={diagnosticDue > 0 ? plural(diagnosticDue, 'diagnostic test taught', 'diagnostic tests taught') : 'All caught up'}
            hintTone={diagnosticDue > 0 ? 'warning' : 'muted'}
            to={diagnosticDue > 0 ? pendingReportsPath('DIAGNOSTIC') : undefined}
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
          <TodaysBookings rows={todayRows} total={todayTotal} from={FROM} className="xl:col-span-3" />
          <div className="min-w-0 xl:col-span-2">
            <NeedsAttention items={attention} />
          </div>
        </div>

        <div className="grid min-w-0 gap-4 lg:grid-cols-2 lg:items-start">
          <PendingReports
            type="DEMO"
            rows={data.demoDue?.results ?? []}
            total={demoDue}
            from={FROM}
            links={[{ to: pendingReportsPath('DEMO'), label: 'View all' }]}
          />
          <PendingReports
            type="DIAGNOSTIC"
            rows={data.diagnosticDue?.results ?? []}
            total={diagnosticDue}
            from={FROM}
            links={[{ to: pendingReportsPath('DIAGNOSTIC'), label: 'View all' }]}
          />
        </div>

        <div className="grid min-w-0 gap-4 xl:grid-cols-5 xl:items-start">
          <UpcomingBookings rows={laterRows} total={count(data.later)} from={FROM} links={TYPE_LINKS} className="xl:col-span-3" />
          <RecentlyCompleted
            rows={data.completed?.results ?? []}
            total={count(data.completed)}
            from={FROM}
            links={TYPE_LINKS.map((link) => ({ ...link, to: `${link.to}?view=completed` }))}
            className="xl:col-span-2"
          />
        </div>

        {data.activity ? (
          <RecentActivity rows={data.activity} title="Recent Admissions Activity" actionTo="/activity?entity=booking" />
        ) : null}
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Admissions Dashboard"
        description="The Demo classes and diagnostic tests you are assigned: today's, what's next, and the feedback and results still due."
        actions={
          <div className="flex flex-wrap items-center gap-2">
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
