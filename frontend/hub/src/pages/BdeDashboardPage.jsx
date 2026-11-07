import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  CalendarCheck,
  CalendarClock,
  CalendarDays,
  CalendarOff,
  ChevronRight,
  ClipboardCheck,
  Inbox,
  PhoneCall,
  PlusIcon,
  Sun,
  Users,
} from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import { BDE_DASHBOARD_URL, bookingTypeLabel, enquiryBookingPath, enquiryError, slotLabel, slotParts } from '@/lib/enquiries';
import { BDE_FOLLOW_UPS_URL } from '@/lib/follow-ups';
import { cn, getInitials } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { DashboardHeader } from '@/components/dashboard/dashboard-header';
import { Tile } from '@/components/dashboard/kpi-cards';
import { Panel, PanelEmpty, ScrollList } from '@/components/dashboard/dashboard-primitives';
import { ShareLinkButtons } from '@/components/dashboard/share-link-buttons';
import { AddEnquiryDialog } from '@/components/enquiries/add-enquiry-dialog';
import { BookingTypeBadge, EnquiryStatusBadge } from '@/components/enquiries/enquiry-badges';
import { BookingStateBadge } from '@/components/bookings/booking-badges';
import { Page } from '@/components/page/page';
import { ResponsiveList } from '@/components/page/responsive-list';
import { AccessDeniedState, ErrorState } from '@/components/page/states';

const enquiryPath = (enquiry) => `/enquiries/${enquiry.id}`;
// A booking opens its enquiry's workspace on Bookings, with that booking highlighted.
const bookingPath = (booking) => enquiryBookingPath(booking.enquiry.id, booking.id);

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-5">
        <Skeleton className="h-72 rounded-xl xl:col-span-3" />
        <Skeleton className="h-72 rounded-xl xl:col-span-2" />
      </div>
      <Skeleton className="h-56 rounded-xl" />
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
        tone="default"
        label="Total Enquiries"
        value={enquiries?.total ?? 0}
        hint={enquiries?.last_7_days > 0 ? `+${enquiries.last_7_days} in the last 7 days` : 'None new this week'}
        hintTone={enquiries?.last_7_days > 0 ? 'success' : 'muted'}
        to="/enquiries"
      />
      <Tile
        icon={CalendarCheck}
        tone="demo"
        label="Demo Bookings"
        value={demo.total}
        hint={countHint(demo.upcoming, 'upcoming', 'None upcoming')}
        to="/demo-bookings"
      />
      <Tile
        icon={ClipboardCheck}
        tone="diagnostic"
        label="Diagnostic Bookings"
        value={diagnostic.total}
        hint={countHint(diagnostic.upcoming, 'upcoming', 'None upcoming')}
        to="/diagnostic-bookings"
      />
      <Tile
        icon={CalendarClock}
        tone="warning"
        label="Upcoming Bookings"
        value={upcoming?.total ?? 0}
        hint={next ? `Next: ${slotLabel(next)}` : 'Nothing scheduled'}
        to="/enquiries?status=BOOKED"
      />
    </div>
  );
}

