import { BarChart3, CalendarDays } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Panel } from './dashboard-primitives';

const chartConfig = {
  signups: {
    label: 'New Students',
    color: 'var(--primary)',
  },
};

/**
 * Student sign-ups per day over the last seven days. The series comes
 * straight from the stats endpoint; the range chip only names its first and
 * last day.
 */
export function SignupsChart({ data }) {
  const first = data[0]?.day;
  const last = data[data.length - 1]?.day;
  const range = first && last ? `${first} – ${last}` : null;

  return (
    <Panel
      icon={BarChart3}
      title="New Enrollments"
      subtitle="Student sign-ups over the last 7 days"
      action={
        range ? (
          <span className="bg-muted text-muted-foreground hidden h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium whitespace-nowrap sm:inline-flex">
            <CalendarDays className="size-3.5" />
            {range}
          </span>
        ) : null
      }
    >
      <div className="h-44 w-full">
        <ChartContainer config={chartConfig} className="aspect-auto h-full w-full">
          <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={8} tick={{ fontSize: 11 }} interval="preserveStartEnd" />
            <YAxis tickLine={false} axisLine={false} allowDecimals={false} tickMargin={8} tick={{ fontSize: 11 }} />
            <ChartTooltip cursor={false} content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="signups" fill="var(--color-signups)" radius={4} maxBarSize={36} />
          </BarChart>
        </ChartContainer>
      </div>
    </Panel>
  );
}
