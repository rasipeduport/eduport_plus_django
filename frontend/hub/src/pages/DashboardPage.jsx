import { useEffect, useMemo, useRef, useState } from 'react';

import api from '@/lib/api';
import { EXAM_VIEW, PERMISSIONS, can, canAny } from '@/lib/access';
import { keepFailed, partsFailedMessage } from '@/lib/refresh-failures';
import { useDashboardRange } from '@/hooks/use-dashboard-range';
import { ErrorState } from '@/components/page/states';
import { Skeleton } from '@/components/ui/skeleton';
import { DashboardHeader } from '@/components/dashboard/dashboard-header';
import { DashboardRangeFilter } from '@/components/dashboard/dashboard-range-filter';
import { KpiCards } from '@/components/dashboard/kpi-cards';
import { UpcomingSessions } from '@/components/dashboard/upcoming-sessions';
import { NeedsAttention, attentionItems } from '@/components/dashboard/needs-attention';
import { SignupsChart } from '@/components/dashboard/signups-chart';
import { RecentActivity } from '@/components/dashboard/recent-activity';
import { RecentStudents } from '@/components/dashboard/recent-students';

// One page of the log is fetched; the card shows five at a time and scrolls for the rest.
const ACTIVITY_ROWS = 25;
// What the dashboard's dates are without a pick: the last seven days, as its sign-ups chart always opened on.
const ACADEMICS_DEFAULT_RANGE = '7d';
// Each read's part of the dashboard, as an error names it.
const LABELS = {
  stats: 'the dashboard figures',
  students: 'students',
  sessions: 'sessions',
  homework: 'homework',
  activity: 'recent activity',
  additionalExams: 'additional exams',
};
const LIST_PARTS = ['students', 'sessions', 'homework', 'activity', 'additionalExams'];

/** The parts whose read failed, each marked `kept` when it is still showing an earlier read. */
const failuresOf = (failed, loaded) => {
  if (failed.length) console.error('Dashboard reads failed', failed);
  return failed.map((name) => ({ label: LABELS[name], kept: loaded.has(name) }));
};

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <Skeleton className="h-12 w-72 max-w-full" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-[3fr_2fr]">
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
      <div className="grid gap-4 md:grid-cols-[3fr_2fr]">
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
      <Skeleton className="h-56" />
    </div>
  );
}

/**
 * The staff dashboard (the Academics Dashboard; a mentor's /dashboard).
 * Everything on it is read from endpoints the Hub already serves this
 * account: the stats endpoint (totals, and the sign-ups on the dashboard's
 * dates) plus the students, sessions, homework and activity lists, and
 * additional exams for whoever may view exams. The dates (Today | 7 Days |
 * This Month | All Time | Custom, the last 7 days unless picked, kept in the
 * URL) move only the sign-ups -- the New Enrollments chart and the Total
 * Students tile's count of new students -- so picking them reads the stats
 * alone again; every other figure is as things stand now. Each request fails
 * on its own: a failed one keeps what its panel showed before (empty only
 * when it never loaded), and the message above names every part that failed.
 */
