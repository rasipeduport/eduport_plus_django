import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeftIcon, CalendarClockIcon, HistoryIcon, LayoutDashboardIcon, ListOrderedIcon, SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import {
  bookingError,
  bookingPagePath,
  bookingStudentHistoryUrl,
  bookingUrl,
  cancelReasonLabel,
  redemoCloseUrl,
  redemoListPath,
  redemoPagePath,
  redemoReopenUrl,
  redemoUrl,
} from '@/lib/bookings';
import { slotLabel } from '@/lib/enquiries';
import { useHistory } from '@/hooks/use-history';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AssignTutorDialog } from '@/components/bookings/assign-tutor-dialog';
import { CancelBookingDialog } from '@/components/bookings/cancel-booking-dialog';
import { RedemoCloseDialog } from '@/components/bookings/redemo-close-dialog';
import { RescheduleBookingDialog } from '@/components/bookings/reschedule-booking-dialog';
import { RedemoActionBar } from '@/components/bookings/redemo-workspace/redemo-action-bar';
import { RedemoAttempts } from '@/components/bookings/redemo-workspace/redemo-attempts';
import { RedemoHeader, RedemoProgress } from '@/components/bookings/redemo-workspace/redemo-header';
import { RedemoOverview } from '@/components/bookings/redemo-workspace/redemo-overview';
import { RedemoScheduler } from '@/components/bookings/redemo-workspace/redemo-scheduler';
import { RedemoSidePanel } from '@/components/bookings/redemo-workspace/redemo-side-panel';
import { HistoryTimeline } from '@/components/history/history-timeline';
import { EmptyState, Page } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';

const TABS = [
  { key: 'overview', label: 'Overview', icon: LayoutDashboardIcon },
  { key: 'scheduling', label: 'Scheduling', icon: CalendarClockIcon },
  { key: 'history', label: 'History', icon: HistoryIcon },
  { key: 'attempts', label: 'Attempts', icon: ListOrderedIcon },
];

function WorkspaceSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <Skeleton className="h-36 rounded-xl" />
      <Skeleton className="h-24 rounded-xl" />
      <Skeleton className="h-9 w-full max-w-md" />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Skeleton className="h-80 rounded-xl" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
    </div>
  );
}

/**
 * One Re-Demo request in full (GET /api/bookings/redemos/<id>/), for
 * administrators -- a page of its own, where the request's side sheet used
 * to be:
 *
 *   header        the student, class and syllabus, the request's status and
 *                 which Re-Demo it is, its BDE and when it was asked for, and
 *                 the Demo it repeats (IST and the student's time) with that
 *                 Demo's report as a PDF; then where it has got to (the API's
 *                 `progress`)
 *   Overview      the request and its reason, the original Demo and its
 *                 report, the Re-Demo as it stands, the remarks for its tutor
 *   Scheduling    By time / By tutor on the student's clock beside IST, while
 *                 the API allows it (`actions.schedule`)
 *   History       the student's History (backend bookings.timeline), every
 *                 booking shown first
 *   Attempts      the original Demo and each Re-Demo booked for the request,
 *                 oldest first, and the lead's other Re-Demo requests
 *
 * Beside them the student, the parent and the quick actions (the parent's
 * WhatsApp text, the original report's PDF); under them a sticky bar of what
 * may be done now (RedemoActionBar). Every rule is the API's; the tab is kept
 * in the URL (?tab=), and the way back is where it was opened from
 * (location.state.from), else the Re-Demo requests with this one highlighted.
 */
