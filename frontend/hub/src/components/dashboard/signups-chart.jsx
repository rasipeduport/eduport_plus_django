import { BarChart3 } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { UNIT_WORDS, bucketLabel } from '@/lib/dashboard-range';
import { Panel } from './dashboard-primitives';

const chartConfig = {
  signups: {
    label: 'New Students',
    color: 'var(--primary)',
  },
};

const plural = (count, one, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

/**
 * Student sign-ups over the dashboard's dates, as the stats endpoint counts
 * them (`signups`: their total and buckets of Indian dates -- day by day for
 * up to a month, then week, month or year by year). The dates are the
 * dashboard's own filter's; this panel has no picker of its own. Without
 * `signups` (their read failed) it says so rather than drawing a false zero.
 */
export function SignupsChart({ signups }) {
  const buckets = signups?.buckets ?? [];
  const unit = signups?.unit ?? 'day';
  const total = signups?.total ?? 0;
  const data = buckets.map((bucket) => ({ day: bucketLabel(bucket, unit), signups: bucket.signups }));

  return (
    <Panel
      icon={BarChart3}
      title="New Enrollments"
      subtitle={signups ? `${plural(total, 'student sign-up')} on these dates, ${UNIT_WORDS[unit]} (IST)` : 'Student sign-ups on these dates (IST)'}
    >
      <div className="relative h-44 w-full">
        <ChartContainer config={chartConfig} className="aspect-auto h-full w-full">
          <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={8} tick={{ fontSize: 11 }} interval="preserveStartEnd" minTickGap={16} />
            <YAxis tickLine={false} axisLine={false} allowDecimals={false} tickMargin={8} tick={{ fontSize: 11 }} domain={[0, (max) => Math.max(4, max)]} />
            {/* The bucket named: a week or a month reads as one bar. */}
            <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
            <Bar dataKey="signups" fill="var(--color-signups)" radius={4} maxBarSize={36} />
          </BarChart>
        </ChartContainer>
        {total === 0 ? (
          <p className="text-muted-foreground pointer-events-none absolute inset-x-0 top-[38%] text-center text-xs">
            {signups ? 'No sign-ups on these dates' : 'The sign-ups for these dates could not be loaded'}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
