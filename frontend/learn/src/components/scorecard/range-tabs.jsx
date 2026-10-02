import { cn } from '../../lib/utils';

export const RANGES = [
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'all', label: 'All time' },
];

export function RangeTabs({ value, onChange }) {
  return (
    <div className="border-border-light bg-surface-muted inline-flex rounded-xl border p-1">
      {RANGES.map((r) => (
        <button
          key={r.value}
          type="button"
          onClick={() => onChange(r.value)}
          className={cn(
            'rounded-lg px-4 py-1.5 text-sm font-semibold transition-all duration-150 cursor-pointer',
            value === r.value ? 'bg-surface-elevated text-text-primary shadow-card' : 'text-text-muted hover:text-text-secondary'
          )}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}
