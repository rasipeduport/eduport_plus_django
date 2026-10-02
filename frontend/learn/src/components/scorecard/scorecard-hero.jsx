import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, TrendingDown, TrendingUp, Trophy } from 'lucide-react';
import api from '../../lib/api';
import { Card } from '../ui/card';
import { cn } from '../../lib/utils';
import { scoreTone } from '../../lib/exam-status';

/** "Your Progress" tile on the dashboard: last-30-days overall, delta, sparkline (Learn ScorecardHero). */
export function ScorecardHero({ refreshKey }) {
  const [card, setCard] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get('/api/student/scorecard/', { params: { range: 'month' } })
      .then((res) => {
        if (!cancelled) setCard(res.data);
      })
      .catch(() => {
        if (!cancelled) setCard(null);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (!card) return null;

  const overall = card.overall;
  const tone = overall == null ? null : scoreTone(overall);
  const points = (card.buckets || []).map((b) => b.exam ?? b.homework);
  const sparkW = 120;
  const sparkH = 36;
  const xs = points.map((_, i) => (points.length <= 1 ? sparkW / 2 : (i / (points.length - 1)) * sparkW));
  let d = '';
  let open = false;
  points.forEach((v, i) => {
    if (v == null) {
      open = false;
      return;
    }
    d += `${open ? 'L' : 'M'}${xs[i]} ${sparkH - (v / 100) * sparkH} `;
    open = true;
  });

  return (
    <Link to="/scorecard" className="block">
      <Card interactive padding="md">
        <div className="flex items-center gap-4">
          <div className={cn('flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl', tone ? tone.bg : 'bg-surface-muted')}>
            <Trophy className={cn('h-5 w-5', tone ? tone.text : 'text-text-muted')} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-text-secondary text-xs font-semibold uppercase tracking-wide">Your Progress</p>
            {overall == null ? (
              <p className="text-text-muted mt-0.5 text-sm">
                {card.lifetime_count > 0 ? 'No scores in the last 30 days.' : 'Your scores will appear here once your first exam is marked.'}
              </p>
            ) : (
              <div className="mt-0.5 flex items-baseline gap-2">
                <span className={cn('text-2xl font-bold tabular-nums', tone.text)}>{overall}%</span>
                {card.delta != null && (
                  <span className={cn('inline-flex items-center gap-0.5 text-xs font-semibold', card.delta >= 0 ? 'text-primary-hover' : 'text-danger')}>
                    {card.delta >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                    {card.delta > 0 ? '+' : ''}
                    {card.delta}
                  </span>
                )}
                <span className="text-text-muted text-xs">last 30 days</span>
              </div>
            )}
          </div>
          {d && (
            <svg width={sparkW} height={sparkH} viewBox={`0 0 ${sparkW} ${sparkH}`} className="hidden shrink-0 sm:block">
              <path d={d.trim()} fill="none" stroke={tone ? tone.stroke : 'var(--color-border)'} strokeWidth="2" strokeLinecap="round" />
            </svg>
          )}
          <ChevronRight className="text-text-muted h-4 w-4 shrink-0" />
        </div>
      </Card>
    </Link>
  );
}
