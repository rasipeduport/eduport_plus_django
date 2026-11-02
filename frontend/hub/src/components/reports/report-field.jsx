import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { MAX_SCORE, PERFORMANCE_LEVELS, itemProblems, textLimit } from '@/lib/reports';
import { CharCounter } from './char-counter';
import { ItemListInput } from './item-list-input';

// The ids a field's control is described by: its count, its hint, its error.
const describedBy = (...ids) => ids.filter(Boolean).join(' ') || undefined;

/**
 * One report field: its label (every field is required), the control, a hint
 * and the problem with it -- the form's or the API's. ``aside`` sits at the
 * label's right (a character count). ``group`` labels a set of controls (an
 * item list) instead of one.
 */
export function ReportField({ id, label, hint, error, aside, group = false, children }) {
  const labelId = `${id}-label`;
  return (
    <div
      className="grid content-start gap-2"
      role={group ? 'group' : undefined}
      aria-labelledby={group ? labelId : undefined}
    >
      <div className="flex items-end justify-between gap-2">
        <Label id={labelId} htmlFor={group ? undefined : id} required>
          {label}
        </Label>
        {aside}
      </div>
      {children}
      {hint ? (
        <p id={`${id}-hint`} className="text-muted-foreground text-xs">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="text-destructive text-sm">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** A free-text field (remarks, plan, reviews) with its count, kept to the API's limit for ``field``. */
export function ReportTextField({ id, field, label, hint, value, error, onChange, rows = 5, disabled }) {
  const max = textLimit(field);
  const countId = `${id}-count`;
  return (
    <ReportField
      id={id}
      label={label}
      hint={hint}
      error={error}
      aside={<CharCounter id={countId} value={value} max={max} />}
    >
      <Textarea
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={rows}
        maxLength={max}
        disabled={disabled}
        aria-required="true"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(countId, hint && `${id}-hint`, error && `${id}-error`)}
      />
    </ReportField>
  );
}

/** A score: a whole number from 0 (1 for the maximum) to MAX_SCORE, typed as digits. */
export function ScoreField({ id, label, value, error, onChange, disabled }) {
  return (
    <ReportField id={id} label={label} error={error}>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        inputMode="numeric"
        autoComplete="off"
        maxLength={String(MAX_SCORE).length}
        disabled={disabled}
        aria-required="true"
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(error && `${id}-error`)}
      />
    </ReportField>
  );
}

/** The Diagnostic report's Performance Level, one of the API's four. */
export function PerformanceLevelField({ id, value, error, onChange, disabled }) {
  return (
    <ReportField id={id} label="Performance level" error={error}>
      <Select value={value ?? ''} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger
          id={id}
          className="w-full"
          aria-label="Performance level"
          aria-required="true"
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(error && `${id}-error`)}
        >
          <SelectValue placeholder="Choose a level" />
        </SelectTrigger>
        <SelectContent>
          {PERFORMANCE_LEVELS.map((level) => (
            <SelectItem key={level.value} value={level.value}>
              {level.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </ReportField>
  );
}

/**
 * A list the tutor writes an item at a time (Strength Areas, Skills to
 * Strengthen). A problem with one item marks that row; one with the list as a
 * whole (no items at all) marks every row.
 */
export function ReportListField({ id, label, hint, items, error, onChange, disabled }) {
  return (
    <ReportField id={id} label={label} hint={hint} error={error} group>
      <ItemListInput
        id={id}
        label={label}
        items={items}
        onChange={onChange}
        disabled={disabled}
        invalid={Boolean(error) && !itemProblems(items).some(Boolean)}
        describedBy={describedBy(hint && `${id}-hint`, error && `${id}-error`)}
      />
    </ReportField>
  );
}
