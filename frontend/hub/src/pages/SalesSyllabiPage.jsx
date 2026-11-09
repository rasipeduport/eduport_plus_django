import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { BadgePercentIcon, Loader2Icon, PlusIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import {
  BOARDS,
  GRADES,
  STRUCTURES,
  SYLLABI_URL,
  SYLLABUS_STATUSES,
  duplicateUrl,
  salesError,
  syllabusPdfUrl,
} from '@/lib/sales';
import { useFlashNotice } from '@/hooks/use-flash-notice';
import { useListParams } from '@/hooks/use-list-params';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';
import { PublishDialog, SyllabusActionDialog } from '@/components/sales/syllabus-dialogs';
import { SyllabusFilters, SyllabusList } from '@/components/sales/syllabus-list';
import { useSyllabusPdf } from '@/components/sales/syllabus-pdf';

const PAGE_SIZE = 25;
const valid = (options, value) => (options.some((option) => option.value === value) ? value : '');

/**
 * Syllabus & Plans, for administrators (Sales & Finance): every syllabus on
 * offer or being written, searched and filtered in the URL, each with what
 * can be done to it -- view, edit its draft (or start one), preview or
 * download its PDF, publish, deactivate or reactivate, duplicate. Publishing
 * and deactivating ask first. The API enforces each again.
 */
export default function SalesSyllabiPage({ user }) {
  const navigate = useNavigate();
  const { searchParams, update, clear } = useListParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useFlashNotice();
  const [actionError, setActionError] = useState('');
  const [duplicating, setDuplicating] = useState(false);
  const duplicatingRef = useRef(false);
  // An answer that comes after the Admin has left must not bring them back.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const [lifecycle, setLifecycle] = useState(null); // { action, row }
  const [publishing, setPublishing] = useState(null);
  const pdf = useSyllabusPdf();

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const q = (searchParams.get('q') ?? '').trim();
  const status = valid(SYLLABUS_STATUSES, searchParams.get('status'));
  const structure = valid(STRUCTURES, searchParams.get('structure'));
  const board = valid(BOARDS, searchParams.get('board'));
  const grade = valid(GRADES, searchParams.get('grade'));
  const filters = { q, status, structure, board, grade };

  useEffect(() => {
    let active = true;
    setPending(true);
    const params = { page, page_size: PAGE_SIZE };
    if (q) params.q = q;
    if (status) params.status = status;
    if (structure) params.structure = structure;
    if (board) params.board = board;
    if (grade) params.grade = grade;
    api
      .get(SYLLABI_URL, { params })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load the syllabuses.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [page, q, status, structure, board, grade, reloadKey]);

  const retry = () => setReloadKey((key) => key + 1);

  // A new action starts with nothing left over from the last one.
  const openLifecycle = (action, row) => {
    setActionError('');
    setLifecycle({ action, row });
  };

  const actions = {
    startDraft: (row) => openLifecycle('startDraft', row),
    deactivate: (row) => openLifecycle('deactivate', row),
    reactivate: (row) => openLifecycle('reactivate', row),
    publish: (row) => {
      setActionError('');
      setPublishing(row);
    },
    previewPdf: (row) => pdf.preview(syllabusPdfUrl(row.id)),
    downloadPdf: (row) => pdf.download(syllabusPdfUrl(row.id)),
    // One copy at a time: the menus offer no second Duplicate while one is being made.
    duplicate: async (row) => {
      if (duplicatingRef.current) return;
      duplicatingRef.current = true;
      setDuplicating(true);
      setActionError('');
      try {
        const response = await api.post(duplicateUrl(row.id));
        if (!alive.current) return;
        navigate(`/sales-syllabus/${response.data.id}/edit`, {
          state: { notice: `Copied ${row.title} as a new draft. Give it its own title, then publish it when ready.` },
        });
      } catch (err) {
        if (alive.current) setActionError(salesError(err, 'Could not duplicate the syllabus.').message);
      } finally {
        duplicatingRef.current = false;
        if (alive.current) setDuplicating(false);
      }
    },
  };

  const LIFECYCLE_NOTICES = {
    deactivate: (row) => `${row.title} is inactive: it is hidden from the sales to come.`,
    reactivate: (row) => `${row.title} is active again.`,
  };

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to syllabuses." message={failure.message} />;
  } else {
    let list;
    if (!data && !failure) {
      list = <TableSkeleton toolbar={false} />;
    } else if (!data) {
      list = <ErrorState message={failure.message} onRetry={retry} pending={pending} />;
    } else {
      list = (
        <>
          {failure ? <ErrorState message={failure.message} onRetry={retry} pending={pending} /> : null}
          <SyllabusList
            rows={data.results ?? []}
            total={data.count ?? 0}
            page={page}
            pageSize={PAGE_SIZE}
            filtered={Object.values(filters).some(Boolean)}
            pending={pending}
            actions={actions}
            pdfPending={pdf.pending}
            duplicating={duplicating}
            onChange={update}
            onClear={clear}
            onCreate={() => navigate('/sales-syllabus/new')}
          />
        </>
      );
    }
    content = (
      <div className="flex flex-col gap-4">
        <SyllabusFilters filters={filters} onChange={update} onClear={clear} />
        {pdf.pending ? (
          <p role="status" className="text-muted-foreground flex items-center gap-2 text-sm">
            <Loader2Icon className="size-4 animate-spin" aria-hidden="true" />
            {pdf.pending === 'download' ? 'Preparing the PDF download…' : 'Drawing the PDF…'}
          </p>
        ) : null}
        {actionError ? <ErrorState message={actionError} /> : null}
        {pdf.error ? <ErrorState message={pdf.error} /> : null}
        {list}
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Syllabus & Plans"
        description="The syllabuses on offer: their chapters, the plans each is sold as and the PDF parents receive. Edits are drafts until you publish them."
        actions={
          <>
            {can(user, PERMISSIONS.manageSalesPricing) ? (
              <Button variant="outline" asChild>
                <Link to="/sales-pricing">
                  <BadgePercentIcon />
                  Global pricing
                </Link>
              </Button>
            ) : null}
            <Button asChild>
              <Link to="/sales-syllabus/new">
                <PlusIcon />
                New syllabus
              </Link>
            </Button>
          </>
        }
      />

      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}

      {content}

      <SyllabusActionDialog
        action={lifecycle?.action ?? null}
        syllabus={lifecycle?.row ?? null}
        onOpenChange={(open) => {
          if (!open) setLifecycle(null);
        }}
        onDone={(detail, action) => {
          if (!alive.current) return;
          const row = lifecycle?.row;
          if (action === 'startDraft') {
            navigate(`/sales-syllabus/${detail.id}/edit`, {
              state: { notice: `Draft revision ${detail.draft.number} started. The published version stays as it is until you publish.` },
            });
            return;
          }
          setNotice(LIFECYCLE_NOTICES[action]?.(row) ?? null);
          retry();
        }}
        onRefused={(refused, action) => {
          if (!alive.current) return;
          // Someone started the draft meanwhile: open it.
          if (action === 'startDraft' && refused.code === 'DRAFT_EXISTS') {
            navigate(`/sales-syllabus/${lifecycle.row.id}/edit`);
            return;
          }
          // Deactivated or reactivated meanwhile: the list shows it as it is now, and says why.
          if (['ALREADY_INACTIVE', 'NOT_INACTIVE', 'SYLLABUS_INACTIVE'].includes(refused.code)) {
            setLifecycle(null);
            setActionError(`${lifecycle.row.title}: ${refused.message} The list now shows it as it is.`);
            retry();
          }
        }}
      />
      <PublishDialog
        syllabusId={publishing?.id}
        open={Boolean(publishing)}
        onOpenChange={(open) => {
          if (!open) setPublishing(null);
        }}
        onStale={retry}
        onPublished={(detail) => {
          if (!alive.current) return;
          setNotice(`${detail.published.title}: revision ${detail.published.number} is published.`);
          retry();
        }}
      />
      {pdf.dialog}
    </Page>
  );
}
