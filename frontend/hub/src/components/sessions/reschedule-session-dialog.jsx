import { useState } from 'react';

import { FormDialog } from '@/components/form-dialog';
import { Label } from '@/components/ui/label';
import { DURATIONS, MINUTE_OPTIONS, SlotEditor, emptySlot, wallTimeFor } from '@/components/exams/slot-editor';
import api from '@/lib/api';
import { describeApiError } from '@/lib/api-errors';
import {
  DEFAULT_TIMEZONE,
  MENTOR_TIMEZONE,
  TIMEZONE_OPTIONS,
  formatDateInZone,
  formatTimeInZone,
  timezoneShortLabel,
  utcToZonedWallTime,
  zonedWallTimeToUtc,
} from '@/lib/timezone';

import { SchedulingError } from './scheduling-error';

const HOUR_IN_MS = 60 * 60 * 1000;

/** "United Arab Emirates" for a listed zone; the raw identifier otherwise. */
function timezoneLongLabel(zone) {
  return TIMEZONE_OPTIONS.find((o) => o.value === zone)?.label ?? zone;
}

/**
 * The slot a session occupies, read back in the student's zone.
 *
 * The exact stored minute is kept (no rounding to the 5-minute grid): a
 * class booked at 8:37 through the old free-form picker must open at 8:37,
 * so confirming the dialog without touching it never moves the lesson.
 * The duration is kept when it is one the API allows; anything else falls
 * back to 1 hour, which the API would otherwise reject on save.
 */
function slotFromSession(session, zone) {
  const wall = utcToZonedWallTime(session.start_time, zone);
  const [y, m, d] = wall.date.split('-').map(Number);
  const [hour24, minute] = wall.time.split(':').map(Number);
  const hours = (new Date(session.end_time) - new Date(session.start_time)) / HOUR_IN_MS;
  return {
    date: new Date(y, m - 1, d),
    hour: String(hour24 % 12 === 0 ? 12 : hour24 % 12),
    minute: String(minute).padStart(2, '0'),
    meridiem: hour24 >= 12 ? 'PM' : 'AM',
    duration: DURATIONS.includes(hours) ? hours : 1,
  };
}

/** The 5-minute grid, plus the session's own minute when it sits off the grid. */
function minuteOptionsFor(minute) {
  if (!minute || MINUTE_OPTIONS.some((o) => o.value === minute)) return MINUTE_OPTIONS;
  return [...MINUTE_OPTIONS, { value: minute, label: minute }].sort((a, b) => Number(a.value) - Number(b.value));
}

/** `Wed, 7 Oct 2026 · 8:35 PM – 9:35 PM UAE` */
function formatWindow(start, end, zone) {
  return `${formatDateInZone(start, zone)} · ${formatTimeInZone(start, zone)} – ${formatTimeInZone(end, zone)} ${timezoneShortLabel(zone)}`;
}

/**
 * Reschedule one session, entering the new time in the student's zone -- the
 * New Session sheet's date / time / duration UX applied to an existing row.
 *
 * The zone is the student's stored timezone (IST when unset) and is shown
 * read-only: rescheduling moves the session and nothing else, so the
 * student's record is never written from here. The API keeps its existing
 * contract (`start_time` as a UTC instant + `duration_hours`); the wall time
 * is converted with the same rules the server applies to new bookings.
 */
