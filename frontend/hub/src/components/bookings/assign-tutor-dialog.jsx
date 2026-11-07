import { useEffect, useId, useState } from 'react';
import { Loader2Icon, SearchIcon, SearchXIcon, XIcon } from 'lucide-react';

import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { ErrorState } from '@/components/page/states';
import { useIsMobile } from '@/hooks/use-mobile';
import { bookingError, bookingTutorUrl, bookingTutorsUrl } from '@/lib/bookings';
import { slotLabel } from '@/lib/enquiries';
import { cn } from '@/lib/utils';
import { AvailabilityBadge } from './booking-badges';

function TutorSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      {[0, 1, 2].map((key) => (
        <Skeleton key={key} className="h-14" />
      ))}
    </div>
  );
}

/** Whose booking it is and when, under the title: the student, the booking's type and its slot (IST). */
function BookingLine({ booking }) {
  if (!booking) return null;
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-foreground font-medium">{booking.student_name}</span>
      <span aria-hidden="true">·</span>
      <BookingTypeBadge type={booking.booking_type} />
      <span aria-hidden="true">·</span>
      <span>{slotLabel(booking.slot)}</span>
    </span>
  );
}

/**
 * One tutor to pick, as a compact row: a radio, their name and email, the
 * Current badge for the tutor teaching the booking now, Available or
 * Unavailable and, where the API gives one, why. An unavailable tutor -- and
 * the current one, whom choosing again would change nothing -- stays listed
 * but cannot be picked.
 */
function TutorOption({ tutor, name, checked, onSelect }) {
  const disabled = tutor.status !== 'AVAILABLE' || tutor.current;
  return (
    <label
      aria-disabled={disabled || undefined}
      className={cn(
        'flex items-start gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors',
        'has-[input:focus-visible]:ring-ring/50 has-[input:focus-visible]:ring-[3px]',
        disabled ? 'bg-muted/40 cursor-not-allowed' : 'hover:bg-muted/40 cursor-pointer',
        checked && 'border-primary bg-primary/5 hover:bg-primary/5'
      )}
    >
      <input
        type="radio"
        name={name}
        value={tutor.id}
        checked={checked}
        onChange={() => onSelect(tutor.id)}
        disabled={disabled}
        className="accent-primary mt-0.5 size-4 shrink-0"
      />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-medium">{tutor.full_name}</span>
          {tutor.current ? <Badge variant="info">Current</Badge> : null}
        </span>
        <span className="text-muted-foreground block truncate text-xs">{tutor.email}</span>
        {tutor.reason?.message ? <span className="text-muted-foreground mt-1 block text-xs">{tutor.reason.message}</span> : null}
      </span>
      <AvailabilityBadge status={tutor.status} />
    </label>
  );
}

/** A heading and its tutors -- Available tutors, or Unavailable tutors -- or what to say when there are none. */
function TutorGroup({ title, tutors, empty, name, selected, onSelect }) {
  const headingId = useId();
  if (!tutors.length && !empty) return null;
  return (
    <div role="group" aria-labelledby={headingId} className="flex flex-col gap-1.5">
      <p id={headingId} className="text-muted-foreground text-xs font-medium">
        {title} <span className="tabular-nums">({tutors.length})</span>
      </p>
      {tutors.length ? (
        tutors.map((tutor) => (
          <TutorOption key={tutor.id} tutor={tutor} name={name} checked={selected === tutor.id} onSelect={onSelect} />
        ))
      ) : (
        <p className="text-muted-foreground rounded-lg border border-dashed px-3 py-2.5 text-sm">{empty}</p>
      )}
    </div>
  );
}

/**
 * Choosing who teaches a booking. Every active tutor for its slot comes from
 * the API (GET /api/bookings/<type>/<id>/tutors/), Available or Unavailable
 * with the reason it gives -- a class or another booking at that time, never
 * another child's name -- and the current tutor marked: searched by name or
 * email here, in this list (nothing new is asked of the API), and shown in two
 * groups, the available tutors first. Only an available tutor can be picked,
 * one at a time; the API checks again when assigning
 * (PUT /api/bookings/<type>/<id>/tutor/) and a refusal is shown as it comes,
 * with the list read again. Nothing closes the dialog while the assignment is
 * on its way; it closes once the API has taken it. A dialog, or on a phone
 * the Hub's bottom sheet (as the student invitation's).
 */
