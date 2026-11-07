import { useEffect, useState } from 'react';
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeftIcon, ReceiptIndianRupeeIcon, SearchXIcon } from 'lucide-react';

import api from '@/lib/api';
import { can, PERMISSIONS } from '@/lib/access';
import { bdeBookingCancelUrl, bdeRedemoUrl, readBookingType } from '@/lib/bookings';
import { bookingTypeLabel, enquiryError, enquiryUrl, slotLabel } from '@/lib/enquiries';
import { COMING_SOON } from '@/lib/navigation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsCount, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { CancelBookingDialog } from '@/components/bookings/cancel-booking-dialog';
import { RequestRedemoDialog } from '@/components/bookings/request-redemo-dialog';
import { BookingCommunicationSheet } from '@/components/communications/communication-sheet';
import { EmptyState, Page } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';
import { LeadReportsPanel } from '@/components/reports/lead-reports-panel';
import { EnquiryBookings } from '@/components/enquiries/workspace/enquiry-bookings';
import { EnquiryFollowUps } from '@/components/enquiries/workspace/enquiry-follow-ups';
import { EnquiryHeader } from '@/components/enquiries/workspace/enquiry-header';
import { EnquiryNotes } from '@/components/enquiries/workspace/enquiry-notes';
import { EnquiryOverview } from '@/components/enquiries/workspace/enquiry-overview';

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
 * accounts.view_own_lead_communications), Sales & Payment, still to come, and
 * the notes staff keep on it -- the BDE, the tutors teaching its bookings and
 * the administrators (Notes, never the parent's). The parent is called or
 * messaged from here, and sent the BDE's own Demo or Diagnostic booking link on
 * WhatsApp.
 *
 * The URL keeps where the BDE is: `tab` (Overview when absent), `highlight`
 * (the booking a link opened the workspace for, on Bookings) and, for holders
 * of accounts.view_own_lead_communications, `booking` and `booking_type` --
 * that booking's parent communication open in a side sheet, where the BDE asks
 * the parent to confirm and records their answer when the API offers it. A
 * link with only a booking (from before the workspace had tabs) opens the
 * sheet on Bookings. The API answers another BDE's enquiry -- one reassigned
 * away from this BDE included -- exactly as one that does not exist.
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
  const [notice, setNotice] = useState(null);
  const canSeeCommunication = can(user, PERMISSIONS.viewOwnLeadCommunications);
  const canShareLinks = can(user, PERMISSIONS.viewOwnBookingLinks);
  const canSeeReports = can(user, PERMISSIONS.viewOwnLeadReports);
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
    { key: 'sales', label: 'Sales & Payment' },
    { key: 'notes', label: 'Notes' },
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

  /** The enquiry as it now stands, read in place -- after an action in a booking's communication sheet. */
  const refreshEnquiry = () => {
    api
      .get(enquiryUrl(enquiryId))
      .then((response) => setEnquiry(response.data))
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
            <EnquiryOverview enquiry={enquiry} onShowBooking={showBooking} />
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
              <EnquiryFollowUps enquiryId={enquiry.id} from={location.state?.from ?? null} />
            </TabsContent>
          ) : null}
          {/* Still to come: says so. */}
          <TabsContent value="sales">
            <EmptyState
              icon={ReceiptIndianRupeeIcon}
              title={
                <span className="inline-flex flex-wrap items-center justify-center gap-2">
                  Sales &amp; Payment <Badge variant="highlight">{COMING_SOON}</Badge>
                </span>
              }
              description="The plan this family chooses, its payments and where they stand will appear here."
            />
          </TabsContent>
          <TabsContent value="notes">
            <EnquiryNotes enquiryId={enquiry.id} />
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
          setEnquiry(updated);
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
          setEnquiry(updated);
          setNotice(
            `Asked for a Re-Demo of ${updated.student_name}'s demo on ${slotLabel(requestingRedemo.slot)}. An administrator schedules it; then tell the parent the date and time shown here.`
          );
        }}
      />
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
        />
      ) : null}
    </Page>
  );
}
