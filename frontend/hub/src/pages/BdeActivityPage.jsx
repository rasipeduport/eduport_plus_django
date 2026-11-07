import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { History } from 'lucide-react';

import api from '@/lib/api';
import { enquiryError } from '@/lib/enquiries';
import { BDE_ACTIVITY_URL } from '@/lib/follow-ups';
import { useListParams } from '@/hooks/use-list-params';
import { Skeleton } from '@/components/ui/skeleton';
import { ActivityFeed } from '@/components/enquiries/activity-feed';
import { EmptyState, Page, PageHeader } from '@/components/page/page';
import { Pagination } from '@/components/page/pagination';
import { AccessDeniedState, ErrorState } from '@/components/page/states';

const PAGE_SIZE = 30;

/**
 * A BDE's activity: what has happened to their own enquiries' bookings, newest
 * first and a day at a time in Indian time, from GET /api/bde/activity/ --
 * booked, tutor assigned, started, moved, cancelled, completed, the parent's
 * answer, a report updated -- and whether it was the BDE's own doing. Never
 * who else acted, nor why: the API keeps that with the administrators. Each
 * opens its booking in the enquiry's workspace; the way back returns here.
 * The page is kept in the URL (page). The staff activity log (ActivityPage) is
 * not the BDE's to read.
 */
export default function BdeActivityPage() {
  const location = useLocation();
  const { searchParams, update } = useListParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);

  useEffect(() => {
    let active = true;
    setPending(true);
    api
      .get(BDE_ACTIVITY_URL, { params: { page, page_size: PAGE_SIZE } })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, 'Could not load your activity.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [page, reloadKey]);

  const retry = () => setReloadKey((key) => key + 1);
  const rows = data?.results ?? [];
  const total = data?.count ?? 0;

  let content;
  if (failure?.status === 403) {
    content = (
      <AccessDeniedState
        title={failure.code === 'NOT_A_BDE' ? 'Activity here belongs to BDE accounts.' : "You don't have access to this activity."}
        message={failure.message}
      />
    );
  } else if (!data && !failure) {
    content = (
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-48 rounded-xl" />
      </div>
    );
  } else if (!data) {
    content = <ErrorState message={failure.message} onRetry={retry} pending={pending} />;
  } else {
    content = (
      <>
        {failure ? <ErrorState message={failure.message} onRetry={retry} pending={pending} /> : null}
        {rows.length ? (
          <div className={pending ? 'opacity-60' : undefined}>
            <ActivityFeed rows={rows} from={{ to: `${location.pathname}${location.search}`, label: 'Activity' }} />
          </div>
        ) : (
          <EmptyState
            icon={History}
            title="No activity yet"
            description="Bookings made for your enquiries, and everything that happens to them, appear here."
          />
        )}
        {total > PAGE_SIZE ? (
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

  return (
    <Page>
      <PageHeader
        title="Activity"
        description="What has happened to your enquiries' bookings, newest first, in Indian time (IST)."
      />
      {content}
    </Page>
  );
}
