import { useEffect, useState } from 'react';
import { CopyIcon, EyeIcon, InfoIcon, KeyRoundIcon, MoreHorizontalIcon, RefreshCwIcon, TriangleAlertIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { PERMISSIONS, can } from '@/lib/access';
import api from '@/lib/api';

const errorMessage = (err, fallback) => err.response?.data?.message || err.response?.data?.detail || fallback;

// What Copy Login Details and the credentials dialog put on the clipboard.
const loginDetails = (invitation, credentials) =>
  `Eduport Plus Learn\n${invitation.student_name} · ${credentials.student_code}\nUsername: ${credentials.username}\nTemporary password: ${credentials.temporary_password}\nChange your password at first sign in.`;

function CredentialsBody({ invitation, credentials, copyFailed }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(copyFailed ? 'Clipboard unavailable. Copy the credentials manually.' : '');
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(loginDetails(invitation, credentials));
      setCopied(true);
      setError('');
    } catch {
      setError('Clipboard unavailable. Copy the credentials manually.');
    }
  };
  return (
    <div className="min-w-0 space-y-4">
      <p className="text-sm">
        {invitation.student_name} · {credentials.student_code}
      </p>
      <label className="block space-y-1 text-sm">
        Username
        <Input readOnly value={credentials.username} />
      </label>
      <label className="block space-y-1 text-sm">
        Temporary password
        <Input readOnly autoComplete="off" value={credentials.temporary_password} />
      </label>
      {error ? (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      ) : null}
      <Button onClick={copy}>
        <CopyIcon />
        {copied ? 'Copied' : 'Copy credentials'}
      </Button>
    </div>
  );
}

// The two ways an administrator gives an account a new temporary password (backend
// invitations.views): a pending account's is regenerated, an activated account's
// password is reset. Either way the account must choose its own at its next sign-in.
const REPLACEMENTS = {
  regenerate: {
    icon: RefreshCwIcon,
    title: 'Regenerate Temporary Password',
    lead: (invitation) => `A new temporary password will be generated for ${invitation.student_name} (${invitation.student_code}).`,
    tone: 'info',
    points: [
      'The old temporary password will no longer work.',
      'Share the new credentials securely with the student/parent.',
      'The student must set a new password on first login.',
    ],
    confirm: 'Generate New Password',
    working: 'Generating…',
    failed: 'Could not regenerate the temporary password.',
    shownFailed: 'The temporary password was regenerated, but could not be shown',
    done: 'The old temporary password no longer works. Share these privately with the student or parent; the student sets their own password at first sign in.',
  },
  reset: {
    icon: KeyRoundIcon,
    title: 'Reset Password',
    lead: (invitation) => `A temporary password will replace the Learn password of ${invitation.student_name} (${invitation.student_code}).`,
    tone: 'warning',
    points: [
      "The student's current password stops working immediately and is never shown.",
      'They are signed out of Learn on every device.',
      'The account stays Activated; they must set a new password at their next login.',
      'Share the new temporary password securely with the student/parent.',
    ],
    confirm: 'Reset Password',
    working: 'Resetting…',
    failed: 'Could not reset the password.',
    shownFailed: 'The password was reset, but the temporary password could not be shown',
    done: 'The previous password no longer works and the student has been signed out. Share these privately with the student or parent; they set a new password at their next login.',
  },
};

const TONES = {
  info: { box: 'border-info/20 bg-info/5', icon: InfoIcon, iconClass: 'text-info' },
  warning: { box: 'border-warning/30 bg-warning/5', icon: TriangleAlertIcon, iconClass: 'text-warning' },
};

/**
 * Regenerate Temporary Password or Reset Password (`kind`, one of
 * REPLACEMENTS): asks first, then replaces the password (POST
 * .../credentials/<kind>/ with the last update the list showed, so a second
 * click or another administrator's change is refused rather than repeated).
 * `onReplaced` reads the new password through the audited reveal; `onChanged`
 * reads the list again whenever the row may have moved on.
 */
