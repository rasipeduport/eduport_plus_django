import { useState } from 'react';
import { format } from 'date-fns';
import { EyeIcon, EyeOffIcon, InfoIcon } from 'lucide-react';

import { FormDialog } from '@/components/form-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/lib/api';
import { formatDate } from '@/lib/utils';
import { PASSWORD_RULE } from '@/lib/password-policy';
import {
  HANDOVER_ROLES,
  TEAM_ROLES,
  assignableRoles,
  isActiveMember,
  isLocked,
  memberFormValues,
  memberUrl,
  planMemberSave,
  roleLabel,
  teamError,
  validateMemberForm,
} from '@/lib/team';
import { MemberPermissionsEditor } from './member-permissions-editor';
import { HandoverDialog } from './student-handover';

const DETAIL_FIELDS = new Set(['username', 'full_name', 'email', 'mobile_number', 'role']);

// The details field each PATCH refusal belongs to.
const FIELD_FOR_CODE = {
  USERNAME_TAKEN: 'username',
  EMAIL_IN_USE: 'email',
  INVALID_ROLE: 'role',
  HANDOVER_REQUIRED: 'role',
  LAST_ADMIN: 'role',
};

const STEP_LABELS = { details: 'details', permissions: 'permissions', password: 'temporary password' };

// Checked in the permission selector but never assigned: saving would drop them unnoticed.
const unassignedMessage = (count) =>
  `Click Assign Selected to add the ${count === 1 ? 'selected permission' : `${count} selected permissions`}, ` +
  'or clear the selection, before saving.';

const formatDateTime = (value) => (value ? format(new Date(value), 'd MMM yyyy, h:mm a') : '—');

function Field({ id, label, required = false, hint, error, children }) {
  return (
    <div className="grid content-start gap-2">
      <Label htmlFor={id} required={required}>
        {label}
      </Label>
      {children}
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
      {error ? <div className="text-destructive text-sm">{error}</div> : null}
    </div>
  );
}

function SummaryRow({ label, children }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function passwordState(member) {
  // Staff never sign in with Google, so an account without a password cannot sign in at all.
  if (member.has_password === false) return 'None: they cannot sign in until you set a temporary password';
  if (member.must_change_password) return 'Temporary; must be replaced at their next sign-in';
  return 'Set';
}

/** Read-only account state. Directory readers receive fewer fields from the API. */
function AccountSummary({ member }) {
  const full = member.permissions !== undefined;
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-semibold">Account</h2>
      <dl className="divide-y rounded-md border px-4">
        <SummaryRow label="Status">
          {isActiveMember(member) ? 'Active' : `Deactivated ${formatDateTime(member.deactivated_at)}`}
          {!isActiveMember(member) && member.deactivation_reason ? (
            <span className="text-muted-foreground block">Reason: {member.deactivation_reason}</span>
          ) : null}
        </SummaryRow>
        {full ? (
          <>
            <SummaryRow label="Password">{passwordState(member)}</SummaryRow>
            <SummaryRow label="Sign-in lockout">
              {isLocked(member) ? `Locked until ${formatDateTime(member.locked_until)}` : 'Not locked'}
            </SummaryRow>
            <SummaryRow label="Last sign-in">{formatDateTime(member.last_login)}</SummaryRow>
            <SummaryRow label="Created by">
              {member.invited_by ? member.invited_by.full_name || member.invited_by.email : '—'}
            </SummaryRow>
          </>
        ) : null}
        <SummaryRow label="Joined">{formatDate(member.created_at)}</SummaryRow>
      </dl>
    </section>
  );
}

/**
 * The Details & Permissions tab of /team/:memberId. Saving sends only what
 * changed, in order: details (PATCH), permissions (PUT), then the optional
 * password reset. Each call is checked by the API; if one is refused, the ones
 * before it stay saved, the form keeps the rest of the edits, and the refusal
 * is shown at the field it concerns. `restriction` (the viewer's own account,
 * or an account beyond their reach) makes the whole form read-only.
 */
