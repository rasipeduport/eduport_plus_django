import { Card } from '../ui/card';
import { cn } from '../../lib/utils';
import { formatDate } from '../../lib/formatting';
import { scoreTone } from '../../lib/exam-status';

const CATEGORY_LABEL = { homework: 'Homework', exam: 'Chapter exam', additional_exam: 'Additional exam' };

/** The most recent scores in the window (Learn RecentScores). */
export function RecentScores({ entries }) {
  if (!entries || entries.length === 0) return null;
  return (
    <Card padding="md">
      <h3 className="text-text-secondary mb-3 text-xs font-semibold uppercase tracking-wide">Recent scores</h3>
      <ul className="divide-border-light divide-y">
        {entries.map((e, i) => {
          const tone = scoreTone(e.pct);
          return (
            <li key={`${e.label}-${e.scored_at}-${i}`} className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <p className="text-text-primary truncate text-sm font-semibold">{e.label}</p>
                <p className="text-text-muted text-xs">
                  {CATEGORY_LABEL[e.category] || 'Chapter exam'} · {formatDate(e.scored_at)}
                </p>
              </div>
              <span className={cn('shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-semibold tabular-nums', tone.bg, tone.text, tone.border)}>
                {e.score}/{e.max_score} · {e.pct}%
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
