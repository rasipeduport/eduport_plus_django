import { Link } from 'react-router-dom';
import { CalendarClock, CalendarDays, CalendarOff, ChevronRight, Sun } from 'lucide-react';
import { format } from 'date-fns';

import { indianToday } from '@/lib/bde-booking-filters';
import { isJoinable } from '@/lib/bookings';
import { bookingTypeLabel, slotLabel, slotParts } from '@/lib/enquiries';
import { isHttpsUrl } from '@/lib/exam-status';
import { sessionHours } from '@/lib/session-status';
import { AHEAD_ROWS, bookingPath, deviceKeepsIst } from '@/lib/tutor-dashboards';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { ReportStateBadge } from '@/components/bookings/booking-badges';
import { JoinMeetButton } from '@/components/bookings/meet-link';
import { Panel, PanelEmpty, ScrollList } from './dashboard-primitives';

// The Tutor Hub's Main and Admissions dashboards' lists of work in time order:
// today's on a timeline, what comes after today as a list. A Demo or
// Diagnostic booking reads in Indian time, as the booking pages show it, and
// opens its workspace (`from` is its way back); a regular class reads in this
// device's time, as the Sessions page shows it, and opens that student's classes.

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;
const studentName = (session) => session.students?.full_name || 'Student';
const classesPath = (session) => (session.student_id ? `/sessions?student_id=${session.student_id}` : '/sessions');
const byTime = (a, b) => a.at - b.at;
const todayLabel = () => slotParts(indianToday(), '00:00').day;

/** Small outline links to the pages a panel draws from, for its header. */
export function PanelLinks({ links }) {
  if (!links?.length) return null;
  return (
    <div className="flex flex-wrap justify-end gap-2">
      {links.map((link) => (
        <Button key={link.to} variant="outline" size="sm" asChild>
          <Link to={link.to}>{link.label}</Link>
        </Button>
      ))}
    </div>
  );
}

