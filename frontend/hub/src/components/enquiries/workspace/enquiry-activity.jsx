import { useEffect, useState } from 'react';
import { History } from 'lucide-react';

import api from '@/lib/api';
import { enquiryError } from '@/lib/enquiries';
import { BDE_ACTIVITY_URL } from '@/lib/follow-ups';
import { Skeleton } from '@/components/ui/skeleton';
import { ActivityFeed } from '@/components/enquiries/activity-feed';
import { EmptyState } from '@/components/page/page';
import { ErrorState } from '@/components/page/states';

// One enquiry's bookings make few events: the latest page is enough here; the Activity page has the rest.
const PAGE_SIZE = 50;

/**
 * What has happened to this enquiry's bookings, newest first, a day at a time
 * in Indian time -- never who else acted, nor why. Read when the tab opens.
 */
export function EnquiryActivity({ enquiryId }) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(BDE_ACTIVITY_URL, { params: { enquiry: enquiryId, page_size: PAGE_SIZE } })
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, "Could not load this enquiry's activity."));
      });
    return () => {
      active = false;
    };
  }, [enquiryId, reloadKey]);

  if (failure && !data) return <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  if (!data) return <Skeleton className="h-40 rounded-xl" aria-busy="true" />;
  if (!data.results.length) {
    return (
      <EmptyState
        icon={History}
        title="No activity yet"
        description="Bookings made for this enquiry, and everything that happens to them, appear here."
      />
    );
  }
  return <ActivityFeed rows={data.results} inEnquiry />;
}
