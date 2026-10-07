import { Link } from 'react-router-dom';
import { AlertCircle, CalendarCheck, ChevronRight, TrendingUp, UserCheck, Users } from 'lucide-react';

import { cn } from '@/lib/utils';
import { ToneIcon } from './dashboard-primitives';

function Tile({ icon, tone, label, value, hint, hintTone = 'muted', to }) {
  const body = (
    <>
      <ToneIcon icon={icon} tone={tone} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className="text-muted-foreground text-xs font-medium text-pretty">{label}</p>
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
 * loads: the stats endpoint (totals, this week's sign-ups), the students list
 * (active count), the sessions list (today's and upcoming classes) and the
 * Needs Attention items.
 */
export function KpiCards({ stats, students, sessions, attentionTotal }) {
  const total = stats?.students ?? students.length;
  const active = students.filter((s) => (s.status || 'active').toLowerCase() === 'active').length;
  const thisWeek = (stats?.signup_data ?? []).reduce((sum, d) => sum + (d.signups || 0), 0);
  const activePct = total > 0 ? Math.round((active / total) * 100) : 0;

  const now = Date.now();
  const scheduled = sessions.filter((s) => (s.status || '').toLowerCase() === 'scheduled');
  const upcoming = scheduled.filter((s) => new Date(s.end_time).getTime() >= now);
  const today = new Date();
  const classesToday = scheduled.filter((s) => {
    const d = new Date(s.start_time);
    return d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate();
  }).length;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Tile
        icon={Users}
        tone="info"
        label="Total Students"
        value={total}
        hint={thisWeek > 0 ? `+${thisWeek} this week` : 'No new sign-ups this week'}
        hintTone={thisWeek > 0 ? 'success' : 'muted'}
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
        hint={`${upcoming.length} upcoming`}
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
