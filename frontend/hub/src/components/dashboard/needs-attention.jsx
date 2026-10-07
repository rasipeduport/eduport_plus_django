import { Link } from 'react-router-dom';
import { AlertTriangle, BookOpen, CheckCircle2, ClipboardList, Mail, Video } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Panel } from './dashboard-primitives';

/**
 * Items that need a staff member's hand, each counted from a list the Hub
 * already serves this role:
 *   - homework with status "submitted" (the tutor has not scored it yet)
 *   - attended classes whose notes / recording / homework are not all in
 *     (the API's derived display_status "pending")
 *   - pending invitations (the stats endpoint's count; admins act on them)
 *   - additional exams with a submitted answer sheet and no score yet
 *     (tutors are not served the exam endpoints, so the row is left out)
 * Returns rows with a count, a hint and where to go to act on them.
 */
export function attentionItems({ homework, sessions, additionalExams, stats, role }) {
  const items = [
    {
      key: 'homework',
      icon: BookOpen,
      label: 'Homework awaiting review',
      count: homework.filter((h) => (h.status || '').toLowerCase() === 'submitted').length,
      to: '/homework',
    },
    {
      key: 'content',
      icon: Video,
      label: 'Sessions missing content',
      count: sessions.filter((s) => (s.display_status || '').toLowerCase() === 'pending').length,
      to: '/sessions',
    },
  ];
  if (role === 'ADMIN') {
    items.push({
      key: 'invitations',
      icon: Mail,
      label: 'Pending invitations',
      count: stats?.pending_invitations ?? 0,
      to: '/invitations',
    });
  }
  if (additionalExams) {
    items.push({
      key: 'exams',
      icon: ClipboardList,
      label: 'Unscored exams',
      count: additionalExams.filter((e) => (e.status || '').toLowerCase() === 'submitted').length,
      to: '/exams',
    });
  }
  return items;
}

export function NeedsAttention({ items, actionTo }) {
  const total = items.reduce((sum, item) => sum + item.count, 0);

  return (
    <Panel icon={AlertTriangle} title="Needs Attention" actionTo={actionTo}>
      <ul className="divide-y">
        {items.map((item) => {
          const Icon = item.icon;
          const content = (
            <>
              <span
                className={cn(
                  'flex size-7 shrink-0 items-center justify-center rounded-md',
                  item.count > 0 ? 'bg-warning/10 text-warning' : 'bg-muted text-muted-foreground'
                )}
              >
                <Icon className="size-3.5" />
              </span>
              <span className="min-w-0 flex-1 truncate text-sm">{item.label}</span>
              <span
                className={cn(
                  'shrink-0 text-sm font-semibold tabular-nums',
                  item.count > 0 ? 'text-foreground' : 'text-muted-foreground'
                )}
              >
                {item.count}
              </span>
            </>
          );
          return (
            <li key={item.key}>
              {item.count > 0 ? (
                <Link to={item.to} className="hover:bg-muted/40 -mx-2 flex items-center gap-3 rounded-md px-2 py-2.5 transition-colors">
                  {content}
                </Link>
              ) : (
                <div className="flex items-center gap-3 py-2.5">{content}</div>
              )}
            </li>
          );
        })}
      </ul>

      {total === 0 ? (
        <div className="bg-success/10 mt-4 flex items-start gap-3 rounded-lg border border-success/20 px-3 py-2.5">
          <CheckCircle2 className="text-success mt-0.5 size-4 shrink-0" />
          <div className="min-w-0">
            <p className="text-success text-sm font-medium">Everything is up to date</p>
            <p className="text-muted-foreground text-xs">No pending items that need attention right now.</p>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}
