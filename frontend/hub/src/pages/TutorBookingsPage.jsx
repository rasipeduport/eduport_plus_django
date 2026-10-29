import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RefreshCwIcon, ShieldAlertIcon } from 'lucide-react';

import api from '@/lib/api';
import { TUTOR_BOOKINGS_URL, bookingError, readTutorFilters, tutorListParams } from '@/lib/bookings';
import { Button } from '@/components/ui/button';
import { TableSkeleton } from '@/components/table-skeleton';
import { TutorBookingList } from '@/components/bookings/tutor-booking-list';
import { TutorBookingSheet } from '@/components/bookings/tutor-booking-sheet';

const PAGE_SIZE = 25;

function AccessDenied({ failure }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
      <ShieldAlertIcon className="text-muted-foreground size-8" />
      <p className="font-medium">You don&apos;t have access to My Bookings.</p>
      <p className="text-muted-foreground max-w-md text-sm">{failure.message}</p>
    </div>
  );
}

/**
 * My Bookings for tutors: the Demo and Diagnostic bookings the caller is
 * assigned to teach (GET /api/tutor/bookings/), filtered and paged by the
 * API, each opened read-only in a side sheet (?booking=<id>). Opens for the
 * TUTOR role holding accounts.view_assigned_bookings (lib/access). The API
 * serves only the caller's own bookings, with the child and the slot and
 * nothing of the parent, the BDE or the assignment; tutors are assigned on
 * the administrators' Bookings page, never here.
 */
export default function TutorBookingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const filters = readTutorFilters(searchParams);
  const { type, when } = filters;
  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const openId = searchParams.get('booking');

  useEffect(() => {
    let active = true;
    setPending(true);
    api
      .get(TUTOR_BOOKINGS_URL, { params: tutorListParams({ type, when }, page, PAGE_SIZE) })
      .then((response) => {
        if (!active) return;
        setData(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load your bookings.'));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
  }, [type, when, page, reloadKey]);

  const reload = () => setReloadKey((key) => key + 1);

  const update = (updates) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === '') params.delete(key);
      else params.set(key, value);
    }
    // Any filter change (anything but paging or the open booking) starts again at page 1.
    if (!('page' in updates) && !('booking' in updates)) params.delete('page');
    setSearchParams(params);
  };

  let content;
  if (failure?.status === 403) {
    content = <AccessDenied failure={failure} />;
  } else if (!data && !failure) {
    content = <TableSkeleton columns={6} />;
  } else if (!data) {
    content = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={reload} disabled={pending}>
          Try again
        </Button>
      </div>
    );
  } else {
    content = (
      <>
        {failure ? (
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <p className="text-destructive text-sm">{failure.message}</p>
            <Button variant="outline" size="sm" onClick={reload} disabled={pending}>
              Try again
            </Button>
          </div>
        ) : null}
        <TutorBookingList
          rows={data.results ?? []}
          total={data.count ?? 0}
          page={page}
          pageSize={PAGE_SIZE}
          filters={filters}
          pending={pending}
          onChange={update}
          onOpen={(id) => update({ booking: id })}
        />
      </>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">My Bookings</h1>
          <p className="text-muted-foreground max-w-3xl text-sm">
            The demo classes and diagnostic tests you are assigned to teach. Times are Indian time (IST).
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={reload} disabled={pending}>
          <RefreshCwIcon />
          Refresh
        </Button>
      </div>

      {content}

      <TutorBookingSheet
        bookingId={openId}
        open={Boolean(openId)}
        onOpenChange={(open) => {
          if (!open) update({ booking: null });
        }}
        reloadKey={reloadKey}
      />
    </div>
  );
}
