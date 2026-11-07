import { useEffect, useId, useState } from 'react';
import { LockIcon, StickyNoteIcon } from 'lucide-react';

import api from '@/lib/api';
import { istMoment } from '@/lib/communications';
import { NOTE_MAX_LENGTH, enquiryError } from '@/lib/enquiries';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { EmptyState } from '@/components/page/page';
import { ErrorState } from '@/components/page/states';

/** Up to two initials of a name, for its avatar: "Anjali Menon" -> "AM". */
function initials(name) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join('');
}

/** One note: who wrote it, in which role and when (IST), then what it says. */
function Note({ note }) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden="true"
        className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-medium"
      >
        {initials(note.author.full_name)}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-sm font-medium">{note.author.full_name}</span>
          <Badge variant="outline">{note.author_role_label}</Badge>
          <time dateTime={note.created_at} className="text-muted-foreground text-xs">
            {istMoment(note.created_at)}
          </time>
        </p>
        <p className="text-sm leading-relaxed break-words whitespace-pre-wrap">{note.body}</p>
      </div>
    </li>
  );
}

/**
 * The notes staff keep on one enquiry (bookings.LeadNote) -- its BDE, the
 * tutors teaching its bookings and the administrators -- oldest first, with a
 * box to add one, read from and added to `url`: each role's own route to the
 * same notes (the BDE's /api/bde/enquiries/<id>/notes/, the administrators'
 * /api/leads/<id>/notes/), which checks the caller may see that enquiry.
 * Notes belong to the enquiry, so its Demo and Diagnostic bookings share
 * them; they are never shown to the parent or the student, and are kept as
 * written. `emptyDescription`, `placeholder` and `loadError` word it for the
 * reader. Read when shown.
 */
export function LeadNotes({ url, emptyDescription, placeholder, loadError }) {
  const fieldId = useId();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(url)
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, loadError));
      });
    return () => {
      active = false;
    };
  }, [url, loadError, reloadKey]);

  const add = (event) => {
    event.preventDefault();
    const body = draft.trim();
    if (!body || pending) return;
    setPending(true);
    setError(null);
    api
      .post(url, { body })
      .then((response) => {
        // The API answers the notes as they now stand, anyone else's new ones included.
        setData(response.data);
        setDraft('');
      })
      .catch((err) => setError(enquiryError(err, 'Could not add the note.').message))
      .finally(() => setPending(false));
  };

  if (failure && !data) return <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  if (!data) return <Skeleton className="h-40 rounded-xl" aria-busy="true" />;

  return (
    <div className="flex flex-col gap-4">
      {data.results.length ? (
        <ol aria-label="Notes" className="bg-card flex flex-col gap-5 rounded-xl border p-4">
          {data.results.map((note) => (
            <Note key={note.id} note={note} />
          ))}
        </ol>
      ) : (
        <EmptyState
          icon={StickyNoteIcon}
          title="No notes yet"
          description={emptyDescription}
        />
      )}
      <form onSubmit={add} className="bg-card flex flex-col gap-3 rounded-xl border p-4">
        <Label htmlFor={fieldId} required>
          Add a note
        </Label>
        <Textarea
          id={fieldId}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={3}
          maxLength={NOTE_MAX_LENGTH}
          placeholder={placeholder}
          aria-required="true"
          aria-invalid={error ? true : undefined}
          disabled={pending}
        />
        {error ? (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
            <LockIcon className="size-3.5 shrink-0" aria-hidden="true" />
            Staff only: never shown to the parent or the student.
          </p>
          <Button type="submit" disabled={pending || !draft.trim()}>
            {pending ? 'Adding…' : 'Add Note'}
          </Button>
        </div>
      </form>
    </div>
  );
}
