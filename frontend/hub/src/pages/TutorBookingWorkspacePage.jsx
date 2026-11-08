import { useEffect, useState } from 'react';
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeftIcon, SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { bookingError, tutorBookingNotesUrl, tutorBookingPagePath, tutorBookingUrl, tutorBookingsPagePath } from '@/lib/bookings';
import { istMoment } from '@/lib/communications';
import { bookingTypeLabel } from '@/lib/enquiries';
import { reportWords } from '@/lib/reports';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TutorBookingActivity } from '@/components/bookings/tutor-workspace/tutor-booking-activity';
import { TutorBookingHeader } from '@/components/bookings/tutor-workspace/tutor-booking-header';
import { TutorBookingOverview } from '@/components/bookings/tutor-workspace/tutor-booking-overview';
import { TutorBookingSession } from '@/components/bookings/tutor-workspace/tutor-booking-session';
import { TutorFeedbackPanel } from '@/components/bookings/tutor-workspace/tutor-feedback-panel';
import { LeadNotes } from '@/components/notes/lead-notes';
import { EmptyState, Page } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';

const LISTS = { DEMO: 'Demo Bookings', DIAGNOSTIC: 'Diagnostic Bookings' };

function WorkspaceSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <Skeleton className="h-14 w-96 max-w-full" />
      <Skeleton className="h-9 w-full max-w-xl" />
      <Skeleton className="h-16 rounded-xl" />
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-48 rounded-xl" />
        <Skeleton className="h-48 rounded-xl" />
        <Skeleton className="h-48 rounded-xl" />
      </div>
    </div>
  );
}

/**
 * One Demo or Diagnostic booking (`type`) assigned to the signed-in tutor, in
 * a workspace of its own -- laid out as the other roles' booking workspaces
 * are, holding only what the tutor teaches with:
 *
 *   Overview            what the class needs now, the parent (the country only),
 *                       the student and the enquiry, the enquiry's journey, and
 *                       for a Re-Demo why it is taught again
 *   Bookings            the class to join and teach: when (IST), type, status,
 *                       Join Meet and the action it takes now -- Start, then
 *                       its feedback or results
 *   Feedback / Results  the report once in, as it prints, with its PDF and every
 *                       version; else why it cannot be written yet
 *   Notes               the enquiry's notes, shared with its BDE and the administrators
 *   Activity            the booking as it has gone: the slot, the start, each version
 *
 * The header joins the Meet room, starts the class (which opens Meet and
 * records the start its report needs) and opens the report page to write or
 * edit it. Every rule is the API's (GET /api/tutor/bookings/<type>/<id>/ and
 * the routes under it): a booking not assigned to the caller is answered as
 * one that does not exist, and nothing of the parent is sent. The tab is
 * kept in the URL (?tab=); the way back is the list it was opened from
 * (location.state.from), else its type's list.
 */
