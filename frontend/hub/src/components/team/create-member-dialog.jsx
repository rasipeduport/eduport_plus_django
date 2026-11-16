import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/lib/api';
import { EMAIL_RE } from '@/lib/utils';
import { passwordPolicyError } from '@/lib/password-policy';
import { TEAM_URL, assignableRoles, roleLabel, teamError } from '@/lib/team';
import { TemporaryPasswordFields } from './temporary-password-fields';

const FORM_ID = 'create-team-member';
const EMPTY = { full_name: '', username: '', email: '', role: '', mobile_number: '' };
const FORM_FIELDS = new Set([...Object.keys(EMPTY), 'temporary_password']);

// The form field each refusal belongs to; anything else is shown above the
// buttons.
const FIELD_FOR_CODE = {
  USERNAME_TAKEN: 'username',
  EMAIL_IN_USE: 'email',
  INVALID_ROLE: 'role',
  SUPERUSER_REQUIRED: 'role',
  PASSWORD_POLICY: 'temporary_password',
};

function FieldError({ message }) {
  return message ? <p className="text-destructive text-sm">{message}</p> : null;
}

/**
 * Creates a staff account holding a temporary password the administrator
 * types. The Admin role is offered to superusers only, the one rule the API
 * applies to it; every other refusal comes back from the API.
 */
export function CreateMemberDialog({ viewer, open, onOpenChange, onCreated }) {
  const roles = assignableRoles(viewer);
  const [form, setForm] = useState(EMPTY);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [passwordDetails, setPasswordDetails] = useState([]);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  // A clean form on every open; the password is dropped on every close.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    setPassword('');
    setConfirm('');
    if (open) {
      setForm(EMPTY);
      setFieldErrors({});
      setPasswordDetails([]);
      setError('');
    }
  }

  const setField = (name) => (event) => setForm((current) => ({ ...current, [name]: event.target.value }));

  async function handleSubmit(event) {
    event.preventDefault();
    setError('');
    setPasswordDetails([]);

    const errors = {};
    if (!form.full_name.trim()) errors.full_name = 'Enter their name.';
    if (!form.username.trim()) errors.username = 'Choose a username.';
    if (!EMAIL_RE.test(form.email.trim())) errors.email = 'Enter a valid email address.';
    if (!form.role) errors.role = 'Choose a role.';
    if (!password) errors.temporary_password = 'Set a temporary password.';
    else if (passwordPolicyError(password)) errors.temporary_password = passwordPolicyError(password);
    else if (password !== confirm) errors.temporary_password = 'The two passwords do not match.';
    setFieldErrors(errors);
    if (Object.keys(errors).length) return;

    setPending(true);
    try {
      const response = await api.post(TEAM_URL, {
        full_name: form.full_name.trim(),
        username: form.username.trim(),
        email: form.email.trim(),
        role: form.role,
        ...(form.mobile_number.trim() ? { mobile_number: form.mobile_number.trim() } : {}),
        temporary_password: password,
      });
      const member = response.data;
      setPassword('');
      setConfirm('');
      onCreated?.(
        `Created ${member.full_name || member.username} (${member.username}) as ${roleLabel(member.role)}. ` +
          'Share the temporary password with them privately; they must replace it when they first sign in.'
      );
      onOpenChange(false);
    } catch (err) {
      const failure = teamError(err, 'Could not create the account.');
      const field =
        FIELD_FOR_CODE[failure.code] ??
        (failure.code === 'INVALID_INPUT' && failure.fields.length === 1 ? failure.fields[0] : null);
      if (field && FORM_FIELDS.has(field)) {
        setFieldErrors({ [field]: failure.message });
        if (failure.code === 'PASSWORD_POLICY') setPasswordDetails(failure.details);
      } else {
        setError(failure.message);
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add staff member"
      description={
        'They sign in with this username and the temporary password, and must choose their own password ' +
        'before using the Hub.'
      }
      error={error}
      formId={FORM_ID}
      confirmLabel="Create account"
      pendingLabel="Creating…"
      pending={pending}
      size="lg"
    >
      <form id={FORM_ID} onSubmit={handleSubmit} className="flex flex-col gap-4 py-1" noValidate>
        <div className="grid gap-2">
          <Label htmlFor="team-create-name" required>
            Name
          </Label>
          <Input
            id="team-create-name"
            value={form.full_name}
            onChange={setField('full_name')}
            placeholder="Full name"
            disabled={pending}
            aria-required="true"
            aria-invalid={fieldErrors.full_name ? true : undefined}
          />
          <FieldError message={fieldErrors.full_name} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid content-start gap-2">
            <Label htmlFor="team-create-username" required>
              Username
            </Label>
            <Input
              id="team-create-username"
              value={form.username}
              onChange={setField('username')}
              placeholder="e.g. jane.doe"
              autoComplete="off"
              disabled={pending}
              aria-required="true"
              aria-invalid={fieldErrors.username ? true : undefined}
            />
            <FieldError message={fieldErrors.username} />
          </div>
          <div className="grid content-start gap-2">
            <Label htmlFor="team-create-role" required>
              Role
            </Label>
            <Select
              value={form.role}
              onValueChange={(role) => setForm((current) => ({ ...current, role }))}
              disabled={pending}
            >
              <SelectTrigger
                id="team-create-role"
                className="w-full"
                aria-required="true"
                aria-invalid={fieldErrors.role ? true : undefined}
              >
                <SelectValue placeholder="Choose a role" />
              </SelectTrigger>
              <SelectContent>
                {roles.map((role) => (
                  <SelectItem key={role.value} value={role.value}>
                    {role.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldError message={fieldErrors.role} />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid content-start gap-2">
            <Label htmlFor="team-create-email" required>
              Email
            </Label>
            <Input
              id="team-create-email"
              type="email"
              value={form.email}
              onChange={setField('email')}
              placeholder="name@eduport.app"
              disabled={pending}
              aria-required="true"
              aria-invalid={fieldErrors.email ? true : undefined}
            />
            <FieldError message={fieldErrors.email} />
          </div>
          <div className="grid content-start gap-2">
            <Label htmlFor="team-create-mobile">Phone number (optional)</Label>
            <Input
              id="team-create-mobile"
              value={form.mobile_number}
              onChange={setField('mobile_number')}
              placeholder="+91 98765 43210"
              inputMode="tel"
              disabled={pending}
              aria-invalid={fieldErrors.mobile_number ? true : undefined}
            />
            <FieldError message={fieldErrors.mobile_number} />
          </div>
        </div>
        <TemporaryPasswordFields
          idPrefix="team-create"
          password={password}
          confirm={confirm}
          onPasswordChange={setPassword}
          onConfirmChange={setConfirm}
          error={fieldErrors.temporary_password}
          details={passwordDetails}
          disabled={pending}
        />
      </form>
    </FormDialog>
  );
}
