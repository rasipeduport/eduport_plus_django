import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2, Trophy } from 'lucide-react';
import api from '../lib/api';
import { Card } from '../components/ui/card';
import { ScoreRing } from '../components/scorecard/score-ring';
import { ProgressChart } from '../components/scorecard/progress-chart';
import { CategoryBreakdown } from '../components/scorecard/category-breakdown';
import { RecentScores } from '../components/scorecard/recent-scores';
import { RangeTabs, RANGES } from '../components/scorecard/range-tabs';
import { useRefreshOnFocus } from '../hooks/useRefreshOnFocus';

const RANGE_LABEL = { week: 'this week', month: 'the last 30 days', all: 'all time' };

/** Progress / performance page (Learn /scorecard). */
export default function ScorecardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get('range');
  const range = RANGES.some((r) => r.value === raw) ? raw : 'month';
  const [card, setCard] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await api.get('/api/student/scorecard/', { params: { range } });
      setCard(res.data);
    } catch (err) {
      console.error('Failed to load scorecard', err);
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);
  useRefreshOnFocus(load);

  if (loading || !card) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  const hasScores = card.lifetime_count > 0;

  return (
    <div className="space-y-5 md:space-y-6">
      <section className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-text-primary text-xl font-bold md:text-2xl">Scorecard</h1>
          <p className="text-text-secondary mt-1 text-sm">How your exams and homework are going.</p>
        </div>
        {hasScores && <RangeTabs value={range} onChange={(v) => setSearchParams(v === 'month' ? {} : { range: v })} />}
      </section>

      {!hasScores ? (
        <Card>
          <div className="flex flex-col items-center justify-center gap-3 py-6 text-center">
            <div className="bg-surface-muted flex h-12 w-12 items-center justify-center rounded-2xl">
              <Trophy className="text-text-muted h-5 w-5" />
            </div>
            <div>
              <p className="text-text-primary text-sm font-semibold">No scores yet</p>
              <p className="text-text-muted mt-0.5 text-xs">Your progress will appear here once your first exam is marked.</p>
            </div>
          </div>
        </Card>
      ) : card.total_count === 0 ? (
        <Card>
          <div className="py-6 text-center">
            <p className="text-text-primary text-sm font-semibold">No scores in this range yet</p>
            <p className="text-text-muted mt-0.5 text-xs">Try "All time".</p>
          </div>
        </Card>
      ) : (
        <div className="grid min-w-0 gap-4 md:grid-cols-[auto_1fr] md:items-start">
          <Card padding="md" className="flex min-w-0 items-center justify-center">
            <ScoreRing value={card.overall} delta={card.delta} label={RANGE_LABEL[range]} />
          </Card>
          <Card padding="md" className="min-w-0">
            <ProgressChart buckets={card.buckets || []} />
          </Card>
          <div className="min-w-0 space-y-4 md:col-span-2">
            <CategoryBreakdown categories={card.categories || []} />
            <RecentScores key={range} entries={card.recent || []} range={range} totalCount={card.total_count || 0} />
          </div>
        </div>
      )}
    </div>
  );
}
