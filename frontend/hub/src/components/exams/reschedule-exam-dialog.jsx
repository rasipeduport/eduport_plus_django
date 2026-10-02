import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Label } from '@/components/ui/label';
import { TimezoneSelect } from '@/components/sessions/timezone-select';
import api from '@/lib/api';
import { DEFAULT_TIMEZONE, zonedWallTimeToUtc } from '@/lib/timezone';

import { SlotEditor, emptySlot, slotFromExam, wallTimeFor } from './slot-editor';

/** Reschedule a scheduled chapter exam (the Hub's RescheduleDialog). */
export function RescheduleExamDialog({ exam, studentTimezone, open, onOpenChange, onSaved }) {
  const zone = studentTimezone || DEFAULT_TIMEZONE;
  const [slot, setSlot] = useState(emptySlot());
  const [timezone, setTimezone] = useState(zone);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open && exam) {
      setSlot(slotFromExam(exam, zone));
      setTimezone(zone);
      setError('');
    }
  }

  const handleConfirm = async () => {
    const wall = wallTimeFor(slot);
    if (!wall) {
      setError('Please complete date, hour, minute, and AM/PM.');
      return;
    }
    try {
      zonedWallTimeToUtc(wall, timezone);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid date and time.');
      return;
    }
    setPending(true);
    setError('');
    try {
      await api.put('/api/exams/', {
        id: exam.id,
        local_date: wall.date,
        local_time: wall.time,
        timezone,
        duration_hours: slot.duration,
      });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.message || 'Failed to reschedule exam.');
    } finally {
      setPending(false);
    }
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={(v) => !pending && onOpenChange(v)}
      title="Reschedule Exam"
      description={exam?.chapter_name}
      error={error}
      onConfirm={handleConfirm}
      confirmLabel="Reschedule"
      pendingLabel="Saving…"
      pending={pending}
      size="md"
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Label>New Date &amp; Time</Label>
          <TimezoneSelect value={timezone} onValueChange={setTimezone} disabled={pending} className="w-52" />
        </div>
        <SlotEditor slot={slot} onChange={setSlot} disabled={pending} />
      </div>
    </FormDialog>
  );
}
