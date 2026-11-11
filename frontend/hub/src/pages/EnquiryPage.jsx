import { useEffect, useState } from 'react';
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeftIcon, ReceiptIndianRupeeIcon, SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { can, PERMISSIONS } from '@/lib/access';
import { bdeBookingCancelUrl, bdeEnquiryHistoryUrl, bdeRedemoCloseUrl, bdeRedemoReopenUrl, bdeRedemoUrl, readBookingType } from '@/lib/bookings';
import { bookingTypeLabel, enquiryError, enquiryTimezoneUrl, enquiryUrl, slotLabel } from '@/lib/enquiries';
import { COMING_SOON } from '@/lib/navigation';
import { savedTimezoneLabel } from '@/lib/timezone';
import { useHistory } from '@/hooks/use-history';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsCount, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { CancelBookingDialog } from '@/components/bookings/cancel-booking-dialog';
import { RedemoCloseDialog } from '@/components/bookings/redemo-close-dialog';
import { RequestRedemoDialog } from '@/components/bookings/request-redemo-dialog';
import { BookingCommunicationSheet } from '@/components/communications/communication-sheet';
import { StudentTimezoneDialog } from '@/components/leads/student-timezone-dialog';
import { EmptyState, Page } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';
import { LeadReportsPanel } from '@/components/reports/lead-reports-panel';
import { EnquiryBookings } from '@/components/enquiries/workspace/enquiry-bookings';
import { EnquiryFollowUps } from '@/components/enquiries/workspace/enquiry-follow-ups';
import { EnquiryHeader } from '@/components/enquiries/workspace/enquiry-header';
import { EnquiryNotes } from '@/components/enquiries/workspace/enquiry-notes';
import { EnquiryOverview } from '@/components/enquiries/workspace/enquiry-overview';
import { EnquiryPlanChoosing } from '@/components/enquiries/workspace/enquiry-plan-choosing';
import { EnquirySalesPayment } from '@/components/enquiries/workspace/enquiry-sales-payment';
import { HistoryTimeline } from '@/components/history/history-timeline';

function EnquirySkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <Skeleton className="h-14 w-80 max-w-full" />
      <Skeleton className="h-9 w-full max-w-xl" />
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-44 rounded-xl" />
        <Skeleton className="h-44 rounded-xl" />
        <Skeleton className="h-44 rounded-xl" />
      </div>
    </div>
  );
}

/** An enquiry the API answered as missing (404) or not this account's to see (403), in the page kit's states. */
function Unavailable({ failure }) {
  if (failure.status === 404) {
    return (
      <EmptyState
        icon={SearchXIcon}
        title="Enquiry not found"
        description="It may have been removed, assigned to another BDE, or it is not one of your enquiries."
        action={
          <Button variant="outline" asChild>
            <Link to="/enquiries">Go to My Enquiries</Link>
          </Button>
        }
      />
    );
  }
  return <AccessDeniedState title="You don't have access to this enquiry." message={failure.message} />;
}

/**
 * One of the BDE's enquiries, in one workspace whichever page it was opened
 * from: the parent and the child and how the enquiry has moved (Overview),
 * every booking made for them (Bookings), the reports on those bookings to send
 * to the parent (Tutor Feedback, for holders of accounts.view_own_lead_reports),
 * the calls and parent messages still to do (Follow-ups, for holders of
 * accounts.view_own_lead_communications), initial Sales & Payment, and
 * the notes staff keep on it -- the BDE, the tutors teaching its bookings and
 * the administrators (Notes, never the parent's) -- and every change to its
 * bookings, oldest first, with who made it and why (History, backend
 * bookings.timeline). The parent is called or messaged from here, and sent the
 * BDE's own Demo or Diagnostic booking link on WhatsApp. A Demo sent for a
 * Re-Demo may have its request closed while nothing is booked for it, and
 * reopened.
 *
 * The URL keeps where the BDE is: `tab` (Overview when absent), `highlight`
 * (the booking a link opened the workspace for, on Bookings) and, for holders
 * of accounts.view_own_lead_communications, `booking` and `booking_type` --
 * that booking's parent communication open in a side sheet, where the BDE asks
 * the parent to confirm and records their answer when the API offers it. A
 * link with only a booking (from before the workspace had tabs) opens the
 * sheet on Bookings. The API answers another BDE's enquiry -- one reassigned
 * away from this BDE included -- exactly as one that does not exist. A BDE
 * holding accounts.change_student_timezone sets or corrects the student's
 * time zone from the Overview, which every booking's Student Time follows.
 */
