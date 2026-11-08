import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertCircle, CalendarCheck, CalendarCheck2, CalendarDays, FileClock, GraduationCap, LayoutGrid, School } from 'lucide-react';

import api from '@/lib/api';
import { ACTIVITY_VIEW, EXAM_VIEW, HOMEWORK_VIEW, PERMISSIONS, SESSION_VIEW, STUDENT_VIEW, can, canAny, canOpenPage } from '@/lib/access';
import { indianToday } from '@/lib/bde-booking-filters';
import { bookingError } from '@/lib/bookings';
import { sessionsToday } from '@/lib/session-day';
import {
  AHEAD_ROWS,
  LIST_ROWS,
  TUTOR_DASHBOARDS,
  bookingAttention,
  byLatestClass,
  classesAfterToday,
  indianTomorrow,
  pendingReportsPath,
  settledData,
  tutorBookings,
} from '@/lib/tutor-dashboards';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { DashboardHeader } from '@/components/dashboard/dashboard-header';
import { Tile } from '@/components/dashboard/kpi-cards';
import { NeedsAttention, attentionItems } from '@/components/dashboard/needs-attention';
import { RecentActivity } from '@/components/dashboard/recent-activity';
import { PendingReports } from '@/components/dashboard/tutor-reports';
import { TodaysWork, UpcomingWork } from '@/components/dashboard/tutor-work';
import { Page } from '@/components/page/page';
import { ErrorState } from '@/components/page/states';

const ACTIVITY_ROWS = 25;
const FROM = TUTOR_DASHBOARDS.main;
const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;
const isActive = (student) => (student.status || 'active').toLowerCase() === 'active';

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
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

/**
 * The Tutor Hub's Main Dashboard: the signed-in tutor's work across
 * Admissions -- the Demo and Diagnostic bookings they are assigned -- and
 * Academics -- their regular classes. The headline numbers, today's work on
 * one timeline, what needs their hand, what comes after today, the feedback
 * and results still due and their latest activity; the detail is on the
 * Admissions and Academics dashboards and the pages they open. Everything is
 * read from APIs the Hub already serves a tutor, each only with its
 * permission: their bookings (GET /api/tutor/bookings/, filtered by the API --
 * only ever their own), sessions, students, homework, additional exams and
 * their own activity. Each request fails on its own, so one refused list only
 * blanks its own part.
 */
