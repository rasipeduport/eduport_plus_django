import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { InboxIcon, PlusIcon, SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { ENQUIRIES_URL, LEAD_STATUSES, SOURCE_FILTERS, enquiryError } from '@/lib/enquiries';
import { useListParams } from '@/hooks/use-list-params';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { ShareLinkButtons } from '@/components/dashboard/share-link-buttons';
import { AddEnquiryDialog } from '@/components/enquiries/add-enquiry-dialog';
import { MyEnquiriesList } from '@/components/enquiries/my-enquiries-list';
import { EmptyState, Page, PageHeader } from '@/components/page/page';
import { FilterSelect, ListToolbar, SearchField } from '@/components/page/list-toolbar';
import { Pagination } from '@/components/page/pagination';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';

const PAGE_SIZE = 25;
const STATUS_VALUES = new Set(LEAD_STATUSES.map((status) => status.value));
const SOURCE_VALUES = new Set(SOURCE_FILTERS.map((source) => source.value));

/**
 * What the list says when it has no rows: no enquiry matches the filters, the
 * page asked for is past the last one, or the BDE has no enquiries yet.
 */
function NoEnquiries({ filtered, total, onClear, onFirstPage, onAdd }) {
  if (total > 0) {
    return (
      <EmptyState
        icon={SearchXIcon}
        title="Nothing on this page"
        description="This page is past the last one."
        action={
          <Button variant="outline" onClick={onFirstPage}>
            Go to the first page
          </Button>
        }
      />
    );
  }
  if (filtered) {
    return (
      <EmptyState
        icon={SearchXIcon}
        title="No enquiries match these filters"
        description="Try another search, or clear the filters to see every enquiry."
        action={
          <Button variant="outline" onClick={onClear}>
            Clear filters
          </Button>
        }
      />
    );
  }
  return (
    <EmptyState
      icon={InboxIcon}
      title="No enquiries yet"
      description="Share your booking links, or add an enquiry that reached you another way."
      action={
        onAdd ? (
          <Button onClick={onAdd}>
            <PlusIcon />
            Add Enquiry
          </Button>
        ) : null
      }
    />
  );
}

/**
 * My Enquiries: the BDE's own enquiries -- the ones their booking links
 * brought in, the ones they added by hand and the ones an administrator
 * assigned them -- with their booking links to share. Search, filters and the
 * page are kept in the URL (q, status, source, page) and applied by the API,
 * which serves each BDE only the enquiries they own now: one reassigned to
 * another BDE is gone from here.
 */
export default function EnquiriesPage({ user }) {
  const canAdd = can(user, PERMISSIONS.addEnquiry);
  const canShareLinks = can(user, PERMISSIONS.viewOwnBookingLinks);
  const { searchParams, update, clear } = useListParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [added, setAdded] = useState(null);
  const [addOpen, setAddOpen] = useState(false);

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const q = (searchParams.get('q') ?? '').trim();
  const status = STATUS_VALUES.has(searchParams.get('status')) ? searchParams.get('status') : '';
  const source = SOURCE_VALUES.has(searchParams.get('source')) ? searchParams.get('source') : '';
  const filtered = Boolean(q || status || source);

  useEffect(() => {
    let active = true;
    setPending(true);

    const params = { page, page_size: PAGE_SIZE };
    if (q) params.q = q;
    if (status) params.status = status;
    if (source) params.source = source;

    api
      .get(ENQUIRIES_URL, { params })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, 'Could not load your enquiries.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });

    return () => {
      active = false;
    };
  }, [page, q, status, source, reloadKey]);

  const retry = () => setReloadKey((key) => key + 1);
  const handleAdded = (enquiry) => {
    setAdded(enquiry);
    retry();
  };

  let content;
  if (failure?.status === 403) {
    content = (
      <AccessDeniedState
        title={failure.code === 'NOT_A_BDE' ? 'Enquiries belong to BDE accounts.' : "You don't have access to enquiries."}
        message={failure.message}
      />
    );
  } else {
    const rows = data?.results ?? [];
    const total = data?.count ?? 0;
    let list;
    if (!data && !failure) {
      list = <TableSkeleton columns={6} toolbar={false} />;
    } else if (!data) {
      list = <ErrorState message={failure.message} onRetry={retry} pending={pending} />;
    } else {
      list = (
        <>
          {/* A later page or filter that failed to load keeps the rows already shown. */}
          {failure ? <ErrorState message={failure.message} onRetry={retry} pending={pending} /> : null}
          {rows.length ? (
            <MyEnquiriesList rows={rows} pending={pending} />
          ) : (
            <NoEnquiries
              filtered={filtered}
              total={total}
              onClear={clear}
              onFirstPage={() => update({ page: null })}
              onAdd={canAdd ? () => setAddOpen(true) : null}
            />
          )}
          {total > 0 ? (
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              pending={pending}
              onPageChange={(next) => update({ page: String(next) })}
            />
          ) : null}
        </>
      );
    }
    content = (
      <div className="flex flex-col gap-4">
        <ListToolbar active={filtered} onClear={clear}>
          <SearchField
            value={q}
            onSearch={(text) => update({ q: text || null })}
            label="Search enquiries"
            placeholder="Search parent, student or phone…"
          />
          <FilterSelect
            label="Filter by status"
            placeholder="All statuses"
            value={status}
            onChange={(value) => update({ status: value || null })}
            options={LEAD_STATUSES}
          />
          <FilterSelect
            label="Filter by source"
            placeholder="All sources"
            value={source}
            onChange={(value) => update({ source: value || null })}
            options={SOURCE_FILTERS}
          />
        </ListToolbar>
        {list}
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title="My Enquiries"
        description="Every enquiry that is yours: from your booking links, added by you, or assigned to you. Search, filter and open one to take action."
        actions={
          <>
            {/* The BDE's own booking links, to share with any parent. */}
            {canShareLinks ? <ShareLinkButtons /> : null}
            {canAdd ? (
              <Button variant="outline" onClick={() => setAddOpen(true)}>
                <PlusIcon />
                Add Enquiry
              </Button>
            ) : null}
          </>
        }
      />

      {added ? (
        <Notice onDismiss={() => setAdded(null)}>
          Added the enquiry for {added.student_name}.{' '}
          <Link to={`/enquiries/${added.id}`} className="font-medium underline">
            Open it
          </Link>
        </Notice>
      ) : null}

      {content}

      {canAdd ? <AddEnquiryDialog open={addOpen} onOpenChange={setAddOpen} onCreated={handleAdded} /> : null}
    </Page>
  );
}
