import { useState } from 'react';
import { EyeIcon, EyeOffIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PASSWORD_RULE } from '@/lib/password-policy';

/**
 * A password input with an eye button that shows or hides what was typed.
 * Hidden again whenever it mounts, so a reopened dialog never starts revealed.
 */
function PasswordInput({ name, disabled, ...props }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <Input type={shown ? 'text' : 'password'} disabled={disabled} className="pr-10" {...props} />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="absolute top-0 right-0 size-9"
        onClick={() => setShown((current) => !current)}
        aria-label={`${shown ? 'Hide' : 'Show'} ${name}`}
        aria-pressed={shown}
        disabled={disabled}
      >
        {shown ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
      </Button>
    </div>
  );
}

/**
 * The temporary password an administrator types, twice. It lives only in the
 * caller's state -- never logged, stored or shown back -- and the account must
 * replace it at its next sign-in. The API applies the password policy and
 * explains a refusal in `details`.
 */
export function TemporaryPasswordFields({
  idPrefix,
  password,
  confirm,
  onPasswordChange,
  onConfirmChange,
  error,
  details = [],
  disabled = false,
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-2">
        <Label htmlFor={`${idPrefix}-password`} required>
          Temporary password
        </Label>
        <PasswordInput
          name="temporary password"
          id={`${idPrefix}-password`}
          autoComplete="new-password"
          value={password}
          onChange={(event) => onPasswordChange(event.target.value)}
          disabled={disabled}
          aria-required="true"
          aria-invalid={error ? true : undefined}
        />
        <p className="text-muted-foreground text-xs">{PASSWORD_RULE}</p>
      </div>
      <div className="grid gap-2">
        <Label htmlFor={`${idPrefix}-confirm`} required>
          Confirm temporary password
        </Label>
        <PasswordInput
          name="password confirmation"
          id={`${idPrefix}-confirm`}
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => onConfirmChange(event.target.value)}
          disabled={disabled}
          aria-required="true"
          aria-invalid={error ? true : undefined}
        />
      </div>
      {error ? (
        <div className="text-destructive text-sm">
          <p>{error}</p>
          {details.length ? (
            <ul className="mt-1 list-disc pl-5">
              {details.map((detail) => (
                <li key={detail}>{detail}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
