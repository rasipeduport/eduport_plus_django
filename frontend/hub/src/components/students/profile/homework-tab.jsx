import { BookOpen } from 'lucide-react';
import { format } from 'date-fns';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { HOMEWORK_STATUS_VARIANT, homeworkStatusLabel } from '@/lib/homework-status';
import { EMPTY, EmptyState, ProfileTable, SectionHeading, Td } from './profile-primitives';

const COLUMNS = [
  { key: 'session', label: 'Class' },
  { key: 'status', label: 'Status' },
  { key: 'assigned', label: 'Assigned' },
  { key: 'submitted', label: 'Submitted' },
  { key: 'score', label: 'Score' },
  { key: 'scored_by', label: 'Scored by' },
  { key: 'actions', label: '', className: 'w-24' },
];

/**
 * Homework tab: one row per assignment, which is one per attended class that
 * carries homework. The mentor sets it on the session, the student submits
 * once, the tutor grades — the row opens the same grade sheet /homework uses,
 * so a tutor can grade straight from the profile.
 */
export function HomeworkTab({ homework, stats, canScore, onOpen }) {
  const awaiting = stats?.submitted ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <SectionHeading
        title={`${homework.length} ${homework.length === 1 ? 'assignment' : 'assignments'}`}
        description={
          awaiting > 0
            ? `${awaiting} waiting to be reviewed by the tutor.`
            : 'Set on an attended class, submitted once by the student, graded by the tutor.'
        }
      />
      {homework.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          message="No homework assigned yet."
          hint="Homework appears once an attended class carries a homework link or file."
        />
      ) : (
        <ProfileTable
          columns={COLUMNS}
          rows={homework}
          keyOf={(row) => row.id}
          emptyMessage="No homework assigned yet."
          renderRow={(row) => {
            const status = (row.status || '').toLowerCase();
            const grade = canScore && status === 'submitted';
            return (
              <>
                <Td>
                  <span className="block max-w-56 truncate font-medium" title={row.session?.title}>
                    {row.session?.title || EMPTY}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {row.session?.start_time ? format(new Date(row.session.start_time), 'd MMM yyyy') : ''}
                  </span>
                </Td>
                <Td>
                  <Badge variant={HOMEWORK_STATUS_VARIANT[status] || 'secondary'}>{homeworkStatusLabel(row)}</Badge>
                </Td>
                <Td className="text-muted-foreground text-sm whitespace-nowrap">
                  {row.assigned_at ? format(new Date(row.assigned_at), 'd MMM yyyy') : EMPTY}
                </Td>
                <Td className="text-muted-foreground text-sm whitespace-nowrap">
                  {row.submitted_at ? format(new Date(row.submitted_at), 'd MMM, h:mm a') : EMPTY}
                </Td>
                <Td className="text-sm whitespace-nowrap tabular-nums">
                  {status === 'scored' && row.score != null ? (
                    `${row.score}/${row.max_score}`
                  ) : (
                    <span className="text-muted-foreground">{EMPTY}</span>
                  )}
                </Td>
                <Td className="text-muted-foreground max-w-40 truncate text-sm">
                  {row.scored_by_profile?.full_name || row.scored_by_profile?.email || EMPTY}
                </Td>
                <Td className="text-right">
                  <Button variant={grade ? 'default' : 'outline'} size="sm" onClick={() => onOpen(row.id)}>
                    {grade ? 'Grade' : 'View'}
                  </Button>
                </Td>
              </>
            );
          }}
        />
      )}
    </div>
  );
}
