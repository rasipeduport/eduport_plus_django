import { useLayoutEffect, useRef, useState } from 'react';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { ChartContainer, ChartTooltip } from '@/components/ui/chart';
import { wholeAed } from '@/lib/payments';
import { axisCeiling, bucketLabel, compactAed } from '@/lib/sales-dashboard';

// Sales value and money received: two series on one AED axis, each its own
// colour per theme (validated as a pair for colour-blind readers in both). The
// light aqua is under 3:1 on white, so the legend spells out each total.
const chartConfig = {
  sales: { label: 'Sales value', theme: { light: '#2a78d6', dark: '#3987e5' } },
  collected: { label: 'Collected', theme: { light: '#1baf7a', dark: '#199e70' } },
};
const SERIES = [
  { key: 'sales', count: 'sales_count', noun: ['sale', 'sales'] },
  { key: 'collected', count: 'payments', noun: ['payment', 'payments'] },
];

const counted = (count, [one, many]) => `${count} ${count === 1 ? one : many}`;

const MARGIN = { top: 4, right: 4, left: 0, bottom: 0 };
const Y_AXIS_WIDTH = 72;
const BAR_GAP = 2;
const MAX_BAR = 28;

/** The element's laid-out width in pixels: 0 until the browser lays it out (and always in tests). */
function useWidth(ref) {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const measure = () => setWidth(element.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

/**
 * Each bar's width, in pixels, for `buckets` buckets across `width`: the pair
 * takes at most 70% of its bucket and each bar at most MAX_BAR. Given a size,
 * recharts sets a bucket's two bars side by side, centred in it; given only a
 * cap, it centres each bar in its own half of the bucket, so a wide bucket (a
 * single day) drew them far apart. Undefined until the chart is laid out.
 */
function barWidth(width, buckets) {
  if (!width || !buckets) return undefined;
  const bucket = (width - Y_AXIS_WIDTH - MARGIN.left - MARGIN.right) / buckets;
  return Math.max(1, Math.min(MAX_BAR, Math.floor((bucket * 0.7 - BAR_GAP) / 2)));
}

function Swatch({ series }) {
  return <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: `var(--color-${series})` }} aria-hidden="true" />;
}

/** One bucket's figures under the pointer: its dates, then each series' amount and how many made it. */
function TrendTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="border-border/50 bg-background grid min-w-40 gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
      <p className="font-medium">{row.label}</p>
      {SERIES.map((series) => (
        <div key={series.key} className="flex items-center gap-2">
          <Swatch series={series.key} />
          <span className="text-muted-foreground flex-1">{chartConfig[series.key].label}</span>
          <span className="font-medium tabular-nums">{wholeAed(row[series.key])}</span>
          <span className="text-muted-foreground tabular-nums">({counted(row[series.count], series.noun)})</span>
        </div>
      ))}
    </div>
  );
}

/**
 * The span's sales value beside what was received, bucket by bucket (the
 * API's day, week or month), with each total in the legend and the same
 * figures as a table for screen readers.
 */
export function SalesTrendChart({ trend, totals }) {
  const data = trend.buckets.map((bucket) => ({
    label: bucketLabel(bucket, trend.unit),
    sales: Number(bucket.sales_value),
    collected: Number(bucket.collected),
    sales_count: bucket.sales_count,
    payments: bucket.payments,
  }));
  const empty = data.every((row) => row.sales === 0 && row.collected === 0);
  const area = useRef(null);
  const barSize = barWidth(useWidth(area), data.length);
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <ul className="flex flex-wrap gap-x-5 gap-y-1 text-xs" aria-label="Totals for these dates">
        {SERIES.map((series) => (
          <li key={series.key} className="flex items-center gap-1.5">
            <Swatch series={series.key} />
            <span className="text-muted-foreground">{chartConfig[series.key].label}</span>
            <span className="font-semibold tabular-nums">{wholeAed(totals[series.key])}</span>
          </li>
        ))}
      </ul>
      <div ref={area} className="relative h-56 w-full" aria-hidden="true">
        <ChartContainer config={chartConfig} className="aspect-auto h-full w-full">
          <BarChart data={data} margin={MARGIN} barGap={BAR_GAP} barCategoryGap="20%" barSize={barSize}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} tick={{ fontSize: 11 }} interval="preserveStartEnd" minTickGap={16} />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={Y_AXIS_WIDTH}
              tickMargin={4}
              tick={{ fontSize: 11 }}
              tickFormatter={compactAed}
              domain={[0, axisCeiling]}
              tickCount={5}
              allowDecimals={false}
            />
            <ChartTooltip cursor={{ fillOpacity: 0.4 }} content={<TrendTooltip />} />
            <Bar dataKey="sales" fill="var(--color-sales)" radius={[4, 4, 0, 0]} maxBarSize={MAX_BAR} />
            <Bar dataKey="collected" fill="var(--color-collected)" radius={[4, 4, 0, 0]} maxBarSize={MAX_BAR} />
          </BarChart>
        </ChartContainer>
        {empty ? (
          <p className="text-muted-foreground pointer-events-none absolute inset-x-0 top-[40%] text-center text-xs">
            Nothing sold or received on these dates
          </p>
        ) : null}
      </div>
      <table className="sr-only">
        <caption>Sales value and money received, by date</caption>
        <thead>
          <tr>
            <th scope="col">Dates</th>
            <th scope="col">Sales value</th>
            <th scope="col">Collected</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label}</th>
              <td>{`${wholeAed(row.sales)} (${counted(row.sales_count, SERIES[0].noun)})`}</td>
              <td>{`${wholeAed(row.collected)} (${counted(row.payments, SERIES[1].noun)})`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
