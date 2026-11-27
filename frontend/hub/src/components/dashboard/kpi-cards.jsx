import { Link } from 'react-router-dom';
import { AlertCircle, CalendarCheck, ChevronRight, TrendingUp, UserCheck, Users } from 'lucide-react';

import { remainingToday, sessionsToday } from '@/lib/session-day';
import { cn } from '@/lib/utils';
import { ToneIcon } from './dashboard-primitives';

/**
 * One headline number; a link when `to` is given. Shared with the BDE and
 * Admissions dashboards; `labelClassName` adds to its label's classes.
 */
export function Tile({ icon, tone, label, value, hint, hintTone = 'muted', to, labelClassName }) {
  const body = (
    <>
      <ToneIcon icon={icon} tone={tone} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className={cn('text-muted-foreground text-xs font-medium text-pretty', labelClassName)}>{label}</p>
          {to ? <ChevronRight className="text-muted-foreground size-4 shrink-0" /> : null}
        </div>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        {hint ? (
          <p
            className={cn(
              'mt-0.5 flex items-center gap-1 text-xs',
              hintTone === 'muted' && 'text-muted-foreground',
              hintTone === 'success' && 'text-success',
              hintTone === 'warning' && 'text-warning'
            )}
          >
            {hintTone === 'success' ? <TrendingUp className="size-3" /> : null}
            {hint}
          </p>
        ) : null}
      </div>
    </>
  );
  const className = 'bg-card flex items-start gap-3 rounded-xl border p-4 transition-colors';
  return to ? (
    <Link to={to} className={cn(className, 'hover:bg-muted/40')}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}

/**
 * The four headline numbers. Every figure is read from what the page already
 * loads: the stats endpoint (totals) and `signups`, its sign-ups on the
 * dashboard's dates -- the only figure here the date filter moves -- the students list
 * (active count), the sessions list (today's and upcoming classes) and the
 * Needs Attention items, all as they stand now.
 */
export function KpiCards({ stats, signups, students, sessions, attentionTotal }) {
  const total = stats?.students ?? students.length;
  const active = students.filter((s) => (s.status || 'active').toLowerCase() === 'active').length;
  // The sign-ups on the dashboard's dates; none named while they could not be read.
  const joined = signups?.total ?? 0;
  const activePct = total > 0 ? Math.round((active / total) * 100) : 0;

  // Same local-day rule as the Upcoming Sessions panel, so the two agree.
  const now = new Date();
  const classesToday = sessionsToday(sessions, now).length;
  const remaining = remainingToday(sessions, now).length;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Tile
        icon={Users}
        tone="info"
        label="Total Students"
        value={total}
        hint={!signups ? null : joined > 0 ? `+${joined} on these dates` : 'No new sign-ups on these dates'}
        hintTone={joined > 0 ? 'success' : 'muted'}
        to="/students"
      />
      <Tile
        icon={UserCheck}
        tone="success"
        label="Active Students"
        value={active}
        hint={total > 0 ? `${activePct}% of total` : 'No students yet'}
        to="/students"
      />
      <Tile
        icon={CalendarCheck}
        tone="warning"
        label="Classes Today"
        value={classesToday}
        hint={classesToday === 0 ? 'None scheduled' : remaining === 0 ? 'All done for today' : `${remaining} still to come`}
        to="/sessions"
      />
      <Tile
        icon={AlertCircle}
        tone={attentionTotal > 0 ? 'destructive' : 'default'}
        label="Needs Attention"
        value={attentionTotal}
        hint={attentionTotal > 0 ? (attentionTotal === 1 ? 'Needs your action' : 'Items need your action') : 'All clear'}
        hintTone={attentionTotal > 0 ? 'warning' : 'muted'}
      />
    </div>
  );
}
