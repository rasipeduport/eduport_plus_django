import { useEffect, useState } from 'react';
import { CheckCircle2Icon, HistoryIcon, PhoneCallIcon } from 'lucide-react';

import api from '@/lib/api';
import { enquiryError } from '@/lib/enquiries';
import { BDE_FOLLOW_UPS_URL } from '@/lib/follow-ups';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { FollowUpHistory, FollowUpList } from '@/components/enquiries/follow-up-list';
import { ErrorState } from '@/components/page/states';

// One enquiry has a handful of bookings and follow-ups: one page holds them all.
const PAGE_SIZE = 50;

/** One enquiry's open follow-ups, or those that are over (`state` closed), read again on `reloadKey`. */
function useEnquiryFollowUps(enquiryId, state, reloadKey) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(BDE_FOLLOW_UPS_URL, { params: { enquiry: enquiryId, state, page_size: PAGE_SIZE } })
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, "Could not load this enquiry's follow-ups."));
      });
    return () => {
      active = false;
    };
  }, [enquiryId, state, reloadKey]);

  return { data, failure };
}

/**
 * The enquiry's follow-ups: what is still to do -- soonest due first, each done
 * here or opening its booking's communication in the workspace (`from` is the
 * workspace's own way back, kept as the sheet opens) -- and, under it, what is
 * over, Completed or Missed. Read when the tab opens, and again after an action.
 */
export function EnquiryFollowUps({ enquiryId, from }) {
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const open = useEnquiryFollowUps(enquiryId, 'open', reloadKey);
  const closed = useEnquiryFollowUps(enquiryId, 'closed', reloadKey);
  const retry = () => setReloadKey((key) => key + 1);
  const changed = (message) => {
    setNotice(message);
    retry();
  };

  let content;
  if (open.failure && !open.data) {
    content = <ErrorState message={open.failure.message} onRetry={retry} />;
  } else if (!open.data) {
    content = <Skeleton className="h-32 rounded-xl" aria-busy="true" />;
  } else if (!open.data.results.length) {
    content = (
      <PanelEmpty
        icon={CheckCircle2Icon}
        message="Nothing to follow up"
        hint="Calls, confirmations and tutor reports this enquiry needs from you appear here."
      />
    );
  } else {
    content = <FollowUpList rows={open.data.results} inEnquiry from={from} onChanged={changed} />;
  }

  const summary = open.data?.summary;
  const history = closed.data?.results ?? [];
  return (
    <div className="flex flex-col gap-6">
      <Panel
        icon={PhoneCallIcon}
        title="Follow-ups"
        subtitle={
          summary && summary.total
            ? `${summary.overdue} overdue · ${summary.today} due today · ${summary.upcoming} upcoming · Indian time (IST)`
            : 'What this enquiry needs from you next, in Indian time (IST)'
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
      {history.length || closed.failure ? (
        <Panel icon={HistoryIcon} title="History" subtitle="Follow-ups completed or missed, newest first">
          {closed.failure ? <ErrorState message={closed.failure.message} onRetry={retry} /> : <FollowUpHistory rows={history} />}
        </Panel>
      ) : null}
    </div>
  );
}
