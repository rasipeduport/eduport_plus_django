import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { CUSTOM_SOURCE_MAX_LENGTH } from '@/lib/enquiries';

/**
 * The name of an Other lead source ("Newspaper advertisement"), shown only
 * while Other is the chosen source -- in Add lead and in the lead's Edit
 * details alike. Required there; the API trims it and refuses a blank one.
 */
export function CustomSourceInput({ id, value, onChange, error, disabled }) {
  const errorId = `${id}-error`;
  return (
    <div className="grid content-start gap-2 sm:col-span-2">
      <Label htmlFor={id} required>
        Specify Lead Source
      </Label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Enter lead source name"
        maxLength={CUSTOM_SOURCE_MAX_LENGTH}
        autoComplete="off"
        disabled={disabled}
        aria-required="true"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
      />
      {error ? (
        <p id={errorId} className="text-destructive text-sm" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
