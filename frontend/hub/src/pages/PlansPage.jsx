import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { BOARDS, CATALOGUE_URL, GRADES, STRUCTURES, salesError } from '@/lib/sales';
import { useListParams } from '@/hooks/use-list-params';
import { TableSkeleton } from '@/components/table-skeleton';
import { Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState } from '@/components/page/states';
import { CatalogueFilters, CatalogueList } from '@/components/sales/catalogue-list';

const PAGE_SIZE = 25;
const valid = (options, value) => (options.some((option) => option.value === value) ? value : '');

/**
 * Plans & Pricing, for BDEs: the plans on sale -- each syllabus as its
 * published revision sells it -- searched and filtered in the URL, each
 * opening on its packages, its PDF and, for a Bridge Course, the days to
 * choose. Drafts, inactive syllabuses and everything the administrators
 * manage stay out of it: the API (the catalogue) never sends them.
 */
export default function PlansPage({ onSelect, enquiry }) {
  const { searchParams, update } = useListParams();
  const clear = () => update({ q: null, structure: null, board: null, grade: null, page: null });
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const q = (searchParams.get('q') ?? '').trim();
  const structure = valid(STRUCTURES, searchParams.get('structure'));
  const board = valid(BOARDS, searchParams.get('board'));
  const grade = valid(GRADES, searchParams.get('grade'));
  const filters = { q, structure, board, grade };

  useEffect(() => {
    let active = true;
    setPending(true);
    const params = { page, page_size: PAGE_SIZE };
    if (q) params.q = q;
    if (structure) params.structure = structure;
    if (board) params.board = board;
    if (grade) params.grade = grade;
    api
      .get(CATALOGUE_URL, { params })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load the plans.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [page, q, structure, board, grade, reloadKey]);

  const retry = () => setReloadKey((key) => key + 1);

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to plans and pricing." message={failure.message} />;
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
          <CatalogueList
            rows={data.results ?? []}
            total={data.count ?? 0}
            page={page}
            pageSize={PAGE_SIZE}
            filtered={Object.values(filters).some(Boolean)}
            pending={pending}
            onChange={update}
            onClear={clear}
            onSelect={onSelect}
            enquiry={enquiry}
          />
        </>
      );
    }
    content = (
      <div className="flex flex-col gap-4">
        <CatalogueFilters filters={filters} onChange={update} onClear={clear} />
        {list}
      </div>
    );
  }

  const Frame = onSelect ? 'div' : Page;
  return (
    <Frame className={onSelect ? 'flex flex-col gap-4' : undefined}>
      <PageHeader
        title={onSelect ? '1. Select a syllabus' : 'Plans & Pricing'}
        description={
          onSelect
            ? `Choose the syllabus for ${enquiry.student_name}. Its published revision determines the available plans and chapters.`
            : 'Browse published syllabuses and share their PDFs. To create a student quote, open My Enquiries → Plan Choosing.'
        }
      />
      {content}
    </Frame>
  );
}
