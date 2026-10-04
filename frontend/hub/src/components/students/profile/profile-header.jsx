import { ArrowLeft, Video } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { getInitials } from '@/lib/utils';
import { ActionCell } from '../action-cell';
import { StudentStatusBadge } from './profile-primitives';

/**
 * Identity strip at the top of a student profile: who this is, what state
 * their enrolment is in, and the same row actions the students table offers,
 * so opening a profile never means going back to the list to act.
 *
 * Tutors get the identity half only — their table row has no action menu
 * either, just a way into the student's classes.
 */
export function ProfileHeader({ student, role, onChanged }) {
  const name = student.full_name;
  const email = student.profile?.email ?? null;
  const meetLink = (student.meet_link || '').trim();
  // Mentors and admins share the row action menu; a tutor's row has none.
  const canAct = role === 'admin' || role === 'mentor';
  // Grades are stored as the school writes them ("10", "Grade 10", "Year 9"),
  // so the label is only added when the value does not already carry one.
  const grade = (student.grade || '').trim();
  const gradeLabel = !grade || /grade|year|class/i.test(grade) ? grade : `Grade ${grade}`;
  const subtitle = [gradeLabel, student.syllabus, student.school_name].filter(Boolean).join(' · ');

  return (
    <div className="flex flex-col gap-4">
      <Button variant="ghost" size="sm" className="text-muted-foreground -ml-2 w-fit" asChild>
        <Link to="/students">
          <ArrowLeft className="size-4" />
          Students
        </Link>
      </Button>

      <div className="flex flex-wrap items-start gap-4">
        <Avatar className="size-12 rounded-full">
          <AvatarImage
            src={student.profile?.avatar_url || undefined}
            alt={name || email || 'Student'}
            className="size-12 rounded-full object-cover"
          />
          <AvatarFallback className="size-12 rounded-full text-sm">{getInitials(name, email)}</AvatarFallback>
        </Avatar>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-xl font-semibold">{name}</h1>
            <StudentStatusBadge status={student.status} note={student.status_note} />
          </div>
          <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="font-mono">{student.student_code}</span>
            {subtitle ? (
              <>
                <span aria-hidden="true">·</span>
                <span className="truncate">{subtitle}</span>
              </>
            ) : null}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {meetLink ? (
            <Button variant="outline" size="sm" asChild>
              <a href={meetLink} target="_blank" rel="noopener noreferrer">
                <Video className="size-4" />
                Join Meet
              </a>
            </Button>
          ) : null}
          {canAct ? <ActionCell student={student} role={role} onChanged={onChanged} showProfileLink={false} /> : null}
        </div>
      </div>
    </div>
  );
}
