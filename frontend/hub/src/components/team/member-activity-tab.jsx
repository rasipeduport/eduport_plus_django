import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { ActivityList } from '@/components/activity/activity-list';
import { EmptyState, SectionHeading, TabSkeleton } from '@/components/students/profile/profile-primitives';
import api from '@/lib/api';
import { teamError } from '@/lib/team';

const PAGE_SIZE = 25;

/**
 * Activity Log tab of /team/:memberId: one account's history, newest first --
 * what they did, and every change made to their account (role, password,
 * permissions, deactivation). Read from the activity log's own endpoint with
 * ?subject=, so the rows are exactly this account's and the log's access rules
 * still apply.
 */
export function MemberActivityTab({ memberId, memberName, refreshKey }) {
  const [rows, setRows] = useState(null);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(
    async (nextPage) => {
      setPending(true);
      setError('');
      try {
        const res = await api.get('/api/activity/', {
          params: { subject: memberId, page: nextPage, page_size: PAGE_SIZE },
        });
        const results = res.data.results ?? [];
        setCount(res.data.count ?? results.length);
        setRows((current) => (nextPage === 1 ? results : [...(current ?? []), ...results]));
        setPage(nextPage);
      } catch (err) {
        setError(teamError(err, 'Could not load the activity log.').message);
      } finally {
        setPending(false);
      }
    },
    [memberId]
  );

  useEffect(() => {
    load(1);
  }, [load, refreshKey]);

  if (rows === null) {
    if (!error) return <TabSkeleton rows={6} />;
    return (
      <div className="rounded-xl border px-6 py-12 text-center">
        <p className="text-destructive text-sm">{error}</p>
        <Button variant="outline" className="mt-4" onClick={() => load(1)} disabled={pending}>
          Try again
        </Button>
      </div>
    );
  }

  const hasMore = rows.length < count;

  return (
    <div className="flex flex-col gap-4">
      <SectionHeading
        title={`${count} ${count === 1 ? 'entry' : 'entries'}`}
        description={`What ${memberName} did, and every change made to their account.`}
      />
      {rows.length === 0 ? (
        <EmptyState message="No activity recorded for this account yet." />
      ) : (
        <>
          <ActivityList rows={rows} />
          {hasMore ? (
            <Button variant="outline" className="w-fit" disabled={pending} onClick={() => load(page + 1)}>
              {pending ? 'Loading…' : `Load ${Math.min(PAGE_SIZE, count - rows.length)} more`}
            </Button>
          ) : null}
        </>
      )}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </div>
  );
}
