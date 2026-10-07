import { Link } from 'react-router-dom';
import { ArrowRight, Users } from 'lucide-react';
import { format } from 'date-fns';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { StudentStatusBadge } from '@/components/students/profile/profile-primitives';
import { getInitials } from '@/lib/utils';
import { Panel, PanelEmpty, ScrollList } from './dashboard-primitives';

const MAX_VISIBLE = 5;

/** Students newest first, from the list the Hub already serves this role; five visible, the rest by scrolling. */
export function RecentStudents({ students }) {
  const rows = [...students].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  return (
    <Panel
      icon={Users}
      title="Recent Students"
      action={
        <Button variant="outline" size="sm" asChild>
          <Link to="/students">
            <span className="sm:hidden">View all</span>
            <span className="hidden sm:inline">View all students</span>
          </Link>
        </Button>
      }
    >
      {rows.length === 0 ? (
        <PanelEmpty icon={Users} message="No students enrolled yet." hint="New enrolments land here as they are invited." />
      ) : (
        <ScrollList maxRows={MAX_VISIBLE} total={rows.length} className="divide-y">
          {rows.map((student) => {
            const name = student.full_name;
            const email = student.profile?.email ?? null;
            const meta = [student.student_code, student.grade].filter(Boolean).join(' · ');
            return (
              <li key={student.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3 first:pt-0 last:pb-0">
                <div className="flex min-w-0 flex-1 basis-44 items-center gap-3">
                  <Avatar className="size-9 rounded-full">
                    <AvatarImage
                      src={student.profile?.avatar_url || undefined}
                      alt={name || email || 'Student'}
                      className="size-9 rounded-full object-cover"
                    />
                    <AvatarFallback className="size-9 rounded-full text-xs">{getInitials(name, email)}</AvatarFallback>
                  </Avatar>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{name || email || '—'}</p>
                    <p className="text-muted-foreground truncate font-mono text-xs">{meta}</p>
                  </div>
                </div>
                <StudentStatusBadge status={student.status} note={student.status_note} className="shrink-0" />
                <span className="text-muted-foreground shrink-0 text-xs whitespace-nowrap sm:ml-auto">
                  Joined {format(new Date(student.created_at), 'd MMM yyyy')}
                </span>
                <Button variant="outline" size="sm" className="ml-auto sm:ml-0" asChild>
                  <Link to={`/students/${student.id}`}>
                    View
                    <ArrowRight className="size-4" />
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