/** One of today's bookings on the agenda's timeline: when, what and for whom, and where it stands. */
function AgendaItem({ booking }) {
  const when = slotParts(booking.date, booking.time);
  const type = bookingTypeLabel(booking.booking_type);
  const { enquiry } = booking;
  return (
    <li className="group relative flex gap-3 rounded-md has-[a:focus-visible]:ring-[3px] has-[a:focus-visible]:ring-ring/50">
      <span className="w-16 shrink-0 pt-0.5 text-sm font-medium whitespace-nowrap tabular-nums">{when.time}</span>
      <span className="flex flex-col items-center" aria-hidden="true">
        <span
          className={cn(
            'mt-1.5 size-2.5 shrink-0 rounded-full ring-4',
            booking.booking_type === 'DIAGNOSTIC' ? 'bg-diagnostic ring-diagnostic/15' : 'bg-demo ring-demo/15'
          )}
        />
        <span className="bg-border mt-1.5 w-px flex-1 group-last:hidden" />
      </span>
      <div className="min-w-0 flex-1 pb-5 group-last:pb-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Link
            to={bookingPath(booking)}
            className="hover:underline focus-visible:underline focus-visible:outline-none after:absolute after:inset-0"
          >
            <span className="font-medium">{type}</span>
            <span className="text-muted-foreground"> · </span>
            <span className="font-medium">{enquiry.student_name}</span>
          </Link>
          <BookingStateBadge booking={booking} />
        </div>
        <p className="text-muted-foreground mt-0.5 text-xs">
          {[enquiry.grade, `Parent: ${enquiry.parent_name}`, booking.tutor ? `Tutor: ${booking.tutor.full_name}` : null]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </div>
    </li>
  );
}

/** How many follow-up reminders are due today, opening Follow-ups on them. */
function FollowUpsLine({ followUps }) {
  const plural = (count) => (count === 1 ? 'follow-up' : 'follow-ups');
  const due = followUps.today ? `${followUps.today} ${plural(followUps.today)} due today` : 'No follow-ups due today';
  return (
    <Link
      to="/follow-ups?due=today"
      className="hover:bg-muted/40 mt-4 flex items-center gap-3 rounded-lg border px-3 py-2 text-sm transition-colors"
    >
      <PhoneCall className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1">{due}</span>
      <ChevronRight className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
    </Link>
  );
}

/**
 * Today's Demo classes and diagnostic tests for the BDE's enquiries, on a
 * timeline. "Today" is the API's Indian date (agenda.date), the day the slots
 * are booked in -- never this device's -- so it is named, not assumed. With
 * the BDE's follow-ups to see (`followUps`), how many reminders are due today.
 */
function TodaysAgenda({ agenda, followUps, className }) {
  const rows = agenda?.rows ?? [];
  const total = agenda?.total ?? rows.length;
  const day = agenda?.date ? slotParts(agenda.date, '00:00').day : 'Today';
  const subtitle = total > rows.length ? `${day} · the first ${rows.length} of ${total} · IST` : `${day} · Indian time (IST)`;

  return (
    <Panel
      icon={CalendarDays}
      title="Today's Agenda"
      subtitle={subtitle}
      className={className}
      action={
        total > 0 ? (
          <Badge variant="secondary" className="tabular-nums">
            {total} {total === 1 ? 'booking' : 'bookings'}
          </Badge>
        ) : null
      }
    >
      {rows.length === 0 ? (
        <PanelEmpty icon={Sun} message="Nothing booked for today" hint="Demo classes and diagnostic tests booked for today appear here." />
      ) : (
        <ol aria-label="Today's bookings">
          {rows.map((booking) => (
            <AgendaItem key={booking.id} booking={booking} />
          ))}
        </ol>
      )}
      {followUps ? <FollowUpsLine followUps={followUps} /> : null}
    </Panel>
  );
}

function RecentEnquiries({ rows, className }) {
  return (
    <Panel icon={Inbox} title="Recent Enquiries" subtitle="The latest to reach you" actionTo="/enquiries" className={className}>
      {rows.length === 0 ? (
        <PanelEmpty icon={Inbox} message="No enquiries yet" hint="Share your booking links to start receiving them." />
      ) : (
        <ScrollList total={rows.length} className="divide-y">
          {rows.map((enquiry) => (
            <li key={enquiry.id} className="py-2.5 first:pt-0 last:pb-0">
              <Link
                to={enquiryPath(enquiry)}
                className="hover:bg-muted/40 -mx-2 flex items-center gap-3 rounded-md px-2 py-1 transition-colors"
              >
                <Avatar className="size-8 rounded-full" aria-hidden="true">
                  <AvatarFallback className="rounded-full text-xs">{getInitials(enquiry.student_name, null)}</AvatarFallback>
                </Avatar>
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

// The Upcoming Bookings table; a phone shows each as a card instead (UpcomingCard).
const UPCOMING_COLUMNS = [
  {
    key: 'when',
    header: 'When',
    className: 'whitespace-nowrap',
    cell: (booking) => {
      const when = slotParts(booking.date, booking.time);
      return (
        <>
          <p className="font-medium">{when.day}</p>
          <p className="text-muted-foreground text-xs">{when.time}</p>
        </>
      );
    },
  },
  { key: 'type', header: 'Type', cell: (booking) => <BookingTypeBadge type={booking.booking_type} /> },
  {
    key: 'student',
    header: 'Student',
    cell: (booking) => (
      <>
        <p className="font-medium">{booking.enquiry.student_name}</p>
        {booking.enquiry.grade ? <p className="text-muted-foreground text-xs">{booking.enquiry.grade}</p> : null}
      </>
    ),
  },
  { key: 'parent', header: 'Parent', cell: (booking) => booking.enquiry.parent_name },
  {
    key: 'open',
    header: { srOnly: 'Open' },
    headerClassName: 'w-10',
    cell: (booking) => (
      <Button variant="ghost" size="icon" className="size-8" asChild>
        <Link to={bookingPath(booking)} aria-label={`Open the enquiry for ${booking.enquiry.student_name}`}>
          <ChevronRight className="size-4" />
        </Link>
      </Button>
    ),
  },
];

function UpcomingCard({ booking }) {
  return (
    <article className="hover:bg-muted/40 relative flex items-center gap-3 rounded-lg border p-3 transition-colors has-[a:focus-visible]:ring-[3px] has-[a:focus-visible]:ring-ring/50">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">
          <Link to={bookingPath(booking)} className="outline-none after:absolute after:inset-0 after:rounded-lg">
            {booking.enquiry.student_name}
          </Link>
          {booking.enquiry.grade ? <span className="text-muted-foreground font-normal"> · {booking.enquiry.grade}</span> : null}
        </p>
        <p className="text-muted-foreground mt-0.5 text-xs">{slotLabel(booking)}</p>
        <p className="text-muted-foreground truncate text-xs">Parent: {booking.enquiry.parent_name}</p>
      </div>
      <BookingTypeBadge type={booking.booking_type} />
    </article>
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
        <ResponsiveList
          label="Upcoming bookings"
          columns={UPCOMING_COLUMNS}
          rows={rows}
          renderCard={(booking) => <UpcomingCard booking={booking} />}
        />
      )}
    </Panel>
  );
}

/**
 * The BDE dashboard: the BDE's own enquiries and the demo and diagnostic
 * bookings made for them -- the headline numbers, today's agenda, the latest
 * enquiries and what is booked next -- from one request the API scopes to the
 * signed-in BDE. Booking times are Indian time, as the booking pages offer them.
 */
export default function BdeDashboardPage({ user }) {
  const navigate = useNavigate();
  const canAdd = can(user, PERMISSIONS.addEnquiry);
  const canShareLinks = can(user, PERMISSIONS.viewOwnBookingLinks);
  const canFollowUp = can(user, PERMISSIONS.viewOwnLeadCommunications);
  const [data, setData] = useState(null);
  const [followUps, setFollowUps] = useState(null);
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

  // The follow-ups' counts beside today's agenda, for a BDE who may see their leads' communication; a failure leaves them out.
  useEffect(() => {
    if (!canFollowUp) return undefined;
    let active = true;
    api
      .get(BDE_FOLLOW_UPS_URL, { params: { page_size: 1 } })
      .then((response) => {
        if (active) setFollowUps(response.data.summary ?? null);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [canFollowUp, reloadKey]);

  let content;
  if (failure && !data && failure.status === 403) {
    content = <AccessDeniedState title="This dashboard belongs to BDE accounts." message={failure.message} />;
  } else if (failure && !data) {
    content = <ErrorState message={failure.message} onRetry={() => setReloadKey((key) => key + 1)} />;
  } else if (!data) {
    content = <DashboardSkeleton />;
  } else {
    content = (
      <>
        <KpiTiles data={data} />
        <div className="grid min-w-0 gap-4 xl:grid-cols-5 xl:items-start">
          <TodaysAgenda agenda={data.agenda} followUps={followUps} className="xl:col-span-3" />
          <RecentEnquiries rows={data.recent_enquiries ?? []} className="xl:col-span-2" />
        </div>
        <UpcomingBookings upcoming={data.upcoming} />
      </>
    );
  }

  return (
    <Page>
      <DashboardHeader user={user} subtitle="Your enquiries and their bookings at a glance." />

      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link to="/enquiries">
              <Inbox />
              My Enquiries
            </Link>
          </Button>
          {canAdd ? (
            <Button variant="outline" onClick={() => setAddOpen(true)}>
              <PlusIcon />
              Add Enquiry
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
    </Page>
  );
}
