import { useEffect, useState } from 'react';
import { CheckCircle2Icon, PhoneCallIcon } from 'lucide-react';

import api from '@/lib/api';
import { enquiryError } from '@/lib/enquiries';
import { BDE_FOLLOW_UPS_URL } from '@/lib/follow-ups';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { FollowUpList } from '@/components/enquiries/follow-up-list';
import { ErrorState } from '@/components/page/states';

// One enquiry has a handful of bookings and reminders: one page holds them all.
const PAGE_SIZE = 50;

/**
 * The enquiry's reminders -- what needs the BDE now, soonest due first, each
 * done here or opening its booking's communication in the workspace (`from`
 * is the workspace's own way back, kept as the sheet opens). Read when the
 * tab opens, and again after an action. What is over is the enquiry's own:
 * its status, its bookings and their communication.
 */
export function EnquiryFollowUps({ enquiryId, from }) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);

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

  const retry = () => setReloadKey((key) => key + 1);
  const changed = (message) => {
    setNotice(message);
    retry();
  };

  let content;
  if (failure && !data) {
    content = <ErrorState message={failure.message} onRetry={retry} />;
  } else if (!data) {
    content = <Skeleton className="h-32 rounded-xl" aria-busy="true" />;
  } else if (!data.results.length) {
    content = (
      <PanelEmpty
        icon={CheckCircle2Icon}
        message="Nothing to follow up"
        hint="Reminders for calls, confirmations and tutor reports on this enquiry appear here."
      />
    );
  } else {
    content = <FollowUpList rows={data.results} inEnquiry from={from} onChanged={changed} />;
  }

  const summary = data?.summary;
  return (
    <Panel
      icon={PhoneCallIcon}
      title="Follow-ups"
      subtitle={
        summary && summary.total
          ? `${summary.today} due today · ${summary.upcoming} upcoming · Indian time (IST)`
          : 'What this enquiry needs from you now, in Indian time (IST)'
      }
    >
      <div className="flex flex-col gap-3">
        {notice ? (
          <p role="status" className="bg-success/10 text-success rounded-md px-3 py-2 text-sm">
            {notice}
          </p>
        ) : null}
        {content}
      </div>
    </Panel>
  );
}
