import { BookOpen, CalendarCheck, ClipboardList, GraduationCap, History, Mail, StickyNote, UserRound } from 'lucide-react';
import { format } from 'date-fns';

import { actionLabel, describeActivity } from '@/lib/activity-format';
import { Panel, PanelEmpty, ScrollList } from './dashboard-primitives';

const MAX_VISIBLE = 5;

const ENTITY_ICON = {
  student: GraduationCap,
  student_note: StickyNote,
  session: CalendarCheck,
  exam: ClipboardList,
  additional_exam: ClipboardList,
  homework: BookOpen,
  invitation: Mail,
  profile: UserRound,
};

/**
 * The latest entries of the activity log, as /activity shows them: an admin
 * sees everyone's, a mentor or tutor their own (the API scopes the rows).
 */
export function RecentActivity({ rows }) {
  // Newest first, whatever order the page arrived in.
  const sorted = [...rows].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  return (
    <Panel icon={History} title="Recent Activity" actionTo="/activity">
      {rows.length === 0 ? (
        <PanelEmpty icon={History} message="No activity recorded yet." />
      ) : (
        <ScrollList maxRows={MAX_VISIBLE} total={sorted.length} className="divide-y">
          {sorted.map((row) => {
            const Icon = ENTITY_ICON[row.entity_type] || History;
            const who = row.actor_name ?? row.actor_email ?? 'Unknown';
            return (
              <li key={row.id} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
                <span className="bg-muted text-muted-foreground mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full">
                  <Icon className="size-3.5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <p className="min-w-0 truncate text-sm font-medium">
                      {who} <span className="text-muted-foreground font-normal">· {actionLabel(row.action)}</span>
                    </p>
                    <span className="text-muted-foreground shrink-0 text-xs whitespace-nowrap">
                      {format(new Date(row.created_at), 'd MMM, h:mm a')}
                    </span>
                  </div>
                  <p className="text-muted-foreground truncate text-xs">
                    {describeActivity(row)}
                    {row.entity_label ? ` · ${row.entity_label}` : ''}
                  </p>
                </div>
              </li>
            );
          })}
        </ScrollList>
      )}
    </Panel>
  );
}
