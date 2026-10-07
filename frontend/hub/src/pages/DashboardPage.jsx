import { useEffect, useMemo, useState } from 'react';

import api from '@/lib/api';
import { Skeleton } from '@/components/ui/skeleton';
import { DashboardHeader } from '@/components/dashboard/dashboard-header';
import { KpiCards } from '@/components/dashboard/kpi-cards';
import { UpcomingSessions } from '@/components/dashboard/upcoming-sessions';
import { NeedsAttention, attentionItems } from '@/components/dashboard/needs-attention';
import { SignupsChart } from '@/components/dashboard/signups-chart';
import { RecentActivity } from '@/components/dashboard/recent-activity';
import { RecentStudents } from '@/components/dashboard/recent-students';

// One page of the log is fetched; the card shows five at a time and scrolls for the rest.
const ACTIVITY_ROWS = 25;

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
 * The staff dashboard. Everything on it is read from endpoints the Hub
 * already serves this role: the stats endpoint (totals, sign-ups) plus the
 * students, sessions, homework and activity lists, and additional exams for
 * admins and mentors. Each request fails on its own, so one slow or refused
 * list only blanks its own panel.
 */
export default function DashboardPage({ user }) {
  const role = user?.role || 'ADMIN';
  const canSeeExams = role !== 'TUTOR';

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;

    (async () => {
      const requests = [
        api.get('/api/dashboard/stats/'),
        api.get('/api/students/'),
        api.get('/api/sessions/'),
        api.get('/api/homework/'),
        api.get('/api/activity/', { params: { page: 1, page_size: ACTIVITY_ROWS } }),
        canSeeExams ? api.get('/api/additional-exams/') : Promise.resolve(null),
      ];
      const [stats, students, sessions, homework, activity, additional] = await Promise.allSettled(requests);
      if (!active) return;

      const value = (result, pick) => (result.status === 'fulfilled' && result.value ? pick(result.value.data) : null);
      setData({
        stats: value(stats, (d) => d),
        students: value(students, (d) => (Array.isArray(d) ? d : [])) ?? [],
        sessions: value(sessions, (d) => d.sessions ?? []) ?? [],
        homework: value(homework, (d) => d.homework ?? []) ?? [],
        activity: value(activity, (d) => d.results ?? []) ?? [],
        // null (not an empty list) when this role is not served exams, so the
        // attention list leaves the row out rather than showing a false zero.
        additionalExams: canSeeExams ? (value(additional, (d) => d.additional_exams ?? []) ?? []) : null,
      });
      if (stats.status === 'rejected') {
        console.error('Stats loading failed', stats.reason);
        setError(stats.reason?.response?.data?.message || 'Some dashboard figures could not be loaded.');
      }
      setLoading(false);
    })();

    return () => {
      active = false;
    };
  }, [canSeeExams]);

  const attention = useMemo(
    () =>
      data
        ? attentionItems({
            homework: data.homework,
            sessions: data.sessions,
            additionalExams: data.additionalExams,
            stats: data.stats,
            role,
          })
        : [],
    [data, role]
  );
  const attentionTotal = attention.reduce((sum, item) => sum + item.count, 0);

  return (
    <div className="container mx-auto flex flex-col gap-5 px-4 py-16">
      {loading || !data ? (
        <DashboardSkeleton />
      ) : (
        <>
          <DashboardHeader user={user} />

          {error && <p className="text-destructive text-sm">{error}</p>}

          <KpiCards stats={data.stats} students={data.students} sessions={data.sessions} attentionTotal={attentionTotal} />

          <div className="grid min-w-0 gap-4 md:grid-cols-[3fr_2fr]">
            <UpcomingSessions sessions={data.sessions} students={data.students} />
            <NeedsAttention items={attention} actionTo={attentionTotal > 0 ? attention.find((i) => i.count > 0)?.to : undefined} />
          </div>

          <div className="grid min-w-0 gap-4 md:grid-cols-[3fr_2fr] md:items-start">
            <SignupsChart students={data.students} />
            <RecentActivity rows={data.activity} />
          </div>

          <RecentStudents students={data.students} />
        </>
      )}
    </div>
  );
}
