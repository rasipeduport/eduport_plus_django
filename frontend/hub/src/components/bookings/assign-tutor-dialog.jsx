import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { FormDialog } from '@/components/form-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { bookingError, bookingTutorUrl, bookingTutorsUrl } from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';
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

/**
 * Choosing who teaches a booking. Every active tutor for its slot comes from
 * the API (GET /api/bookings/<id>/tutors/), Available or Unavailable with the
 * reason it gives -- a class or another booking at that time, never another
 * child's name -- and the current tutor marked. Only an available tutor can be
 * picked; the API checks again when assigning (PUT /api/bookings/<id>/tutor/)
 * and a refusal is shown as it comes, with the list read again.
 */
export function AssignTutorDialog({ booking, open, onOpenChange, onAssigned }) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState('');
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const bookingId = booking?.id;

  // A fresh dialog on every open.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setData(null);
      setFailure(null);
      setError(null);
      setSelected('');
    }
  }

  useEffect(() => {
    if (!open || !bookingId) return undefined;
    let active = true;
    setFailure(null);
    api
      .get(bookingTutorsUrl(bookingId))
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load the tutors.'));
      });
    return () => {
      active = false;
    };
  }, [open, bookingId, reloadKey]);

  const tutors = data?.tutors ?? [];
  const current = tutors.find((tutor) => tutor.current);
  const choice = tutors.find((tutor) => tutor.id === selected);
  const changeable = Boolean(data?.tutor_changeable);
  const canSubmit = Boolean(changeable && choice && choice.status === 'AVAILABLE' && !choice.current);

  async function assign() {
    if (!canSubmit) return;
    setPending(true);
    setError(null);
    try {
      const response = await api.put(bookingTutorUrl(bookingId), { tutor_id: selected });
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

  let body;
  if (failure) {
    body = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  } else if (!data) {
    body = <TutorSkeleton />;
  } else if (!changeable) {
    body = <p className="text-muted-foreground text-sm">{data.tutor_change_refusal?.message}</p>;
  } else if (tutors.length === 0) {
    body = <p className="text-muted-foreground text-sm">There are no active tutors to choose from.</p>;
  } else {
    body = (
      <fieldset className="flex max-h-[50vh] flex-col gap-2 overflow-y-auto pr-1" disabled={pending}>
        <legend className="sr-only">Tutors</legend>
        {tutors.map((tutor) => {
          const unavailable = tutor.status !== 'AVAILABLE';
          return (
            <label
              key={tutor.id}
              className={cn(
                'flex items-start gap-3 rounded-md border p-3 text-sm transition-colors',
                unavailable ? 'cursor-not-allowed opacity-70' : 'hover:bg-muted/40 cursor-pointer',
                selected === tutor.id && 'border-primary bg-muted/40'
              )}
            >
              <input
                type="radio"
                name="booking-tutor"
                value={tutor.id}
                checked={selected === tutor.id}
                onChange={() => setSelected(tutor.id)}
                disabled={unavailable}
                className="mt-1"
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{tutor.full_name}</span>
                  {tutor.current ? <Badge variant="info">Current</Badge> : null}
                  <AvailabilityBadge status={tutor.status} />
                </span>
                <span className="text-muted-foreground block truncate text-xs">{tutor.email}</span>
                {tutor.reason ? <span className="text-muted-foreground mt-1 block text-xs">{tutor.reason.message}</span> : null}
              </span>
            </label>
          );
        })}
      </fieldset>
    );
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={current ? 'Change tutor' : 'Assign tutor'}
      description={
        booking
          ? `${booking.student_name} · ${bookingTypeLabel(booking.booking_type)} · ${slotLabel(booking.slot)}`
          : null
      }
      error={error}
      onConfirm={assign}
      confirmLabel={current ? 'Reassign' : 'Assign'}
      pendingLabel="Saving…"
      confirmDisabled={!canSubmit}
      pending={pending}
      size="lg"
    >
      {body}
    </FormDialog>
  );
}
