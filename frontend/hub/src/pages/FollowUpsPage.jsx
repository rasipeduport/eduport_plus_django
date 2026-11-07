import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { CheckCircle2Icon, SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { enquiryError } from '@/lib/enquiries';
import { BDE_FOLLOW_UPS_URL, FOLLOW_UP_DUE, FOLLOW_UP_TYPES } from '@/lib/follow-ups';
import { useListParams } from '@/hooks/use-list-params';
import { Button } from '@/components/ui/button';
import { Tabs, TabsCount, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TableSkeleton } from '@/components/table-skeleton';
import { FollowUpList } from '@/components/enquiries/follow-up-list';
import { FilterSelect, ListToolbar } from '@/components/page/list-toolbar';
import { EmptyState, Page, PageHeader } from '@/components/page/page';
import { Pagination } from '@/components/page/pagination';
import { AccessDeniedState, ErrorState } from '@/components/page/states';

const PAGE_SIZE = 25;
// The due tabs' value for every open follow-up (no `due` in the URL).
const ALL = 'all';
const DUE_VALUES = new Set(FOLLOW_UP_DUE.map((option) => option.value));
const TYPE_VALUES = new Set(FOLLOW_UP_TYPES.map((option) => option.value));

/**
 * A BDE's follow-ups: the reminders that need them now on their own
 * enquiries -- call a new enquiry, get a parent's confirmation, make the call
 * before a class, share a tutor's report, confirm a scheduled Re-Demo --
 * soonest due first, from GET /api/bde/follow-ups/; never the automatic
 * WhatsApp messages, which stay in each booking's communication. Due today and
 * Upcoming (Indian days) and the type are kept in the URL (due, type, page).
 * Each is done here, in a dialog, or opens where it is done; the way back
 * returns here. A reminder leaves the list once done or once its time is up,
 * and the list is read again with its counts after each action.
 */
export default function FollowUpsPage() {
  const location = useLocation();
  const { searchParams, update, clear } = useListParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);

  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const due = DUE_VALUES.has(searchParams.get('due')) ? searchParams.get('due') : '';
  const type = TYPE_VALUES.has(searchParams.get('type')) ? searchParams.get('type') : '';

  useEffect(() => {
    let active = true;
    setPending(true);

    const params = { page, page_size: PAGE_SIZE };
    if (due) params.due = due;
    if (type) params.type = type;

    api
      .get(BDE_FOLLOW_UPS_URL, { params })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, 'Could not load your follow-ups.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });

    return () => {
      active = false;
    };
  }, [page, due, type, reloadKey]);

  const retry = () => setReloadKey((key) => key + 1);
  const changed = (message) => {
    setNotice(message);
    retry();
  };
  const from = { to: `${location.pathname}${location.search}`, label: 'Follow-ups' };
  const summary = data?.summary;
  const dueLabel = FOLLOW_UP_DUE.find((option) => option.value === due)?.label;

  let content;
  if (failure?.status === 403) {
    content = (
      <AccessDeniedState
        title={failure.code === 'NOT_A_BDE' ? 'Follow-ups belong to BDE accounts.' : "You don't have access to follow-ups."}
        message={failure.message}
      />
    );
  } else {
    const rows = data?.results ?? [];
    const total = data?.count ?? 0;
    let list;
    if (!data && !failure) {
      list = <TableSkeleton columns={5} toolbar={false} />;
    } else if (!data) {
      list = <ErrorState message={failure.message} onRetry={retry} pending={pending} />;
    } else {
      list = (
        <>
          {failure ? <ErrorState message={failure.message} onRetry={retry} pending={pending} /> : null}
          {rows.length ? (
            <FollowUpList rows={rows} pending={pending} from={from} onChanged={changed} />
          ) : total > 0 ? (
            <EmptyState
              icon={SearchXIcon}
              title="Nothing on this page"
              description="This page is past the last one."
              action={
                <Button variant="outline" onClick={() => update({ page: null })}>
                  Go to the first page
                </Button>
              }
            />
          ) : due || type ? (
            <EmptyState
              icon={CheckCircle2Icon}
              title={`No ${dueLabel ? dueLabel.toLowerCase() : 'matching'} follow-ups`}
              description="Nothing to follow up here right now."
              action={
                <Button variant="outline" onClick={clear}>
                  Show every follow-up
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={CheckCircle2Icon}
              title="You're all caught up"
              description="Reminders appear here when an enquiry is assigned to you, a class is coming up, a tutor submits a report or a Re-Demo is scheduled."
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
        <Tabs value={due || ALL} onValueChange={(value) => update({ due: value === ALL ? null : value })}>
          <TabsList aria-label="Follow-ups by when they are due">
            <TabsTrigger value={ALL}>
              All open
              <TabsCount value={summary?.total} />
            </TabsTrigger>
            {FOLLOW_UP_DUE.map((option) => (
              <TabsTrigger key={option.value} value={option.value}>
                {option.label}
                <TabsCount value={summary?.[option.value]} />
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <ListToolbar active={Boolean(type)} onClear={() => update({ type: null })}>
          <FilterSelect
            label="Filter by type"
            placeholder="Every type"
            value={type}
            onChange={(value) => update({ type: value || null })}
            options={FOLLOW_UP_TYPES}
          />
        </ListToolbar>
        {notice ? (
          <p role="status" className="bg-success/10 text-success rounded-md px-3 py-2 text-sm">
            {notice}
          </p>
        ) : null}
        {list}
      </div>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Follow-ups"
        description="Reminders for what needs your attention now, soonest first, in Indian time (IST). Each leaves once it is done or its time is up."
      />
      {content}
    </Page>
  );
}
