import { useState } from 'react';
import { PlayIcon } from 'lucide-react';

import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { FormDialog } from '@/components/form-dialog';
import { classMeetLink } from '@/lib/meet-rooms';
import { lifecycleError } from '@/lib/session-lifecycle';

/**
 * A blank tab for the class's Google Meet room, opened while the tutor's
 * click still counts as one (a browser blocks a tab opened only once the API
 * has answered), cut from the Hub (no `opener`) before it loads Meet.
 */
function openMeetTab(link) {
  if (!link) return null;
  const tab = window.open('', '_blank');
  if (tab) tab.opener = null;
  return tab;
}

function showMeet(tab, link) {
  if (!link) tab?.close();
  else if (tab && !tab.closed) tab.location.replace(link);
  else window.open(link, '_blank', 'noopener,noreferrer');
}

/**
 * Start Session (POST /api/sessions/<id>/start/), for whoever may start the
 * class -- its assigned tutor (`asTutor`), the student's mentor or an
 * administrator -- shown by the Sessions table only while its window is open,
 * from 5 minutes before the class until it ends. Confirmed first: the start is
 * recorded, with who gave it, by the server's clock and cannot be undone here.
 * It never completes the class; the tutor's own notes do. Once started, the
 * class's room -- its assigned tutor's Meet link, never the student's -- opens
 * in a new tab and `onStarted` gets the session as
 * the API answers it; a refusal is shown in the dialog, and `onRefresh` reads
 * the list again once it closes.
 */
export function StartSessionButton({ session, asTutor = false, onStarted, onRefresh }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const [refused, setRefused] = useState(false);

  const meetLink = classMeetLink(session);
  const studentName = session.students?.full_name || 'the student';

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
    const meetTab = openMeetTab(meetLink);
    try {
      const response = await api.post(`/api/sessions/${session.id}/start/`);
      const started = response.data.session;
      showMeet(meetTab, classMeetLink(started));
      setOpen(false);
      onStarted?.(started);
    } catch (err) {
      meetTab?.close();
      const failure = lifecycleError(err, 'Could not start this session. Please try again.');
      setError(failure.message);
      // Refused for good: what the table shows is out of date.
      setRefused(failure.status === 403 || failure.status === 404 || failure.status === 409);
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <Button size="sm" onClick={() => changeOpen(true)} aria-label={`Start Session with ${studentName}`}>
        <PlayIcon className="size-4" />
        Start Session
      </Button>
      <FormDialog
        open={open}
        onOpenChange={changeOpen}
        title="Start Session?"
        description={`${session.title} · ${studentName}`}
        error={error}
        onConfirm={start}
        confirmLabel="Start Session"
        pendingLabel="Starting…"
        confirmDisabled={refused}
        cancelLabel="Not yet"
        pending={pending}
      >
        <p className="text-muted-foreground text-sm">
          This records that you started the class now. It cannot be undone.{' '}
          {asTutor
            ? 'After the class, submit your notes to complete it.'
            : "Starting it does not complete it: the tutor's own notes, after the class, do."}{' '}
          {meetLink
            ? "Google Meet opens in a new tab, in the tutor's room."
            : asTutor
              ? 'You have no Meet link yet, so Google Meet will not open. An administrator can add it in Team.'
              : "This class's tutor has no Meet link yet, so Google Meet will not open. An administrator can add it in Team."}
        </p>
      </FormDialog>
    </>
  );
}
