import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon, LockIcon, RefreshCwIcon, ShieldAlertIcon } from 'lucide-react';

import api from '@/lib/api';
import { apiErrorMessage } from '@/lib/api-errors';
import { formatDateInZone, formatShortDateInZone, formatTimeInZone, utcToZonedWallTime } from '@/lib/timezone';
import { FormDialog } from '@/components/form-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

// Slot times and dates are Indian time, whatever zone this device is in
// (backend bookings.scheduling).
const ZONE = 'Asia/Kolkata';
const TYPES = [
  { value: 'demo', label: 'Demo class' },
  { value: 'diagnostic', label: 'Diagnostic test' },
];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
// The four statuses of the parents' booking pages and the Google Sheets
// calendar, from free to full, in that calendar's colours.
const STATUSES = [
  {
    label: 'Available',
    badge: 'bg-green-500/15 text-green-800 dark:bg-green-500/15 dark:text-green-400',
    dot: 'bg-green-500',
  },
  {
    label: 'Filling Fast',
    badge: 'bg-yellow-400/25 text-yellow-800 dark:bg-yellow-400/15 dark:text-yellow-300',
    dot: 'bg-yellow-400',
  },
  {
    label: 'Only a Few Left',
    badge: 'bg-orange-500/15 text-orange-800 dark:bg-orange-500/20 dark:text-orange-300',
    dot: 'bg-orange-500',
  },
  {
    label: 'Fully Booked',
    badge: 'bg-red-900/15 text-red-900 dark:bg-red-900/40 dark:text-red-200',
    dot: 'bg-red-900 dark:bg-red-400',
  },
];
const STATUS_STYLE = Object.fromEntries(STATUSES.map((status) => [status.label, status]));
// The one status an administrator sets by hand: it stops new bookings (the
// API's close; parents see a closed slot as Fully Booked). Every other status
// follows the slot's bookings.
const FULLY_BOOKED = 'Fully Booked';

const pad = (value) => String(value).padStart(2, '0');

/** Today's date in India, as YYYY-MM-DD. */
function indianToday() {
  return utcToZonedWallTime(new Date(), ZONE).date;
}

/** YYYY-MM-DD `days` calendar days on. */
function addDays(iso, days) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

/** `Thu, 29 Oct 2026` for a YYYY-MM-DD date. */
function dateLabel(iso) {
  return formatDateInZone(new Date(`${iso}T12:00:00Z`), 'UTC');
}

// The calendar picks dates in the browser's local time; the page keeps YYYY-MM-DD.
function toPickerDate(iso) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function fromPickerDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** `19:30` as `7:30 PM`. */
function clock(hhmm) {
  const [hours, minutes] = hhmm.split(':').map(Number);
  return `${hours % 12 || 12}:${pad(minutes)} ${hours < 12 ? 'AM' : 'PM'}`;
}

const slotLabel = (slot) => `${clock(slot.time)} – ${clock(slot.end_time)}`;
const plural = (count, noun) => `${count} ${noun}${count === 1 ? '' : 's'}`;

function parentNote(day) {
  switch (day.parent_state) {
    case 'open':
      return 'Open to parents: the booking pages offer this date now.';
    case 'upcoming':
      return `Not open to parents yet: the booking pages offer ${dateLabel(day.window.first)} to ${dateLabel(day.window.last)}. Changes made now apply when this date opens.`;
    case 'today':
      return 'Today: the booking pages no longer offer this date.';
    default:
      return 'This date has passed: its slots are shown as they ended and cannot be changed.';
  }
}

function statusNotice(slot, action, day) {
  const label = slotLabel(slot);
  if (!day.changed?.length) return `${label} was already ${action === 'close' ? 'closed to new bookings' : 'following its bookings'}.`;
  if (action === 'close') return `${label} is now Fully Booked: it takes no new bookings.`;
  const now = day.slots.find((entry) => entry.time === slot.time);
  return `${label} follows its bookings again: ${now?.status ?? slot.open_status}.`;
}

function loadError(err) {
  const response = err?.response;
  return {
    status: response?.status ?? null,
    message: response
      ? apiErrorMessage(err, 'Could not load the slots.')
      : 'Could not reach the server. Check your connection and try again.',
  };
}

