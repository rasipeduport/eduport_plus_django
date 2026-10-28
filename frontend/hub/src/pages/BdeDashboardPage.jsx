import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  CalendarCheck,
  CalendarClock,
  CalendarOff,
  ChevronRight,
  ClipboardCheck,
  Inbox,
  PlusIcon,
  Users,
} from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { BDE_DASHBOARD_URL, enquiryError, slotLabel, slotParts } from '@/lib/enquiries';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DashboardHeader } from '@/components/dashboard/dashboard-header';
import { Tile } from '@/components/dashboard/kpi-cards';
import { Panel, PanelEmpty, ScrollList } from '@/components/dashboard/dashboard-primitives';
import { ShareLinkButtons } from '@/components/dashboard/share-link-buttons';
import { AddEnquiryDialog } from '@/components/enquiries/add-enquiry-dialog';
import { BookingTypeBadge, EnquiryStatusBadge } from '@/components/enquiries/enquiry-badges';

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <Skeleton className="h-12 w-72 max-w-full" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-[3fr_2fr]">
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
    </div>
  );
}

function countHint(count, noun, none) {
  return count > 0 ? `${count} ${noun}` : none;
}

function KpiTiles({ data }) {
  const { enquiries, bookings, upcoming } = data;
  const demo = bookings?.DEMO ?? { total: 0, upcoming: 0 };
  const diagnostic = bookings?.DIAGNOSTIC ?? { total: 0, upcoming: 0 };
  const next = upcoming?.rows?.[0];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Tile
        icon={Users}
        tone="info"
        label="Total Enquiries"
        value={enquiries?.total ?? 0}
        hint={enquiries?.last_7_days > 0 ? `+${enquiries.last_7_days} in the last 7 days` : 'None new this week'}
        hintTone={enquiries?.last_7_days > 0 ? 'success' : 'muted'}
        to="/enquiries"
      />
      <Tile
        icon={CalendarCheck}
        tone="success"
        label="Demo Bookings"
        value={demo.total}
        hint={countHint(demo.upcoming, 'upcoming', 'None upcoming')}
      />
      <Tile
        icon={ClipboardCheck}
        tone="warning"
        label="Diagnostic Bookings"
        value={diagnostic.total}
        hint={countHint(diagnostic.upcoming, 'upcoming', 'None upcoming')}
      />
      <Tile
        icon={CalendarClock}
        tone="default"
        label="Upcoming Bookings"
        value={upcoming?.total ?? 0}
        hint={next ? `Next: ${slotLabel(next)}` : 'Nothing scheduled'}
        to="/enquiries?status=BOOKED"
      />
    </div>
  );
}

function UpcomingBookings({ upcoming }) {
  const rows = upcoming?.rows ?? [];
  const total = upcoming?.total ?? 0;
  const subtitle = total > rows.length ? `The next ${rows.length} of ${total} · Indian time (IST)` : 'Indian time (IST)';

  return (
    <Panel icon={CalendarClock} title="Upcoming Bookings" subtitle={subtitle}>
      {rows.length === 0 ? (
        <PanelEmpty
          icon={CalendarOff}
          message="No upcoming bookings"
          hint="Demo classes and diagnostic tests booked by your enquiries appear here."
        />
      ) : (
        <div className="overflow-hidden rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Student</TableHead>
                <TableHead>Parent</TableHead>
                <TableHead className="w-10">
                  <span className="sr-only">Open</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((booking) => {
                const when = slotParts(booking.date, booking.time);
                return (
                  <TableRow key={booking.id}>
                    <TableCell className="whitespace-nowrap">
                      <p className="font-medium">{when.day}</p>
                      <p className="text-muted-foreground text-xs">{when.time}</p>
                    </TableCell>
                    <TableCell>
                      <BookingTypeBadge type={booking.booking_type} />
                    </TableCell>
                    <TableCell>
                      <p className="font-medium">{booking.enquiry.student_name}</p>
                      {booking.enquiry.grade ? (
                        <p className="text-muted-foreground text-xs">{booking.enquiry.grade}</p>
                      ) : null}
                    </TableCell>
                    <TableCell>{booking.enquiry.parent_name}</TableCell>
                    <TableCell>
                      <Button variant="ghost" size="icon" className="size-8" asChild>
                        <Link
                          to={`/enquiries/${booking.enquiry.id}`}
                          aria-label={`Open the enquiry for ${booking.enquiry.student_name}`}
                        >
                          <ChevronRight className="size-4" />
                        </Link>
                      </Button>
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

function RecentEnquiries({ rows }) {
  return (
    <Panel icon={Inbox} title="Recent Enquiries" subtitle="The latest to reach you" actionTo="/enquiries">
      {rows.length === 0 ? (
        <PanelEmpty icon={Inbox} message="No enquiries yet" hint="Share your booking links to start receiving them." />
      ) : (
        <ScrollList total={rows.length} className="divide-y">
          {rows.map((enquiry) => (
            <li key={enquiry.id} className="py-2.5 first:pt-0 last:pb-0">
              <Link
                to={`/enquiries/${enquiry.id}`}
                className="hover:bg-muted/40 -mx-2 flex items-center gap-3 rounded-md px-2 py-1 transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{enquiry.student_name}</p>
                  <p className="text-muted-foreground truncate text-xs">
                    {[enquiry.grade, enquiry.parent_name, enquiry.source_label].filter(Boolean).join(' · ')}
                  </p>
                </div>
                <EnquiryStatusBadge enquiry={enquiry} />
              </Link>
            </li>
          ))}
        </ScrollList>
      )}
    </Panel>
  );
}

/**
 * The BDE dashboard: the BDE's own enquiries and the demo and diagnostic
 * bookings they made, from one request the API scopes to the signed-in BDE.
 * Booking times are Indian time, as the booking pages offer them.
 */
export default function BdeDashboardPage({ user }) {
  const navigate = useNavigate();
  const canAdd = can(user, PERMISSIONS.addEnquiry);
  const canShareLinks = can(user, PERMISSIONS.viewOwnBookingLinks);
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(BDE_DASHBOARD_URL)
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(enquiryError(err, 'Could not load your dashboard.'));
      });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  let content;
  if (failure && !data) {
    content = (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-destructive text-sm">{failure.message}</p>
        {failure.status !== 403 ? (
          <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
            Try again
          </Button>
        ) : null}
      </div>
    );
  } else if (!data) {
    content = <DashboardSkeleton />;
  } else {
    content = (
      <>
        <KpiTiles data={data} />
        <div className="grid min-w-0 gap-4 md:grid-cols-[3fr_2fr] md:items-start">
          <UpcomingBookings upcoming={data.upcoming} />
          <RecentEnquiries rows={data.recent_enquiries ?? []} />
        </div>
      </>
    );
  }

  return (
    <div className="container mx-auto flex flex-col gap-5 px-4 py-16">
      <DashboardHeader user={user} subtitle="Your enquiries and their bookings at a glance." />

      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link to="/enquiries">
              <Inbox />
              My Enquiries
            </Link>
          </Button>
          {canAdd ? (
            <Button variant="outline" onClick={() => setAddOpen(true)}>
              <PlusIcon />
              Add enquiry
            </Button>
          ) : null}
        </div>
        {/* The BDE's own booking links, shared from here: the Hub has no separate Booking links page. */}
        {canShareLinks ? <ShareLinkButtons /> : null}
      </div>

      {content}

      {canAdd ? (
        <AddEnquiryDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          onCreated={(enquiry) => navigate(`/enquiries/${enquiry.id}`)}
        />
      ) : null}
    </div>
  );
}
