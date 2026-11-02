import { charCount } from '@/lib/reports';
import { cn } from '@/lib/utils';

/**
 * "120/1200": how much of a field's limit is used, counted as the API counts
 * (lib/reports charCount). It turns amber in the last tenth and red past the
 * limit, which only pasted text can reach. Point the field's
 * aria-describedby at ``id`` so the count is read with it.
 */
export function CharCounter({ id, value, max, className }) {
  const count = charCount(value);
  return (
    <span
      id={id}
      className={cn(
        'text-muted-foreground text-xs tabular-nums',
        count > max ? 'text-destructive' : count > max * 0.9 && 'text-warning',
        className
      )}
    >
      {count}/{max}
      <span className="sr-only"> characters</span>
    </span>
  );
}
