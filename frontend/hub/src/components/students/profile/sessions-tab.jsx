import { CalendarCheck, ExternalLink, Star } from 'lucide-react';
import { Link } from 'react-router-dom';
import { format } from 'date-fns';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { HOMEWORK_STATUS_VARIANT, homeworkStatusLabel } from '@/lib/homework-status';
import {
  SESSION_CONTENT_LABEL,
  sessionHours,
  sessionStatusKey,
  sessionStatusLabel,
  sessionStatusVariant,
} from '@/lib/session-status';
import { EMPTY, EmptyState, ProfileTable, SectionHeading, Td } from './profile-primitives';

const COLUMNS = [
  { key: 'when', label: 'When' },
  { key: 'title', label: 'Class' },
  { key: 'status', label: 'Status' },
  { key: 'tutor', label: 'Tutor' },
  { key: 'content', label: 'Content' },
  { key: 'homework', label: 'Homework' },
  { key: 'rating', label: 'Rating' },
];

function StatusCell({ session }) {
  const key = sessionStatusKey(session);
  const badge = <Badge variant={sessionStatusVariant(session)}>{sessionStatusLabel(session)}</Badge>;
  let hint = null;
  if (key === 'cancelled' && session.cancellation_reason) {
    hint = session.cancellation_reason;
  } else if (key === 'pending' && session.missing_content?.length) {
    hint = `Still missing: ${session.missing_content.map((item) => SESSION_CONTENT_LABEL[item] || item).join(', ')}`;
  }
  if (!hint) return badge;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-help">{badge}</span>
      </TooltipTrigger>
      <TooltipContent>
        <p className="max-w-xs">{hint}</p>
      </TooltipContent>
    </Tooltip>
  );
}

/** The three post-session links as small chips; absent ones are muted. */
function ContentCell({ session }) {
  const attended = (session.status || '').toLowerCase() === 'attended';
  const items = Object.entries(SESSION_CONTENT_LABEL).map(([field, label]) => {
    const url = (session[`${field}_link`] || '').trim();
    return { field, label, url };
  });
  if (!attended && !items.some((item) => item.url)) {
    return <span className="text-muted-foreground">{EMPTY}</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((item) =>
        item.url ? (
          <a
            key={item.field}
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:bg-accent inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs transition-colors"
          >
            {item.label}
            <ExternalLink className="size-3 opacity-60" />
          </a>
        ) : (
          <span
            key={item.field}
            className="text-muted-foreground/60 inline-flex items-center rounded-md border border-dashed px-1.5 py-0.5 text-xs"
          >
            {item.label}
          </span>
        )
      )}
    </div>
  );
}

/**
 * Sessions tab: this student's classes, read-only. Booking, rescheduling and
 * marking attended stay on /sessions — the one place those flows live — so
 * this panel reports rather than duplicating them.
 */
export function SessionsTab({ sessions, studentId, onOpenHomework }) {
  const attendedHours = sessions
    .filter((session) => (session.status || '').toLowerCase() !== 'cancelled')
    .reduce((total, session) => total + sessionHours(session), 0);

  return (
    <div className="flex flex-col gap-4">
      <SectionHeading
        title={`${sessions.length} ${sessions.length === 1 ? 'class' : 'classes'}`}
        description={`${Math.round(attendedHours * 10) / 10} hrs booked against the quota. Cancelled classes are not counted.`}
        action={
          <Button variant="outline" size="sm" asChild>
            <Link to={`/sessions?student_id=${studentId}`}>Manage in Sessions</Link>
          </Button>
        }
      />
      {sessions.length === 0 ? (
        <EmptyState
          icon={CalendarCheck}
          message="No classes booked yet."
          hint="Book the first one from the Sessions page."
        />
      ) : (
        <ProfileTable
          columns={COLUMNS}
          rows={sessions}
          keyOf={(session) => session.id}
          emptyMessage="No classes booked yet."
          renderRow={(session) => (
            <>
              <Td className="whitespace-nowrap">
                <span className="block text-sm">{format(new Date(session.start_time), 'd MMM yyyy')}</span>
                <span className="text-muted-foreground text-xs">
                  {format(new Date(session.start_time), 'h:mm a')} – {format(new Date(session.end_time), 'h:mm a')}
                </span>
              </Td>
              <Td>
                <span className="block max-w-56 truncate font-medium" title={session.title}>
                  {session.title}
                </span>
                {session.class_number ? (
                  <span className="text-muted-foreground text-xs">Class {session.class_number} of a series</span>
                ) : null}
              </Td>
              <Td>
                <StatusCell session={session} />
              </Td>
              <Td className="text-muted-foreground max-w-40 truncate text-sm">
                {session.tutor_profile?.full_name || session.tutor_profile?.email || EMPTY}
              </Td>
              <Td>
                <ContentCell session={session} />
              </Td>
              <Td>
                {session.homework ? (
                  <button
                    type="button"
                    onClick={() => onOpenHomework(session.homework.id)}
                    className="cursor-pointer"
                  >
                    <Badge variant={HOMEWORK_STATUS_VARIANT[session.homework.status] || 'secondary'}>
                      {homeworkStatusLabel(session.homework)}
                    </Badge>
                  </button>
                ) : (
                  <span className="text-muted-foreground">{EMPTY}</span>
                )}
              </Td>
              <Td className="whitespace-nowrap">
                {session.rating ? (
                  <span className="inline-flex items-center gap-1 text-sm tabular-nums">
                    <Star className="size-3.5 fill-current opacity-70" />
                    {session.rating}
                  </span>
                ) : (
                  <span className="text-muted-foreground">{EMPTY}</span>
                )}
              </Td>
            </>
          )}
        />
      )}
    </div>
  );
}