function ReplacePasswordDialog({ kind, invitation, open, onOpenChange, onReplaced, onChanged }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const text = REPLACEMENTS[kind];
  const tone = TONES[text.tone];

  const replace = async () => {
    setPending(true);
    setError('');
    try {
      await api.post(`/api/invitations/${invitation.id}/credentials/${kind}/`, {
        last_password_reset_at: invitation.last_password_reset_at ?? null,
      });
    } catch (err) {
      setError(errorMessage(err, text.failed));
      if (err.response?.status === 409) onChanged?.();
      setPending(false);
      return;
    }
    onChanged?.();
    try {
      await onReplaced(kind);
    } catch (err) {
      setError(`${text.shownFailed}: ${errorMessage(err, 'try Reveal Password.')}`);
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (pending) return;
        if (!next) setError('');
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <text.icon className="size-5" aria-hidden="true" />
            {text.title}
          </DialogTitle>
          <DialogDescription>{text.lead(invitation)}</DialogDescription>
        </DialogHeader>
        <div className={`${tone.box} flex gap-3 rounded-lg border p-3 text-sm`}>
          <tone.icon className={`${tone.iconClass} mt-0.5 size-4 shrink-0`} aria-hidden="true" />
          <ul className="list-disc space-y-1 pl-4">
            {text.points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </div>
        {error ? (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={pending} onClick={replace}>
            {pending ? text.working : text.confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * A Learn account's actions, for whoever may reveal its credentials (view +
 * change invitation, as the API checks). Pending: Reveal Password, and a menu
 * with Regenerate Temporary Password and Copy Login Details. Activated: Reset
 * Password -- and, while the temporary password a reset issued waits for the
 * student to replace it, a menu to reveal or copy it. The student's own
 * password is never readable. Every password is read through the audited
 * reveal endpoint and kept in memory only while its dialog is open.
 */
export function InvitationActionCell({ invitation, user, onChanged }) {
  // { credentials, replaced, copyFailed } while the credentials dialog is open;
  // `replaced` names the REPLACEMENTS entry that just issued the password.
  const [shown, setShown] = useState(null);
  // The REPLACEMENTS entry whose confirmation is open.
  const [replacing, setReplacing] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(''), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  const canManage = can(user, PERMISSIONS.changeInvitation) && can(user, PERMISSIONS.viewInvitations);
  const canReveal = canManage && invitation.credentials_available;
  const canRegenerate = canManage && invitation.credentials_regenerable;
  const canReset = canManage && invitation.password_resettable;
  // A dialog stays open even if the row's refreshed state no longer offers its action.
  if (!canReveal && !canRegenerate && !canReset && !shown && !replacing) return null;
  // Reset Password takes the button on an activated row, so Reveal moves into the menu.
  const revealInMenu = canReveal && canReset;

  const fetchCredentials = async (purpose) =>
    (await api.post(`/api/invitations/${invitation.id}/credentials/`, purpose ? { purpose } : undefined)).data;

  const reveal = async () => {
    setPending(true);
    setError('');
    setNotice('');
    try {
      setShown({ credentials: await fetchCredentials() });
    } catch (err) {
      setError(errorMessage(err, 'Could not retrieve credentials.'));
    } finally {
      setPending(false);
    }
  };

  const copyLoginDetails = async () => {
    setPending(true);
    setError('');
    setNotice('');
    try {
      // Logged as a copy, not a reveal (backend invitations.views).
      const credentials = await fetchCredentials('copy');
      try {
        await navigator.clipboard.writeText(loginDetails(invitation, credentials));
        setNotice('Login details copied.');
      } catch {
        setShown({ credentials, copyFailed: true });
      }
    } catch (err) {
      setError(errorMessage(err, 'Could not retrieve credentials.'));
    } finally {
      setPending(false);
    }
  };

  const showReplaced = async (kind) => {
    const credentials = await fetchCredentials();
    setReplacing(null);
    setShown({ credentials, replaced: kind });
  };

  const activated = invitation.status === 'ACCEPTED';
  let credentialsTitle = activated ? 'Temporary Learn credentials' : 'Initial Learn credentials';
  let credentialsNote = activated
    ? 'Share privately with the student or parent. The temporary password is erased when the student sets their own password.'
    : 'Share privately with the student or parent. The temporary password is erased after the first password change.';
  if (shown?.replaced) {
    credentialsTitle = 'New temporary password';
    credentialsNote = REPLACEMENTS[shown.replaced].done;
  }
  const primaryButton = 'bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary';

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        {canReset ? (
          <Button type="button" size="sm" variant="ghost" className={primaryButton} disabled={pending} onClick={() => setReplacing('reset')}>
            Reset Password
          </Button>
        ) : canReveal ? (
          <Button type="button" size="sm" variant="ghost" className={primaryButton} disabled={pending} onClick={reveal}>
            Reveal Password
          </Button>
        ) : null}
        {canRegenerate || canReveal ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                disabled={pending}
                aria-label={`More actions for ${invitation.student_name || invitation.username}`}
              >
                <MoreHorizontalIcon className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {canRegenerate ? (
                <DropdownMenuItem onSelect={() => setReplacing('regenerate')}>
                  <RefreshCwIcon />
                  Regenerate Temporary Password
                </DropdownMenuItem>
              ) : null}
              {revealInMenu ? (
                <DropdownMenuItem onSelect={reveal}>
                  <EyeIcon />
                  Reveal Password
                </DropdownMenuItem>
              ) : null}
              {canReveal ? (
                <DropdownMenuItem onSelect={copyLoginDetails}>
                  <CopyIcon />
                  Copy Login Details
                </DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="text-success text-sm">
          {notice}
        </p>
      ) : null}

      {Object.keys(REPLACEMENTS).map((kind) => (
        <ReplacePasswordDialog
          key={kind}
          kind={kind}
          invitation={invitation}
          open={replacing === kind}
          onOpenChange={(open) => setReplacing(open ? kind : null)}
          onReplaced={showReplaced}
          onChanged={onChanged}
        />
      ))}
      <Dialog open={Boolean(shown)} onOpenChange={(open) => (!open ? setShown(null) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{credentialsTitle}</DialogTitle>
            <DialogDescription>{credentialsNote}</DialogDescription>
          </DialogHeader>
          {shown ? <CredentialsBody invitation={invitation} credentials={shown.credentials} copyFailed={shown.copyFailed} /> : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