export function AssignTutorDialog({ booking, open, onOpenChange, onAssigned }) {
  const isMobile = useIsMobile();
  const radioName = useId();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState('');
  const [query, setQuery] = useState('');
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const bookingId = booking?.id;
  const bookingType = booking?.booking_type;

  // A fresh dialog on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setData(null);
      setFailure(null);
      setError(null);
      setSelected('');
      setQuery('');
    }
  }

  useEffect(() => {
    if (!open || !bookingId || !bookingType) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(bookingTutorsUrl(bookingType, bookingId))
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load the tutors.'));
      });
    return () => {
      active = false;
    };
  }, [open, bookingType, bookingId, reloadKey]);

  const tutors = data?.tutors ?? [];
  const current = tutors.find((tutor) => tutor.current);
  const choice = tutors.find((tutor) => tutor.id === selected);
  const changeable = Boolean(data?.tutor_changeable);
  const canSubmit = Boolean(changeable && choice && choice.status === 'AVAILABLE' && !choice.current);
  // Changing a tutor, or giving the booking its first: what it holds says so before the list arrives.
  const changing = Boolean(booking?.tutor || current);
  const title = changing ? 'Change Tutor' : 'Assign Tutor';

  const search = query.trim().toLowerCase();
  const matches = (tutor) =>
    !search ||
    (tutor.full_name ?? '').toLowerCase().includes(search) ||
    (tutor.email ?? '').toLowerCase().includes(search);
  const available = tutors.filter((tutor) => tutor.status === 'AVAILABLE' && matches(tutor));
  const unavailable = tutors.filter((tutor) => tutor.status !== 'AVAILABLE' && matches(tutor));

  // Nothing closes the dialog while the assignment is on its way.
  const close = (next) => {
    if (!pending) onOpenChange(next);
  };

  async function assign() {
    if (!canSubmit) return;
    setPending(true);
    setError(null);
    try {
      const response = await api.put(bookingTutorUrl(bookingType, bookingId), { tutor_id: selected });
      onAssigned?.(response.data);
      onOpenChange(false);
    } catch (err) {
      const refusal = bookingError(err, 'Could not assign the tutor.');
      setError(refusal.conflict?.message ? `${refusal.message} ${refusal.conflict.message}` : refusal.message);
      // What was free a moment ago may not be any more: show the list as it is now.
      setSelected('');
      setReloadKey((key) => key + 1);
    } finally {
      setPending(false);
    }
  }

  let list;
  if (failure) {
    list = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  } else if (!data) {
    list = <TutorSkeleton />;
  } else if (!changeable) {
    list = <p className="text-muted-foreground text-sm">{data.tutor_change_refusal?.message}</p>;
  } else if (tutors.length === 0) {
    list = <p className="text-muted-foreground text-sm">There are no active tutors to choose from.</p>;
  } else if (!available.length && !unavailable.length) {
    list = (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center">
        <SearchXIcon className="text-muted-foreground size-5" aria-hidden="true" />
        <p className="text-sm">No tutors match “{query.trim()}”.</p>
        <Button variant="ghost" size="sm" onClick={() => setQuery('')}>
          Clear search
        </Button>
      </div>
    );
  } else {
    list = (
      <fieldset className="flex min-w-0 flex-col gap-4" disabled={pending}>
        <legend className="sr-only">Tutors</legend>
        <TutorGroup
          title="Available tutors"
          tutors={available}
          empty={search ? 'No available tutor matches your search.' : 'No tutor is free for this slot.'}
          name={radioName}
          selected={selected}
          onSelect={setSelected}
        />
        <TutorGroup title="Unavailable tutors" tutors={unavailable} name={radioName} selected={selected} onSelect={setSelected} />
      </fieldset>
    );
  }

  // The search, once there are tutors to search, above a list that scrolls on its own.
  const picker = (
    <>
      {data && changeable && tutors.length ? (
        <div className="relative shrink-0">
          <SearchIcon
            className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search tutor by name or email…"
            aria-label="Search tutors"
            className="pl-8"
            disabled={pending}
          />
        </div>
      ) : null}
      {/* Room for the rows' focus ring inside the scrolling area. */}
      <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1 py-0.5">{list}</div>
      {error ? (
        <p role="alert" className="text-destructive shrink-0 text-sm">
          {error}
        </p>
      ) : null}
    </>
  );

  // Who is picked, beside the buttons -- also when the search has hidden them.
  const selection = (className) =>
    choice ? (
      <p className={cn('text-muted-foreground min-w-0 truncate text-sm', className)}>
        Selected: <span className="text-foreground font-medium">{choice.full_name}</span>
      </p>
    ) : null;
  const cancel = (
    <Button type="button" variant="outline" onClick={() => close(false)} disabled={pending}>
      Cancel
    </Button>
  );
  const confirm = (
    <Button type="button" onClick={assign} disabled={pending || !canSubmit}>
      {pending ? <Loader2Icon className="animate-spin" aria-hidden="true" /> : null}
      {pending ? (changing ? 'Changing…' : 'Assigning…') : title}
    </Button>
  );

  if (isMobile) {
    return (
      <Drawer open={open} onOpenChange={close} dismissible={!pending}>
        <DrawerContent>
          <DrawerHeader className="text-left">
            <div className="flex items-start justify-between gap-3">
              <DrawerTitle>{title}</DrawerTitle>
              <DrawerClose asChild>
                <Button variant="ghost" size="icon-sm" className="-mt-1 -mr-2" aria-label="Close" disabled={pending}>
                  <XIcon />
                </Button>
              </DrawerClose>
            </div>
            <DrawerDescription asChild>
              <div>
                <BookingLine booking={booking} />
              </div>
            </DrawerDescription>
          </DrawerHeader>
          <div className="flex min-h-0 flex-1 flex-col gap-3 px-4">{picker}</div>
          <DrawerFooter>
            {selection()}
            {confirm}
            {cancel}
          </DrawerFooter>
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="flex max-h-[min(42rem,calc(100dvh-2rem))] flex-col overflow-hidden sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription asChild>
            <div>
              <BookingLine booking={booking} />
            </div>
          </DialogDescription>
        </DialogHeader>
        {picker}
        <DialogFooter className="shrink-0">
          {selection('mr-auto self-center')}
          {cancel}
          {confirm}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