/** The status parents see, in its colour; a lock marks one an administrator set. */
function StatusBadge({ slot }) {
  return (
    <Badge className={cn('border-transparent', STATUS_STYLE[slot.status]?.badge)}>
      {slot.closed ? <LockIcon /> : null}
      {slot.status}
      {slot.closed ? <span className="sr-only"> (set by an administrator)</span> : null}
    </Badge>
  );
}

function Closure({ slot }) {
  if (!slot.closed) return <span aria-hidden="true">—</span>;
  const at = slot.closed_at ? new Date(slot.closed_at) : null;
  const when = at ? `${formatShortDateInZone(at, ZONE)}, ${formatTimeInZone(at, ZONE)} IST` : null;
  return (
    <div className="flex flex-col gap-0.5">
      <span>{[slot.closed_by ? `Set by ${slot.closed_by}` : 'Set by the schedule command', when].filter(Boolean).join(' · ')}</span>
      {slot.close_reason ? <span className="text-foreground">“{slot.close_reason}”</span> : null}
      <span>
        {slot.open_status === FULLY_BOOKED ? 'Its bookings fill it as well.' : `From its bookings: ${slot.open_status}.`}
      </span>
    </div>
  );
}

/**
 * A slot's status, chosen from the four the booking pages use. Two of them
 * can be picked: Fully Booked, which stops new bookings, and the status the
 * slot's bookings give it, which lifts that. The others would misstate the
 * booking count -- a full slot can never be made Available -- so they are
 * shown but cannot be picked.
 */