function Timeline({ entries, label }) {
  return (
    <ol aria-label={label}>
      {entries.map((entry) => (
        <li key={entry.key} className="group relative flex gap-3">
          <span className="w-16 shrink-0 pt-0.5 text-sm font-medium whitespace-nowrap tabular-nums">{entry.time}</span>
          <span className="flex flex-col items-center" aria-hidden="true">
            <span className={cn('mt-1.5 size-2.5 shrink-0 rounded-full ring-4', entry.dot)} />
            <span className="bg-border mt-1.5 w-px flex-1 group-last:hidden" />
          </span>
          <div className="flex min-w-0 flex-1 flex-wrap items-start justify-between gap-x-3 gap-y-2 pb-5 group-last:pb-0">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <Link to={entry.to} state={entry.state} className="hover:underline focus-visible:underline focus-visible:outline-none">
                  <span className="font-medium">{entry.kind}</span>
                  <span className="text-muted-foreground"> · </span>
                  <span className="font-medium">{entry.name}</span>
                </Link>
                {entry.badge}
              </div>
              {entry.meta ? <p className="text-muted-foreground mt-0.5 text-xs">{entry.meta}</p> : null}
            </div>
            {entry.action}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** A booking on today's timeline: its Indian time, type and student, where it stands, and its Meet room while it is to come. */
function bookingEntry(booking, from) {
  return {
    key: `booking-${booking.id}`,
    at: new Date(booking.slot.starts_at).getTime(),
    time: slotParts(booking.slot.date, booking.slot.time).time,
    dot: booking.booking_type === 'DIAGNOSTIC' ? 'bg-diagnostic ring-diagnostic/15' : 'bg-demo ring-demo/15',
    kind: bookingTypeLabel(booking.booking_type),
    name: booking.student_name,
    to: bookingPath(booking),
    state: from ? { from } : undefined,
    badge: <ReportStateBadge booking={booking} />,
    meta: [booking.grade, booking.syllabus].filter(Boolean).join(' · '),
    action: isJoinable(booking) ? (
      <JoinMeetButton link={booking.tutor_meet_link} label={`Join the Google Meet for ${booking.student_name}`} />
    ) : null,
  };
}

/** A regular class on today's timeline: its local time, student and title, and the student's Meet room until it ends. */
function classEntry(session, now) {
  const start = new Date(session.start_time);
  const ended = new Date(session.end_time) < now;
  const live = !ended && start <= now;
  const meetLink = (session.students?.meet_link || '').trim();
  return {
    key: `class-${session.id}`,
    at: start.getTime(),
    time: format(start, 'h:mm a'),
    dot: 'bg-foreground/50 ring-foreground/10',
    kind: 'Class',
    name: studentName(session),
    to: classesPath(session),
    badge: live ? <Badge variant="info">In progress</Badge> : ended ? <Badge variant="secondary">Ended</Badge> : null,
    meta: [session.title, `${Math.round(sessionHours(session) * 60)} mins`].filter(Boolean).join(' · '),
    action:
      !ended && isHttpsUrl(meetLink) ? (
        <JoinMeetButton link={meetLink} label={`Join the class with ${studentName(session)}`} />
      ) : null,
  };
}

/** Today's Demo classes and diagnostic tests (IST) on a timeline. */
export function TodaysBookings({ rows, total, from, links, className }) {
  const subtitle = total > rows.length ? `${todayLabel()} · the first ${rows.length} of ${total} · IST` : `${todayLabel()} · Indian time (IST)`;
  return (
    <Panel
      icon={CalendarDays}
      title="Today's Bookings"
      subtitle={subtitle}
      className={className}
      action={
        total > 0 || links?.length ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            {total > 0 ? (
              <Badge variant="secondary" className="tabular-nums">
                {plural(total, 'booking', 'bookings')}
              </Badge>
            ) : null}
            <PanelLinks links={links} />
          </div>
        ) : null
      }
    >
      {rows.length === 0 ? (
        <PanelEmpty icon={Sun} message="No Demo or Diagnostic bookings today" hint="The ones you are assigned for today appear here." />
      ) : (
        <Timeline entries={rows.map((booking) => bookingEntry(booking, from))} label="Today's bookings" />
      )}
    </Panel>
  );
}

/**
 * Today's work, both kinds on one timeline: the Demo and Diagnostic bookings
 * (Indian time) and the regular classes (this device's time, the same when it
 * keeps Indian time), ended ones included.
 */
export function TodaysWork({ bookings, bookingTotal, classes, from, links, className }) {
  const now = new Date();
  const entries = [...bookings.map((booking) => bookingEntry(booking, from)), ...classes.map((session) => classEntry(session, now))].sort(byTime);
  const zone = deviceKeepsIst(now) ? 'Indian time (IST)' : 'Bookings in IST, classes in your time';
  const subtitle =
    bookingTotal > bookings.length
      ? `${todayLabel()} · the first ${bookings.length} of ${bookingTotal} bookings · ${zone}`
      : `${todayLabel()} · ${zone}`;
  return (
    <Panel icon={CalendarDays} title="Today's Work" subtitle={subtitle} className={className} action={links?.length ? <PanelLinks links={links} /> : null}>
      {entries.length === 0 ? (
        <PanelEmpty icon={Sun} message="Nothing scheduled today" hint="Today's Demo and Diagnostic bookings and regular classes appear here." />
      ) : (
        <Timeline entries={entries} label="Today's work" />
      )}
    </Panel>
  );
}

function AheadList({ rows }) {
  return (
    <ScrollList total={rows.length} className="divide-y">
      {rows.map((row) => (
        <li key={row.key} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 first:pt-0 last:pb-0">
          <div className="min-w-0 flex-1 basis-48">
            <Link to={row.to} state={row.state} className="text-sm font-medium hover:underline">
              {row.name}
            </Link>
            <p className="text-muted-foreground text-xs">{row.meta}</p>
          </div>
          {row.badge}
          <ChevronRight className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
        </li>
      ))}
    </ScrollList>
  );
}

function bookingAhead(booking, from) {
  return {
    key: `booking-${booking.id}`,
    at: new Date(booking.slot.starts_at).getTime(),
    name: booking.student_name,
    to: bookingPath(booking),
    state: from ? { from } : undefined,
    meta: [slotLabel(booking.slot), booking.grade].filter(Boolean).join(' · '),
    badge: <BookingTypeBadge type={booking.booking_type} />,
  };
}

function classAhead(session) {
  const moment = format(new Date(session.start_time), 'EEE, d MMM · h:mm a');
  return {
    key: `class-${session.id}`,
    at: new Date(session.start_time).getTime(),
    name: studentName(session),
    to: classesPath(session),
    meta: [deviceKeepsIst() ? `${moment} IST` : moment, session.title].filter(Boolean).join(' · '),
    badge: <Badge variant="secondary">Class</Badge>,
  };
}

/** The Demo and Diagnostic bookings after today, soonest first (IST): the first page the API served of `total`. */
export function UpcomingBookings({ rows, total, from, links, className }) {
  return (
    <Panel
      icon={CalendarClock}
      title="Upcoming Bookings"
      subtitle={total > rows.length ? `After today · the next ${rows.length} of ${total} · IST` : 'After today · Indian time (IST)'}
      className={className}
      action={links?.length ? <PanelLinks links={links} /> : null}
    >
      {rows.length === 0 ? (
        <PanelEmpty icon={CalendarOff} message="No bookings after today" hint="Demo classes and diagnostic tests assigned to you appear here." />
      ) : (
        <AheadList rows={rows.map((booking) => bookingAhead(booking, from))} />
      )}
    </Panel>
  );
}

/** What comes after today, both kinds in one list -- the bookings (IST) and the regular classes -- soonest first, the next few only. */
export function UpcomingWork({ bookings, moreBookings, classes, from, links, className }) {
  const all = [...bookings.map((booking) => bookingAhead(booking, from)), ...classes.map(classAhead)].sort(byTime);
  const rows = all.slice(0, AHEAD_ROWS);
  const subtitle = moreBookings || all.length > rows.length ? `After today · the next ${rows.length}` : 'After today';
  return (
    <Panel icon={CalendarClock} title="Upcoming Work" subtitle={subtitle} className={className} action={links?.length ? <PanelLinks links={links} /> : null}>
      {rows.length === 0 ? (
        <PanelEmpty icon={CalendarOff} message="Nothing scheduled after today" hint="Your next bookings and regular classes appear here." />
      ) : (
        <AheadList rows={rows} />
      )}
    </Panel>
  );
}
