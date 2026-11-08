import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeftIcon,
  CalendarDaysIcon,
  CalendarOffIcon,
  ClipboardListIcon,
  GraduationCapIcon,
  MessageCircleIcon,
  PhoneIcon,
  SearchXIcon,
  UserRoundCogIcon,
  UserRoundIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { can, PERMISSIONS } from '@/lib/access';
import { bookingState } from '@/lib/bookings';
import { enquiryError, formatDay, phoneLinks, slotLabel } from '@/lib/enquiries';
import { CAMPAIGN_FIELDS, LEAD_BDES_URL, bookingPageUrl, leadTimezoneUrl, leadUrl } from '@/lib/leads';
import { savedTimezoneLabel, showsStudentTime } from '@/lib/timezone';
import { getInitials } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { StudentTimeCell, StudentTimeLine, StudentTimezone } from '@/components/bookings/student-time';
import { BookingTypeBadge, EnquiryStatusBadge } from '@/components/enquiries/enquiry-badges';
import { AssignOwnerDialog } from '@/components/leads/assign-owner-dialog';
import { StudentTimezoneDialog } from '@/components/leads/student-timezone-dialog';
import { EmptyState, Page } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';

function Field({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 text-sm first:pt-0 last:pb-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

/**
 * The lead's bookings, to read: each is managed in its own workspace, which
 * it opens for holders of accounts.view_all_bookings. Beside each Indian
 * time, the student's own while any booking reads differently (Student Time).
 */
function BookingsPanel({ bookings, canOpen }) {
  const showStudentTime = showsStudentTime(bookings, (booking) => booking.starts_at, (booking) => booking.student_timezone);
  return (
    <Panel icon={CalendarDaysIcon} title="Bookings" subtitle="Demo classes and diagnostic tests, in Indian time (IST)">
      {bookings.length === 0 ? (
        <PanelEmpty icon={CalendarOffIcon} message="No bookings yet" hint="Bookings made for this child appear here." />
      ) : (
        <div className="overflow-hidden rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When (IST)</TableHead>
                {showStudentTime ? <TableHead>Student Time</TableHead> : null}
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Tutor</TableHead>
                <TableHead>Booked on</TableHead>
                {canOpen ? (
                  <TableHead className="w-px">
                    <span className="sr-only">Open</span>
                  </TableHead>
                ) : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {bookings.map((booking) => {
                const state = bookingState(booking);
                return (
                  <TableRow key={booking.id}>
                    <TableCell className="font-medium whitespace-nowrap">{slotLabel(booking)}</TableCell>
                    {showStudentTime ? (
                      <TableCell className="whitespace-nowrap">
                        <StudentTimeCell startsAt={booking.starts_at} timezone={booking.student_timezone} />
                      </TableCell>
                    ) : null}
                    <TableCell>
                      <BookingTypeBadge type={booking.booking_type} />
                    </TableCell>
                    <TableCell>
                      <Badge variant={state.variant}>{state.label}</Badge>
                    </TableCell>
                    <TableCell>{booking.tutor?.full_name ?? <span className="text-muted-foreground">—</span>}</TableCell>
                    <TableCell className="text-muted-foreground whitespace-nowrap">{formatDay(booking.booked_at)}</TableCell>
                    {canOpen ? (
                      <TableCell>
                        <Button variant="ghost" size="sm" asChild>
                          <Link to={bookingPageUrl(booking)}>Open</Link>
                        </Button>
                      </TableCell>
                    ) : null}
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

function LeadSkeleton() {
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
  if (failure.status === 404) {
    return <EmptyState icon={SearchXIcon} title="Lead not found" description="It may have been removed." />;
  }
  return <AccessDeniedState title="You don't have access to this lead." message={failure.message} />;
}

/**
 * One lead in full, for administrators: the parent and the child, where the
 * lead came from (the website's or landing page's campaign tags included),
 * its status, who owns it, and its bookings -- with the parent to call or
 * message, the lead to give to a BDE (accounts.assign_lead_owner) and the
 * student's time zone to set or correct (accounts.change_student_timezone),
 * which every booking's Student Time follows.
 */
export default function LeadPage({ user }) {
  const { leadId } = useParams();
  const canAssign = can(user, PERMISSIONS.assignLeadOwner);
  const canOpenBookings = can(user, PERMISSIONS.viewAllBookings);
  const canChangeTimezone = can(user, PERMISSIONS.changeStudentTimezone);
  const [lead, setLead] = useState(null);
  const [bdes, setBdes] = useState([]);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [assigning, setAssigning] = useState(false);
  const [changingTimezone, setChangingTimezone] = useState(false);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(leadUrl(leadId))
      .then((response) => {
        if (active) setLead(response.data);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, 'Could not load this lead.'));
      });
    return () => {
      active = false;
    };
  }, [leadId, reloadKey]);

  useEffect(() => {
    if (!canAssign) return undefined;
    let active = true;
    api
      .get(LEAD_BDES_URL)
      .then((response) => {
        if (active) setBdes(response.data?.results ?? []);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [canAssign]);

  let content;
  if (failure && (failure.status === 404 || failure.status === 403)) {
    content = <Unavailable failure={failure} />;
  } else if (failure && !lead) {
    content = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  } else if (!lead || lead.id !== leadId) {
    content = <LeadSkeleton />;
  } else {
    const links = phoneLinks(lead.phone_dial_code, lead.phone_number);
    const campaign = CAMPAIGN_FIELDS.filter(([key]) => lead.source_details?.[key]);
    content = (
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <Avatar className="size-12 rounded-full">
              <AvatarFallback className="size-12 rounded-full">{getInitials(lead.student_name, null)}</AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-semibold">{lead.student_name}</h1>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">
                  {[lead.grade, `Parent: ${lead.parent_name}`].filter(Boolean).join(' · ')}
                </span>
                <EnquiryStatusBadge enquiry={lead} />
                <Badge variant="outline">{lead.source_label}</Badge>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {links ? (
              <>
                <Button variant="outline" asChild>
                  <a href={links.tel}>
                    <PhoneIcon />
                    Call
                  </a>
                </Button>
                <Button variant="outline" asChild>
                  <a href={links.whatsapp} target="_blank" rel="noopener noreferrer">
                    <MessageCircleIcon />
                    WhatsApp
                  </a>
                </Button>
              </>
            ) : null}
            {canAssign ? (
              <Button onClick={() => setAssigning(true)}>
                <UserRoundCogIcon />
                {lead.owner ? 'Reassign' : 'Assign'}
              </Button>
            ) : null}
          </div>
        </div>

        <div className="grid min-w-0 gap-4 lg:grid-cols-3">
          <Panel icon={UserRoundIcon} title="Parent">
            <dl className="divide-y">
              <Field label="Name">{lead.parent_name}</Field>
              <Field label="Phone">
                <span className="tabular-nums">{lead.phone}</span>
              </Field>
              <Field label="Email">{lead.parent_email}</Field>
              <Field label="Country">{lead.country}</Field>
              <Field label="Student timezone">
                <StudentTimezone zone={lead.student_timezone} onChange={canChangeTimezone ? () => setChangingTimezone(true) : null} />
              </Field>
            </dl>
          </Panel>
          <Panel icon={GraduationCapIcon} title="Student">
            <dl className="divide-y">
              <Field label="Name">{lead.student_name}</Field>
              <Field label="Class">{lead.grade}</Field>
              <Field label="School">{lead.school_name}</Field>
              <Field label="Syllabus">{lead.syllabus}</Field>
            </dl>
          </Panel>
          <Panel icon={ClipboardListIcon} title="Lead">
            <dl className="divide-y">
              <Field label="Source">{lead.source_label}</Field>
              {campaign.map(([key, label]) => (
                <Field key={key} label={label}>
                  {lead.source_details[key]}
                </Field>
              ))}
              <Field label="Status">{lead.status_label}</Field>
              <Field label="Next booking">
                {lead.next_booking ? (
                  <>
                    {slotLabel(lead.next_booking)}
                    {/* The next booking is this lead's: its student's zone is the lead's own. */}
                    <StudentTimeLine
                      startsAt={lead.next_booking.starts_at}
                      timezone={lead.student_timezone}
                      className="text-xs font-normal"
                    />
                  </>
                ) : null}
              </Field>
              <Field label="Owner">
                {lead.owner ? lead.owner.full_name : <span className="text-muted-foreground">Unassigned</span>}
              </Field>
              {lead.owner ? <Field label="Owner since">{formatDay(lead.added_at)}</Field> : null}
              <Field label="Received">{formatDay(lead.created_at)}</Field>
              {lead.added_by ? <Field label="Added by">{lead.added_by.full_name}</Field> : null}
            </dl>
          </Panel>
        </div>

        <BookingsPanel bookings={lead.bookings ?? []} canOpen={canOpenBookings} />
      </div>
    );
  }

  return (
    <Page>
      <div className="flex flex-col gap-4">
        <Button variant="ghost" size="sm" className="text-muted-foreground -ml-2 w-fit" asChild>
          <Link to="/leads">
            <ArrowLeftIcon className="size-4" />
            Leads
          </Link>
        </Button>
        {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}
      </div>
      {content}
      {canAssign && lead ? (
        <AssignOwnerDialog
          lead={lead}
          bdes={bdes}
          open={assigning}
          onOpenChange={setAssigning}
          onAssigned={(updated) => {
            setLead(updated);
            setNotice(`${updated.student_name}'s lead is now ${updated.owner?.full_name}'s.`);
          }}
          onStale={() => setReloadKey((key) => key + 1)}
        />
      ) : null}
      {canChangeTimezone && lead ? (
        <StudentTimezoneDialog
          lead={lead}
          url={leadTimezoneUrl(lead.id)}
          open={changingTimezone}
          onOpenChange={setChangingTimezone}
          onSaved={(updated) => {
            // The API answers the lead as it now stands: every booking's Student Time follows.
            setLead(updated);
            setNotice(
              updated.student_timezone
                ? `${updated.student_name}'s timezone is now ${savedTimezoneLabel(updated.student_timezone)}.`
                : `${updated.student_name}'s timezone is no longer set.`
            );
          }}
        />
      ) : null}
    </Page>
  );
}