function StatusSelect({ slot, disabled, onChoose }) {
  const choosable = new Set([FULLY_BOOKED, slot.open_status]);
  return (
    <Select value={slot.status} onValueChange={(value) => onChoose(slot, value)} disabled={disabled}>
      <SelectTrigger size="sm" aria-label={`Status of ${slotLabel(slot)}`} className="w-44">
        <SelectValue />
      </SelectTrigger>
      <SelectContent position="popper" align="end">
        {STATUSES.map((status) => (
          <SelectItem key={status.label} value={status.label} disabled={!choosable.has(status.label)}>
            <span aria-hidden="true" className={cn('size-2 shrink-0 rounded-full', status.dot)} />
            {status.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function SlotsSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      <Skeleton className="h-4 w-64 max-w-full" />
      {[0, 1, 2, 3, 4, 5].map((key) => (
        <Skeleton key={key} className="h-10 w-full" />
      ))}
    </div>
  );
}

function NoAccess() {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
      <ShieldAlertIcon className="text-muted-foreground size-8" />
      <p className="font-medium">You don&apos;t have access to booking slots.</p>
      <p className="text-muted-foreground max-w-md text-sm">Ask an administrator if you need to manage them.</p>
    </div>
  );
}

/**
 * Confirms one slot's new status before anything is saved: the slot, its
 * current status and the one it would get. Setting it to Fully Booked takes
 * an optional reason, kept with the slot.
 */
function StatusChangeDialog({ change, typeLabel, date, onConfirm, onOpenChange }) {
  const open = Boolean(change);
  // The last change stays on screen while the dialog closes.
  const [shown, setShown] = useState(change);
  if (change && change !== shown) setShown(change);
  const [reason, setReason] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setReason('');
      setError('');
    }
  }

  const current = change ?? shown;
  if (!current) return null;
  const { slot, action } = current;
  const closing = action === 'close';
  const free = Math.max(slot.capacity - slot.booked, 0);
  let effect;
  if (closing) {
    const kept = slot.booked ? ` Its ${plural(slot.booked, 'booking')} ${slot.booked === 1 ? 'is' : 'are'} kept.` : '';
    effect = `Parents can't book it: it shows as Fully Booked until you set it back to the status its bookings give it.${kept}`;
  } else {
    effect = free
      ? `Its status follows its bookings again: parents can book its ${plural(free, 'remaining seat')}.`
      : 'Its status follows its bookings again; all its seats are booked, so it stays Fully Booked.';
  }

  const handleConfirm = async () => {
    setPending(true);
    setError('');
    const failure = await onConfirm(current, reason.trim());
    setPending(false);
    if (failure) setError(failure);
    else onOpenChange(false);
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={(value) => !pending && onOpenChange(value)}
      title="Change this slot's status?"
      description={`${typeLabel} · ${dateLabel(date)}`}
      error={error}
      onConfirm={handleConfirm}
      confirmLabel="Confirm"
      pendingLabel="Saving…"
      confirmVariant={closing ? 'destructive' : 'default'}
      cancelLabel="Cancel"
      pending={pending}
    >
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Time slot</dt>
        <dd className="font-medium">{slotLabel(slot)} IST</dd>
        <dt className="text-muted-foreground">Current status</dt>
        <dd>
          <StatusBadge slot={slot} />
        </dd>
        <dt className="text-muted-foreground">New status</dt>
        <dd>
          <StatusBadge slot={{ ...slot, closed: closing, status: closing ? FULLY_BOOKED : slot.open_status }} />
        </dd>
      </dl>
      <p className="text-muted-foreground text-sm">{effect}</p>
      {closing ? (
        <div className="flex flex-col gap-2">
          <Label htmlFor="slot-close-reason">Reason (optional)</Label>
          <textarea
            id="slot-close-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            maxLength={500}
            placeholder="e.g. Teacher training"
            className="border-input bg-transparent placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 w-full rounded-md border px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-[3px]"
            disabled={pending}
          />
        </div>
      ) : null}
    </FormDialog>
  );
}

/**
 * Booking slot management for administrators: one date's Demo class or
 * Diagnostic test slots -- each one-hour slot with its bookings and the
 * status parents see -- and each slot's status, set from a dropdown and
 * confirmed before it is saved. The API (Django) is the only judge:
 * Available, Filling Fast, Only a Few Left and Fully Booked follow the
 * bookings; an administrator can only set a slot to Fully Booked (closing
 * it: it keeps its bookings and takes no new one) or put it back on the
 * status its bookings give it. The booking type and date live in the URL
 * (?type=demo&date=2026-10-29), so a view can be linked.
 */
export default function BookingSlotsPage() {
  const [params, setParams] = useSearchParams();
  const type = TYPES.some((entry) => entry.value === params.get('type')) ? params.get('type') : 'demo';
  const requested = params.get('date');
  const date = requested && ISO_DATE.test(requested) ? requested : addDays(indianToday(), 1);
  const typeLabel = TYPES.find((entry) => entry.value === type).label;
  // Everything below belongs to one booking type and date: what was loaded
  // or reported for another is ignored once the view changes.
  const view = `${type}/${date}`;

  const [day, setDay] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [result, setResult] = useState({ view, notice: '', error: '' });
  const [pendingChange, setPendingChange] = useState(null);
  const [saving, setSaving] = useState(false);
  const [calendarOpen, setCalendarOpen] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .get(`/api/booking-slots/${type}/${date}/`)
      .then((response) => {
        if (!active) return;
        setDay({ view, ...response.data });
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure({ view, ...loadError(err) });
      });
    return () => {
      active = false;
    };
  }, [type, date, view, reloadKey]);

  const current = day?.view === view ? day : null;
  const failed = failure?.view === view ? failure : null;
  const { notice, error } = result.view === view ? result : { notice: '', error: '' };

  const choose = (next) => {
    setParams(
      (previous) => {
        const merged = new URLSearchParams(previous);
        for (const [name, value] of Object.entries(next)) merged.set(name, value);
        return merged;
      },
      { replace: true }
    );
  };
  const reload = () => setReloadKey((key) => key + 1);

  // Picking a status only asks: the dropdown keeps showing the saved one
  // until the change is confirmed and the API answers. Fully Booked closes an
  // open slot; the status its bookings give it reopens a closed one.
  const chooseStatus = (slot, value) => {
    if (value === slot.status) return;
    if (value === FULLY_BOOKED && !slot.closed) setPendingChange({ slot, action: 'close' });
    else if (slot.closed && value === slot.open_status) setPendingChange({ slot, action: 'reopen' });
  };

  const saveStatus = async ({ slot, action }, reason) => {
    setSaving(true);
    try {
      const response = await api.post(`/api/booking-slots/${type}/${date}/`, { action, times: [slot.time], reason });
      setDay({ view, ...response.data });
      setResult({ view, notice: statusNotice(slot, action, response.data), error: '' });
      return null;
    } catch (err) {
      const message = apiErrorMessage(err, 'Could not save the new status. Please try again.');
      setResult({ view, notice: '', error: message });
      // Whatever went wrong, show the slots as the backend has them now.
      reload();
      return message;
    } finally {
      setSaving(false);
    }
  };

  const slots = current?.slots ?? [];
  const editable = Boolean(current?.editable);

  let content;
  if (failed?.status === 403) {
    content = <NoAccess />;
  } else if (failed) {
    content = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failed.message}</p>
        <Button variant="outline" size="sm" onClick={reload}>
          Try again
        </Button>
      </div>
    );
  } else if (!current) {
    content = <SlotsSkeleton />;
  } else {
    const booked = slots.reduce((sum, slot) => sum + slot.booked, 0);
    const closed = slots.filter((slot) => slot.closed).length;
    content = (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1 text-sm">
          <p>{parentNote(current)}</p>
          <p className="text-muted-foreground">
            {plural(slots.length, 'slot')} · {booked} booked · {closed} closed by an administrator · up to {current.capacity}{' '}
            bookings a slot
          </p>
        </div>

        {notice ? (
          <p role="status" className="text-sm">
            {notice}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        ) : null}

        {slots.length === 0 ? (
          <p className="text-muted-foreground rounded-md border px-6 py-12 text-center text-sm">
            No {typeLabel.toLowerCase()} times are scheduled.
          </p>
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time (IST)</TableHead>
                  <TableHead>Bookings</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Details</TableHead>
                  {editable ? <TableHead>Set status</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {slots.map((slot) => (
                  <TableRow key={slot.time}>
                    <TableCell className="font-medium whitespace-nowrap">
                      {slotLabel(slot)}
                      {slot.scheduled ? null : (
                        <span className="text-muted-foreground block text-xs font-normal">No longer offered</span>
                      )}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {slot.booked} / {slot.capacity}
                    </TableCell>
                    <TableCell>
                      <StatusBadge slot={slot} />
                    </TableCell>
                    <TableCell className="text-muted-foreground min-w-48 text-xs">
                      <Closure slot={slot} />
                    </TableCell>
                    {editable ? (
                      <TableCell>
                        {/* A time no longer offered can only be put back (the API closes offered times only). */}
                        {slot.scheduled || slot.closed ? (
                          <StatusSelect slot={slot} disabled={saving} onChoose={chooseStatus} />
                        ) : null}
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold">Booking slots</h1>
        <p className="text-muted-foreground text-sm">
          The one-hour slots parents book for a demo class or a diagnostic test. Each slot&apos;s status follows its
          bookings: Available, Filling Fast, Only a Few Left or Fully Booked. To stop new bookings, set a slot to Fully
          Booked; it keeps the bookings it holds (marked with a lock) until you set it back to the status its bookings
          give it. Times are Indian time (IST).
        </p>
      </div>

      <div className="mb-4 flex flex-col gap-3">
        <Tabs value={type} onValueChange={(value) => choose({ type: value })}>
          <TabsList>
            {TYPES.map((entry) => (
              <TabsTrigger key={entry.value} value={entry.value}>
                {entry.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="icon" aria-label="Previous day" onClick={() => choose({ date: addDays(date, -1) })}>
            <ChevronLeftIcon />
          </Button>
          <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" className="w-52 justify-between font-normal">
                <span className="truncate">{dateLabel(date)}</span>
                <ChevronDownIcon className="shrink-0" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto overflow-hidden p-0" align="start">
              <Calendar
                mode="single"
                selected={toPickerDate(date)}
                defaultMonth={toPickerDate(date)}
                captionLayout="dropdown"
                onSelect={(picked) => {
                  if (!picked) return;
                  choose({ date: fromPickerDate(picked) });
                  setCalendarOpen(false);
                }}
              />
            </PopoverContent>
          </Popover>
          <Button variant="outline" size="icon" aria-label="Next day" onClick={() => choose({ date: addDays(date, 1) })}>
            <ChevronRightIcon />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => choose({ date: addDays(indianToday(), 1) })}>
            Tomorrow
          </Button>
          <Button variant="ghost" size="sm" onClick={reload} disabled={saving}>
            <RefreshCwIcon />
            Refresh
          </Button>
        </div>
      </div>

      {content}

      <StatusChangeDialog
        change={pendingChange}
        typeLabel={typeLabel}
        date={date}
        onConfirm={saveStatus}
        onOpenChange={(open) => {
          if (!open) setPendingChange(null);
        }}
      />
    </div>
  );
}