export default function DashboardPage({ user }) {
  const canSeeExams = canAny(user, EXAM_VIEW);
  const canSeeInvitations = can(user, PERMISSIONS.viewInvitations);
  const [range, pickRange, query] = useDashboardRange(ACADEMICS_DEFAULT_RANGE);

  // The five lists, read together; the stats, read on their own whenever the dates change,
  // kept with the dates they were read for (`query`).
  const [lists, setLists] = useState(null);
  const [statsAnswer, setStatsAnswer] = useState(undefined);
  const [listsPending, setListsPending] = useState(true);
  const [statsPending, setStatsPending] = useState(true);
  // Each part whose last read failed, and whether it was showing an earlier read (`kept`).
  const [failures, setFailures] = useState({ lists: [], stats: [] });
  // Refresh, on request only: this page makes six reads, so it is never read again on its own.
  const [reloadKey, setReloadKey] = useState(0);
  const refresh = () => setReloadKey((key) => key + 1);
  // The parts that have loaded at least once: a failure of one of these keeps it on screen.
  const loadedParts = useRef(new Set());

  useEffect(() => {
    let active = true;
    setListsPending(true);

    (async () => {
      const requests = [
        api.get('/api/students/'),
        api.get('/api/sessions/'),
        api.get('/api/homework/'),
        api.get('/api/activity/', { params: { page: 1, page_size: ACTIVITY_ROWS } }),
        canSeeExams ? api.get('/api/additional-exams/') : Promise.resolve(null),
      ];
      const [students, sessions, homework, activity, additional] = await Promise.allSettled(requests);
      if (!active) return;

      // Undefined for a read that failed: that part keeps what it had.
      const value = (result, pick) => (result.status === 'fulfilled' && result.value ? pick(result.value.data) : undefined);
      const fresh = {
        students: value(students, (d) => (Array.isArray(d) ? d : [])),
        sessions: value(sessions, (d) => d.sessions ?? []),
        homework: value(homework, (d) => d.homework ?? []),
        activity: value(activity, (d) => d.results ?? []),
        // null (not an empty list) when this account is not served exams, so the
        // attention list leaves the row out rather than showing a false zero.
        additionalExams: canSeeExams ? value(additional, (d) => d.additional_exams ?? []) : null,
      };
      const failed = LIST_PARTS.filter((name) => fresh[name] === undefined);
      setFailures((previous) => ({ ...previous, lists: failuresOf(failed, loadedParts.current) }));
      for (const name of LIST_PARTS) if (fresh[name] !== undefined) loadedParts.current.add(name);
      setLists((previous) =>
        keepFailed(fresh, previous, {
          students: [],
          sessions: [],
          homework: [],
          activity: [],
          additionalExams: canSeeExams ? [] : null,
        })
      );
      setListsPending(false);
    })();

    return () => {
      active = false;
    };
  }, [canSeeExams, reloadKey]);

  useEffect(() => {
    let active = true;
    setStatsPending(true);
    api
      .get('/api/dashboard/stats/', { params: query })
      .then((response) => {
        if (!active) return;
        loadedParts.current.add('stats');
        setStatsAnswer({ data: response.data, query });
        setFailures((previous) => ({ ...previous, stats: [] }));
      })
      .catch(() => {
        if (!active) return;
        setFailures((previous) => ({ ...previous, stats: failuresOf(['stats'], loadedParts.current) }));
        // Never loaded: the tiles fall back to the lists. Loaded before: its totals stay (they are as things
        // stand), its sign-ups only for the dates they were read for (below).
        setStatsAnswer((previous) => previous ?? null);
      })
      .finally(() => {
        if (active) setStatsPending(false);
      });
    return () => {
      active = false;
    };
  }, [query, reloadKey]);

  // Named in LABELS' order: the figures first, then the lists.
  const failed = [...failures.stats, ...failures.lists];
  const error = partsFailedMessage(
    failed.map((part) => part.label),
    new Set(failed.filter((part) => part.kept).map((part) => part.label))
  );
  const pending = listsPending || statsPending;
  const stats = statsAnswer?.data ?? null;
  // The sign-ups shown are the dates' own: those read for other dates stay on screen (dimmed) only while
  // these are being read, never once their read has failed.
  const signupsShown = statsAnswer?.query === query || statsPending;
  const signups = signupsShown ? stats?.signups : undefined;

  const attention = useMemo(
    () =>
      lists
        ? attentionItems({
            homework: lists.homework,
            sessions: lists.sessions,
            additionalExams: lists.additionalExams,
            stats,
            canSeeInvitations,
          })
        : [],
    [lists, stats, canSeeInvitations]
  );
  const attentionTotal = attention.reduce((sum, item) => sum + item.count, 0);

  return (
    <div className="container mx-auto flex flex-col gap-5 px-4 py-16">
      {!lists || statsAnswer === undefined ? (
        <DashboardSkeleton />
      ) : (
        <>
          <DashboardHeader
            user={user}
            filter={
              <DashboardRangeFilter
                range={range}
                fallback={ACADEMICS_DEFAULT_RANGE}
                answered={signupsShown ? stats?.range : undefined}
                onPick={pickRange}
                onRefresh={refresh}
                pending={pending}
                className="sm:w-auto"
              />
            }
          />

          {error ? <ErrorState message={error} onRetry={refresh} pending={pending} /> : null}

          <KpiCards stats={stats} signups={signups} students={lists.students} sessions={lists.sessions} attentionTotal={attentionTotal} />

          <div className="grid min-w-0 gap-4 md:grid-cols-[3fr_2fr]">
            <UpcomingSessions sessions={lists.sessions} students={lists.students} />
            <NeedsAttention items={attention} actionTo={attentionTotal > 0 ? attention.find((i) => i.count > 0)?.to : undefined} />
          </div>

          <div className="grid min-w-0 gap-4 md:grid-cols-[3fr_2fr] md:items-start">
            <div className={statsPending ? 'opacity-70 transition-opacity' : undefined} aria-busy={statsPending || undefined}>
              <SignupsChart signups={signups} />
            </div>
            <RecentActivity rows={lists.activity} />
          </div>

          <RecentStudents students={lists.students} />
        </>
      )}
    </div>
  );
}
