import { useState } from 'react';
import { format } from 'date-fns';
import { AlertTriangleIcon, ChevronDownIcon, ExternalLinkIcon, InfoIcon, PlusIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Calendar } from '@/components/ui/calendar';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import api from '@/lib/api';
import { cn, normalizeTitle } from '@/lib/utils';
import {
  DEFAULT_TIMEZONE,
  MENTOR_TIMEZONE,
  formatDateInZone,
  formatTimeInZone,
  timezoneShortLabel,
  zonedWallTimeToUtc,
} from '@/lib/timezone';

import { TimeSelect } from './time-select';
import { TimezoneSelect } from './timezone-select';

// The Hub links every booking to one shared planning folder; neither backend
// stores a per-student plan URL. Same constant as the Hub's sheet.
const PLAN_DRIVE_URL = 'https://drive.google.com/drive/folders/1xebuhtrury_sqyS-9rXCCmZ0bI7AdRJj';

const MAX_SERIES_ITEMS = 20;
const HOURS = Array.from({ length: 12 }, (_, i) => i + 1);
const MINUTES = Array.from({ length: 12 }, (_, i) => (i * 5).toString().padStart(2, '0'));
const DURATIONS = [0.5, 1, 1.5, 2];

const HOUR_OPTIONS = HOURS.map((h) => ({ value: String(h), label: String(h) }));
const MINUTE_OPTIONS = MINUTES.map((m) => ({ value: m, label: m }));
const DURATION_OPTIONS = DURATIONS.map((d) => ({ value: String(d), label: `${d}h` }));

const emptyClass = () => ({ date: undefined, hour: '', minute: '', meridiem: '', duration: 1 });

const nextDay = (d) => {
  const r = new Date(d);
  r.setDate(r.getDate() + 1);
  return r;
};

const prefilledFrom = (prev) => ({
  date: prev.date ? nextDay(prev.date) : undefined,
  hour: prev.hour,
  minute: prev.minute,
  meridiem: prev.meridiem,
  duration: prev.duration,
});

function to24Hour(hour12, meridiem) {
  if (meridiem === 'AM') return hour12 === 12 ? 0 : hour12;
  return hour12 === 12 ? 12 : hour12 + 12;
}

/**
 * The calendar day a picked `Date` represents, read from its LOCAL parts.
 * `toISOString().slice(0, 10)` would be wrong: the calendar hands back
 * midnight local, which in any zone ahead of UTC belongs to the previous day.
 */
function toLocalDateString(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** A completed row as the student's wall clock reads it. Null while incomplete. */
function wallTimeFor(c) {
  if (!c.date || c.hour === '' || c.minute === '' || c.meridiem === '') return null;
  const hour24 = to24Hour(Number(c.hour), c.meridiem);
  return { date: toLocalDateString(c.date), time: `${String(hour24).padStart(2, '0')}:${c.minute}` };
}

/**
 * The instant a row names, for previewing only; the API re-derives it from the
 * wall time and zone, and that result is what gets stored. Null when the row is
 * incomplete or the time falls in a DST gap (the submit path explains why).
 */
function startInstantFor(c, zone) {
  const wall = wallTimeFor(c);
  if (!wall) return null;
  try {
    return zonedWallTimeToUtc(wall, zone);
  } catch {
    return null;
  }
}

function formatCredits(value) {
  return Number.isInteger(value) ? value.toString() : value.toFixed(1);
}

function Switch({ checked, onCheckedChange, id, disabled }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors',
        'focus-visible:ring-ring/50 focus-visible:outline-none focus-visible:ring-[3px]',
        'disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-primary' : 'bg-input'
      )}
    >
      <span
        className={cn(
          'bg-background pointer-events-none inline-block size-4 rounded-full shadow-sm ring-0 transition-transform',
          checked ? 'translate-x-4' : 'translate-x-0'
        )}
      />
    </button>
  );
}