export default function RedemoWorkspacePage({ user }) {
  const { redemoId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const canChangeTutor = can(user, PERMISSIONS.assignBookingTutor);
  const back = location.state?.from ?? { to: redemoListPath(redemoId), label: 'Re-Demo requests' };
  const tabsRef = useRef(null);

  const [redemo, setRedemo] = useState(null);
  const [failure, setFailure] = useState(null);
  // reloadKey reads the request again; historyKey its History, after any change.
  const [reloadKey, setReloadKey] = useState(0);
  const [historyKey, setHistoryKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const [closing, setClosing] = useState(null);
  // The dialog last opened ('close' or 'reopen'): kept while it animates closed, so it never turns into the other.
  const [lastClosing, setLastClosing] = useState(null);
  const [acting, setActing] = useState(null);

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(redemoUrl(redemoId))
      .then((response) => {
        if (active) setRedemo(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load this Re-Demo request.'));
      });
    return () => {
      active = false;
    };
  }, [redemoId, reloadKey]);

  // Nothing of another request shows while this one loads.
  const shown = redemo && redemo.id === redemoId ? redemo : null;

  const tab = TABS.some((entry) => entry.key === searchParams.get('tab')) ? searchParams.get('tab') : 'overview';
  const setTab = (next) => {
    const params = new URLSearchParams(searchParams);
    if (next === 'overview') params.delete('tab');
    else params.set('tab', next);
    setSearchParams(params, { replace: true, state: location.state });
  };
  // Read only while its tab is open.
  const history = useHistory(
    tab === 'history' && shown ? bookingStudentHistoryUrl('DEMO', shown.original.id) : null,
    `${reloadKey}|${historyKey}`
  );

  // A write answers the request in full: shown as it comes, its History read again.
  const updated = (next, message) => {
    setRedemo(next);
    setHistoryKey((key) => key + 1);
    if (message) setNotice(message);
  };
  // A change to its booking: the request read again.
  const changed = (message) => {
    setNotice(message);
    setReloadKey((key) => key + 1);
  };
  const openClosing = (mode) => {
    setClosing(mode);
    setLastClosing(mode);
  };
  const shownClosing = closing ?? lastClosing;

  // A booking of the request opens in its own workspace; back comes here, on the same tab.
  const here = { to: `${location.pathname}${location.search}`, label: `${shown?.student_name ?? 'The'}'s Re-Demo request` };
  const openBooking = (id) => navigate(bookingPagePath('DEMO', id), { state: { from: here } });
  // Another request of the chain, with the same way back as this one.
  const openRedemo = (id) => navigate(redemoPagePath(id), { state: location.state });
  // The Re-Demo booked for the request: its full booking for the dialog that changes it.
  const actOn = (action, bookingId) => {
    api
      .get(bookingUrl('DEMO', bookingId))
      .then((response) => setActing({ action, booking: response.data }))
      .catch((err) => setNotice(bookingError(err, 'Could not load the Re-Demo booking.').message));
  };
  const closeActing = (open) => {
    if (!open) setActing(null);
  };
  const toScheduling = () => {
    setTab('scheduling');
    tabsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  let content;
  if (failure && failure.status === 404) {
    content = (
      <EmptyState
        icon={SearchXIcon}
        title="Re-Demo request not found"
        description="It may be a mistyped link, or a request that does not exist."
        action={
          <Button variant="outline" asChild>
            <Link to={redemoListPath()}>Go to Re-Demo requests</Link>
          </Button>
        }
      />
    );
  } else if (failure && failure.status === 403) {
    content = <AccessDeniedState title="You don't have access to Re-Demo requests." message={failure.message} />;
  } else if (failure && !shown) {
    content = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  } else if (!shown) {
    content = <WorkspaceSkeleton />;
  } else {
    content = (
      <>
        {failure ? <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} /> : null}
        <RedemoHeader redemo={shown} />
        <RedemoProgress steps={shown.progress} />

        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem] xl:grid-cols-[minmax(0,1fr)_22rem]">
          <Tabs ref={tabsRef} value={tab} onValueChange={setTab} className="min-w-0 scroll-mt-20">
            <TabsList>
              {TABS.map(({ key, label, icon: Icon }) => (
                <TabsTrigger key={key} value={key}>
                  <Icon className="size-4" aria-hidden="true" />
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>

            <TabsContent value="overview">
              <RedemoOverview
                redemo={shown}
                onSaved={(next) => updated(next)}
                onOpenBooking={openBooking}
              />
            </TabsContent>

            <TabsContent value="scheduling">
              <RedemoScheduler
                redemo={shown}
                onScheduled={(next) =>
                  updated(
                    next,
                    `${next.student_name}'s Re-Demo is booked with ${next.tutor?.full_name} on ${slotLabel(next.booking?.slot)}. The BDE tells the parent.`
                  )
                }
              />
            </TabsContent>

            <TabsContent value="history">
              <HistoryTimeline
                state={history}
                allByDefault
                subtitle="Every change to this student's bookings: the original Demo, its Re-Demos and the rest."
              />
            </TabsContent>

            <TabsContent value="attempts">
              <RedemoAttempts redemo={shown} onOpenBooking={openBooking} onOpenRedemo={openRedemo} />
            </TabsContent>
          </Tabs>

          <aside className="min-w-0 lg:pt-[3.875rem]" aria-label="Student and quick actions">
            <RedemoSidePanel redemo={shown} user={user} onDetailsSaved={(_lead, message) => changed(message)} />
          </aside>
        </div>

        <RedemoActionBar
          redemo={shown}
          tab={tab}
          canChangeTutor={canChangeTutor}
          onSchedule={toScheduling}
          onClose={() => openClosing('close')}
          onReopen={() => openClosing('reopen')}
          onBookingAction={actOn}
        />
      </>
    );
  }

  return (
    <Page>
      <Button variant="ghost" size="sm" className="text-muted-foreground -ml-2 self-start" asChild>
        <Link to={back.to}>
          <ArrowLeftIcon className="size-4" />
          {back.label}
        </Link>
      </Button>
      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}
      {content}

      <RedemoCloseDialog
        mode={shownClosing ?? 'close'}
        subject={shown ? `${shown.student_name} · Re-Demo of the Demo on ${slotLabel(shown.original?.slot)}` : null}
        open={Boolean(closing)}
        onOpenChange={(open) => {
          if (!open) setClosing(null);
        }}
        url={shown ? (shownClosing === 'reopen' ? redemoReopenUrl : redemoCloseUrl)(shown.id) : ''}
        // Refused (booked or closed meanwhile): read the request again, as it is now.
        onRefused={() => setReloadKey((key) => key + 1)}
        onDone={(next) =>
          updated(
            next,
            next.status === 'CLOSED'
              ? `Closed ${next.student_name}'s Re-Demo request (${next.closed?.reason?.label}). Its Demo reads Completed again.`
              : `Reopened ${next.student_name}'s Re-Demo request. It is waiting to be scheduled.`
          )
        }
      />

      <RescheduleBookingDialog
        booking={acting?.action === 'reschedule' ? acting.booking : null}
        open={acting?.action === 'reschedule'}
        onOpenChange={closeActing}
        onRescheduled={({ booking: replacement }) =>
          changed(`Moved ${replacement.student_name}'s Re-Demo to ${slotLabel(replacement.slot)}.`)
        }
      />
      {canChangeTutor ? (
        <AssignTutorDialog
          booking={acting?.action === 'change_tutor' ? acting.booking : null}
          open={acting?.action === 'change_tutor'}
          onOpenChange={closeActing}
          onAssigned={(next) => changed(`${next.tutor?.full_name} now teaches ${next.student_name}'s Re-Demo.`)}
        />
      ) : null}
      <CancelBookingDialog
        booking={acting?.action === 'cancel' ? acting.booking : null}
        open={acting?.action === 'cancel'}
        onOpenChange={closeActing}
        onCancelled={(next) =>
          changed(
            `Cancelled ${next.student_name}'s Re-Demo (${cancelReasonLabel(next.cancel_reason_code)}). The request waits to be scheduled again.`
          )
        }
      />
    </Page>
  );
}
