import { useCallback, useEffect, useState } from 'react';
import { Lock, Pencil, StickyNote, Trash2, X } from 'lucide-react';
import { format } from 'date-fns';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import api from '@/lib/api';
import { cn } from '@/lib/utils';
import { EmptyState, SectionHeading, TabSkeleton } from './profile-primitives';

const MAX_LENGTH = 4000;
const ROLE_LABEL = { ADMIN: 'Admin', MENTOR: 'Mentor', TUTOR: 'Tutor' };

function NoteTextarea({ value, onChange, disabled, autoFocus, placeholder, id }) {
  return (
    <textarea
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      autoFocus={autoFocus}
      rows={4}
      maxLength={MAX_LENGTH}
      placeholder={placeholder}
      className="border-input placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 dark:bg-input/30 w-full min-w-0 resize-y rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50"
    />
  );
}

function NoteCard({ note, onEdited, onDeleted }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(note.body);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const save = async () => {
    const body = draft.trim();
    if (!body) {
      setError('A note cannot be empty.');
      return;
    }
    setPending(true);
    setError('');
    try {
      const res = await api.patch(`/api/students/notes/${note.id}/`, { body });
      setEditing(false);
      onEdited(res.data.note);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to save the note.');
    } finally {
      setPending(false);
    }
  };

  const remove = async () => {
    setPending(true);
    setError('');
    try {
      await api.delete(`/api/students/notes/${note.id}/`);
      setConfirmOpen(false);
      onDeleted(note.id);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to delete the note.');
      setPending(false);
    }
  };

  return (
    <li className="bg-card rounded-xl border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{note.author_name || 'Unknown'}</span>
        {note.author_role ? (
          <Badge variant="secondary">{ROLE_LABEL[note.author_role] || note.author_role}</Badge>
        ) : null}
        <span className="text-muted-foreground ml-auto text-xs whitespace-nowrap">
          {format(new Date(note.created_at), 'd MMM yyyy, h:mm a')}
          {note.edited_at ? ' · edited' : ''}
        </span>
      </div>

      {editing ? (
        <div className="mt-3 flex flex-col gap-2">
          <NoteTextarea value={draft} onChange={setDraft} disabled={pending} autoFocus />
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={save} disabled={pending}>
              {pending ? 'Saving…' : 'Save'}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={pending}
              onClick={() => {
                setDraft(note.body);
                setEditing(false);
                setError('');
              }}
            >
              <X className="size-4" />
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <p className="mt-2 text-sm leading-relaxed whitespace-pre-wrap">{note.body}</p>
      )}

      {error ? <p className="text-destructive mt-2 text-xs">{error}</p> : null}

      {!editing && (note.can_edit || note.can_delete) ? (
        <div className="mt-3 flex items-center gap-1">
          {note.can_edit ? (
            <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => setEditing(true)}>
              <Pencil className="size-3.5" />
              Edit
            </Button>
          ) : null}
          {note.can_delete ? (
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-destructive"
              onClick={() => setConfirmOpen(true)}
            >
              <Trash2 className="size-3.5" />
              Delete
            </Button>
          ) : null}
        </div>
      ) : null}

      <Dialog open={confirmOpen} onOpenChange={(open) => !pending && setConfirmOpen(open)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete this note?</DialogTitle>
            <DialogDescription>
              The note is removed for every staff member. The deletion itself is kept in the activity log.
            </DialogDescription>
          </DialogHeader>
          <p className="text-muted-foreground max-h-32 overflow-y-auto text-sm whitespace-pre-wrap">{note.body}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={pending}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={remove} disabled={pending}>
              {pending ? 'Deleting…' : 'Delete note'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}

/**
 * Notes tab: the staff's own running commentary on a student.
 *
 * Internal by design — every Hub role (admin, mentor, tutor) reads and writes
 * the notes of a student they can already open, and nothing in the Learn app
 * ever serves them, so this is the one place they appear. Editing is the
 * author's alone; an admin may delete any note. Both are logged.
 */
export function NotesTab({ studentId, studentName }) {
  const [notes, setNotes] = useState(null);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/students/${studentId}/notes/`);
      setNotes(res.data.notes ?? []);
      setLoadError('');
    } catch {
      setNotes([]);
      setLoadError('Failed to load notes.');
    }
  }, [studentId]);

  useEffect(() => {
    load();
  }, [load]);

  const add = async (event) => {
    event.preventDefault();
    const body = draft.trim();
    if (!body) {
      setError('A note cannot be empty.');
      return;
    }
    setPending(true);
    setError('');
    try {
      const res = await api.post(`/api/students/${studentId}/notes/`, { body });
      setNotes((current) => [res.data.note, ...(current ?? [])]);
      setDraft('');
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to add the note.');
    } finally {
      setPending(false);
    }
  };

  if (notes === null) return <TabSkeleton rows={3} />;

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading
        title={`${notes.length} ${notes.length === 1 ? 'note' : 'notes'}`}
        description={`Internal notes about ${studentName}. Visible to Hub staff only — never to the student.`}
        action={
          <Badge variant="outline" className="gap-1">
            <Lock className="size-3" />
            Staff only
          </Badge>
        }
      />

      <form onSubmit={add} className="flex flex-col gap-2">
        <label htmlFor="new-note" className="sr-only">
          Add a note
        </label>
        <NoteTextarea
          id="new-note"
          value={draft}
          onChange={(value) => setDraft(value)}
          disabled={pending}
          placeholder="What should the rest of the team know about this student?"
        />
        <div className="flex items-center gap-3">
          <Button type="submit" size="sm" disabled={pending || !draft.trim()}>
            {pending ? 'Adding…' : 'Add note'}
          </Button>
          <span
            className={cn(
              'text-muted-foreground text-xs tabular-nums',
              draft.length > MAX_LENGTH - 200 && 'text-warning'
            )}
          >
            {draft.length}/{MAX_LENGTH}
          </span>
          {error ? <span className="text-destructive text-xs">{error}</span> : null}
        </div>
      </form>

      {loadError ? <p className="text-destructive text-sm">{loadError}</p> : null}

      {notes.length === 0 ? (
        <EmptyState
          icon={StickyNote}
          message="No notes yet."
          hint="Add the first one above — handovers, parent conversations, anything the next person needs."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {notes.map((note) => (
            <NoteCard
              key={note.id}
              note={note}
              onEdited={(updated) =>
                setNotes((current) => current.map((row) => (row.id === updated.id ? updated : row)))
              }
              onDeleted={(id) => setNotes((current) => current.filter((row) => row.id !== id))}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