function ClassRowEditor({ row, index, compact, canRemove, onChange, onRemove }) {
  const [calendarOpen, setCalendarOpen] = useState(false);

  const set = (key, value) => onChange({ ...row, [key]: value });

  if (!compact) {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <span className="text-muted-foreground text-xs">Date</span>
            <Popover modal open={calendarOpen} onOpenChange={setCalendarOpen}>
              <PopoverTrigger asChild>
                <Button type="button" variant="outline" className="w-48 justify-between font-normal">
                  <span className="truncate">{row.date ? format(row.date, 'PPP') : 'Select date'}</span>
                  <ChevronDownIcon className="shrink-0" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-auto overflow-hidden p-0" align="start">
                <Calendar
                  mode="single"
                  selected={row.date}
                  captionLayout="dropdown"
                  defaultMonth={row.date}
                  onSelect={(date) => {
                    set('date', date);
                    setCalendarOpen(false);
                  }}
                />
              </PopoverContent>
            </Popover>
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-muted-foreground text-xs">Time</span>
            <div className="flex items-center gap-1.5">
              <TimeSelect
                ariaLabel="Hour"
                value={row.hour}
                onValueChange={(v) => set('hour', v)}
                options={HOUR_OPTIONS}
                placeholder="HH"
                className="w-20"
              />
              <span className="text-muted-foreground">:</span>
              <TimeSelect
                ariaLabel="Minute"
                value={row.minute}
                onValueChange={(v) => set('minute', v)}
                options={MINUTE_OPTIONS}
                placeholder="MM"
                className="w-20"
              />
              <ButtonGroup className="ml-1">
                <Button
                  type="button"
                  size="sm"
                  variant={row.meridiem === 'AM' ? 'default' : 'outline'}
                  onClick={() => set('meridiem', 'AM')}
                >
                  AM
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={row.meridiem === 'PM' ? 'default' : 'outline'}
                  onClick={() => set('meridiem', 'PM')}
                >
                  PM
                </Button>
              </ButtonGroup>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <Label>Duration</Label>
          <ButtonGroup>
            {DURATIONS.map((d) => (
              <Button
                key={d}
                type="button"
                size="sm"
                variant={row.duration === d ? 'default' : 'outline'}
                onClick={() => set('duration', d)}
              >
                {d === 1 ? '1 hour' : `${d} hours`}
              </Button>
            ))}
          </ButtonGroup>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="text-muted-foreground text-xs">Class {index + 1}</span>
      <div className="flex flex-wrap items-center gap-1.5">
        <Popover modal open={calendarOpen} onOpenChange={setCalendarOpen}>
          <PopoverTrigger asChild>
            <Button type="button" variant="outline" size="sm" className="h-9 w-[88px] justify-between px-2 font-normal">
              <span className="truncate">{row.date ? format(row.date, 'd MMM') : 'Date'}</span>
              <ChevronDownIcon className="size-3.5 shrink-0" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto overflow-hidden p-0" align="start">
            <Calendar
              mode="single"
              selected={row.date}
              captionLayout="dropdown"
              defaultMonth={row.date}
              onSelect={(date) => {
                set('date', date);
                setCalendarOpen(false);
              }}
            />
          </PopoverContent>
        </Popover>

        <TimeSelect
          ariaLabel="Hour"
          value={row.hour}
          onValueChange={(v) => set('hour', v)}
          options={HOUR_OPTIONS}
          placeholder="HH"
          className="w-16 px-2"
        />
        <TimeSelect
          ariaLabel="Minute"
          value={row.minute}
          onValueChange={(v) => set('minute', v)}
          options={MINUTE_OPTIONS}
          placeholder="MM"
          className="w-16 px-2"
        />
        <ButtonGroup>
          <Button
            type="button"
            size="sm"
            variant={row.meridiem === 'AM' ? 'default' : 'outline'}
            onClick={() => set('meridiem', 'AM')}
            className="px-2"
          >
            AM
          </Button>
          <Button
            type="button"
            size="sm"
            variant={row.meridiem === 'PM' ? 'default' : 'outline'}
            onClick={() => set('meridiem', 'PM')}
            className="px-2"
          >
            PM
          </Button>
        </ButtonGroup>
        <TimeSelect
          ariaLabel="Duration (hours)"
          value={String(row.duration)}
          onValueChange={(v) => set('duration', Number(v))}
          options={DURATION_OPTIONS}
          placeholder="Dur"
          className="w-[72px] px-2"
        />
        {canRemove && (
          <Button type="button" variant="ghost" size="icon-sm" onClick={onRemove} aria-label={`Remove class ${index + 1}`}>
            <XIcon className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}

/**
 * Right-side "New Session" drawer, ported from the Hub's NewSessionSheet.
 *
 * `student` is the row from GET /api/students/ the page is filtered on (id,
 * total_class_quota, tutor_profile, timezone); `creditsUsed` is the hours of
 * their non-cancelled sessions. The API enforces every rule again -- quota,
 * conflicts, tutor, zone -- this sheet only mirrors them for fast feedback.
 */
export function NewSessionSheet({ student, creditsUsed = 0, open, onOpenChange, onCreated }) {
  const studentId = student?.id ?? '';
  const classQuota = student?.total_class_quota ?? 0;
  const hasTutor = Boolean(student?.tutor_profile);
  // Raw column: null when unset, which the sheet surfaces.
  const studentTimezone = student?.timezone || null;
  // Times are entered in the student's zone. Falls back to IST when the
  // student has none set, which matches how sessions were scheduled before.
  const initialTimezone = studentTimezone ?? DEFAULT_TIMEZONE;

  const [title, setTitle] = useState('');
  const [isSeries, setIsSeries] = useState(false);
  const [classes, setClasses] = useState([emptyClass()]);
  const [timezone, setTimezone] = useState(initialTimezone);

  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');

  // The page mounts one sheet and the filtered student can change while it is
  // closed, so the form re-syncs from the student each time it opens.
  // Adjusting state during render, guarded by the previous open value, is
  // React's recommended alternative to a synchronising effect.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setTitle('');
      setIsSeries(false);
      setClasses([emptyClass()]);
      setTimezone(initialTimezone);
      setError('');
    }
  }

  // Saving writes the zone back to the student, but only when the mentor
  // actually picks a different one. Compared against the RESOLVED initial
  // value, not the raw column: a student with no timezone opens on the IST
  // default, and treating that as a change would PUT on every booking.
  const timezoneChanged = timezone !== initialTimezone;

  const effective = isSeries ? classes : classes.slice(0, 1);
  const seriesCreditsTotal = effective.reduce((sum, c) => sum + c.duration, 0);
  const creditsRemaining = Math.max(0, classQuota - creditsUsed);
  const overBudget = seriesCreditsTotal > classQuota - creditsUsed + 1e-9;

  const normalizedTitle = normalizeTitle(title);
  const reachedCap = classes.length >= MAX_SERIES_ITEMS;

  const resetForm = () => {
    setTitle('');
    setIsSeries(false);
    setClasses([emptyClass()]);
    setTimezone(initialTimezone);
    setError('');
  };

  const handleOpenChange = (value) => {
    if (isSaving) return;
    if (!value) resetForm();
    onOpenChange(value);
  };

  const updateRow = (index, next) => {
    setClasses((prev) => prev.map((c, i) => (i === index ? next : c)));
  };

  const removeRow = (index) => {
    setClasses((prev) => prev.filter((_, i) => i !== index));
  };

  const addRow = () => {
    if (reachedCap) return;
    setClasses((prev) => [...prev, prefilledFrom(prev[prev.length - 1])]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!studentId) {
      setError('Missing student scope.');
      return;
    }
    if (!hasTutor) {
      setError('This student has no tutor assigned. Assign a tutor before creating a session.');
      return;
    }
    if (!normalizedTitle) {
      setError('Please enter a session title.');
      return;
    }

    // Wall clock + zone go to the API, which converts to UTC. The mentor's
    // browser zone is not involved in the stored value at any point.
    const items = [];
    for (let i = 0; i < effective.length; i++) {
      const row = effective[i];
      const label = isSeries ? `Class ${i + 1}` : 'this session';
      const wall = wallTimeFor(row);
      if (!wall) {
        setError(`Please complete date, hour, minute, and AM/PM for ${label}.`);
        return;
      }
      // Catches DST gaps before a round trip; the API re-checks anyway.
      try {
        zonedWallTimeToUtc(wall, timezone);
      } catch (err) {
        setError(err instanceof Error ? `${label}: ${err.message}` : `${label}: invalid date and time.`);
        return;
      }
      items.push({ local_date: wall.date, local_time: wall.time, duration_hours: row.duration });
    }

    if (overBudget) {
      setError(`Selected ${isSeries ? 'series' : 'duration'} exceeds the remaining quota balance.`);
      return;
    }

    setIsSaving(true);
    try {
      // Persist the zone first. Anything rendering from the student's zone
      // would otherwise show a session created in a zone the student does not
      // carry at the wrong hour. Fail closed rather than saving one.
      if (timezoneChanged) {
        try {
          await api.put('/api/students/', { id: studentId, timezone });
        } catch (err) {
          setError(
            err.response?.data?.message || err.response?.data?.error || "Failed to update the student's timezone."
          );
          return;
        }
      }

      try {
        await api.post('/api/sessions/', {
          student_id: studentId,
          base_title: title,
          series: isSeries,
          timezone,
          items,
        });
      } catch (err) {
        setError(
          err.response
            ? err.response.data?.error || err.response.data?.message || 'Failed to create session(s).'
            : 'Network error. Please try again.'
        );
        return;
      }

      onCreated?.();
      resetForm();
      onOpenChange(false);
    } finally {
      setIsSaving(false);
    }
  };

  // For a series this is the first class -- the reference under the quota
  // line shows that one, since a row per class would bury the quota it sits
  // next to.
  const singleRow = effective[0];
  const singleStart = singleRow ? startInstantFor(singleRow, timezone) : null;
  const singleEnd = singleStart ? new Date(singleStart.getTime() + singleRow.duration * 60 * 60 * 1000) : null;

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent side="right" className="flex flex-col sm:max-w-md">
        <SheetHeader>
          <SheetTitle>New Session</SheetTitle>
          <SheetDescription>Schedule a new 1-to-1 session for this student.</SheetDescription>
          <a
            href={PLAN_DRIVE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-muted/40 hover:bg-muted text-foreground mt-2 flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors"
          >
            <InfoIcon className="text-muted-foreground size-4 shrink-0" />
            <span>View plan details in Drive</span>
            <ExternalLinkIcon className="text-muted-foreground ml-auto size-3.5 shrink-0" />
          </a>
        </SheetHeader>

        <form id="new-session-form" onSubmit={handleSubmit} className="flex flex-1 flex-col gap-6 overflow-y-auto px-4 py-2">
          {!hasTutor && (
            <div className="border-destructive/40 bg-destructive/5 text-destructive flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
              <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
              <span>This student has no tutor assigned. Assign a tutor before scheduling a session.</span>
            </div>
          )}

          <div className="flex flex-col gap-2">
            <Label htmlFor="session-title">Session Title</Label>
            <Input
              id="session-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Real Numbers"
            />
            {normalizedTitle && (
              <p className="text-muted-foreground text-xs">
                Saved as:{' '}
                <span className="text-foreground font-medium">
                  {normalizedTitle}
                  {isSeries ? ' - Class N' : ''}
                </span>
              </p>
            )}
          </div>

          <Separator />

          <label htmlFor="series-toggle" className="flex cursor-pointer items-center justify-between gap-3">
            <div className="flex flex-col">
              <span className="text-sm font-medium">Schedule as a series</span>
              <span className="text-muted-foreground text-xs">Book multiple recurring classes at once.</span>
            </div>
            <Switch id="series-toggle" checked={isSeries} onCheckedChange={setIsSeries} disabled={isSaving} />
          </label>

          <div className="flex flex-col gap-3">
            {/* One zone governs every class in a series: it belongs to the
                student, not to an individual booking. */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label>Date &amp; Time</Label>
              <TimezoneSelect value={timezone} onValueChange={setTimezone} disabled={isSaving} className="w-56" />
            </div>
            <p className="text-muted-foreground -mt-1 text-xs">
              {!studentTimezone
                ? 'This student has no timezone set. Enter times in the timezone you pick — saving will store it on the student.'
                : timezoneChanged
                  ? "Enter the student's local time. Saving will update the student's timezone to this."
                  : "Enter the student's local time. Changing this updates the student's timezone."}
            </p>
            {!isSeries ? (
              <ClassRowEditor
                row={classes[0]}
                index={0}
                compact={false}
                canRemove={false}
                onChange={(next) => updateRow(0, next)}
                onRemove={() => {}}
              />
            ) : (
              <div className="flex flex-col gap-3">
                {classes.map((c, i) => (
                  <ClassRowEditor
                    key={i}
                    row={c}
                    index={i}
                    compact
                    canRemove={classes.length > 1}
                    onChange={(next) => updateRow(i, next)}
                    onRemove={() => removeRow(i)}
                  />
                ))}
                <Button type="button" variant="outline" onClick={addRow} disabled={reachedCap} className="w-full border-dashed">
                  <PlusIcon className="size-4" />
                  {reachedCap ? `Series cap reached (${MAX_SERIES_ITEMS})` : `Add Class ${classes.length + 1}`}
                </Button>
              </div>
            )}
          </div>

          {!isSeries && singleStart && singleEnd && (
            <div className="bg-muted/40 text-muted-foreground rounded-md border px-3 py-2 text-xs">
              Session scheduled: <span className="text-foreground font-medium">{formatDateInZone(singleStart, timezone)}</span>{' '}
              ·{' '}
              <span className="text-foreground font-medium">
                {formatTimeInZone(singleStart, timezone)} – {formatTimeInZone(singleEnd, timezone)}
              </span>{' '}
              {timezoneShortLabel(timezone)}
            </div>
          )}

          {isSeries && (
            <div className="bg-muted/40 text-muted-foreground rounded-md border px-3 py-2 text-xs">
              Series total:{' '}
              <span className="text-foreground font-medium">
                {classes.length} {classes.length === 1 ? 'class' : 'classes'}
              </span>{' '}
              ·{' '}
              <span className={cn('font-medium', overBudget ? 'text-destructive' : 'text-foreground')}>
                {formatCredits(seriesCreditsTotal)} credits
              </span>
            </div>
          )}

          {error && <p className="text-destructive text-sm">{error}</p>}
        </form>

        <div className="mt-auto px-4 pb-3">
          <p
            className={cn(
              'text-center text-xs',
              overBudget || creditsRemaining <= 0 ? 'text-destructive font-medium' : 'text-muted-foreground'
            )}
          >
            Quota balance: {formatCredits(creditsRemaining)} / {classQuota} credits left
          </p>

          {/* Reference only, never an input: confirms what the mentor typed
              against their own clock, so a Gulf 5 PM class is visibly a
              6:30 PM IST commitment before it is booked. */}
          {singleStart && (
            <div className="text-muted-foreground mt-2 space-y-0.5 text-center text-xs">
              <p>
                Student time:{' '}
                <span className="text-foreground font-medium">
                  {formatTimeInZone(singleStart, timezone)} {timezoneShortLabel(timezone)}
                </span>
                {isSeries && effective.length > 1 && <span> · first of {effective.length}</span>}
              </p>
              <p>
                Mentor time:{' '}
                <span className="text-foreground font-medium">
                  {formatTimeInZone(singleStart, MENTOR_TIMEZONE)} {timezoneShortLabel(MENTOR_TIMEZONE)}
                </span>
              </p>
            </div>
          )}
        </div>

        <SheetFooter className="border-t p-4 sm:p-4">
          <Button type="button" variant="outline" onClick={() => handleOpenChange(false)} disabled={isSaving}>
            Cancel
          </Button>
          <Button type="submit" form="new-session-form" disabled={isSaving || overBudget || !hasTutor || !studentId}>
            {isSaving
              ? 'Creating…'
              : isSeries
                ? `Create ${classes.length} ${classes.length === 1 ? 'Class' : 'Classes'}`
                : 'Create Session'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
