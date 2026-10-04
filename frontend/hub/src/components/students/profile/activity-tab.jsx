import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { ActivityList } from '@/components/activity/activity-list';
import api from '@/lib/api';
import { EmptyState, SectionHeading, TabSkeleton } from './profile-primitives';

const PAGE_SIZE = 25;

/**
 * Activity tab: everything that has been done to this student and their
 * classes, newest first. Reads the activity log's own endpoint, which already
 * pins a mentor or tutor to the entries they wrote themselves — so this panel
 * is the student's full history for an admin and the caller's own history for
 * everyone else, exactly as /activity is.
 */
export function ActivityTab({ studentId, role }) {
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
          params: { student_id: studentId, page: nextPage, page_size: PAGE_SIZE },
        });
        const results = res.data.results ?? [];
        setCount(res.data.count ?? results.length);
        setRows((current) => (nextPage === 1 ? results : [...(current ?? []), ...results]));
        setPage(nextPage);
      } catch {
        setError('Failed to load activity.');
        setRows((current) => current ?? []);
      } finally {
        setPending(false);
      }
    },
    [studentId]
  );

  useEffect(() => {
    load(1);
  }, [load]);

  if (rows === null) return <TabSkeleton rows={6} />;

  const hasMore = rows.length < count;

  return (
    <div className="flex flex-col gap-4">
      <SectionHeading
        title={`${count} ${count === 1 ? 'entry' : 'entries'}`}
        description={
          role === 'admin'
            ? 'Every change to this student, their classes, exams and homework.'
            : 'The changes you have made to this student and their classes.'
        }
      />
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      {rows.length === 0 ? (
        <EmptyState message="No activity recorded yet." />
      ) : (
        <>
          <ActivityList rows={rows} emptyMessage="No activity recorded yet." />
          {hasMore ? (
            <Button variant="outline" className="w-fit" disabled={pending} onClick={() => load(page + 1)}>
              {pending ? 'Loading…' : `Load ${Math.min(PAGE_SIZE, count - rows.length)} more`}
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}
