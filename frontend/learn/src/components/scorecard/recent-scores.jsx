import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, Loader2 } from 'lucide-react';
import api from '../../lib/api';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { cn } from '../../lib/utils';
import { formatDate } from '../../lib/formatting';
import { resultPath, scoreTone } from '../../lib/exam-status';

const CATEGORY_LABEL = { homework: 'Homework', exam: 'Chapter exam', additional_exam: 'Additional exam' };
const PAGE_SIZE = 8; // keep equal to RECENT_PAGE_SIZE in backend/exams/services.py

/**
 * The scores in the window, newest first (Learn RecentScores). Page 1 is the
 * scorecard's own `recent`; "View more" pages the rest from /api/student/scores/.
 * Mount with `key={range}` so a range change starts over from page 1.
 */
export function RecentScores({ entries, range, totalCount = 0 }) {
  const [extra, setExtra] = useState([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // A refreshed page 1 (focus refetch) restarts the list; nothing old is kept.
  useEffect(() => {
    setExtra([]);
    setPage(1);
    setError('');
  }, [entries, range]);

  if (!entries || entries.length === 0) return null;

  const seen = new Set(entries.map((e) => e.id));
  const rows = [...entries, ...extra.filter((e) => !seen.has(e.id))];
  const hasMore = rows.length < totalCount;

  const loadMore = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get('/api/student/scores/', { params: { range, page: page + 1, page_size: PAGE_SIZE } });
      setExtra((prev) => {
        const known = new Set([...entries, ...prev].map((e) => e.id));
        return [...prev, ...(res.data.results || []).filter((e) => !known.has(e.id))];
      });
      setPage(page + 1);
    } catch (err) {
      console.error('Failed to load more scores', err);
      setError('Could not load more scores. Try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card padding="md">
      <h3 className="text-text-secondary mb-3 text-xs font-semibold uppercase tracking-wide">Recent scores</h3>
      <ul className="divide-border-light divide-y">
        {rows.map((e) => {
          const tone = scoreTone(e.pct);
          const to = resultPath(e);
          const body = (
            <>
              <div className="min-w-0 flex-1">
                <p className="text-text-primary truncate text-sm font-semibold">{e.label}</p>
                <p className="text-text-muted text-xs">
                  {CATEGORY_LABEL[e.category] || 'Chapter exam'} · {formatDate(e.scored_at)}
                </p>
              </div>
              <span className={cn('shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-semibold tabular-nums whitespace-nowrap', tone.bg, tone.text, tone.border)}>
                {e.score}/{e.max_score} · {e.pct}%
              </span>
              {to && <ChevronRight className="text-text-muted h-4 w-4 shrink-0" />}
            </>
          );
          return (
            <li key={e.id || `${e.label}-${e.scored_at}`}>
              {to ? (
                <Link to={to} state={{ from: '/scorecard' }} className="hover:bg-surface-muted -mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors">
                  {body}
                </Link>
              ) : (
                <div className="flex items-center gap-3 py-2.5">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
      {(hasMore || error) && (
        <div className="mt-3 flex flex-col items-center gap-2">
          {error && <p className="text-danger text-xs">{error}</p>}
          {hasMore && (
            <Button type="button" variant="secondary" size="sm" onClick={loadMore} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              View more
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
