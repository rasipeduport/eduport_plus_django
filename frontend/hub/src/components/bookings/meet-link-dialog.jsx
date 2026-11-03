import { useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MEET_LINK_EXAMPLE, meetLinkProblem, memberMeetLinkUrl, teamError } from '@/lib/team';

const FORM_ID = 'booking-meet-link-form';

/**
 * Setting or changing a tutor's permanent Google Meet link from a booking's
 * sheet (PUT /api/team/<id>/meet-link/, the Team page's endpoint): the API
 * lets only team managers do it, and keeps every booking that has ended with
 * the link it had. A link is required here -- removing one is the Team
 * page's. `tutor` is the booking's ({id, full_name}), `link` its current one.
 */
export function MeetLinkDialog({ tutor, link, open, onOpenChange, onSaved }) {
  const [value, setValue] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  // A fresh dialog on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setValue(link ?? '');
      setError(null);
    }
  }

  async function save(event) {
    event.preventDefault();
    const text = value.trim();
    const problem = text ? meetLinkProblem(text) : "Enter the tutor's Google Meet link.";
    if (problem) {
      setError(problem);
      return;
    }
    setPending(true);
    setError(null);
    try {
      const response = await api.put(memberMeetLinkUrl(tutor.id), { tutor_meet_link: text });
      onSaved?.(response.data);
      onOpenChange(false);
    } catch (err) {
      setError(teamError(err, 'Could not save the Meet link.').message);
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={link ? 'Change Meet link' : 'Set Meet link'}
      description={tutor ? `${tutor.full_name}'s permanent Google Meet link.` : null}
      error={error}
      formId={FORM_ID}
      confirmLabel="Save link"
      pending={pending}
      size="md"
    >
      <form id={FORM_ID} onSubmit={save} noValidate className="grid gap-2">
        <Label htmlFor="booking-meet-link">Google Meet link</Label>
        <Input
          id="booking-meet-link"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={MEET_LINK_EXAMPLE}
          inputMode="url"
          autoComplete="off"
          disabled={pending}
          aria-invalid={error ? true : undefined}
        />
        <p className="text-muted-foreground text-xs">
          Saved on the tutor&apos;s account: this booking and their other bookings that have not ended use it.
          Past bookings keep the link they had.
        </p>
      </form>
    </FormDialog>
  );
}