export function RescheduleSessionDialog({ session, studentTimezone, open, onOpenChange, onSaved }) {
  const zone = studentTimezone || DEFAULT_TIMEZONE;
  const [slot, setSlot] = useState(emptySlot());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  // Re-sync from the session each time the dialog opens (see NewSessionSheet
  // for why this is done during render rather than in an effect).
  const [prevOpen, setPrevOpen] = useState(open);
  const [minuteOptions, setMinuteOptions] = useState(MINUTE_OPTIONS);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open && session) {
      const initial = slotFromSession(session, zone);
      setSlot(initial);
      setMinuteOptions(minuteOptionsFor(initial.minute));
      setError('');
    }
  }

  const currentStart = session ? new Date(session.start_time) : null;
  const currentEnd = session ? new Date(session.end_time) : null;

  // Preview only: the stored instant is whatever the API derives from the
  // UTC value sent on confirm, which is this same conversion.
  const previewWall = wallTimeFor(slot);
  let previewStart = null;
  if (previewWall) {
    try {
      previewStart = zonedWallTimeToUtc(previewWall, zone);
    } catch {
      previewStart = null;
    }
  }
  const previewEnd = previewStart ? new Date(previewStart.getTime() + slot.duration * HOUR_IN_MS) : null;

  const handleConfirm = async () => {
    const wall = wallTimeFor(slot);
    if (!wall) {
      setError('Please complete date, hour, minute, and AM/PM.');
      return;
    }
    // Surfaces a DST gap with the reason before a round trip.
    let instant;
    try {
      instant = zonedWallTimeToUtc(wall, zone);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid date and time.');
      return;
    }
    setPending(true);
    setError('');
    try {
      await api.put('/api/sessions/', {
        id: session.id,
        start_time: instant.toISOString(),
        duration_hours: slot.duration,
      });
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      // A 409 names the session or exam that blocks the slot; shown as it came.
      setError(err.response ? describeApiError(err, 'Failed to reschedule session.') : 'Network error. Please try again.');
    } finally {
      setPending(false);
    }
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={(v) => !pending && onOpenChange(v)}
      title="Reschedule Session"
      description={session?.title}
      onConfirm={handleConfirm}
      confirmLabel="Reschedule"
      pendingLabel="Rescheduling…"
      pending={pending}
      size="md"
    >
      <div className="flex flex-col gap-4">
        {currentStart && currentEnd && (
          <div className="bg-muted/40 text-muted-foreground rounded-md border px-3 py-2 text-xs">
            <p className="font-medium">Current schedule</p>
            <p className="text-foreground mt-0.5">{formatWindow(currentStart, currentEnd, zone)}</p>
            <p className="mt-0.5">
              Student: <span className="text-foreground">{formatTimeInZone(currentStart, zone)} {timezoneShortLabel(zone)}</span>
              {' | '}
              Mentor: <span className="text-foreground">{formatTimeInZone(currentStart, MENTOR_TIMEZONE)} {timezoneShortLabel(MENTOR_TIMEZONE)}</span>
            </p>
          </div>
        )}

        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Label>Date &amp; Time</Label>
            {/* Read-only on purpose: the zone belongs to the student and is
                changed on their profile or when booking, never from here. */}
            <span className="text-foreground text-sm font-medium" aria-label="Student timezone">
              {timezoneLongLabel(zone)}
            </span>
          </div>
          <p className="text-muted-foreground -mt-1 text-xs">
            {studentTimezone
              ? "Enter the student's local time."
              : 'This student has no timezone set. Times are entered in IST, the default.'}
          </p>
          <SlotEditor slot={slot} onChange={setSlot} disabled={pending} minuteOptions={minuteOptions} />
        </div>

        {previewStart && previewEnd && (
          <div className="bg-muted/40 text-muted-foreground rounded-md border px-3 py-2 text-xs">
            <p className="font-medium">New session time</p>
            <p className="text-foreground mt-0.5">{formatWindow(previewStart, previewEnd, zone)}</p>
            <p className="mt-0.5">
              Student time: <span className="text-foreground font-medium">{formatTimeInZone(previewStart, zone)} {timezoneShortLabel(zone)}</span>
            </p>
            <p>
              Mentor time: <span className="text-foreground font-medium">{formatTimeInZone(previewStart, MENTOR_TIMEZONE)} {timezoneShortLabel(MENTOR_TIMEZONE)}</span>
            </p>
          </div>
        )}

        <SchedulingError error={error} />
      </div>
    </FormDialog>
  );
}
