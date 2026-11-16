import { useEffect, useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/lib/api';
import { HANDOVER_ROLES, reassignUrl, teamError } from '@/lib/team';

/**
 * The colleague a departing mentor's or tutor's active students go to: the
 * active staff of the same role (the slim /api/mentors/ or /api/tutors/ list,
 * which already leaves deactivated staff out), minus the person leaving.
 */
export function ReplacementSelect({ member, value, onChange, disabled = false }) {
  const handover = HANDOVER_ROLES[member.role];
  const [options, setOptions] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!handover) return undefined;
    let active = true;
    api
      .get(handover.list)
      .then((response) => {
        if (active) setOptions((response.data[handover.key] ?? []).filter((option) => option.id !== member.id));
      })
      .catch((err) => {
        if (!active) return;
        setError(teamError(err, `Could not load the active ${handover.noun}s.`).message);
        setOptions([]);
      });
    return () => {
      active = false;
    };
  }, [handover, member.id]);

  if (!handover) return null;

  let placeholder = `Choose a ${handover.noun}`;
  if (options === null) placeholder = 'Loading…';
  else if (!options.length) placeholder = `No other active ${handover.noun}`;

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor="team-handover-replacement">Hand their students over to</Label>
      <Select value={value} onValueChange={onChange} disabled={disabled || !options?.length}>
        <SelectTrigger id="team-handover-replacement" className="w-full">
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {(options ?? []).map((option) => (
            <SelectItem key={option.id} value={option.id}>
              {option.full_name || option.email}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </div>
  );
}

/**
 * Hands every active student of `member` to a colleague of the same role
 * (POST /api/users/<id>/reassign/). A tutor's scheduled classes, or a
 * mentor's open exams, move with them; completed history keeps its attribution.
 */
export function HandoverDialog({ member, open, onOpenChange, onDone }) {
  const handover = HANDOVER_ROLES[member.role];
  const [replacement, setReplacement] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setReplacement('');
      setError('');
    }
  }

  const name = member.full_name || member.username;

  async function handleConfirm() {
    setPending(true);
    setError('');
    try {
      await api.post(reassignUrl(member.id), { [handover.field]: replacement });
      onDone?.(`Handed over ${name}'s active students.`);
      onOpenChange(false);
    } catch (err) {
      setError(teamError(err, 'Could not hand over the students.').message);
    } finally {
      setPending(false);
    }
  }

  if (!handover) return null;

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Hand over students"
      description={
        <>
          Move every active student of <strong>{name}</strong> to another {handover.noun}.{' '}
          {handover.noun === 'tutor' ? 'Their scheduled classes' : 'Their open exams'} move too; completed history
          stays with {name}.
        </>
      }
      error={error}
      onConfirm={handleConfirm}
      confirmLabel="Hand over students"
      pendingLabel="Handing over…"
      confirmDisabled={!replacement}
      pending={pending}
      size="md"
    >
      <div className="py-1">
        <ReplacementSelect member={member} value={replacement} onChange={setReplacement} disabled={pending} />
      </div>
    </FormDialog>
  );
}