export default function TutorBookingWorkspacePage({ type }) {
  const { bookingId } = useParams();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const words = reportWords(type);
  const back = location.state?.from ?? { to: tutorBookingsPagePath(type), label: LISTS[type] };

  const [booking, setBooking] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);

  const reload = () => setReloadKey((key) => key + 1);

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(tutorBookingUrl(type, bookingId))
      .then((response) => {
        if (active) setBooking(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, 'Could not load this booking.'));
      });
    return () => {
      active = false;
    };
  }, [type, bookingId, reloadKey]);

  const tabs = [
    { key: 'overview', label: 'Overview' },
    { key: 'session', label: 'Bookings' },
    { key: 'feedback', label: words.tab },
    { key: 'notes', label: 'Notes' },
    { key: 'activity', label: 'Activity' },
  ];
  const requested = searchParams.get('tab');
  const tab = tabs.some((entry) => entry.key === requested) ? requested : 'overview';
  const setTab = (next) => {
    const params = new URLSearchParams(searchParams);
    if (next === 'overview') params.delete('tab');
    else params.set('tab', next);
    setSearchParams(params, { replace: true, state: location.state });
  };

  // Nothing of another booking shows while this one loads.
  const shown = booking && booking.id === bookingId && booking.booking_type === type ? booking : null;

  // Started here: show the booking as the API answered it.
  const started = (updated) => {
    setBooking(updated);
    setNotice(
      `You started the ${bookingTypeLabel(type).toLowerCase()} ${istMoment(updated.started_at) ?? 'now'}. ${words.write} here once you have taught it.`
    );
  };

  // The report page's way back: this booking's feedback tab (its Session tab, from there), with this page's own way back kept.
  const reportStateFor = (backTab) => ({
    from: {
      to: `${tutorBookingPagePath(type, bookingId)}?tab=${backTab}`,
      label: shown ? shown.student_name : 'Booking',
      state: location.state ?? null,
    },
  });
  const reportState = reportStateFor('feedback');
  const sessionReportState = reportStateFor('session');

  // Start opens five minutes before the class (the API's rule, its start_refusal
  // until then): the booking is read again when it opens, so Start shows then.
  // Should this device's clock run ahead of the server's, it is read again every
  // fifteen seconds until the API offers it.
  const startOpensAt = shown?.start_refusal?.code === 'START_TOO_EARLY' ? shown.start_opens_at : null;
  useEffect(() => {
    if (!startOpensAt) return undefined;
    const wait = new Date(startOpensAt).getTime() - Date.now() + 1000;
    // Further off than a timer can wait (about 24 days): read again on the next visit.
    if (!(wait < 2 ** 31)) return undefined;
    const timer = setTimeout(() => setReloadKey((key) => key + 1), wait > 0 ? wait : 15_000);
    return () => clearTimeout(timer);
  }, [startOpensAt, shown]);

  let content;
  if (failure && failure.status === 404) {
    content = (
      <EmptyState
        icon={SearchXIcon}
        title="Booking not found"
        description="It may no longer be assigned to you, or the link may be mistyped."
        action={
          <Button variant="outline" asChild>
            <Link to={tutorBookingsPagePath(type)}>Go to {LISTS[type]}</Link>
          </Button>
        }
      />
    );
  } else if (failure && failure.status === 403) {
    content = <AccessDeniedState title="You don't have access to bookings." message={failure.message} />;
  } else if (failure && !shown) {
    content = <ErrorState message={failure.message} onRetry={reload} />;
  } else if (!shown) {
    content = <WorkspaceSkeleton />;
  } else {
    content = (
      <>
        {failure ? <ErrorState message={failure.message} onRetry={reload} /> : null}
        <TutorBookingHeader booking={shown} onStarted={started} onRefresh={reload} reportState={reportState} />
        <Tabs value={tab} onValueChange={setTab}>
          <div className="max-w-full overflow-x-auto">
            <TabsList>
              {tabs.map((entry) => (
                <TabsTrigger key={entry.key} value={entry.key}>
                  {entry.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          <TabsContent value="overview">
            <TutorBookingOverview
              booking={shown}
              onStarted={started}
              onRefresh={reload}
              reportState={reportState}
            />
          </TabsContent>

          <TabsContent value="session">
            <TutorBookingSession booking={shown} onStarted={started} onRefresh={reload} reportState={sessionReportState} />
          </TabsContent>

          <TabsContent value="feedback">
            <TutorFeedbackPanel
              booking={shown}
              reloadKey={reloadKey}
              onStarted={started}
              onRefresh={reload}
              reportState={reportState}
            />
          </TabsContent>

          <TabsContent value="notes">
            <LeadNotes
              url={tutorBookingNotesUrl(type, shown.id)}
              emptyDescription="Notes the BDE, the administrators and you add to this student's enquiry appear here, oldest first. Its Demo and Diagnostic bookings share them."
              placeholder="Write a note for the BDE and the administrators…"
              loadError="Could not load the notes on this booking."
            />
          </TabsContent>

          <TabsContent value="activity">
            <TutorBookingActivity booking={shown} reloadKey={reloadKey} />
          </TabsContent>
        </Tabs>
      </>
    );
  }

  return (
    <Page>
      <Button variant="ghost" size="sm" className="text-muted-foreground -ml-2 self-start" asChild>
        <Link to={back.to} state={back.state ?? undefined}>
          <ArrowLeftIcon className="size-4" />
          {back.label}
        </Link>
      </Button>
      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}
      {content}
    </Page>
  );
}
