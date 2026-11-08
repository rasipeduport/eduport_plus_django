import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { TIMEZONE_OPTIONS } from '@/lib/timezone';

// The "Not set" item's value: Radix gives no item the empty value, so it
// stands in for '' inside the select, and the caller only ever sees ''.
const NOT_SET = '__not_set__';

/**
 * Picks the zone a session's wall-clock time is entered in.
 *
 * The list comes from `TIMEZONE_OPTIONS`; a value outside that list (set
 * directly on the student) still renders, so an unusual stored zone is never
 * silently swapped for a listed one.
 *
 * A lead's Student timezone uses it too, with what it needs beyond a
 * session's: `id` for a `<Label htmlFor>`, `allowNotSet` for a first "Not
 * set" option (the value '' -- no zone), `ariaLabel` in place of "Student
 * timezone", `size` for a form's full-height fields and `invalid` for a field
 * the API refused. Left out, the select is the sessions' and exams' own.
 */
export function TimezoneSelect({
  value,
  onValueChange,
  className,
  disabled,
  id,
  allowNotSet = false,
  ariaLabel = 'Student timezone',
  size = 'sm',
  invalid,
}) {
  const isListed = TIMEZONE_OPTIONS.some((o) => o.value === value);
  const selected = allowNotSet && !value ? NOT_SET : value;
  const change = allowNotSet ? (next) => onValueChange(next === NOT_SET ? '' : next) : onValueChange;

  return (
    <Select value={selected} onValueChange={change} disabled={disabled}>
      <SelectTrigger
        id={id}
        aria-label={ariaLabel}
        aria-invalid={invalid ? true : undefined}
        size={size}
        className={className}
      >
        <SelectValue placeholder="Select timezone" />
      </SelectTrigger>
      <SelectContent position="popper">
        {allowNotSet ? <SelectItem value={NOT_SET}>Not set</SelectItem> : null}
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
