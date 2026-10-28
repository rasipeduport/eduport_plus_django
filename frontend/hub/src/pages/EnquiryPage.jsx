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
  ShieldAlertIcon,
  UserRoundIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { enquiryError, enquiryUrl, formatDay, phoneLinks, slotLabel } from '@/lib/enquiries';
import { getInitials } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { BookingTypeBadge, EnquiryStatusBadge } from '@/components/enquiries/enquiry-badges';

function Field({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 text-sm first:pt-0 last:pb-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

function bookingState(booking) {
  if (booking.status === 'CANCELLED') return { label: 'Cancelled', variant: 'outline' };
  return booking.ended ? { label: 'Done', variant: 'secondary' } : { label: 'Upcoming', variant: 'success' };
}

function BookingsPanel({ bookings }) {
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
                <TableHead>Booked on</TableHead>
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
                      <Badge variant={state.variant}>{state.label}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground whitespace-nowrap">{formatDay(booking.booked_at)}</TableCell>
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
      <p className="font-medium">{missing ? 'Enquiry not found' : "You don't have access to this enquiry."}</p>
      <p className="text-muted-foreground max-w-md text-sm">
        {missing ? 'It may have been removed, or it is not one of your enquiries.' : failure.message}
      </p>
    </div>
  );
}

/**
 * One of the BDE's enquiries in full: the parent, the child and every booking
 * made for them. Read-only for now -- follow-ups come with their own module.
 * The API answers another BDE's enquiry exactly as one that does not exist.
 */
export default function EnquiryPage() {
  const { enquiryId } = useParams();
  const [enquiry, setEnquiry] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

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
        </div>

        <div className="grid min-w-0 gap-4 lg:grid-cols-3">
          <Panel icon={UserRoundIcon} title="Parent">
            <dl className="divide-y">
              <Field label="Name">{enquiry.parent_name}</Field>
              <Field label="Phone">
                <span className="tabular-nums">{enquiry.phone}</span>
              </Field>
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
          <Panel icon={ClipboardListIcon} title="Enquiry">
            <dl className="divide-y">
              <Field label="Source">{enquiry.source_label}</Field>
              <Field label="Status">{enquiry.status_label}</Field>
              <Field label="Next booking">{enquiry.next_booking ? slotLabel(enquiry.next_booking) : null}</Field>
              <Field label="Yours since">{formatDay(enquiry.added_at)}</Field>
              <Field label="First received">{formatDay(enquiry.created_at)}</Field>
            </dl>
          </Panel>
        </div>

        <BookingsPanel bookings={enquiry.bookings ?? []} />
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-16">
      <Button variant="ghost" size="sm" className="text-muted-foreground mb-4 -ml-2" asChild>
        <Link to="/enquiries">
          <ArrowLeftIcon className="size-4" />
          My Enquiries
        </Link>
      </Button>
      {content}
    </div>
  );
}
