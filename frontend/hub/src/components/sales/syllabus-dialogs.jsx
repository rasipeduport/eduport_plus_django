import { useEffect, useRef, useState } from 'react';
import { TriangleAlertIcon } from 'lucide-react';

import api from '@/lib/api';
import {
  deactivateUrl,
  draftUrl,
  publishUrl,
  reactivateUrl,
  salesError,
  syllabusUrl,
} from '@/lib/sales';
import { FormDialog } from '@/components/form-dialog';

/**
 * Other active syllabuses with the same grade, board, syllabus version and
 * structure (the API's `similar`, about the draft when there is one): a
 * warning only -- titles may tell offerings apart. `subject` names the
 * revision it is about ("Draft revision 2"), where the page shows more than one.
 */
export function SimilarWarning({ similar, subject }) {
  if (!similar?.length) return null;
  return (
    <div className="border-warning/30 bg-warning/5 flex gap-2 rounded-lg border px-3 py-2 text-sm" role="note">
      <TriangleAlertIcon className="text-warning mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0">
        <p className="font-medium">{subject ? `${subject}: similar syllabuses exist` : 'Similar syllabuses exist'}</p>
        <p className="text-muted-foreground">
          Same grade, board, syllabus version and structure:{' '}
          {similar.map((other) => `${other.title} (${other.status.toLowerCase()})`).join(', ')}. You can still go ahead.
        </p>
      </div>
    </div>
  );
}

/**
 * Publishing a syllabus's draft, on explicit confirmation (D4): the draft
 * becomes what BDEs sell from and the revision it replaces stays, unchanged,
 * in the history. It reads the syllabus when it opens (`syllabusId`). Given
 * `seen` -- the draft as the page showed it (`{ number, updated_at }`) when
 * the dialog opened -- it publishes that draft only: one saved since -- or gone, published or
 * discarded -- is refused for the rest of this opening, here or by the API
 * (DRAFT_CHANGED), and `onStale` lets the page reload; reopening the dialog
 * reads the syllabus again. Without `seen` (the list, which shows no draft),
 * it publishes the draft it describes.
 * `onPublished(detail)` gets the syllabus as published.
 */
