import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  BadgePercentIcon,
  CopyIcon,
  DownloadIcon,
  FileSearchIcon,
  FileTextIcon,
  HistoryIcon,
  ListOrderedIcon,
  Loader2Icon,
  MoreHorizontalIcon,
  PencilIcon,
  SendIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { formatDay } from '@/lib/enquiries';
import { useFlashNotice } from '@/hooks/use-flash-notice';
import {
  duplicateUrl,
  formatAmount,
  planTypeLabel,
  revisionPdfUrl,
  salesError,
  structureLabel,
  syllabusUrl,
} from '@/lib/sales';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';
import { Field, Fields, WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { PackageCards } from '@/components/sales/package-cards';
import { PlanTypeBadges, SyllabusStatusBadge } from '@/components/sales/syllabus-badges';
import { PublishDialog, SimilarWarning, SyllabusActionDialog } from '@/components/sales/syllabus-dialogs';
import { useSyllabusPdf } from '@/components/sales/syllabus-pdf';

const HISTORY_STATES = {
  PUBLISHED: { label: 'Published', variant: 'success' },
  SUPERSEDED: { label: 'Superseded', variant: 'outline' },
  DRAFT: { label: 'Draft', variant: 'secondary' },
};

/** A revision's chapter table, as the PDF prints it, with its totals. */
function ChapterTable({ revision }) {
  const bridge = revision.structure === 'BRIDGE_COURSE';
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-16">{bridge ? 'Day' : 'SL'}</TableHead>
            <TableHead>Chapter name</TableHead>
            {bridge ? (
              <TableHead className="w-28">Classes</TableHead>
            ) : (
              <>
                <TableHead className="w-32">Regular classes</TableHead>
                <TableHead className="w-32">Revision classes</TableHead>
              </>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {revision.chapters.map((chapter) => (
            <TableRow key={chapter.id ?? chapter.position}>
              <TableCell className="tabular-nums">{chapter.position}</TableCell>
              <TableCell className="whitespace-normal">{chapter.name}</TableCell>
              {bridge ? (
                <TableCell className="tabular-nums">{chapter.bridge_classes}</TableCell>
              ) : (
                <>
                  <TableCell className="tabular-nums">{chapter.regular_classes}</TableCell>
                  <TableCell className="tabular-nums">{chapter.revision_classes}</TableCell>
                </>
              )}
            </TableRow>
          ))}
          <TableRow className="bg-muted/50 font-medium">
            <TableCell />
            <TableCell>Total</TableCell>
            {bridge ? (
              <TableCell className="tabular-nums">{revision.totals.bridge}</TableCell>
            ) : (
              <>
                <TableCell className="tabular-nums">{revision.totals.regular}</TableCell>
                <TableCell className="tabular-nums">{revision.totals.revision}</TableCell>
              </>
            )}
          </TableRow>
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * One syllabus, for administrators: what it offers (its published revision)
 * and, while one is being written, its draft -- each with its details,
 * chapters, priced packages and inclusions -- and every revision it has had.
 * From here a draft is edited (or started), previewed and published, the PDF
 * downloaded, and the syllabus deactivated, reactivated or duplicated.
 * Published revisions never change (D4).
 */
export default function SalesSyllabusPage() {
  const { syllabusId } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useFlashNotice();
  const [view, setView] = useState(null); // 'published' | 'draft'
  const [action, setAction] = useState(null);
  const [publishing, setPublishing] = useState(false);
  const [actionError, setActionError] = useState('');
  const [duplicating, setDuplicating] = useState(false);
  const duplicatingRef = useRef(false);
  const pdf = useSyllabusPdf();
  // An answer that comes after the Admin has left must not bring them back.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    api
      .get(syllabusUrl(syllabusId))
      .then((response) => {
        if (!active) return;
        setDetail(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load the syllabus.'));
      });
    return () => {
      active = false;
    };
  }, [syllabusId, reloadKey]);

  const reload = () => setReloadKey((key) => key + 1);

  if (failure?.status === 403) {
    return (
      <Page>
        <AccessDeniedState title="You don't have access to syllabuses." message={failure.message} />
      </Page>
    );
  }
  if (failure && !detail) {
    return (
      <Page>
        <ErrorState message={failure.status === 404 ? 'This syllabus does not exist.' : failure.message} onRetry={reload} />
      </Page>
    );
  }
  if (!detail) {
    return (
      <Page>
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </Page>
    );
  }

  const { published, draft } = detail;
  const shown = (view === 'draft' && draft) || (view === 'published' && published) || published || draft;
  const inactive = detail.status === 'INACTIVE';

  // A new action starts with nothing left over from the last one.
  const openAction = (name) => {
    setActionError('');
    setAction(name);
  };

  // Copies the revision on screen: the published one, or the draft from its tab. One copy at a time.
  const duplicate = async () => {
    if (duplicatingRef.current) return;
    duplicatingRef.current = true;
    setDuplicating(true);
    setActionError('');
    try {
      const response = await api.post(duplicateUrl(syllabusId), { revision: shown.number });
      if (!alive.current) return;
      navigate(`/sales-syllabus/${response.data.id}/edit`, {
        state: { notice: `Copied revision ${shown.number} as a new draft. Give it its own title, then publish it when ready.` },
      });
    } catch (err) {
      if (alive.current) setActionError(salesError(err, 'Could not duplicate the syllabus.').message);
    } finally {
      duplicatingRef.current = false;
      if (alive.current) setDuplicating(false);
    }
  };

  const NOTICES = {
    deactivate: 'This syllabus is inactive: it is hidden from the sales to come.',
    reactivate: 'This syllabus is active again.',
    discardDraft: 'The draft is discarded. The published revision is unchanged.',
  };

  return (
    <Page className="max-w-5xl">
      <PageHeader
        title={shown.title}
        description={[`Grade ${shown.grade}`, shown.board, shown.syllabus_version, structureLabel(shown.structure)]
          .filter(Boolean)
          .join(' · ')}
        actions={
          <>
            <SyllabusStatusBadge status={detail.status} draftRevision={published ? draft?.number : null} />
            {!inactive && draft ? (
              <Button variant="outline" asChild>
                <Link to={`/sales-syllabus/${syllabusId}/edit`}>
                  <PencilIcon />
                  Edit draft
                </Link>
              </Button>
            ) : null}
            {!inactive && !draft ? (
              <Button variant="outline" onClick={() => openAction('startDraft')}>
                <PencilIcon />
                Edit
              </Button>
            ) : null}
            {!inactive && draft ? (
              <Button
                onClick={() => {
                  setActionError('');
                  setPublishing(true);
                }}
              >
                <SendIcon />
                Publish…
              </Button>
            ) : null}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="More actions">
                  <MoreHorizontalIcon className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={duplicate} disabled={duplicating}>
                  <CopyIcon />
                  Duplicate revision {shown.number}
                </DropdownMenuItem>
                {published && draft && !inactive ? (
                  <DropdownMenuItem variant="destructive" onSelect={() => openAction('discardDraft')}>
                    Discard draft
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuSeparator />
                {inactive ? (
                  <DropdownMenuItem onSelect={() => openAction('reactivate')}>Reactivate</DropdownMenuItem>
                ) : (
                  <DropdownMenuItem variant="destructive" onSelect={() => openAction('deactivate')}>
                    Deactivate
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
        actionsClassName="items-center"
      />

      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}
      {actionError ? <ErrorState message={actionError} /> : null}
      {pdf.error ? <ErrorState message={pdf.error} /> : null}
      <SimilarWarning similar={detail.similar} subject={published && draft ? `Draft revision ${draft.number}` : null} />

      {published && draft ? (
        <Tabs value={shown === draft ? 'draft' : 'published'} onValueChange={setView}>
          <TabsList>
            <TabsTrigger value="published">Published · revision {published.number}</TabsTrigger>
            <TabsTrigger value="draft">Draft · revision {draft.number}</TabsTrigger>
          </TabsList>
        </Tabs>
      ) : null}

      <WorkspaceCard
        icon={FileTextIcon}
        title={shown.is_draft ? `Draft revision ${shown.number}` : `Published revision ${shown.number}`}
        action={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => pdf.preview(`${revisionPdfUrl(syllabusId, shown.number)}`)}
              disabled={Boolean(pdf.pending)}
            >
              {pdf.pending === 'preview' ? <Loader2Icon className="size-4 animate-spin" /> : <FileSearchIcon className="size-4" />}
              Preview PDF
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => pdf.download(revisionPdfUrl(syllabusId, shown.number))}
              disabled={Boolean(pdf.pending)}
            >
              {pdf.pending === 'download' ? <Loader2Icon className="size-4 animate-spin" /> : <DownloadIcon className="size-4" />}
              Download PDF
            </Button>
          </div>
        }
      >
        <Fields>
          <Field label="PDF title">
            {shown.title}
            <p className="text-muted-foreground text-xs font-normal">{shown.subtitle_display}</p>
          </Field>
          <Field label="Packages page">{shown.package_title_display}</Field>
          <Field label="Grade">Grade {shown.grade}</Field>
          <Field label="Board">{shown.board}</Field>
          <Field label="Syllabus version">{shown.syllabus_version}</Field>
          <Field label="Structure">{structureLabel(shown.structure)}</Field>
          <Field label="Plan types">
            <PlanTypeBadges planTypes={shown.plan_types} />
          </Field>
          {detail.reference ? (
            <Field label="Loaded from">
              {detail.reference}
              <p className="text-muted-foreground text-xs font-normal">Check it against this reference PDF before publishing.</p>
            </Field>
          ) : null}
          <Field label={shown.is_draft ? 'Last saved' : 'Published'}>
            {shown.is_draft
              ? `${formatDay(shown.updated_at)} by ${shown.updated_by?.name ?? '—'}`
              : `${formatDay(shown.published_at)} by ${shown.published_by?.name ?? '—'}`}
          </Field>
        </Fields>
      </WorkspaceCard>

      <WorkspaceCard icon={ListOrderedIcon} title={shown.structure === 'BRIDGE_COURSE' ? 'Days' : 'Chapters'}>
        <ChapterTable revision={shown} />
      </WorkspaceCard>

      <WorkspaceCard
        icon={BadgePercentIcon}
        title="Packages"
        action={
          <Button variant="link" size="sm" className="h-auto px-0" asChild>
            <Link to="/sales-pricing">Global pricing</Link>
          </Button>
        }
      >
        {detail.pricing ? (
          <>
            <p className="text-muted-foreground text-sm">
              Priced at pricing version {detail.pricing.version}, in effect now.
              {shown.plan_types.includes('CHAPTER_PLAN')
                ? ` Also sold as a ${planTypeLabel('CHAPTER_PLAN')}: chosen chapters at ${formatAmount(detail.pricing.offer_fee, detail.pricing.currency)} a class.`
                : ''}
            </p>
            <PackageCards packages={shown.packages ?? []} currency={detail.pricing.currency} />
          </>
        ) : (
          <p className="text-sm">
            No pricing is set up yet.{' '}
            <Link to="/sales-pricing" className="font-medium underline">
              Set up the pricing
            </Link>{' '}
            to price the packages and draw PDFs.
          </p>
        )}
        {shown.inclusions.length ? (
          <div className="mt-2">
            <p className="mb-1 text-sm font-medium">Inclusions</p>
            <ul className="text-muted-foreground list-disc pl-5 text-sm">
              {shown.inclusions.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </WorkspaceCard>

      <WorkspaceCard icon={HistoryIcon} title="History">
        <ul className="divide-y">
          {detail.history.map((row) => (
            <li key={row.number} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-sm">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 font-medium">
                  Revision {row.number}
                  <Badge variant={HISTORY_STATES[row.state].variant}>{HISTORY_STATES[row.state].label}</Badge>
                </p>
                <p className="text-muted-foreground">
                  {row.title} ·{' '}
                  {row.published_at
                    ? `published ${formatDay(row.published_at)} by ${row.published_by?.name ?? '—'}`
                    : `started ${formatDay(row.created_at)} by ${row.created_by?.name ?? '—'}`}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => pdf.preview(revisionPdfUrl(syllabusId, row.number))}
                disabled={Boolean(pdf.pending)}
                aria-label={`Preview the PDF of revision ${row.number}`}
              >
                <FileSearchIcon className="size-4" />
                PDF
              </Button>
            </li>
          ))}
        </ul>
        <p className="text-muted-foreground text-xs">
          Published revisions never change; each is kept for the sales made from it. PDFs are priced as now.
        </p>
      </WorkspaceCard>

      <SyllabusActionDialog
        action={action}
        syllabus={detail}
        onOpenChange={(open) => {
          if (!open) setAction(null);
        }}
        onDone={(updated, done) => {
          if (!alive.current) return;
          setActionError('');
          if (done === 'startDraft') {
            navigate(`/sales-syllabus/${syllabusId}/edit`, {
              state: { notice: `Draft revision ${updated.draft.number} started. The published version stays as it is until you publish.` },
            });
            return;
          }
          setDetail(updated);
          setView(null);
          setNotice(NOTICES[done] ?? null);
        }}
        onRefused={(refused, refusedAction) => {
          if (!alive.current) return;
          // Someone started the draft meanwhile: open it.
          if (refusedAction === 'startDraft' && refused.code === 'DRAFT_EXISTS') {
            navigate(`/sales-syllabus/${syllabusId}/edit`);
            return;
          }
          // The syllabus changed meanwhile (its draft saved or published, or it was deactivated or
          // reactivated): the page shows it as it is now, and says why nothing was done.
          if (refused.code === 'DRAFT_CHANGED' && refusedAction === 'discardDraft') {
            setAction(null);
            setActionError('This draft was changed or published meanwhile. The page now shows it as it is: check it before discarding.');
            reload();
          } else if (['ALREADY_INACTIVE', 'NOT_INACTIVE', 'SYLLABUS_INACTIVE'].includes(refused.code)) {
            setAction(null);
            setActionError(`${refused.message} The page now shows it as it is.`);
            reload();
          }
        }}
      />
      <PublishDialog
        syllabusId={syllabusId}
        seen={draft}
        open={publishing}
        onOpenChange={setPublishing}
        onStale={reload}
        onPublished={(updated) => {
          if (!alive.current) return;
          setActionError('');
          setDetail(updated);
          setView(null);
          setNotice(`Revision ${updated.published.number} is published. It is what BDEs sell from now on.`);
        }}
      />
      {pdf.dialog}
    </Page>
  );
}
