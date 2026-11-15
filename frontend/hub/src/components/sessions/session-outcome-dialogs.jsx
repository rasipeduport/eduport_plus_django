import { useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { OUTCOME_NOTE_MAX, OUTCOME_REASONS, lifecycleError, outcomeReasonLabel } from '@/lib/session-lifecycle';
import { mentorZoneFormatter } from '@/lib/timezone';
import { cn } from '@/lib/utils';

const STAMP_FORMAT = mentorZoneFormatter({ month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
const stamp = (iso) => (iso ? STAMP_FORMAT.format(new Date(iso)) : '');

const describe = (session) =>
  session ? `${session.title} · ${session.students?.full_name || 'the student'} · ${stamp(session.start_time)}` : null;

/** A fresh dialog on every open: ``reset`` runs as it opens. */
function useOnOpen(open, reset) {
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) reset();
  }
}

function ReasonPicker({ value, onChange, disabled, name }) {
  return (
    <fieldset className="flex flex-col gap-2" disabled={disabled}>
      <legend className="mb-1 text-sm font-medium">What happened?</legend>
      {OUTCOME_REASONS.map((option) => (
        <label
          key={option.value}
          className={cn(
            'hover:bg-muted/40 flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm',
            value === option.value && 'border-primary bg-muted/40'
          )}
        >
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
            className="mt-0.5"
          />
          <span>
            <span className="font-medium">{option.label}</span>
            <span className="text-muted-foreground block text-xs">{option.hint}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

function NoteField({ id, label, value, onChange, required, disabled, placeholder }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>
        {label}
        {required ? null : <span className="text-muted-foreground font-normal">(optional)</span>}
      </Label>
      <Textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={OUTCOME_NOTE_MAX}
        rows={3}
        disabled={disabled}
        placeholder={placeholder}
      />
    </div>
  );
}

/**
 * No-show / Not Conducted (POST /api/sessions/<id>/outcome/): an
 * administrator or the student's mentor records what happened to a class
 * that ended without its tutor's completion, for a reason from the list
 * (Other needs a note). Final once recorded -- only an administrator can
 * correct it -- and it rejects late notes still awaiting approval
 * (``rejectingLateNotes`` says so). The API checks it all again.
 */
export function RecordOutcomeDialog({ session, open, onOpenChange, onSaved, rejectingLateNotes = false }) {
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => {
    setReason('');
    setNote('');
    setError(null);
  });

  const noteRequired = reason === 'OTHER';
  const ready = Boolean(reason) && (!noteRequired || note.trim());

  async function record() {
    if (!session || !ready) return;
    setPending(true);
    setError(null);
    try {
      const response = await api.post(`/api/sessions/${session.id}/outcome/`, { reason, note: note.trim() || null });
      onSaved?.(response.data.session);
      onOpenChange(false);
    } catch (err) {
      setError(lifecycleError(err, 'Could not record the outcome.').message);
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={rejectingLateNotes ? 'Reject late notes' : 'Record outcome'}
      description={describe(session)}
      error={error}
      onConfirm={record}
      confirmLabel="Record outcome"
      pendingLabel="Recording…"
      confirmVariant="destructive"
      confirmDisabled={!ready}
      pending={pending}
      size="md"
    >
      <p className="text-muted-foreground text-sm">
        {rejectingLateNotes
          ? "The tutor's late notes will not complete this class. Record what actually happened instead. "
          : 'Record why this class was not conducted. '}
        Once recorded, it is final: only an administrator can correct it, and the class never counts toward Tutor Earnings.
      </p>
      <ReasonPicker value={reason} onChange={setReason} disabled={pending} name="session-outcome-reason" />
      <NoteField
        id="session-outcome-note"
        label="Note "
        value={note}
        onChange={setNote}
        required={noteRequired}
        disabled={pending}
        placeholder="What happened, for the record"
      />
    </FormDialog>
  );
}

/**
 * Late notes (POST /api/sessions/<id>/late-notes/approve/): the tutor's notes
 * came in more than 48 hours after the class. Approving them completes the
 * class as of when they came in, and it then counts toward Tutor Earnings;
 * rejecting them is recording the class's outcome (``onReject``).
 */
export function ReviewLateNotesDialog({ session, open, onOpenChange, onSaved, onReject }) {
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => setError(null));

  async function approve() {
    if (!session) return;
    setPending(true);
    setError(null);
    try {
      const response = await api.post(`/api/sessions/${session.id}/late-notes/approve/`);
      onSaved?.(response.data.session);
      onOpenChange(false);
    } catch (err) {
      setError(lifecycleError(err, 'Could not approve the late notes.').message);
    } finally {
      setPending(false);
    }
  }

  const notes = (session?.notes_link || '').trim();
  const tutor = session?.tutor_profile?.full_name || session?.tutor_profile?.email || 'The tutor';

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Review late notes"
      description={describe(session)}
      error={error}
      onConfirm={approve}
      confirmLabel="Approve & complete"
      pendingLabel="Approving…"
      cancelLabel="Close"
      pending={pending}
      size="md"
    >
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted-foreground">
          {tutor} submitted these notes {stamp(session?.late_notes_submitted_at)}, after the 48 hours that ended{' '}
          {stamp(session?.notes_due_by)}. Approving them completes the class as of then, and it counts toward Tutor
          Earnings.
        </p>
        {notes ? (
          <a href={notes} target="_blank" rel="noopener noreferrer" className="text-primary break-all underline">
            Open the notes
          </a>
        ) : (
          <p className="text-destructive">The notes are no longer on this class.</p>
        )}
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground self-start text-xs underline"
          onClick={() => onReject?.(session)}
          disabled={pending}
        >
          Reject them and record what happened instead
        </button>
      </div>
    </FormDialog>
  );
}

/**
 * An administrator's correction of a recorded outcome made by mistake
 * (accounts.correct_session_outcome): change its reason
 * (POST /api/sessions/<id>/outcome/correct/) or remove it altogether
 * (…/outcome/revoke/), the class then back to what it was. Every correction
 * says why, and is kept in the activity log.
 */
export function CorrectOutcomeDialog({ session, open, onOpenChange, onSaved }) {
  const [mode, setMode] = useState('reason');
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [why, setWhy] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  useOnOpen(open, () => {
    setMode('reason');
    setReason(session?.outcome_reason || '');
    setNote(session?.outcome_note || '');
    setWhy('');
    setError(null);
  });

  const revoking = mode === 'revoke';
  const ready = Boolean(why.trim()) && (revoking || (Boolean(reason) && (reason !== 'OTHER' || note.trim())));

  async function save() {
    if (!session || !ready) return;
    setPending(true);
    setError(null);
    try {
      const response = revoking
        ? await api.post(`/api/sessions/${session.id}/outcome/revoke/`, { correction_note: why.trim() })
        : await api.post(`/api/sessions/${session.id}/outcome/correct/`, {
            reason,
            note: note.trim() || null,
            correction_note: why.trim(),
          });
      onSaved?.(response.data.session);
      onOpenChange(false);
    } catch (err) {
      setError(lifecycleError(err, 'Could not correct the outcome.').message);
    } finally {
      setPending(false);
    }
  }

  const recorder = session?.outcome_recorded_by_profile?.full_name || session?.outcome_recorded_by_profile?.email || 'staff';

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Correct outcome"
      description={describe(session)}
      error={error}
      onConfirm={save}
      confirmLabel={revoking ? 'Remove outcome' : 'Save correction'}
      pendingLabel="Saving…"
      confirmVariant={revoking ? 'destructive' : 'default'}
      confirmDisabled={!ready}
      pending={pending}
      size="md"
    >
      <p className="text-muted-foreground text-sm">
        Recorded as {outcomeReasonLabel(session?.outcome_reason)} by {recorder} {stamp(session?.outcome_recorded_at)}.
        Correct it only for a genuine mistake; the correction and its reason are kept in the activity log.
      </p>
      <fieldset className="flex gap-4 text-sm" disabled={pending}>
        <legend className="sr-only">Correction</legend>
        {[
          ['reason', 'Change the reason'],
          ['revoke', 'Remove the outcome'],
        ].map(([value, label]) => (
          <label key={value} className="flex cursor-pointer items-center gap-2">
            <input type="radio" name="session-outcome-correction" checked={mode === value} onChange={() => setMode(value)} />
            {label}
          </label>
        ))}
      </fieldset>
      {revoking ? (
        <p className="text-muted-foreground text-sm">
          The class goes back to how it was before the outcome was recorded, and any late notes the outcome rejected
          await approval again.
        </p>
      ) : (
        <>
          <ReasonPicker value={reason} onChange={setReason} disabled={pending} name="session-outcome-corrected-reason" />
          <NoteField
            id="session-outcome-corrected-note"
            label="Note "
            value={note}
            onChange={setNote}
            required={reason === 'OTHER'}
            disabled={pending}
          />
        </>
      )}
      <NoteField
        id="session-outcome-correction-note"
        label="Why is it being corrected?"
        value={why}
        onChange={setWhy}
        required
        disabled={pending}
        placeholder="e.g. Recorded against the wrong class"
      />
    </FormDialog>
  );
}
