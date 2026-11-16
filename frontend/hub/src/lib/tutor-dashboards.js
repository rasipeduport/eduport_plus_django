// What the Tutor Hub's Main Dashboard (pages/TutorMainDashboardPage) and
// Admissions Dashboard (pages/TutorAdmissionsDashboardPage) read and how they
// count it. Every figure comes from a list the Hub already serves a tutor --
// their own bookings (GET /api/tutor/bookings/, filtered by the API), sessions,
// students, homework, additional exams and their own activity -- never from a
// sum of its own. (The Academics Dashboard is pages/DashboardPage, the staff dashboard.)
import { FileClock, MessageSquareText, PlayCircle, VideoOff } from 'lucide-react';

import api from '@/lib/api';
import { indianToday } from '@/lib/bde-booking-filters';
import { TUTOR_BOOKINGS_URL, isJoinable, tutorBookingPagePath, tutorBookingsPagePath } from '@/lib/bookings';

// Each dashboard is also the way back for a booking opened from it
// (location.state.from), which keeps its own sidebar item current there.
export const TUTOR_DASHBOARDS = {
  main: { to: '/dashboard', label: 'Main Dashboard' },
  admissions: { to: '/admissions-dashboard', label: 'Admissions Dashboard' },
  academics: { to: '/academics-dashboard', label: 'Academics Dashboard' },
};

// One page of each booking list is read: enough for a tutor's day and their
// reports due. A dashboard lists at most AHEAD_ROWS of what comes after today.
export const LIST_ROWS = 50;
export const AHEAD_ROWS = 20;

// The activity log's entries about Demo and Diagnostic work a tutor does:
// starting and completing a booking, and submitting and editing its report.
export const ADMISSIONS_ENTITIES = ['booking', 'report'];

/** One page of the signed-in tutor's own bookings: a single row (only its count is wanted) unless `page_size` says otherwise. */
export const tutorBookings = (params) => api.get(TUTOR_BOOKINGS_URL, { params: { page: 1, page_size: 1, ...params } });

/** What one of Promise.allSettled's results answered: null when it failed or was never asked. */
export const settledData = (result) => (result.status === 'fulfilled' && result.value ? result.value.data : null);

/** The Indian date after today, as YYYY-MM-DD: where "after today" starts for the booking lists' class dates. */
export function indianTomorrow(now = new Date()) {
  const [year, month, day] = indianToday(now).split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day + 1)).toISOString().slice(0, 10);
}

/** A booking's workspace. */
export const bookingPath = (booking) => tutorBookingPagePath(booking.booking_type, booking.id);

/** A type's list with every booking of it. */
export const allBookingsPath = (type) => `${tutorBookingsPagePath(type)}?view=all`;

/** A type's list at the classes taught whose feedback (Demo) or results (Diagnostic) are still due. */
export const pendingReportsPath = (type) => `${tutorBookingsPagePath(type)}?view=completed&feedback=due`;

/** How many of `bookings` are Demo classes and how many diagnostic tests. */
export function countByType(bookings) {
  return {
    DEMO: bookings.filter((booking) => booking.booking_type === 'DEMO').length,
    DIAGNOSTIC: bookings.filter((booking) => booking.booking_type === 'DIAGNOSTIC').length,
  };
}

/** Bookings newest class first. */
export const byLatestClass = (a, b) => new Date(b.slot.starts_at) - new Date(a.slot.starts_at);

/**
 * What needs the tutor's hand on their bookings, as Needs Attention rows:
 * today's classes whose time has come without a start, the Demo feedback and
 * Diagnostic results due (the API's counts), and the classes still to come --
 * today's not yet ended (`today`) and the ones after today (`later`) -- with
 * no Meet room to teach in. `home` is where a row with nothing to open points.
 */
export function bookingAttention({ today, later, demoFeedbackDue, diagnosticResultsDue, home }) {
  const late = today.filter((booking) => booking.status === 'BOOKED' && booking.activity_state === 'LATE');
  const noMeet = [...today.filter(isJoinable), ...later].filter((booking) => !booking.tutor_meet_link);
  return [
    {
      key: 'late',
      icon: PlayCircle,
      label: 'Classes to start now',
      count: late.length,
      to: late[0] ? bookingPath(late[0]) : home,
    },
    {
      key: 'feedback',
      icon: MessageSquareText,
      label: 'Demo feedback due',
      count: demoFeedbackDue,
      to: pendingReportsPath('DEMO'),
    },
    {
      key: 'results',
      icon: FileClock,
      label: 'Diagnostic results due',
      count: diagnosticResultsDue,
      to: pendingReportsPath('DIAGNOSTIC'),
    },
    {
      key: 'meet',
      icon: VideoOff,
      label: 'Upcoming bookings without a Meet link',
      count: noMeet.length,
      to: noMeet[0] ? bookingPath(noMeet[0]) : home,
    },
  ];
}

const isScheduled = (session) => (session.status || '').toLowerCase() === 'scheduled';

/** Scheduled classes that start after today's local date, soonest first (lib/session-day keeps today's). */
export function classesAfterToday(sessions, now = new Date()) {
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).getTime();
  return sessions
    .filter((session) => isScheduled(session) && new Date(session.start_time).getTime() >= tomorrow)
    .sort((a, b) => new Date(a.start_time) - new Date(b.start_time));
}

/** Whether this device keeps Indian time, so a regular class's local time (as the Sessions page shows it) is IST too. */
export const deviceKeepsIst = (now = new Date()) => now.getTimezoneOffset() === -330;
