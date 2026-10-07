import { useMemo, useState } from 'react';
import { BarChart3, CalendarDays } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { addDays, differenceInCalendarDays, format, isSameDay, startOfDay, subDays } from 'date-fns';

import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useIsMobile } from '@/hooks/use-mobile';
import { isOnLocalDay } from '@/lib/session-day';
import { Panel } from './dashboard-primitives';

const chartConfig = {
  signups: {
    label: 'New Students',
    color: 'var(--primary)',
  },
};

const DEFAULT_DAYS = 7;

/** The last seven days ending today, as local calendar days. */
export function defaultRange(now = new Date()) {
  const to = startOfDay(now);
  return { from: subDays(to, DEFAULT_DAYS - 1), to };
}

/**
 * Sign-ups per local calendar day between `from` and `to` inclusive, counted
 * from the students the page already holds (the same role-scoped set the
 * stats endpoint sums its fixed seven-day series from).
 */
export function signupSeries(students, range) {
  const days = differenceInCalendarDays(range.to, range.from) + 1;
  return Array.from({ length: days }, (_, i) => {
    const day = addDays(range.from, i);
    return {
      day: format(day, 'MMM d'),
      signups: students.filter((s) => isOnLocalDay(s.created_at, day)).length,
    };
  });
}

function sameRange(a, b) {
  return isSameDay(a.from, b.from) && isSameDay(a.to, b.to);
}

/** "Oct 1 – Oct 5", "Oct 5" for a single day; the year is added only when it is not this year. */
function rangeLabel(range, now = new Date()) {
  const thisYear = range.from.getFullYear() === now.getFullYear() && range.to.getFullYear() === now.getFullYear();
  const f = (d) => format(d, thisYear ? 'MMM d' : 'MMM d, yyyy');
  return isSameDay(range.from, range.to) ? f(range.to) : `${f(range.from)} – ${f(range.to)}`;
}

/**
 * Student sign-ups per day. Defaults to the last seven days; the calendar
 * control opens a range picker that re-counts the same student data for any
 * past range (Apply commits, Cancel keeps the current selection).
 */
export function SignupsChart({ students }) {
  const isMobile = useIsMobile();
  const today = useMemo(() => startOfDay(new Date()), []);
  const initial = useMemo(() => defaultRange(today), [today]);

  const [range, setRange] = useState(initial);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(undefined);

  const isDefault = sameRange(range, initial);
  const singleDay = isSameDay(range.from, range.to);
  const data = useMemo(() => signupSeries(students, range), [students, range]);
  const total = data.reduce((sum, d) => sum + d.signups, 0);
  const label = rangeLabel(range, today);

  const subtitle = isDefault
    ? 'Student sign-ups over the last 7 days'
    : singleDay
      ? `Student sign-ups on ${label}`
      : `Student sign-ups from ${label}`;

  const openPicker = (next) => {
    // Every open starts with a clean pick (the control already names the
    // applied range): the first click is the start, a second the end, and a
    // single click on its own is a single day. Cancel drops the draft.
    if (next) setDraft(undefined);
    setOpen(next);
  };

  const apply = () => {
    if (!draft?.from) return;
    // One click in the picker is a single day; a second click closes the range.
    const from = startOfDay(draft.from);
    const to = startOfDay(draft.to ?? draft.from);
    setRange(from <= to ? { from, to } : { from: to, to: from });
    setOpen(false);
  };

  const reset = () => {
    setRange(initial);
    setOpen(false);
  };

  return (
    <Panel
      icon={BarChart3}
      title="New Enrollments"
      subtitle={subtitle}
      action={
        <Popover open={open} onOpenChange={openPicker}>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" aria-label={`Date range: ${label}`}>
              <CalendarDays className="size-4" />
              {label}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="end">
            <Calendar
              mode="range"
              selected={draft}
              onSelect={setDraft}
              required
              defaultMonth={range.from}
              numberOfMonths={isMobile ? 1 : 2}
              disabled={{ after: today }}
            />
            <div className="flex flex-wrap items-center justify-between gap-2 border-t p-3">
              <Button variant="ghost" size="sm" onClick={reset} disabled={isDefault} className="text-muted-foreground">
                Last 7 days
              </Button>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={() => openPicker(false)}>
                  Cancel
                </Button>
                <Button size="sm" onClick={apply} disabled={!draft?.from}>
                  Apply
                </Button>
              </div>
            </div>
          </PopoverContent>
        </Popover>
      }
    >
      <div className="relative h-44 w-full">
        <ChartContainer config={chartConfig} className="aspect-auto h-full w-full">
          <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={8} tick={{ fontSize: 11 }} interval="preserveStartEnd" minTickGap={16} />
            <YAxis tickLine={false} axisLine={false} allowDecimals={false} tickMargin={8} tick={{ fontSize: 11 }} domain={[0, (max) => Math.max(4, max)]} />
            <ChartTooltip cursor={false} content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="signups" fill="var(--color-signups)" radius={4} maxBarSize={36} />
          </BarChart>
        </ChartContainer>
        {total === 0 ? (
          <p className="text-muted-foreground pointer-events-none absolute inset-x-0 top-[38%] text-center text-xs">
            No sign-ups {isDefault ? 'in the last 7 days' : singleDay ? `on ${label}` : 'in this range'}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
