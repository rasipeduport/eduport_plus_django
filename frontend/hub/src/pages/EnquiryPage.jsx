import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeftIcon,
  CalendarDaysIcon,
  CalendarOffIcon,
  ClipboardListIcon,
  GraduationCapIcon,
  MessageCircleIcon,
  PhoneIcon,
  SearchXIcon,
  ShieldAlertIcon,
  UserRoundIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { can, PERMISSIONS } from '@/lib/access';
import { bdeBookingCancelUrl, bdeDemoInviteUrl, bookingState, readBookingType } from '@/lib/bookings';
import { istMoment } from '@/lib/communications';
import { bookingTypeLabel, enquiryError, enquiryUrl, formatDay, phoneLinks, slotLabel } from '@/lib/enquiries';
import { getInitials } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { BookingTypeBadge, EnquiryStatusBadge } from '@/components/enquiries/enquiry-badges';
import { CancelBookingDialog } from '@/components/bookings/cancel-booking-dialog';
import { DemoInviteButton } from '@/components/bookings/demo-invite-button';
import { MeetLink } from '@/components/bookings/meet-link';
import { ParentConfirmationBadge } from '@/components/communications/communication-badges';
import { ShareLinkButtons } from '@/components/dashboard/share-link-buttons';
import { BookingCommunicationSheet } from '@/components/communications/communication-sheet';
import { LeadReportsPanel } from '@/components/reports/lead-reports-panel';

