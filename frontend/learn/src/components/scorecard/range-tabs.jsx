import { cn } from '../../lib/utils';

export const RANGES = [
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'all', label: 'All time' },
];

export function RangeTabs({ value, onChange }) {
  return (
    <div role="tablist" className="border-border-light bg-surface-muted inline-flex w-full rounded-xl border p-1 sm:w-auto">
      {RANGES.map((r) => (
        <button
          key={r.value}
          type="button"
          onClick={() => onChange(r.value)}
          className={cn(
            'min-h-10 flex-1 rounded-lg px-4 py-1.5 text-sm font-semibold transition-all duration-150 cursor-pointer sm:flex-none lg:min-h-0',
            value === r.value ? 'bg-surface-elevated text-text-primary shadow-card' : 'text-text-muted hover:text-text-secondary'
          )}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}
