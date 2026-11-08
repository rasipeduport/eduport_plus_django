import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeftIcon,
  CalendarClockIcon,
  CalendarX2Icon,
  FileTextIcon,
  HistoryIcon,
  RotateCcwIcon,
  SearchXIcon,
  UserRoundCogIcon,
  UserRoundPlusIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import {
  REDEMO_VIEW,
  bookingDemoInviteUrl,
  bookingError,
  bookingPagePath,
  bookingRedemoUrl,
  bookingUrl,
  bookingsPagePath,
  cancelReasonLabel,
  conducted,
  tutorChangeable,
} from '@/lib/bookings';
import { bookingTypeLabel, enquiryError, slotLabel } from '@/lib/enquiries';
import { leadNotesUrl, leadUrl } from '@/lib/leads';
import { useBookingCommunication } from '@/hooks/use-booking-communication';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Panel } from '@/components/dashboard/dashboard-primitives';
import { AssignTutorDialog } from '@/components/bookings/assign-tutor-dialog';
import { BookingEvents, useBookingHistory } from '@/components/bookings/booking-history';
import { CancelBookingDialog } from '@/components/bookings/cancel-booking-dialog';
import { DemoInviteButton } from '@/components/bookings/demo-invite-button';
import { RequestRedemoDialog } from '@/components/bookings/request-redemo-dialog';
import { RescheduleBookingDialog } from '@/components/bookings/reschedule-booking-dialog';
import { BookingHeader } from '@/components/bookings/workspace/booking-header';
import { BookingOverview } from '@/components/bookings/workspace/booking-overview';
import { BookingsTab } from '@/components/bookings/workspace/bookings-tab';
import { CommunicationSection } from '@/components/communications/communication-section';
import { LeadNotes } from '@/components/notes/lead-notes';
import { EmptyState, Page } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';
import { AdminReportSection } from '@/components/reports/admin-report-section';

const LISTS = { DEMO: 'Demo Bookings', DIAGNOSTIC: 'Diagnostic Bookings' };

function WorkspaceSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <Skeleton className="h-14 w-96 max-w-full" />
      <Skeleton className="h-9 w-full max-w-2xl" />
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-56 rounded-xl" />
        <Skeleton className="h-56 rounded-xl" />
        <Skeleton className="h-56 rounded-xl" />
      </div>
    </div>
  );
}

/**
 * One Demo or Diagnostic booking (`type`) in full, for administrators -- a
 * page of its own, laid out as a BDE's enquiry workspace is, with everything
 * the booking's former side sheet held:
 *
 *   Overview        the parent, the student and the enquiry, then -- for
 *                   holders of accounts.view_all_leads -- the enquiry's
 *                   journey and every booking made for the child (the
 *                   booking's own facts -- its slot in IST, where it stands,
 *                   its start, seat, how it came in, any move, cancellation
 *                   or Re-Demo -- head the page, in BookingHeader)
 *   Bookings        every Demo and Diagnostic booking made for the child, as
 *                   a BDE's enquiry lists them -- when, type, status, the
 *                   parent's confirmation, the tutor and Meet link, when
 *                   booked -- this one highlighted (accounts.view_all_leads)
 *   Communication   the parent's confirmation, the communication workflow
 *                   and every message, call and task, as the BDE's
 *                   communication sheet lays them out, to read only
 *                   (accounts.view_all_communications)
 *   Notes           the enquiry's notes, shared with its BDE and its tutors
 *                   (bookings.LeadNote, accounts.view_all_leads)
 *   Tutor Feedback  its report, read-only, with its PDF and every version
 *   Activity        its whole timeline, the bookings it replaced included
 *
 * The header messages the parent on WhatsApp and offers what the booking allows:
 * one tutor action -- Assign Tutor, or Change Tutor once it has one
 * (accounts.assign_booking_tutor, while the API says its tutor may change) --
 * Reschedule and Cancel booking (the API's actions), Request Re-Demo for a
 * completed Demo and Send Demo Invitation for a Diagnostic whose report is in.
 * Every rule is the API's (GET /api/bookings/<type>/<id>/ and the routes
 * under it); the tab is kept in the URL (?tab=), and the way back is the list
 * it was opened from (location.state.from), else its type's list.
 */
