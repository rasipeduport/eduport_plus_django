import { useState } from 'react';
import { AlertTriangleIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { TimezoneSelect } from '@/components/sessions/timezone-select';
import api from '@/lib/api';
import { DEFAULT_TIMEZONE, formatDateInZone, formatTimeInZone, timezoneShortLabel, zonedWallTimeToUtc } from '@/lib/timezone';

import { SlotEditor, emptySlot, wallTimeFor } from './slot-editor';

/**
 * "New Chapter Exam" drawer (the Hub's NewExamSheet). The chapter comes from
 * the student's sessions (GET /api/exams/chapter-names/); date, time and
 * duration are entered in the student's zone exactly like a class.
 */
export function NewExamSheet({ student, chapterNames, open, onOpenChange, onCreated }) {
  const studentId = student?.id ?? '';
  const initialTimezone = student?.timezone || DEFAULT_TIMEZONE;

  const [chapter, setChapter] = useState('');
  const [slot, setSlot] = useState(emptySlot());
  const [timezone, setTimezone] = useState(initialTimezone);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setChapter('');
      setSlot(emptySlot());
      setTimezone(initialTimezone);
      setError('');
    }
  }

  const noChapters = !chapterNames || chapterNames.length === 0;
  const timezoneChanged = timezone !== initialTimezone;

  const wall = wallTimeFor(slot);
  let start = null;
  if (wall) {
    try {
      start = zonedWallTimeToUtc(wall, timezone);
    } catch {
      start = null;
    }
  }
  const end = start ? new Date(start.getTime() + slot.duration * 3600000) : null;

  const handleOpenChange = (value) => {
    if (isSaving) return;
    onOpenChange(value);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!studentId) {
      setError('Missing student scope.');
      return;
    }
    if (!chapter) {
      setError('Please select a chapter.');
      return;
    }
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

    setIsSaving(true);
    try {
      if (timezoneChanged) {
        try {
          await api.put('/api/students/', { id: studentId, timezone });
        } catch (err) {
          setError(err.response?.data?.message || err.response?.data?.error || "Failed to update the student's timezone.");
          return;
        }
      }
      try {
        await api.post('/api/exams/', {
          student_id: studentId,
          chapter_name: chapter,
          local_date: wall.date,
          local_time: wall.time,
          timezone,
          duration_hours: slot.duration,
        });
      } catch (err) {
        setError(err.response ? err.response.data?.error || err.response.data?.message || 'Failed to create exam.' : 'Network error. Please try again.');
        return;
      }
      onCreated?.();
      onOpenChange(false);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent side="right" className="flex flex-col sm:max-w-md">
        <SheetHeader>
          <SheetTitle>New Chapter Exam</SheetTitle>
          <SheetDescription>Schedule a live chapter exam between the mentor and this student.</SheetDescription>
        </SheetHeader>

        <form id="new-exam-form" onSubmit={handleSubmit} className="flex flex-1 flex-col gap-6 overflow-y-auto px-4 py-2">
          {noChapters && (
            <div className="border-destructive/40 bg-destructive/5 text-destructive flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
              <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
              <span>This student has no sessions yet. Schedule a session first — chapter names come from the student's sessions.</span>
            </div>
          )}

          <div className="flex flex-col gap-2">
            <Label htmlFor="exam-chapter">Chapter</Label>
            <Select value={chapter} onValueChange={setChapter} disabled={noChapters || isSaving}>
              <SelectTrigger id="exam-chapter" aria-label="Chapter" className="w-full">
                <SelectValue placeholder="Select a chapter" />
              </SelectTrigger>
              <SelectContent position="popper">
                {(chapterNames || []).map((name) => (
                  <SelectItem key={name} value={name}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">Single sessions by title; a series only once every class in it is attended.</p>
          </div>

          <Separator />

          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label>Date &amp; Time</Label>
              <TimezoneSelect value={timezone} onValueChange={setTimezone} disabled={isSaving} className="w-56" />
            </div>
            <p className="text-muted-foreground -mt-1 text-xs">
              {timezoneChanged ? "Enter the student's local time. Saving will update the student's timezone to this." : "Enter the student's local time."}
            </p>
            <SlotEditor slot={slot} onChange={setSlot} disabled={isSaving} />
          </div>

          {start && end && (
            <div className="bg-muted/40 text-muted-foreground rounded-md border px-3 py-2 text-xs">
              Exam scheduled: <span className="text-foreground font-medium">{formatDateInZone(start, timezone)}</span> ·{' '}
              <span className="text-foreground font-medium">
                {formatTimeInZone(start, timezone)} – {formatTimeInZone(end, timezone)}
              </span>{' '}
              {timezoneShortLabel(timezone)}
            </div>
          )}

          {error && <p className="text-destructive text-sm">{error}</p>}
        </form>

        <div className="mt-auto flex gap-2 border-t px-4 py-3">
          <Button type="button" variant="outline" className="flex-1" onClick={() => handleOpenChange(false)} disabled={isSaving}>
            Cancel
          </Button>
          <Button type="submit" form="new-exam-form" className="flex-1" disabled={isSaving || noChapters}>
            {isSaving ? 'Scheduling…' : 'Schedule Exam'}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