export function MemberDetailsForm({ member, viewer, catalogue, restriction, onSaved, onRetryCatalogue }) {
  const readOnly = Boolean(restriction);
  // The member as the API last returned it to this form: what edits are
  // measured against.
  const [baseline, setBaseline] = useState(member);
  const [values, setValues] = useState(() => memberFormValues(member));
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState({});
  const [passwordDetails, setPasswordDetails] = useState([]);
  const [formError, setFormError] = useState('');
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(null);
  const [handoverOpen, setHandoverOpen] = useState(false);
  // Permissions checked in the selector but not assigned yet.
  const [picked, setPicked] = useState([]);

  const plan = planMemberSave(baseline, values);
  const dirty = Boolean(plan.details || plan.permissions || plan.password || picked.length);
  const roleOptions = readOnly ? TEAM_ROLES : assignableRoles(viewer);
  const name = member.full_name || member.username;

  const setField = (field) => (event) => setValues((current) => ({ ...current, [field]: event.target.value }));

  // Any change to the permissions answers the message shown about them.
  const clearPermissionsError = () =>
    setErrors((current) => (current.permissions ? { ...current, permissions: undefined } : current));
  const changePermissions = (permissions) => {
    setValues((current) => ({ ...current, permissions }));
    clearPermissionsError();
  };
  const changePicked = (next) => {
    setPicked(next);
    clearPermissionsError();
  };

  function clearMessages() {
    setErrors({});
    setPasswordDetails([]);
    setFormError('');
  }

  function cancel() {
    setValues(memberFormValues(baseline));
    setPicked([]);
    setShowPassword(false);
    clearMessages();
  }

  function handleSubmit(event) {
    event.preventDefault();
    clearMessages();
    const problems = validateMemberForm(values) ?? {};
    if (picked.length) problems.permissions = { message: unassignedMessage(picked.length) };
    if (Object.keys(problems).length) {
      setErrors(problems);
      return;
    }
    if (!dirty) return;
    if (plan.details?.role) setConfirming(plan);
    else save(plan);
  }

  function showFailure(step, failure, savedSteps) {
    if (step === 'details') {
      const field =
        FIELD_FOR_CODE[failure.code] ??
        (failure.code === 'SUPERUSER_REQUIRED' && plan.details?.role ? 'role' : null) ??
        (failure.code === 'INVALID_INPUT' && failure.fields.length === 1 ? failure.fields[0] : null);
      if (field && DETAIL_FIELDS.has(field)) {
        // A role change waits for the person's active students to be handed
        // over; offer that here, then the save is simply repeated.
        const handover = failure.code === 'HANDOVER_REQUIRED' && HANDOVER_ROLES[member.role];
        setErrors({
          [field]: (
            <>
              {failure.message}{' '}
              {handover ? (
                <button
                  type="button"
                  onClick={() => setHandoverOpen(true)}
                  className="font-medium underline underline-offset-4"
                >
                  Hand over students…
                </button>
              ) : null}
            </>
          ),
        });
      } else {
        setFormError(failure.message);
      }
    } else if (step === 'permissions') {
      setErrors({ permissions: failure });
    } else {
      setErrors({ password: failure.message });
      setPasswordDetails(failure.details);
    }
    if (savedSteps.length) {
      setFormError(
        `Saved the ${savedSteps.map((saved) => STEP_LABELS[saved]).join(' and ')}; ` +
          `the ${STEP_LABELS[step]} could not be saved.`
      );
    }
  }

  async function save(saving) {
    setConfirming(null);
    setPending(true);
    const saved = [];
    let step = 'details';
    let fresh = null;
    try {
      if (saving.details) {
        step = 'details';
        fresh = (await api.patch(memberUrl(member.id), saving.details)).data;
        saved.push(step);
      }
      if (saving.permissions) {
        step = 'permissions';
        fresh = (await api.put(memberUrl(member.id, 'permissions/'), { permissions: saving.permissions })).data;
        saved.push(step);
      }
      if (saving.password) {
        step = 'password';
        fresh = (await api.post(memberUrl(member.id, 'reset-password/'), { temporary_password: saving.password })).data;
        saved.push(step);
      }
    } catch (err) {
      showFailure(step, teamError(err, 'Could not save the changes.'), saved);
      // What did save becomes the new baseline, so a retry sends only the rest.
      if (fresh) {
        setBaseline(fresh);
        onSaved?.(null, fresh);
      }
      setPending(false);
      return;
    }

    setBaseline(fresh);
    setValues(memberFormValues(fresh));
    setShowPassword(false);
    setPending(false);
    onSaved?.(
      saved.includes('password')
        ? `Saved. ${name} must replace the temporary password at their next sign-in.`
        : 'Changes saved.',
      fresh
    );
  }

  const controlsDisabled = readOnly || pending;

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-8">
      {restriction ? (
        <p className="bg-muted text-muted-foreground flex items-start gap-2 rounded-md p-3 text-sm">
          <InfoIcon className="mt-0.5 size-4 shrink-0" />
          {restriction}
        </p>
      ) : null}

      <section className="grid gap-5 sm:grid-cols-2">
        <Field id="team-member-username" label="Username" required error={errors.username}>
          <Input
            id="team-member-username"
            value={values.username}
            onChange={setField('username')}
            autoComplete="off"
            disabled={controlsDisabled}
            aria-required="true"
            aria-invalid={errors.username ? true : undefined}
          />
        </Field>
        <Field id="team-member-name" label="Full name" required error={errors.full_name}>
          <Input
            id="team-member-name"
            value={values.full_name}
            onChange={setField('full_name')}
            disabled={controlsDisabled}
            aria-required="true"
            aria-invalid={errors.full_name ? true : undefined}
          />
        </Field>
        <Field id="team-member-email" label="Email" required error={errors.email}>
          <Input
            id="team-member-email"
            type="email"
            value={values.email}
            onChange={setField('email')}
            autoComplete="off"
            disabled={controlsDisabled}
            aria-required="true"
            aria-invalid={errors.email ? true : undefined}
          />
        </Field>
        <Field id="team-member-phone" label="Phone" error={errors.mobile_number}>
          <Input
            id="team-member-phone"
            value={values.mobile_number}
            onChange={setField('mobile_number')}
            placeholder="+91 98765 43210"
            inputMode="tel"
            maxLength={20}
            disabled={controlsDisabled}
            aria-invalid={errors.mobile_number ? true : undefined}
          />
        </Field>
        <Field
          id="team-member-role"
          label="Role"
          required
          hint={readOnly ? null : 'A change asks for confirmation when you save.'}
          error={errors.role}
        >
          <Select
            value={values.role}
            onValueChange={(role) => setValues((current) => ({ ...current, role }))}
            disabled={controlsDisabled}
          >
            <SelectTrigger
              id="team-member-role"
              className="w-full"
              aria-required="true"
              aria-invalid={errors.role ? true : undefined}
            >
              <SelectValue placeholder="Choose a role" />
            </SelectTrigger>
            <SelectContent>
              {roleOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {readOnly ? null : (
          <Field
            id="team-member-password"
            label="Reset password (optional)"
            hint={
              `Leave blank to keep the current password. ${PASSWORD_RULE} A new one is temporary: they must ` +
              'replace it at their next sign-in, and their open sessions end.'
            }
            error={
              errors.password ? (
                <>
                  <p>{errors.password}</p>
                  {passwordDetails.length ? (
                    <ul className="mt-1 list-disc pl-5">
                      {passwordDetails.map((detail) => (
                        <li key={detail}>{detail}</li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : null
            }
          >
            <div className="relative">
              <Input
                id="team-member-password"
                type={showPassword ? 'text' : 'password'}
                value={values.password}
                onChange={setField('password')}
                placeholder="Enter a new temporary password"
                autoComplete="new-password"
                disabled={pending}
                className="pr-10"
                aria-invalid={errors.password ? true : undefined}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="absolute top-0 right-0 size-9"
                onClick={() => setShowPassword((shown) => !shown)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                disabled={pending}
              >
                {showPassword ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
              </Button>
            </div>
          </Field>
        )}
      </section>

      <AccountSummary member={member} />

      {member.permissions !== undefined ? (
        <MemberPermissionsEditor
          catalogue={catalogue}
          selected={values.permissions}
          saved={baseline.permissions ?? []}
          picked={picked}
          onChange={changePermissions}
          onPickedChange={changePicked}
          onRetryCatalogue={onRetryCatalogue}
          readOnly={readOnly}
          disabled={pending}
          error={errors.permissions}
        />
      ) : null}

      {formError ? (
        <p role="alert" className="text-destructive text-sm">
          {formError}
        </p>
      ) : null}

      {readOnly ? null : (
        <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
          <Button type="button" variant="outline" onClick={cancel} disabled={pending || !dirty}>
            Cancel
          </Button>
          <Button type="submit" disabled={pending || !dirty}>
            {pending ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      )}

      <FormDialog
        open={Boolean(confirming)}
        onOpenChange={(open) => (open ? null : setConfirming(null))}
        title="Change role?"
        description={
          confirming?.details?.role ? (
            <>
              <strong>{name}</strong> will change from {roleLabel(baseline.role)} to{' '}
              {roleLabel(confirming.details.role)}. Their access changes as soon as you save.
            </>
          ) : null
        }
        onConfirm={() => save(confirming)}
        confirmLabel="Change role and save"
        pending={pending}
        size="md"
      >
        <p className="text-muted-foreground text-sm">
          {confirming?.details?.role === 'ADMIN'
            ? 'Admins can manage students, invitations, and mentor and tutor accounts.'
            : 'Someone with active students must hand them over before their role can change.'}
        </p>
      </FormDialog>

      <HandoverDialog
        member={member}
        open={handoverOpen}
        onOpenChange={setHandoverOpen}
        onDone={(message) => {
          setErrors((current) => ({ ...current, role: undefined }));
          onSaved?.(`${message} Save again to change their role.`, null);
        }}
      />
    </form>
  );
}