export default function TutorMainDashboardPage({ user }) {
  const canSeeBookings = can(user, PERMISSIONS.viewAssignedBookings);
  const canSeeSessions = canAny(user, SESSION_VIEW);
  const canSeeStudents = canAny(user, STUDENT_VIEW);
  const canSeeHomework = canAny(user, HOMEWORK_VIEW);
  const canSeeExams = canAny(user, EXAM_VIEW);
  const canSeeActivity = canAny(user, ACTIVITY_VIEW);
  const [data, setData] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    const today = indianToday();
    const optional = (allowed, request) => (allowed ? request() : Promise.resolve(null));
    const bookings = (params) => optional(canSeeBookings, () => tutorBookings(params));

    (async () => {
      const results = await Promise.allSettled([
        bookings({ type: 'DEMO', when: 'all' }),
        bookings({ type: 'DIAGNOSTIC', when: 'all' }),
        bookings({ when: 'all', from: today, to: today, page_size: LIST_ROWS }),
        bookings({ when: 'upcoming', status: 'BOOKED', from: indianTomorrow(), page_size: AHEAD_ROWS }),
        bookings({ type: 'DEMO', when: 'completed', report: 'due', page_size: LIST_ROWS }),
        bookings({ type: 'DIAGNOSTIC', when: 'completed', report: 'due', page_size: LIST_ROWS }),
        bookings({ when: 'completed', status: 'COMPLETED' }),
        optional(canSeeSessions, () => api.get('/api/sessions/')),
        optional(canSeeStudents, () => api.get('/api/students/')),
        optional(canSeeHomework, () => api.get('/api/homework/')),
        optional(canSeeExams, () => api.get('/api/additional-exams/')),
        optional(canSeeActivity, () => api.get('/api/activity/', { params: { page: 1, page_size: ACTIVITY_ROWS } })),
      ]);
      if (!active) return;
      const [demo, diagnostic, todays, later, demoDue, diagnosticDue, completed, sessions, students, homework, exams, activity] =
        results;
      const refused = results.slice(0, 7).find((result) => result.status === 'rejected');
      const list = (result, pick) => {
        const value = settledData(result);
        return value ? pick(value) : null;
      };
      setData({
        bookingsFailure: refused ? bookingError(refused.reason, 'Some of your bookings could not be loaded.') : null,
        demo: settledData(demo),
        diagnostic: settledData(diagnostic),
        todays: settledData(todays),
        later: settledData(later),
        demoDue: settledData(demoDue),
        diagnosticDue: settledData(diagnosticDue),
        completed: settledData(completed),
        sessions: list(sessions, (d) => d.sessions ?? []),
        students: list(students, (d) => (Array.isArray(d) ? d : [])),
        homework: list(homework, (d) => d.homework ?? []),
        // null (not an empty list) when this account is not served exams, so
        // Needs Attention leaves the row out rather than showing a false zero.
        additionalExams: list(exams, (d) => d.additional_exams ?? []),
        activity: list(activity, (d) => d.results ?? []),
      });
    })();

    return () => {
      active = false;
    };
  }, [canSeeBookings, canSeeSessions, canSeeStudents, canSeeHomework, canSeeExams, canSeeActivity, reloadKey]);

  let content;
  if (!data) {
    content = <DashboardSkeleton />;
  } else {
    const count = (page) => page?.count ?? 0;
    const todayRows = data.todays?.results ?? [];
    const laterRows = data.later?.results ?? [];
    const classesToday = data.sessions ? sessionsToday(data.sessions) : [];
    const bookingsToday = count(data.todays);
    const demoDue = count(data.demoDue);
    const diagnosticDue = count(data.diagnosticDue);
    const pending = demoDue + diagnosticDue;
    const pendingRows = [...(data.demoDue?.results ?? []), ...(data.diagnosticDue?.results ?? [])].sort(byLatestClass);
    // One type due opens its own list; both, the Admissions Dashboard.
    const pendingTo =
      demoDue > 0 && diagnosticDue > 0 ? TUTOR_DASHBOARDS.admissions.to : pendingReportsPath(demoDue > 0 ? 'DEMO' : 'DIAGNOSTIC');

    const attention = [
      ...(canSeeBookings
        ? bookingAttention({
            today: todayRows,
            later: laterRows,
            demoFeedbackDue: demoDue,
            diagnosticResultsDue: diagnosticDue,
            home: TUTOR_DASHBOARDS.admissions.to,
          })
        : []),
      // The staff dashboard's own rows, each only when its list was read.
      ...attentionItems({
        homework: data.homework ?? [],
        sessions: data.sessions ?? [],
        additionalExams: data.additionalExams,
        stats: null,
        canSeeInvitations: false,
      }).filter((item) => (item.key === 'homework' ? data.homework : item.key === 'content' ? data.sessions : true)),
    ];
    const attentionTotal = attention.reduce((sum, item) => sum + item.count, 0);

    const todayParts = [
      canSeeBookings ? `${bookingsToday} Demo/Diagnostic` : null,
      data.sessions ? plural(classesToday.length, 'regular class', 'regular classes') : null,
    ].filter(Boolean);
    const tiles = [
      canSeeBookings && {
        key: 'assigned',
        icon: CalendarCheck2,
        tone: 'default',
        label: 'Assigned Bookings',
        value: count(data.demo) + count(data.diagnostic),
        hint: `${count(data.demo)} Demo · ${count(data.diagnostic)} Diagnostic`,
        to: TUTOR_DASHBOARDS.admissions.to,
      },
      {
        key: 'today',
        icon: CalendarDays,
        tone: 'info',
        label: "Today's Work",
        value: (canSeeBookings ? bookingsToday : 0) + classesToday.length,
        hint: todayParts.join(' · ') || 'Nothing scheduled today',
      },
      canSeeBookings && {
        key: 'pending',
        icon: FileClock,
        tone: pending > 0 ? 'warning' : 'default',
        label: 'Pending Feedback & Results',
        value: pending,
        hint: pending > 0 ? `${demoDue} Demo feedback · ${diagnosticDue} Diagnostic results` : 'All caught up',
        hintTone: pending > 0 ? 'warning' : 'muted',
        to: pending > 0 ? pendingTo : undefined,
      },
      canSeeBookings && {
        key: 'completed',
        icon: CalendarCheck,
        tone: 'success',
        label: 'Completed Bookings',
        value: count(data.completed),
        hint: 'Demo and Diagnostic, report in',
        to: TUTOR_DASHBOARDS.admissions.to,
      },
      data.students && {
        key: 'students',
        icon: GraduationCap,
        tone: 'default',
        label: 'Academic Students',
        value: data.students.length,
        hint: `${data.students.filter(isActive).length} active`,
        to: '/students',
      },
      {
        key: 'attention',
        icon: AlertCircle,
        tone: attentionTotal > 0 ? 'destructive' : 'default',
        label: 'Needs Attention',
        value: attentionTotal,
        hint: attentionTotal > 0 ? plural(attentionTotal, 'item needs you', 'items need you') : 'All clear',
        hintTone: attentionTotal > 0 ? 'warning' : 'muted',
      },
    ].filter(Boolean);

    // The pages behind both kinds of work, for the panels' headers.
    const workLinks = [
      canSeeBookings && { to: TUTOR_DASHBOARDS.admissions.to, label: 'Admissions' },
      canSeeSessions && { to: '/sessions', label: 'Sessions' },
    ].filter(Boolean);
    const pendingLinks = [
      { to: pendingReportsPath('DEMO'), label: 'Demo' },
      { to: pendingReportsPath('DIAGNOSTIC'), label: 'Diagnostic' },
    ];

    content = (
      <>
        {data.bookingsFailure ? (
          <ErrorState message={data.bookingsFailure.message} onRetry={() => setReloadKey((key) => key + 1)} />
        ) : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {tiles.map(({ key, ...tile }) => (
            <Tile key={key} {...tile} />
          ))}
        </div>

        <div className="grid min-w-0 gap-4 xl:grid-cols-5 xl:items-start">
          <TodaysWork
            bookings={todayRows}
            bookingTotal={bookingsToday}
            classes={classesToday}
            from={FROM}
            links={workLinks}
            className="xl:col-span-3"
          />
          <div className="min-w-0 xl:col-span-2">
            <NeedsAttention items={attention} />
          </div>
        </div>

        <div className="grid min-w-0 gap-4 xl:grid-cols-5 xl:items-start">
          <UpcomingWork
            bookings={laterRows}
            moreBookings={count(data.later) > laterRows.length}
            classes={data.sessions ? classesAfterToday(data.sessions) : []}
            from={FROM}
            links={workLinks}
            className={canSeeBookings ? 'xl:col-span-3' : 'xl:col-span-5'}
          />
          {canSeeBookings ? (
            <PendingReports rows={pendingRows} total={pending} from={FROM} links={pendingLinks} className="xl:col-span-2" />
          ) : null}
        </div>

        {data.activity ? <RecentActivity rows={data.activity} /> : null}
      </>
    );
  }

  return (
    <Page>
      <DashboardHeader user={user} subtitle="Your admissions and academic work at a glance." />
      <div className="flex flex-wrap gap-2">
        {canOpenPage(user, TUTOR_DASHBOARDS.admissions.to) ? (
          <Button variant="outline" asChild>
            <Link to={TUTOR_DASHBOARDS.admissions.to}>
              <LayoutGrid />
              Admissions Dashboard
            </Link>
          </Button>
        ) : null}
        {canOpenPage(user, TUTOR_DASHBOARDS.academics.to) ? (
          <Button variant="outline" asChild>
            <Link to={TUTOR_DASHBOARDS.academics.to}>
              <School />
              Academics Dashboard
            </Link>
          </Button>
        ) : null}
      </div>
      {content}
    </Page>
  );
}
