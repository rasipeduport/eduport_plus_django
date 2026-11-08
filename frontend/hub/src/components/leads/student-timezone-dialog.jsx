import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Label } from '@/components/ui/label';
import { TimezoneSelect } from '@/components/sessions/timezone-select';
import api from '@/lib/api';
import { enquiryError } from '@/lib/enquiries';
import { listedTimezone } from '@/lib/timezone';

const FORM_ID = 'change-student-timezone';

// What a refusal says where the API gives no words of its own (backend
// bookings.student_timezones): a zone it does not know, or the lead held by
// another change past the lock's wait.
const REFUSALS = {
  INVALID_TIMEZONE: 'Choose a valid time zone.',
  LEAD_BUSY: "Someone else is changing this student's details right now. Try again in a moment.",
};

/**
 * The zone `lead` keeps, as the select holds it: its listed option under any
 * of its names (Asia/Calcutta opens on India), any other zone as it is, '' for none.
 */
const savedZone = (lead) => listedTimezone(lead?.student_timezone);

/**
 * Sets, corrects or clears (Not set) the time zone `lead`'s student is in --
 * `lead` is the lead or enquiry in full (student_name, student_timezone) --
 * with a PUT of `{ student_timezone }` (null for Not set) to `url`: a BDE's
 * own enquiry's route or the administrators' lead route, which answers the
 * lead as it now stands for `onSaved(updated)`. Only the Student Time staff
 * see changes: every booking stays offered, booked and moved in Indian time.
 */
export function StudentTimezoneDialog({ lead, url, open, onOpenChange, onSaved }) {
  const [zone, setZone] = useState(() => savedZone(lead));
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  // The saved zone again on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setZone(savedZone(lead));
      setError(null);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    // Saved as it was: nothing to change, and nothing to log.
    if (zone === savedZone(lead)) {
      onOpenChange(false);
      return;
    }
    setPending(true);
    setError(null);
    try {
      const response = await api.put(url, { student_timezone: zone || null });
      onSaved?.(response.data);
      onOpenChange(false);
    } catch (err) {
      const code = err?.response?.data?.error;
      setError(enquiryError(err, REFUSALS[code] ?? 'Could not change the student timezone.').message);
    } finally {
      setPending(false);
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Change student timezone"
      description={`The timezone ${lead?.student_name ?? 'the student'} is in. Booking times stay in Indian time (IST); only the Student Time shown beside them changes.`}
      error={error}
      formId={FORM_ID}
      confirmLabel="Save"
      pendingLabel="Saving…"
      pending={pending}
    >
      <form id={FORM_ID} onSubmit={handleSubmit} className="grid gap-2 py-1" noValidate>
        <Label htmlFor="student-timezone">Student timezone</Label>
        <TimezoneSelect
          id="student-timezone"
          value={zone}
          onValueChange={setZone}
          allowNotSet
          size="default"
          className="w-full"
          disabled={pending}
        />
      </form>
    </FormDialog>
  );
}
