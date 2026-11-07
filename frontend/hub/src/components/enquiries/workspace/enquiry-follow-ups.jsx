import { useEffect, useState } from 'react';
import { CheckCircle2Icon, PhoneCallIcon } from 'lucide-react';

import api from '@/lib/api';
import { enquiryError } from '@/lib/enquiries';
import { BDE_FOLLOW_UPS_URL } from '@/lib/follow-ups';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { FollowUpList } from '@/components/enquiries/follow-up-list';
import { ErrorState } from '@/components/page/states';

// One enquiry has a handful of bookings and five steps each: one page holds them all.
const PAGE_SIZE = 50;

/**
 * The enquiry's open follow-ups -- the steps of its bookings' parent
 * communication still to do -- soonest due first, each opening its booking's
 * communication here in the workspace (`from` is the workspace's own way back,
 * kept as the sheet opens). Read when the tab opens.
 */
export function EnquiryFollowUps({ enquiryId, from }) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(BDE_FOLLOW_UPS_URL, { params: { enquiry: enquiryId, page_size: PAGE_SIZE } })
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, "Could not load this enquiry's follow-ups."));
      });
    return () => {
      active = false;
    };
  }, [enquiryId, reloadKey]);

  let content;
  if (failure && !data) {
    content = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  } else if (!data) {
    content = <Skeleton className="h-32 rounded-xl" aria-busy="true" />;
  } else if (!data.results.length) {
    content = (
      <PanelEmpty
        icon={CheckCircle2Icon}
        message="Nothing to follow up"
        hint="Calls and parent messages due on this enquiry's bookings appear here."
      />
    );
  } else {
    content = <FollowUpList rows={data.results} inEnquiry from={from} />;
  }

  const summary = data?.summary;
  return (
    <Panel
      icon={PhoneCallIcon}
      title="Follow-ups"
      subtitle={
        summary && summary.total
          ? `${summary.overdue} overdue · ${summary.today} due today · ${summary.upcoming} upcoming · Indian time (IST)`
          : 'The open steps of this enquiry’s parent communication, in Indian time (IST)'
      }
    >
      {content}
    </Panel>
  );
}
