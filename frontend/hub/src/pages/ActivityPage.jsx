import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import api from '@/lib/api';
import { Skeleton } from '@/components/ui/skeleton';
import { ActivityFeed } from '@/components/activity/activity-feed';

const PAGE_SIZE = 25;
const FEED_ROWS = Array.from({ length: 10 }, (_, i) => i);

function FeedSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      {FEED_ROWS.map((row) => (
        <div key={row} className="flex items-center gap-3 rounded-md border px-4 py-3">
          <Skeleton className="size-8 shrink-0 rounded-full" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-24 shrink-0" />
        </div>
      ))}
    </div>
  );
}

export default function ActivityPage() {
  const [searchParams] = useSearchParams();
  const [data, setData] = useState({ results: [], count: 0, actor_options: [] });
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const getStr = useCallback((key) => searchParams.get(key) ?? '', [searchParams]);

  const page = Math.max(1, parseInt(getStr('page') || '1', 10) || 1);
  const action = getStr('action');
  const entity = getStr('entity');
  const actor = getStr('actor');
  const q = getStr('q').trim();
  const from = getStr('from');
  const to = getStr('to');

  useEffect(() => {
    let active = true;
    setPending(true);
    setError('');

    // Only the filters the API understands; blank ones are left off entirely.
    const params = { page, page_size: PAGE_SIZE };
    if (action) params.action = action;
    if (entity) params.entity = entity;
    if (actor) params.actor = actor;
    if (q) params.q = q;
    if (from) params.from = from;
    if (to) params.to = to;

    api
      .get('/api/activity/', { params })
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setError(err.response?.data?.message || 'Failed to load the activity log.');
      })
      .finally(() => {
        if (active) {
          setLoading(false);
          setPending(false);
        }
      });

    return () => {
      active = false;
    };
  }, [page, action, entity, actor, q, from, to]);

  return (
    <div className="container mx-auto px-4 py-16">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Activity log</h1>
        <p className="text-muted-foreground text-sm">
          A record of who changed what across students, sessions, invitations, and users.
        </p>
      </div>

      {error && <p className="text-destructive mb-4 text-sm">{error}</p>}

      {loading ? (
        <FeedSkeleton />
      ) : (
        <ActivityFeed
          rows={data.results ?? []}
          total={data.count ?? 0}
          page={page}
          pageSize={PAGE_SIZE}
          actorOptions={data.actor_options ?? []}
          filters={{ q, action, entity, actor, from, to }}
          pending={pending}
        />
      )}
    </div>
  );
}
