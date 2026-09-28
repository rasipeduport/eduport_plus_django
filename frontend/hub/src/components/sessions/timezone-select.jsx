import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { TIMEZONE_OPTIONS } from '@/lib/timezone';

/**
 * Picks the zone a session's wall-clock time is entered in.
 *
 * The list comes from `TIMEZONE_OPTIONS`; a value outside that list (set
 * directly on the student) still renders, so an unusual stored zone is never
 * silently swapped for a listed one.
 */
export function TimezoneSelect({ value, onValueChange, className, disabled }) {
  const isListed = TIMEZONE_OPTIONS.some((o) => o.value === value);

  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger aria-label="Student timezone" size="sm" className={className}>
        <SelectValue placeholder="Select timezone" />
      </SelectTrigger>
      <SelectContent position="popper">
        {!isListed && value && <SelectItem value={value}>{value}</SelectItem>}
        {TIMEZONE_OPTIONS.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
