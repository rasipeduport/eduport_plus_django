import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Label } from '@/components/ui/label';
import { TimezoneSelect } from '@/components/sessions/timezone-select';
import api from '@/lib/api';
import { DEFAULT_TIMEZONE, MENTOR_TIMEZONE, formatDateInZone, formatTimeInZone, timezoneShortLabel, zonedWallTimeToUtc } from '@/lib/timezone';

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

  // Preview of the instant the slot names, in the student's zone and the
  // mentor's (IST), like the session sheet's reference block.
  const previewWall = wallTimeFor(slot);
  let previewStart = null;
  if (previewWall) {
    try {
      previewStart = zonedWallTimeToUtc(previewWall, timezone);
    } catch {
      previewStart = null;
    }
  }
  const previewEnd = previewStart ? new Date(previewStart.getTime() + slot.duration * 3600000) : null;

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
        {previewStart && previewEnd && (
          <div className="bg-muted/40 text-muted-foreground rounded-md border px-3 py-2 text-xs">
            <p>
              Exam scheduled: <span className="text-foreground font-medium">{formatDateInZone(previewStart, timezone)}</span> ·{' '}
              <span className="text-foreground font-medium">
                {formatTimeInZone(previewStart, timezone)} – {formatTimeInZone(previewEnd, timezone)}
              </span>{' '}
              {timezoneShortLabel(timezone)}
            </p>
            <p className="mt-1">
              Student time: <span className="text-foreground font-medium">{formatTimeInZone(previewStart, timezone)} {timezoneShortLabel(timezone)}</span>
              {' · '}
              Mentor time: <span className="text-foreground font-medium">{formatTimeInZone(previewStart, MENTOR_TIMEZONE)} {timezoneShortLabel(MENTOR_TIMEZONE)}</span>
            </p>
          </div>
        )}
      </div>
    </FormDialog>
  );
}
