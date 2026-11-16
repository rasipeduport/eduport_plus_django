import { Link } from 'react-router-dom';
import { CalendarCheck, CheckCircle2, FileClock, MessageSquareText } from 'lucide-react';

import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
import { reportWords } from '@/lib/reports';
import { bookingPath } from '@/lib/tutor-dashboards';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { FeedbackBadge } from '@/components/bookings/booking-badges';
import { TutorReportLink } from '@/components/reports/tutor-report-link';
import { Panel, PanelEmpty, ScrollList } from './dashboard-primitives';
import { PanelLinks } from './tutor-work';

// The Tutor Hub's Main and Admissions dashboards' report lists: the classes
// taught whose report is still due, and the bookings completed with theirs
// in. `from` is the way back for each booking or report opened from them.

// One type's pending list, or both (no type).
const PENDING = {
  DEMO: {
    icon: MessageSquareText,
    title: 'Pending Demo Feedback',
    done: 'Every Demo class you taught has its feedback in.',
  },
  DIAGNOSTIC: {
    icon: FileClock,
    title: 'Pending Diagnostic Results',
    done: 'Every diagnostic test you taught has its results in.',
  },
  BOTH: {
    icon: FileClock,
    title: 'Pending Feedback & Results',
    done: 'Every class you taught has its feedback or results in.',
  },
};

/**
 * The classes taught whose feedback (Demo) or results (Diagnostic) are still
 * due -- one `type`'s, or both -- newest class first, each with its way to
 * write them. `total` is how many the API counts; `rows`, the ones it served.
 */
export function PendingReports({ type, rows, total, from, links, className }) {
  const shown = PENDING[type] ?? PENDING.BOTH;
  const state = from ? { from } : undefined;
  return (
    <Panel
      icon={shown.icon}
      title={shown.title}
      subtitle={total > rows.length ? `The latest ${rows.length} of ${total} · Indian time (IST)` : 'Taught, the report not in yet · IST'}
      className={className}
      action={
        total > 0 || links?.length ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            {total > 0 ? (
              <Badge variant="warning" className="tabular-nums">
                {total} pending
              </Badge>
            ) : null}
            <PanelLinks links={links} />
          </div>
        ) : null
      }
    >
      {rows.length === 0 ? (
        <div className="bg-success/10 border-success/20 flex items-start gap-3 rounded-lg border px-3 py-2.5">
          <CheckCircle2 className="text-success mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-success text-sm font-medium">All caught up</p>
            <p className="text-muted-foreground text-xs">{shown.done}</p>
          </div>
        </div>
      ) : (
        <ScrollList total={rows.length} className="divide-y">
          {rows.map((booking) => (
            <li key={booking.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1 basis-40">
                <Link to={bookingPath(booking)} state={state} className="text-sm font-medium hover:underline">
                  {booking.student_name}
                </Link>
                <p className="text-muted-foreground text-xs">
                  {[type ? null : bookingTypeLabel(booking.booking_type), slotLabel(booking.slot), booking.grade]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              </div>
              <FeedbackBadge booking={booking} />
              <TutorReportLink booking={booking} state={state} />
            </li>
          ))}
        </ScrollList>
      )}
    </Panel>
  );
}

/** The bookings completed most recently -- taught, their report in -- each opening its feedback or results. */
export function RecentlyCompleted({ rows, total, from, links, className }) {
  const state = from ? { from } : undefined;
  return (
    <Panel
      icon={CalendarCheck}
      title="Recently Completed"
      subtitle={total > rows.length ? `The latest ${rows.length} of ${total} · Indian time (IST)` : 'Taught, the report in · Indian time (IST)'}
      className={className}
      action={links?.length ? <PanelLinks links={links} /> : null}
    >
      {rows.length === 0 ? (
        <PanelEmpty icon={CalendarCheck} message="No completed bookings yet" hint="A booking is completed once its feedback or results are submitted." />
      ) : (
        <ScrollList total={rows.length} className="divide-y">
          {rows.map((booking) => {
            const words = reportWords(booking.booking_type);
            return (
              <li key={booking.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 first:pt-0 last:pb-0">
                <div className="min-w-0 flex-1 basis-44">
                  <Link to={bookingPath(booking)} state={state} className="text-sm font-medium hover:underline">
                    {booking.student_name}
                  </Link>
                  <p className="text-muted-foreground text-xs">{[slotLabel(booking.slot), booking.grade].filter(Boolean).join(' · ')}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <BookingTypeBadge type={booking.booking_type} />
                  <FeedbackBadge booking={booking} />
                </div>
                <Button variant="outline" size="sm" asChild>
                  <Link
                    to={`${bookingPath(booking)}?tab=feedback`}
                    state={state}
                    aria-label={`View the ${words.noun} for ${booking.student_name}`}
                  >
                    View {words.noun}
                  </Link>
                </Button>
              </li>
            );
          })}
        </ScrollList>
      )}
    </Panel>
  );
}