export default function EnquiryPage({ user }) {
  const { enquiryId } = useParams();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [enquiry, setEnquiry] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [cancelling, setCancelling] = useState(null);
  const [requestingRedemo, setRequestingRedemo] = useState(null);
  // Closing or reopening a Demo's Re-Demo request: { mode: 'close' | 'reopen', booking }, kept while its dialog closes.
  const [changingRedemo, setChangingRedemo] = useState(null);
  const [redemoDialogOpen, setRedemoDialogOpen] = useState(false);
  const [changingTimezone, setChangingTimezone] = useState(false);
  // Bumped by every change made here, so History reads the enquiry's bookings again.
  const [historyKey, setHistoryKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const canSeeCommunication = can(user, PERMISSIONS.viewOwnLeadCommunications);
  const canShareLinks = can(user, PERMISSIONS.viewOwnBookingLinks);
  const canSeeReports = can(user, PERMISSIONS.viewOwnLeadReports);
  const canChangeTimezone = can(user, PERMISSIONS.changeStudentTimezone);
  const canChoosePlan = can(user, PERMISSIONS.viewSalesCatalogue) && can(user, PERMISSIONS.createSalesQuotes);
  const openId = searchParams.get('booking');
  const openType = readBookingType(searchParams.get('booking_type'));
  const highlight = searchParams.get('highlight');
  // Where the BDE came from (a booking list, say), for the way back; My Enquiries otherwise.
  const back = location.state?.from ?? { to: '/enquiries', label: 'My Enquiries' };

  const tabs = [
    { key: 'overview', label: 'Overview' },
    { key: 'bookings', label: 'Bookings', count: enquiry?.bookings?.length },
    ...(canSeeReports ? [{ key: 'feedback', label: 'Tutor Feedback' }] : []),
    ...(canSeeCommunication ? [{ key: 'follow-ups', label: 'Follow-ups' }] : []),
    ...(canChoosePlan ? [{ key: 'plan-choosing', label: 'Plan Choosing' }] : []),
    { key: 'sales', label: 'Sales & Payment' },
    { key: 'notes', label: 'Notes' },
    { key: 'history', label: 'History' },
  ];
  const requested = searchParams.get('tab') || (openId && openType ? 'bookings' : 'overview');
  const tab = tabs.some((entry) => entry.key === requested) ? requested : 'overview';

  const setTab = (next) => {
    const params = new URLSearchParams(searchParams);
    if (next === 'overview') params.delete('tab');
    else params.set('tab', next);
    setSearchParams(params, { replace: true });
  };

  /** Show `booking` on the Bookings tab, highlighted. */
  const showBooking = (booking) => {
    const params = new URLSearchParams(searchParams);
    params.set('tab', 'bookings');
    params.set('highlight', booking.id);
    setSearchParams(params, { replace: true });
  };

  /** The enquiry as an action here answered it: its bookings, and so its History, as they now stand. */
  const changedTo = (updated) => {
    setEnquiry(updated);
    setHistoryKey((key) => key + 1);
  };

  /** The enquiry as it now stands, read in place -- after an action in a booking's communication sheet. */
  const refreshEnquiry = () => {
    api
      .get(enquiryUrl(enquiryId))
      .then((response) => changedTo(response.data))
      .catch((err) => setFailure(enquiryError(err, 'Could not load this enquiry.')));
  };

  /** Open `booking`'s communication sheet, or close it (null) and stay on Bookings. */
  const showCommunication = (booking) => {
    const params = new URLSearchParams(searchParams);
    params.set('tab', 'bookings');
    if (booking) {
      params.set('booking', booking.id);
      params.set('booking_type', booking.booking_type);
    } else {
      params.delete('booking');
      params.delete('booking_type');
    }
    setSearchParams(params);
  };

  // Read only while History is open; again after each change made here.
  const history = useHistory(tab === 'history' ? bdeEnquiryHistoryUrl(enquiryId) : null, `${reloadKey}:${historyKey}`);

  useEffect(() => {
    let active = true;
    setEnquiry(null);
    setFailure(null);
    api
      .get(enquiryUrl(enquiryId))
      .then((response) => {
        if (active) setEnquiry(response.data);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, 'Could not load this enquiry.'));
      });
    return () => {
      active = false;
    };
  }, [enquiryId, reloadKey]);

  let content;
  if (failure && (failure.status === 404 || failure.status === 403)) {
    content = <Unavailable failure={failure} />;
  } else if (failure) {
    content = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  } else if (!enquiry) {
    content = <EnquirySkeleton />;
  } else {
    const recipient = { dialCode: enquiry.phone_dial_code, number: enquiry.phone_number };
    content = (
      <>
        <EnquiryHeader enquiry={enquiry} canShareLinks={canShareLinks} />
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            {tabs.map((entry) => (
              <TabsTrigger key={entry.key} value={entry.key}>
                {entry.label}
                <TabsCount value={entry.count} />
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="overview">
            <EnquiryOverview
              enquiry={enquiry}
              onShowBooking={showBooking}
              onChangeTimezone={canChangeTimezone ? () => setChangingTimezone(true) : null}
            />
          </TabsContent>

          <TabsContent value="bookings">
            <EnquiryBookings
              bookings={enquiry.bookings ?? []}
              highlight={highlight}
              onOpenCommunication={canSeeCommunication ? showCommunication : null}
              onCancel={(booking) =>
                setCancelling({ ...booking, student_name: enquiry.student_name, slot: { date: booking.date, time: booking.time } })
              }
              recipient={recipient}
              onInviteRefused={refreshEnquiry}
              onRequestRedemo={(booking) =>
                setRequestingRedemo({ ...booking, student_name: enquiry.student_name, slot: { date: booking.date, time: booking.time } })
              }
              onCloseRedemo={(booking) => {
                setChangingRedemo({ mode: 'close', booking });
                setRedemoDialogOpen(true);
              }}
              onReopenRedemo={(booking) => {
                setChangingRedemo({ mode: 'reopen', booking });
                setRedemoDialogOpen(true);
              }}
              onShowBooking={showBooking}
            />
          </TabsContent>

          {canSeeReports ? (
            <TabsContent value="feedback">
              <LeadReportsPanel enquiry={enquiry} />
            </TabsContent>
          ) : null}

          {canSeeCommunication ? (
            <TabsContent value="follow-ups">
              {/* Opening one keeps the workspace's own way back. */}
              <EnquiryFollowUps enquiryId={enquiry.id} from={location.state?.from ?? null} onChanged={refreshEnquiry} />
            </TabsContent>
          ) : null}
          {canChoosePlan ? (
            <TabsContent value="plan-choosing">
              <EnquiryPlanChoosing key={enquiry.id} enquiry={enquiry} />
            </TabsContent>
          ) : null}
          <TabsContent value="sales">
            {can(user, PERMISSIONS.manageInitialSales) ? <EnquirySalesPayment enquiryId={enquiry.id} enquiry={enquiry} user={user} onChanged={refreshEnquiry} /> : <AccessDeniedState title="Sales & Payment" message="You do not have access to initial sales and payments." />}
          </TabsContent>
          <TabsContent value="notes">
            <EnquiryNotes enquiryId={enquiry.id} />
          </TabsContent>
          <TabsContent value="history">
            <HistoryTimeline
              state={history}
              subtitle="Every change to this enquiry's bookings, oldest first, in Indian time (IST), with who made it"
              emptyMessage="Nothing has happened to this enquiry's bookings yet."
            />
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
      <CancelBookingDialog
        booking={cancelling}
        open={Boolean(cancelling)}
        onOpenChange={(open) => {
          if (!open) setCancelling(null);
        }}
        cancelUrl={(booking) => bdeBookingCancelUrl(booking.booking_type, booking.id)}
        onCancelled={(updated) => {
          // The API answers the enquiry as it now stands.
          changedTo(updated);
          setNotice(
            `Cancelled ${updated.student_name}'s ${bookingTypeLabel(cancelling.booking_type).toLowerCase()} on ${slotLabel(cancelling.slot)}.`
          );
        }}
      />
      <RequestRedemoDialog
        booking={requestingRedemo}
        open={Boolean(requestingRedemo)}
        onOpenChange={(open) => {
          if (!open) setRequestingRedemo(null);
        }}
        requestUrl={requestingRedemo ? bdeRedemoUrl(requestingRedemo.booking_type, requestingRedemo.id) : ''}
        onRequested={(updated) => {
          // The API answers the enquiry as it now stands.
          changedTo(updated);
          setNotice(
            `Asked for a Re-Demo of ${updated.student_name}'s demo on ${slotLabel(requestingRedemo.slot)}. An administrator schedules it; then tell the parent the date and time shown here.`
          );
        }}
      />
      <RedemoCloseDialog
        mode={changingRedemo?.mode ?? 'close'}
        subject={changingRedemo && enquiry ? `${enquiry.student_name} · Demo · ${slotLabel(changingRedemo.booking)}` : null}
        open={redemoDialogOpen && Boolean(changingRedemo)}
        onOpenChange={setRedemoDialogOpen}
        // Refused (an administrator scheduled it, or another change landed): show the enquiry as it is now.
        onRefused={refreshEnquiry}
        url={
          changingRedemo
            ? (changingRedemo.mode === 'reopen' ? bdeRedemoReopenUrl : bdeRedemoCloseUrl)(
                changingRedemo.booking.booking_type,
                changingRedemo.booking.id
              )
            : ''
        }
        onDone={(updated) => {
          // The API answers the enquiry as it now stands.
          const { changed, ...shown } = updated;
          changedTo(shown);
          const slot = slotLabel(changingRedemo.booking);
          if (changingRedemo.mode === 'reopen') {
            setNotice(
              changed === false
                ? `The Re-Demo request for ${shown.student_name}'s demo on ${slot} was already open.`
                : `Reopened the Re-Demo request for ${shown.student_name}'s demo on ${slot}. An administrator schedules it; then tell the parent the date and time shown here.`
            );
          } else {
            setNotice(
              changed === false
                ? `The Re-Demo request for ${shown.student_name}'s demo on ${slot} was already closed.`
                : `Closed the Re-Demo request for ${shown.student_name}'s demo on ${slot}. The demo reads Completed again; reopen the request if the parent wants the Re-Demo after all.`
            );
          }
        }}
      />
      {canChangeTimezone && enquiry ? (
        <StudentTimezoneDialog
          lead={enquiry}
          url={enquiryTimezoneUrl(enquiry.id)}
          open={changingTimezone}
          onOpenChange={setChangingTimezone}
          onSaved={(updated) => {
            // The API answers the enquiry as it now stands: every booking's Student Time follows.
            changedTo(updated);
            setNotice(
              updated.student_timezone
                ? `${updated.student_name}'s timezone is now ${savedTimezoneLabel(updated.student_timezone)}.`
                : `${updated.student_name}'s timezone is no longer set.`
            );
          }}
        />
      ) : null}
      {canSeeCommunication ? (
        <BookingCommunicationSheet
          bookingType={openType}
          bookingId={openId}
          open={Boolean(openId && openType)}
          onOpenChange={(open) => {
            if (!open) showCommunication(null);
          }}
          reloadKey={reloadKey}
          // The parent's answer may cancel the booking: the bookings table catches up.
          onChanged={refreshEnquiry}
          studentTimezone={enquiry?.student_timezone}
        />
      ) : null}
    </Page>
  );
}