export function PublishDialog({ syllabusId, seen, open, onOpenChange, onPublished, onStale }) {
  const [detail, setDetail] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  // The draft changed (or went) since the page showed it -- latched for this opening: a page that
  // reloads behind the dialog refreshes `seen`, which must not make Publish publish what was not reviewed.
  const [stale, setStale] = useState(false);
  // The page's latest token and callback, for the read below (which runs once per opening).
  const latest = useRef({ seen, onStale });
  useEffect(() => {
    latest.current = { seen, onStale };
  });
  // The draft as the page showed it when this opening began: what the read is checked against and
  // what is published -- a page reloading behind the dialog changes neither.
  const opened = useRef(null);

  // A fresh read each time it opens: it publishes what it shows.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setDetail(null);
      setFailure(null);
      setStale(false);
    }
  }

  useEffect(() => {
    if (!open || !syllabusId) return undefined;
    let active = true;
    const shown = latest.current.seen ?? null;
    opened.current = shown;
    api
      .get(syllabusUrl(syllabusId))
      .then((response) => {
        if (!active) return;
        setDetail(response.data);
        // Saved again, or published or discarded, since the page showed it: the page offers to reload it.
        const fresh = response.data.draft;
        if (shown && (!fresh || fresh.number !== shown.number || fresh.updated_at !== shown.updated_at)) {
          setStale(true);
          latest.current.onStale?.();
        }
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load the syllabus.'));
      });
    return () => {
      active = false;
    };
  }, [open, syllabusId]);

  const draft = detail?.draft;
  const published = detail?.published;
  // Saved again since the page showed it: publishing it would publish what the Admin has not seen.
  const changed = Boolean(seen && draft && (draft.number !== seen.number || draft.updated_at !== seen.updated_at));
  const blocked = stale || changed;

  const confirm = async () => {
    if (!draft || blocked) return;
    const token = opened.current ?? draft;
    setPending(true);
    setFailure(null);
    try {
      const response = await api.post(publishUrl(syllabusId), { revision: token.number, updated_at: token.updated_at });
      onOpenChange(false);
      onPublished?.(response.data);
    } catch (err) {
      const refused = salesError(err, 'Could not publish the syllabus.');
      setFailure(refused);
      if (refused.code === 'DRAFT_CHANGED') onStale?.();
    } finally {
      setPending(false);
    }
  };

  let body = <p className="text-muted-foreground text-sm">Loading the draft…</p>;
  if (detail && !draft) {
    body = <p className="text-sm">This syllabus has no draft to publish.</p>;
  } else if (draft) {
    body = (
      <div className="grid gap-3 text-sm">
        <p>
          <span className="font-medium">{draft.title}</span>, revision {draft.number}, becomes what BDEs sell from.
          {published
            ? ` Revision ${published.number} stays in the history, unchanged.`
            : ' This is its first publication.'}
        </p>
        <SimilarWarning similar={detail.similar} />
        {detail.status === 'INACTIVE' ? (
          <p className="text-destructive">This syllabus is inactive. Reactivate it before publishing.</p>
        ) : null}
        {blocked ? (
          <p className="text-destructive">
            This draft was saved again since you opened it. Reload it and check it before publishing.
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => {
        if (!pending) onOpenChange(next);
      }}
      title={draft ? `Publish revision ${draft.number}?` : 'Publish the draft?'}
      description="Published revisions can never be changed. Later edits start a new draft."
      confirmLabel="Publish"
      pendingLabel="Publishing…"
      pending={pending}
      confirmDisabled={!draft || blocked || detail?.status === 'INACTIVE'}
      onConfirm={confirm}
      error={failure ? (failure.problems.length ? failure.problems.join(' ') : failure.message) : null}
      size="md"
    >
      {body}
    </FormDialog>
  );
}

// The lifecycle actions that need nothing but a confirmation.
const ACTIONS = {
  deactivate: {
    title: 'Deactivate this syllabus?',
    description: 'It is hidden from the sales to come. Nothing is deleted: its revisions stay as they are, and you can reactivate it.',
    confirmLabel: 'Deactivate',
    pendingLabel: 'Deactivating…',
    variant: 'destructive',
    request: (id) => api.post(deactivateUrl(id)),
  },
  reactivate: {
    title: 'Reactivate this syllabus?',
    description: 'It becomes available again: published if it has been published, otherwise a draft.',
    confirmLabel: 'Reactivate',
    pendingLabel: 'Reactivating…',
    request: (id) => api.post(reactivateUrl(id)),
  },
  startDraft: {
    title: 'Edit this published syllabus?',
    description:
      'A new draft revision is copied from the published one. The published revision stays as it is — BDEs keep selling it — until you publish the draft.',
    confirmLabel: 'Start a draft',
    pendingLabel: 'Starting…',
    request: (id) => api.post(draftUrl(id)),
  },
  discardDraft: {
    title: 'Discard this draft?',
    description: 'Its changes are lost. The published revision stays as it is.',
    confirmLabel: 'Discard draft',
    pendingLabel: 'Discarding…',
    variant: 'destructive',
    request: (id, draft) => api.delete(draftUrl(id), { data: { revision: draft.number, updated_at: draft.updated_at } }),
  },
};

/**
 * A confirmation for one of a syllabus's lifecycle actions (`action`: a key
 * of ACTIONS) on `syllabus` (`{ id, draft? }`) as it was when the dialog
 * opened -- a page reloading behind it never changes the draft a discard
 * names. `onDone(detail, action)` gets the syllabus as the API answers after
 * it; `onRefused(failure, action)` hears of a refusal (e.g. DRAFT_EXISTS:
 * someone started the draft meanwhile).
 */
export function SyllabusActionDialog({ action, syllabus, onOpenChange, onDone, onRefused }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const config = ACTIONS[action];

  const [prevAction, setPrevAction] = useState(action);
  const [target, setTarget] = useState(syllabus);
  if (action !== prevAction) {
    setPrevAction(action);
    setError('');
    setTarget(syllabus);
  }

  const confirm = async () => {
    setPending(true);
    setError('');
    try {
      const response = await config.request(target.id, target.draft);
      onOpenChange(false);
      onDone?.(response.data, action);
    } catch (err) {
      const refused = salesError(err, 'Could not change the syllabus.');
      setError(refused.message);
      onRefused?.(refused, action);
    } finally {
      setPending(false);
    }
  };

  return (
    <FormDialog
      open={Boolean(config && syllabus)}
      onOpenChange={(next) => {
        if (!pending) onOpenChange(next);
      }}
      title={config?.title}
      description={config?.description}
      confirmLabel={config?.confirmLabel}
      pendingLabel={config?.pendingLabel}
      confirmVariant={config?.variant ?? 'default'}
      pending={pending}
      onConfirm={confirm}
      error={error}
    />
  );
}
