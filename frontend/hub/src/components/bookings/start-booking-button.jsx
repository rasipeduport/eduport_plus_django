import { useState } from 'react';
import { PlayIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { FormDialog } from '@/components/form-dialog';
import { startError, startLabel, tutorBookingStartUrl } from '@/lib/bookings';
import { bookingTypeLabel, slotLabel } from '@/lib/enquiries';

/**
 * A blank tab for Google Meet, opened while the tutor's click still counts as
 * one: a browser (Safari above all) blocks a tab opened only once the API has
 * answered. Null when the booking has no link or the browser refused the tab.
 * It is cut from the Hub (no `opener`) before it ever loads Meet.
 */
function openMeetTab(link) {
  if (!link) return null;
  const tab = window.open('', '_blank');
  if (tab) tab.opener = null;
  return tab;
}

/**
 * Send the tab opened for Meet to `link` -- the booking's link as the API
 * answered the start -- or close it when the booking no longer has one. With
 * no tab to send (the browser refused it, or the tutor closed it, or the link
 * arrived only with the answer), Meet is opened directly instead.
 */
function showMeet(tab, link) {
  if (!link) tab?.close();
  else if (tab && !tab.closed) tab.location.replace(link);
  else window.open(link, '_blank', 'noopener,noreferrer');
}

/**
 * Start Demo / Start Diagnostic, for the booking's tutor (POST
 * /api/tutor/bookings/<type>/<id>/start/): offered only while the API says
 * the booking may be started (its `actions.start`), and confirmed first --
 * a start is recorded by the server's clock and cannot be undone here. Once
 * started, the booking's Google Meet link opens in a new tab (see openMeetTab).
 * `onStarted` gets the booking as the API answers it; a refusal (the slot
 * ended, a reassignment) is shown in the dialog, and `onRefresh` is asked to
 * read the booking again once the dialog closes.
 */
export function StartBookingButton({ booking, onStarted, onRefresh, size = 'sm' }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const [refused, setRefused] = useState(false);

  if (!booking?.actions?.start) return null;
  const label = startLabel(booking.booking_type);
  const kind = bookingTypeLabel(booking.booking_type);

  function changeOpen(next) {
    setOpen(next);
    if (next) {
      setError(null);
      setRefused(false);
    } else if (refused) {
      onRefresh?.();
    }
  }

  async function start() {
    setPending(true);
    setError(null);
    const meetTab = openMeetTab(booking.tutor_meet_link);
    try {
      const response = await api.post(tutorBookingStartUrl(booking.booking_type, booking.id));
      showMeet(meetTab, response.data.booking.tutor_meet_link);
      setOpen(false);
      onStarted?.(response.data.booking);
    } catch (err) {
      meetTab?.close();
      const failure = startError(err);
      setError(failure.message);
      // Refused for good (409/404): what the page shows is out of date.
      setRefused(failure.status === 404 || failure.status === 409);
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <Button size={size} onClick={() => changeOpen(true)} aria-label={`${label} for ${booking.student_name}`}>
        <PlayIcon className="size-4" />
        {label}
      </Button>
      <FormDialog
        open={open}
        onOpenChange={changeOpen}
        title={`${label}?`}
        description={`${booking.student_name} · ${kind} · ${slotLabel(booking.slot)}`}
        error={error}
        onConfirm={start}
        confirmLabel={label}
        pendingLabel="Starting…"
        confirmDisabled={refused}
        cancelLabel="Not yet"
        pending={pending}
      >
        <p className="text-muted-foreground text-sm">
          This records that you have started the {kind} now. It cannot be undone.{' '}
          {booking.tutor_meet_link
            ? 'Google Meet opens in a new tab.'
            : 'This booking has no Meet link, so Google Meet will not open.'}
        </p>
      </FormDialog>
    </>
  );
}
