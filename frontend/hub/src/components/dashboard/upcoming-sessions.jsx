import { Link } from 'react-router-dom';
import { ArrowRight, CalendarDays, CalendarOff, Clock, Video } from 'lucide-react';
import { format } from 'date-fns';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { isHttpsUrl } from '@/lib/exam-status';
import { remainingToday } from '@/lib/session-day';
import { sessionHours } from '@/lib/session-status';
import { getInitials } from '@/lib/utils';
import { Panel, PanelEmpty, ScrollList } from './dashboard-primitives';

const MAX_VISIBLE = 5;

function SessionRow({ session, grade }) {
  const student = session.students || {};
  const name = student.full_name || '—';
  const studentId = session.student_id || session.student?.id || null;
  const meetLink = (student.meet_link || '').trim();
  const start = new Date(session.start_time);
  const minutes = Math.round(sessionHours(session) * 60);
  const tutor = session.tutor_profile?.full_name || session.tutor_profile?.email || null;
  const meta = [grade, session.title].filter(Boolean).join(' · ');

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3 first:pt-0 last:pb-0">
      <div className="flex min-w-0 flex-1 basis-48 items-center gap-3">
        <Avatar className="size-9 rounded-full">
          <AvatarImage src={student.avatar_url || undefined} alt={name} className="size-9 rounded-full object-cover" />
          <AvatarFallback className="size-9 rounded-full text-xs">{getInitials(name, null)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{name}</p>
          <p className="text-muted-foreground truncate text-xs">{meta || session.title}</p>
        </div>
      </div>

      <div className="flex min-w-0 basis-full items-center gap-x-5 gap-y-1 text-xs sm:basis-auto sm:flex-1">
        <div className="min-w-0">
          <p className="text-sm font-medium whitespace-nowrap">{format(start, 'h:mm a')}</p>
          <p className="text-muted-foreground inline-flex items-center gap-1 whitespace-nowrap">
            <Clock className="size-3" />
            {minutes} mins
          </p>
        </div>
        {tutor ? (
          <div className="min-w-0 border-l pl-5">
            <p className="text-muted-foreground">Tutor</p>
            <p className="truncate text-sm font-medium">{tutor}</p>
          </div>
        ) : null}
      </div>

      <div className="ml-auto shrink-0">
        {isHttpsUrl(meetLink) ? (
          <Button size="sm" asChild>
            <a href={meetLink} target="_blank" rel="noopener noreferrer">
              <Video className="size-4" />
              Join
            </a>
          </Button>
        ) : studentId ? (
          <Button size="sm" variant="outline" asChild>
            <Link to={`/sessions?student_id=${studentId}`}>
              View
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        ) : null}
      </div>
    </li>
  );
}

/**
 * Today's classes that are still to come, across the caller's students --
 * only today's: tomorrow's never fill the list, however short it is. Grades
 * come from the students list (the session payload carries only the
 * student's name, avatar and meet room).
 */
export function UpcomingSessions({ sessions, students }) {
  const now = new Date();
  const rows = remainingToday(sessions, now);
  const gradeOf = new Map(students.map((s) => [s.id, s.grade]));
  const gradeByCode = new Map(students.map((s) => [s.student_code, s.grade]));

  return (
    <Panel icon={CalendarDays} title="Upcoming Sessions" subtitle={`Today · ${format(now, 'EEEE, d MMM yyyy')}`} actionTo="/sessions">
      {rows.length === 0 ? (
        <PanelEmpty icon={CalendarOff} message="No upcoming sessions" hint="Nothing else is scheduled for today." />
      ) : (
        <ScrollList maxRows={MAX_VISIBLE} total={rows.length} className="divide-y">
          {rows.map((session) => (
            <SessionRow
              key={session.id}
              session={session}
              grade={gradeOf.get(session.student_id) ?? gradeByCode.get(session.students?.student_code) ?? null}
            />
          ))}
        </ScrollList>
      )}
    </Panel>
  );
}
