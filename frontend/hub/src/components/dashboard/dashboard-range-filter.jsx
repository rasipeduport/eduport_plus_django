import { useId } from 'react';

import { CUSTOM, DEFAULT_WORDS, RANGE_OPTIONS, rangeWords } from '@/lib/dashboard-range';
import { cn } from '@/lib/utils';
import { DatePresets } from '@/components/page/date-presets';
import { RefreshButton } from '@/components/page/refresh-button';

/**
 * Every dashboard's dates: Today | 7 Days | This Month | All Time | Custom,
 * the span they cover written out beneath in Indian dates, and the
 * dashboard's Refresh beside them. `range` is the span in force (from
 * hooks/use-dashboard-range, which `onPick` -- its `pickRange` -- keeps),
 * `fallback` the dashboard's default (the calendar's reset names it) and
 * `answered` the API's `range`, which names All Time's first date.
 */
export function DashboardRangeFilter({ range, fallback, answered, onPick, onRefresh, pending, className }) {
  const labelId = useId();
  return (
    <div className={cn('flex w-full items-start gap-2', className)}>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:items-end">
        <span id={labelId} className="sr-only">
          Dates to count
        </span>
        <DatePresets
          options={RANGE_OPTIONS}
          value={range.range}
          from={range.from ?? ''}
          to={range.to ?? ''}
          anyLabel={DEFAULT_WORDS[fallback]}
          labelledBy={labelId}
          onPick={(preset) => onPick({ range: preset })}
          onCustom={(picked) => onPick({ range: CUSTOM, ...picked })}
        />
        <p className="text-muted-foreground text-xs" aria-live="polite">
          {rangeWords(range, answered)} · Indian dates (IST)
        </p>
      </div>
      <RefreshButton variant="ghost" iconOnly onClick={onRefresh} pending={pending} />
    </div>
  );
}