function Field({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 text-sm first:pt-0 last:pb-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

/**
 * The enquiry's bookings. Its owner BDE may cancel one that is still booked
 * (Q22) -- the API says which in each booking's `actions` and checks again,
 * that the lead is theirs, on every request -- and, from a Diagnostic whose
 * report is in, send the parent (`recipient`) a Demo invitation (actions.demo_invite;
 * a refusal reads the enquiry again, `onInviteRefused`). With the lead's communication to
 * see (accounts.view_own_lead_communications, `onOpenCommunication`), each
 * shows the parent's answer to the confirmation request and opens its
 * communication.
 */
/**
 * Who teaches a booking and its Google Meet link, to read and pass on -- the
 * API shows them for a booked or completed booking only, and the BDE changes
 * neither: an administrator sets the tutor and the tutor's link.
 */
function Teaching({ booking }) {
  if (!booking.tutor) {
    return booking.status === 'BOOKED' && !booking.ended ? (
      <span className="text-muted-foreground">Not assigned yet</span>
    ) : (
      <span className="text-muted-foreground">—</span>
    );
  }
  return (
    <span className="flex flex-col gap-0.5">
      <span className="font-medium">{booking.tutor.full_name}</span>
      <MeetLink link={booking.tutor_meet_link} />
    </span>
  );
}

function BookingsPanel({ bookings, onCancel, onOpenCommunication, recipient, onInviteRefused }) {
  const communication = Boolean(onOpenCommunication);
  return (
    <Panel icon={CalendarDaysIcon} title="Bookings" subtitle="Demo classes and diagnostic tests, in Indian time (IST)">
      {bookings.length === 0 ? (
        <PanelEmpty
          icon={CalendarOffIcon}
          message="No bookings yet"
          hint="Bookings made through the booking pages for this child appear here."
        />
      ) : (
        <div className="overflow-hidden rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When (IST)</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                {communication ? <TableHead>Confirmation</TableHead> : null}
                <TableHead>Tutor</TableHead>
                <TableHead>Booked on</TableHead>
                <TableHead className="w-px">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {bookings.map((booking) => {
                const state = bookingState(booking);
                return (
                  <TableRow key={booking.id}>
                    <TableCell className="font-medium whitespace-nowrap">{slotLabel(booking)}</TableCell>
                    <TableCell>
                      <BookingTypeBadge type={booking.booking_type} />
                    </TableCell>
                    <TableCell>
                      {/* Where it stands as a class, read-only: only its tutor starts it, never its scheduled time. */}
                      <div className="flex flex-col items-start gap-1">
                        <Badge variant={state.variant}>{state.label}</Badge>
                        {booking.started_at ? (
                          <span className="text-muted-foreground text-xs whitespace-nowrap">
                            Started {istMoment(booking.started_at)}
                          </span>
                        ) : null}
                      </div>
                    </TableCell>
                    {communication ? (
                      <TableCell>
                        <ParentConfirmationBadge status={booking.parent_confirmation} booked={booking.status === 'BOOKED'} />
                      </TableCell>
                    ) : null}
                    <TableCell className="min-w-40 whitespace-normal">
                      <Teaching booking={booking} />
                    </TableCell>
                    <TableCell className="text-muted-foreground whitespace-nowrap">{formatDay(booking.booked_at)}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        {communication ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => onOpenCommunication(booking)}
                            aria-label={`Communication for the ${bookingTypeLabel(booking.booking_type).toLowerCase()} on ${slotLabel(booking)}`}
                          >
                            Communication
                          </Button>
                        ) : null}
                        {booking.actions?.cancel ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => onCancel(booking)}
                            aria-label={`Cancel the ${bookingTypeLabel(booking.booking_type).toLowerCase()} on ${slotLabel(booking)}`}
                          >
                            Cancel
                          </Button>
                        ) : null}
                        {booking.actions?.demo_invite ? (
                          <DemoInviteButton
                            inviteUrl={bdeDemoInviteUrl(booking.booking_type, booking.id)}
                            recipient={recipient}
                            onRefused={onInviteRefused}
                          />
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </Panel>
  );
}

function EnquirySkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <Skeleton className="h-14 w-80 max-w-full" />
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-44" />
        <Skeleton className="h-44" />
        <Skeleton className="h-44" />
      </div>
      <Skeleton className="h-48" />
    </div>
  );
}

function Unavailable({ failure }) {
  const missing = failure.status === 404;
  const Icon = missing ? SearchXIcon : ShieldAlertIcon;
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border px-6 py-12 text-center">
      <Icon className="text-muted-foreground size-8" />
      <p className="font-medium">{missing ? 'Lead not found' : "You don't have access to this lead."}</p>
      <p className="text-muted-foreground max-w-md text-sm">
        {missing ? 'It may have been removed, assigned to another BDE, or it is not one of your leads.' : failure.message}
      </p>
    </div>
  );
}

/**
 * One of the BDE's leads in full: the parent, the child, every booking made
 * for them and the reports on those bookings, to send to the parent (P9, for
 * holders of accounts.view_own_lead_reports); the parent is called or messaged
 * from here, and sent the BDE's own Demo or Diagnostic booking link on
 * WhatsApp. The API answers another BDE's lead -- one reassigned away from
 * this BDE included -- exactly as one that does not exist. Each booking's parent communication opens in a side sheet
 * (?booking=<id>&booking_type=<type>) for holders of
 * accounts.view_own_lead_communications (Phase 3.1), where the BDE asks the
 * parent to confirm and records their answer when the API offers it (3.2).
 */
export default function EnquiryPage({ user }) {
  const { enquiryId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [enquiry, setEnquiry] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [cancelling, setCancelling] = useState(null);
  const [notice, setNotice] = useState(null);
  const canSeeCommunication = can(user, PERMISSIONS.viewOwnLeadCommunications);
  const canShareLinks = can(user, PERMISSIONS.viewOwnBookingLinks);
  const openId = searchParams.get('booking');
  const openType = readBookingType(searchParams.get('booking_type'));

  /** The enquiry as it now stands, read in place -- after an action in a booking's communication sheet. */
  const refreshEnquiry = () => {
    api
      .get(enquiryUrl(enquiryId))
      .then((response) => setEnquiry(response.data))
      .catch((err) => setFailure(enquiryError(err, 'Could not load this lead.')));
  };

  /** Open `booking`'s communication sheet, or close it (null). */
  const showCommunication = (booking) => {
    const params = new URLSearchParams(searchParams);
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
        if (active) setFailure(enquiryError(err, 'Could not load this lead.'));
      });
    return () => {
      active = false;
    };
  }, [enquiryId, reloadKey]);

  let content;
  if (failure && (failure.status === 404 || failure.status === 403)) {
    content = <Unavailable failure={failure} />;
  } else if (failure) {
    content = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
          Try again
        </Button>
      </div>
    );
  } else if (!enquiry) {
    content = <EnquirySkeleton />;
  } else {
    const links = phoneLinks(enquiry.phone_dial_code, enquiry.phone_number);
    content = (
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <Avatar className="size-12 rounded-full">
              <AvatarFallback className="size-12 rounded-full">{getInitials(enquiry.student_name, null)}</AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-semibold">{enquiry.student_name}</h1>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">
                  {[enquiry.grade, `Parent: ${enquiry.parent_name}`].filter(Boolean).join(' · ')}
                </span>
                <EnquiryStatusBadge enquiry={enquiry} />
                <Badge variant="outline">{enquiry.source_label}</Badge>
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:items-end">
            {links ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" asChild>
                  <a href={links.tel}>
                    <PhoneIcon />
                    Call
                  </a>
                </Button>
                <Button asChild>
                  <a href={links.whatsapp} target="_blank" rel="noopener noreferrer">
                    <MessageCircleIcon />
                    WhatsApp
                  </a>
                </Button>
              </div>
            ) : null}
            {/* The BDE's own booking links, sent to this parent's WhatsApp from their menus. */}
            {canShareLinks ? (
              <ShareLinkButtons recipient={{ dialCode: enquiry.phone_dial_code, number: enquiry.phone_number }} />
            ) : null}
          </div>
        </div>

        <div className="grid min-w-0 gap-4 lg:grid-cols-3">
          <Panel icon={UserRoundIcon} title="Parent">
            <dl className="divide-y">
              <Field label="Name">{enquiry.parent_name}</Field>
              <Field label="Phone">
                <span className="tabular-nums">{enquiry.phone}</span>
              </Field>
              <Field label="Email">{enquiry.parent_email}</Field>
              <Field label="Country">{enquiry.country}</Field>
            </dl>
          </Panel>
          <Panel icon={GraduationCapIcon} title="Student">
            <dl className="divide-y">
              <Field label="Name">{enquiry.student_name}</Field>
              <Field label="Class">{enquiry.grade}</Field>
              <Field label="School">{enquiry.school_name}</Field>
              <Field label="Syllabus">{enquiry.syllabus}</Field>
            </dl>
          </Panel>
          <Panel icon={ClipboardListIcon} title="Lead">
            <dl className="divide-y">
              <Field label="Source">{enquiry.source_label}</Field>
              <Field label="Status">{enquiry.status_label}</Field>
              <Field label="Next booking">{enquiry.next_booking ? slotLabel(enquiry.next_booking) : null}</Field>
              <Field label="Yours since">{formatDay(enquiry.added_at)}</Field>
              <Field label="First received">{formatDay(enquiry.created_at)}</Field>
            </dl>
          </Panel>
        </div>

        <BookingsPanel
          bookings={enquiry.bookings ?? []}
          onCancel={(booking) =>
            setCancelling({ ...booking, student_name: enquiry.student_name, slot: { date: booking.date, time: booking.time } })
          }
          onOpenCommunication={canSeeCommunication ? showCommunication : null}
          recipient={{ dialCode: enquiry.phone_dial_code, number: enquiry.phone_number }}
          onInviteRefused={refreshEnquiry}
        />

        {can(user, PERMISSIONS.viewOwnLeadReports) ? <LeadReportsPanel enquiry={enquiry} /> : null}
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      <Button variant="ghost" size="sm" className="text-muted-foreground mb-4 -ml-2" asChild>
        <Link to="/enquiries">
          <ArrowLeftIcon className="size-4" />
          My Leads
        </Link>
      </Button>
      {notice ? (
        <p role="status" className="bg-success/10 text-success mb-4 rounded-md px-3 py-2 text-sm">
          {notice}
        </p>
      ) : null}
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
    </div>
  );
}
