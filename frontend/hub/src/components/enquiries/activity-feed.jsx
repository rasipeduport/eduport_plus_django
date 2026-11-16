import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/badge';
import { enquiryBookingPath } from '@/lib/enquiries';
import { activitySentence } from '@/lib/follow-ups';
import { formatDateInZone, formatTimeInZone, utcToZonedWallTime } from '@/lib/timezone';
import { cn } from '@/lib/utils';

// Activity is read in Indian time, the zone the slots are booked in.
const INDIAN_TIME = 'Asia/Kolkata';

function dayLabel(date, at) {
  const today = utcToZonedWallTime(new Date(), INDIAN_TIME).date;
  const yesterday = utcToZonedWallTime(new Date(Date.now() - 86_400_000), INDIAN_TIME).date;
  if (date === today) return 'Today';
  if (date === yesterday) return 'Yesterday';
  return formatDateInZone(at, INDIAN_TIME);
}

/** `rows` (newest first) grouped by their Indian date, keeping the order. */
function byDay(rows) {
  const days = [];
  for (const row of rows) {
    const date = utcToZonedWallTime(row.at, INDIAN_TIME).date;
    const last = days.at(-1);
    if (last?.date === date) last.rows.push(row);
    else days.push({ date, label: dayLabel(date, row.at), rows: [row] });
  }
  return days;
}

/**
 * What has happened to the BDE's bookings, newest first, a day at a time in
 * Indian time: each event in a sentence, with whose booking it was (a link to
 * it in its enquiry's workspace, unless `inEnquiry`) and whether it was the
 * BDE's own doing. The API sends nothing of who else acted, or why.
 */
export function ActivityFeed({ rows, inEnquiry = false, from = null }) {
  return (
    <div className="flex flex-col gap-5">
      {byDay(rows).map((day) => (
        <section key={day.date} aria-label={day.label} className="flex flex-col gap-2">
          <h2 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{day.label}</h2>
          <ol className="bg-card divide-y rounded-xl border">
            {day.rows.map((row) => (
              <li key={row.id} className="flex items-start gap-3 px-4 py-3">
                <span
                  aria-hidden="true"
                  className={cn(
                    'mt-1.5 size-2.5 shrink-0 rounded-full',
                    row.booking.booking_type === 'DIAGNOSTIC' ? 'bg-diagnostic' : 'bg-demo'
                  )}
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">
                    {activitySentence(row)}
                    {row.by_you ? (
                      <Badge variant="secondary" className="ml-2 align-middle">
                        By you
                      </Badge>
                    ) : null}
                  </p>
                  {inEnquiry ? null : (
                    <p className="text-muted-foreground text-xs">
                      <Link
                        to={enquiryBookingPath(row.enquiry.id, row.booking.id)}
                        state={from ? { from } : undefined}
                        className="text-link font-medium hover:underline"
                      >
                        {row.enquiry.student_name}
                      </Link>
                      {[row.enquiry.grade, row.enquiry.parent_name].filter(Boolean).map((part) => ` · ${part}`)}
                    </p>
                  )}
                </div>
                <time dateTime={row.at} className="text-muted-foreground shrink-0 text-xs whitespace-nowrap tabular-nums">
                  {formatTimeInZone(row.at, INDIAN_TIME)}
                </time>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