export default function BookingWorkspacePage({ user, type }) {
  const { bookingId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const canAssign = can(user, PERMISSIONS.assignBookingTutor);
  const canViewCommunication = can(user, PERMISSIONS.viewAllCommunications);
  const canViewLead = can(user, PERMISSIONS.viewAllLeads);
  const back = location.state?.from ?? { to: bookingsPagePath(type), label: LISTS[type] };

  const [booking, setBooking] = useState(null);
  const [failure, setFailure] = useState(null);
  const [lead, setLead] = useState(null);
  const [leadFailure, setLeadFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const [assigning, setAssigning] = useState(null);
  const [cancelling, setCancelling] = useState(null);
  const [rescheduling, setRescheduling] = useState(null);
  const [requestingRedemo, setRequestingRedemo] = useState(null);

  const reload = () => setReloadKey((key) => key + 1);
  // After a change: say what happened, and read the booking and everything under it again.
  const changed = (message) => {
    setNotice(message);
    reload();
  };

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(bookingUrl(type, bookingId))
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

  // Nothing of another booking shows while this one loads.
  const shown = booking && booking.id === bookingId && booking.booking_type === type ? booking : null;
  const leadId = shown?.lead?.id ?? null;

  // The enquiry the booking belongs to: its journey and its other bookings.
  useEffect(() => {
    if (!canViewLead || !leadId) return undefined;
    let active = true;
    setLeadFailure(null);
    api
      .get(leadUrl(leadId))
      .then((response) => {
        if (active) setLead(response.data);
      })
      .catch((err) => {
        if (active) setLeadFailure(enquiryError(err, "Could not load this booking's enquiry."));
      });
    return () => {
      active = false;
    };
  }, [canViewLead, leadId, reloadKey]);
  const shownLead = lead && lead.id === leadId ? lead : null;

  const history = useBookingHistory(shown ? type : null, shown?.id, reloadKey);
  const communication = useBookingCommunication(canViewCommunication && shown ? type : null, shown?.id, reloadKey);

  const tabs = [
    { key: 'overview', label: 'Overview' },
    { key: 'bookings', label: 'Bookings' },
    ...(canViewCommunication ? [{ key: 'communication', label: 'Communication' }] : []),
    ...(canViewLead ? [{ key: 'notes', label: 'Notes' }] : []),
    { key: 'feedback', label: 'Tutor Feedback' },
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

  // Another booking of the chain or the child's, in its own workspace, with the same way back.
  const openBooking = (id, bookingType = type) => navigate(bookingPagePath(bookingType, id), { state: location.state });
  const openRedemo = (id) => navigate(`${bookingsPagePath('DEMO')}?${new URLSearchParams({ tab: REDEMO_VIEW, redemo: id })}`);
  const typeOf = (entry) => bookingTypeLabel(entry.booking_type).toLowerCase();

  // A move answers the replacement booking, opened next (Q24: whether the tutor came too).
  const moved = ({ booking: replacement, tutor }) => {
    let tutorNote = '';
    if (tutor?.carried_over) tutorNote = ` ${tutor.tutor.full_name} still teaches it.`;
    else if (tutor?.tutor) tutorNote = ` ${tutor.tutor.full_name} isn't free then, so it needs a tutor.`;
    setNotice(`Moved ${replacement.student_name}'s ${typeOf(replacement)} to ${slotLabel(replacement.slot)}.${tutorNote}`);
    openBooking(replacement.id);
  };

  let content;
  if (failure && failure.status === 404) {
    content = (
      <EmptyState
        icon={SearchXIcon}
        title="Booking not found"
        description={`It may be a mistyped link, or a ${bookingTypeLabel(type).toLowerCase()} booking that does not exist.`}
        action={
          <Button variant="outline" asChild>
            <Link to={bookingsPagePath(type)}>Go to {LISTS[type]}</Link>
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
    const leadBrief = shown.lead ?? {};
    const actions = shown.actions ?? {};
    const tutorChange = canAssign && tutorChangeable(shown);
    const headerActions = [
      tutorChange ? (
        <Button key="tutor" size="sm" onClick={() => setAssigning(shown)}>
          {shown.tutor ? <UserRoundCogIcon /> : <UserRoundPlusIcon />}
          {shown.tutor ? 'Change Tutor' : 'Assign Tutor'}
        </Button>
      ) : null,
      actions.reschedule ? (
        <Button key="reschedule" variant="outline" size="sm" onClick={() => setRescheduling(shown)}>
          <CalendarClockIcon />
          Reschedule
        </Button>
      ) : null,
      // A completed Demo, to be taught again: a reason, shown back, then the request.
      actions.request_redemo ? (
        <Button key="redemo" variant="outline" size="sm" onClick={() => setRequestingRedemo(shown)}>
          <RotateCcwIcon />
          Request Re-Demo
        </Button>
      ) : null,
      // The parent's invitation to book a Demo, from a Diagnostic whose report is in.
      actions.demo_invite ? (
        <DemoInviteButton
          key="invite"
          inviteUrl={bookingDemoInviteUrl(type, shown.id)}
          recipient={{ dialCode: leadBrief.phone_dial_code, number: leadBrief.phone_number }}
          onRefused={reload}
        />
      ) : null,
      actions.cancel ? (
        <Button key="cancel" variant="destructive" size="sm" onClick={() => setCancelling(shown)}>
          <CalendarX2Icon />
          Cancel booking
        </Button>
      ) : null,
    ].filter(Boolean);

    content = (
      <>
        <BookingHeader
          booking={shown}
          actions={headerActions.length ? headerActions : null}
          onOpenBooking={openBooking}
          onOpenRedemo={openRedemo}
        />
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            {tabs.map((entry) => (
              <TabsTrigger key={entry.key} value={entry.key}>
                {entry.label}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="overview">
            <BookingOverview
              booking={shown}
              lead={shownLead}
              leadFailure={leadFailure}
              onRetryLead={reload}
              showLead={canViewLead}
              onOpenBooking={openBooking}
            />
          </TabsContent>

          <TabsContent value="bookings">
            {/* To read only: the booking's tutor is given or changed from the header. */}
            <BookingsTab
              booking={shown}
              lead={shownLead}
              leadFailure={leadFailure}
              onRetryLead={reload}
              showLead={canViewLead}
              showConfirmation={canViewCommunication}
            />
          </TabsContent>

          {canViewCommunication ? (
            <TabsContent value="communication">
              <CommunicationSection state={communication} />
            </TabsContent>
          ) : null}

          {canViewLead ? (
            <TabsContent value="notes">
              <LeadNotes
                url={leadNotesUrl(leadBrief.id)}
                emptyDescription="Notes the BDE, the tutors and the administrators add to this enquiry appear here, oldest first. Its Demo and Diagnostic bookings share them."
                placeholder="Write a note for the BDE and the tutors…"
                loadError="Could not load this enquiry's notes."
              />
            </TabsContent>
          ) : null}

          <TabsContent value="feedback">
            {/* Only a booked or completed booking has a report to write or read. */}
            {shown.status === 'BOOKED' || conducted(shown) ? (
              <AdminReportSection booking={shown} reloadKey={reloadKey} />
            ) : (
              <EmptyState
                icon={FileTextIcon}
                title="No report for this booking"
                description={
                  shown.status === 'RESCHEDULED'
                    ? 'It was moved to another slot: the report belongs to the booking that replaced it.'
                    : 'It was cancelled, so no class was taught and no report is written.'
                }
              />
            )}
          </TabsContent>

          <TabsContent value="activity">
            <Panel
              icon={HistoryIcon}
              title="Activity"
              subtitle="Every change to this booking and the bookings it replaced, oldest first, in Indian time (IST)"
            >
              <BookingEvents state={history} bookingId={shown.id} />
            </Panel>
          </TabsContent>
        </Tabs>
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

      {canAssign ? (
        <AssignTutorDialog
          booking={assigning}
          open={Boolean(assigning)}
          onOpenChange={(open) => {
            if (!open) setAssigning(null);
          }}
          onAssigned={(updated) => changed(`${updated.tutor?.full_name} now teaches ${updated.student_name}'s ${typeOf(updated)}.`)}
        />
      ) : null}

      <RescheduleBookingDialog
        booking={rescheduling}
        open={Boolean(rescheduling)}
        onOpenChange={(open) => {
          if (!open) setRescheduling(null);
        }}
        onRescheduled={moved}
      />

      <CancelBookingDialog
        booking={cancelling}
        open={Boolean(cancelling)}
        onOpenChange={(open) => {
          if (!open) setCancelling(null);
        }}
        onCancelled={(updated) =>
          changed(`Cancelled ${updated.student_name}'s ${typeOf(updated)} (${cancelReasonLabel(updated.cancel_reason_code)}).`)
        }
      />

      <RequestRedemoDialog
        booking={requestingRedemo}
        open={Boolean(requestingRedemo)}
        onOpenChange={(open) => {
          if (!open) setRequestingRedemo(null);
        }}
        requestUrl={requestingRedemo ? bookingRedemoUrl(requestingRedemo.booking_type, requestingRedemo.id) : ''}
        onRequested={() =>
          changed(
            `Asked for a Re-Demo of ${requestingRedemo.student_name}'s demo. It is now Re-Demo required; schedule it in Demo Bookings' Re-Demo requests tab.`
          )
        }
      />
    </Page>
  );
}
