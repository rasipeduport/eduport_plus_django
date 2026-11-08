import { CalendarDaysIcon, CalendarOffIcon } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { BookingStatus, Teaching } from '@/components/enquiries/workspace/enquiry-bookings';
import { ParentConfirmationBadge } from '@/components/communications/communication-badges';
import { ResponsiveList } from '@/components/page/responsive-list';
import { AccessDeniedState, ErrorState } from '@/components/page/states';
import { formatDay, slotLabel } from '@/lib/enquiries';

// The width the table needs; narrower areas show cards.
const MIN_TABLE_WIDTH = 1000;

/**
 * Said after the slot of the booking being viewed: its highlight (the row's
 * tint, the card's ring) shows it to the eye, this to a screen reader.
 * Nothing for any other booking.
 */
function Viewing({ entry, bookingId }) {
  return entry.id === bookingId ? <span className="sr-only"> (the booking you are viewing)</span> : null;
}

/**
 * Every Demo and Diagnostic booking made for the child (the administrators'
 * booking workspace, its Bookings tab), as a BDE's enquiry lists them -- from
 * the lead in full (`lead`, GET /api/leads/<id>/, for holders of
 * accounts.view_all_leads): when (IST), its type, where it stands (its start
 * and any Re-Demo included), the parent's answer to the confirmation request
 * (for holders of accounts.view_all_communications, `showConfirmation`), who
 * teaches it with its Meet link, and when it was booked; the booking being
 * viewed highlighted, and named as such to a screen reader (Viewing). To read
 * only: its tutor is given or changed from the workspace's header, and
 * another booking opens from the Overview's All Bookings. A table where it
 * fits, a card per booking on a phone or a narrow screen.
 */
export function BookingsTab({ booking, lead, leadFailure, onRetryLead, showLead, showConfirmation }) {
  if (!showLead) {
    return (
      <AccessDeniedState
        title="You don't have access to this enquiry's bookings."
        message="They are shown to whoever may see every lead."
      />
    );
  }
  if (leadFailure && !lead) return <ErrorState message={leadFailure.message} onRetry={onRetryLead} />;
  if (!lead) return <Skeleton className="h-56 rounded-xl" aria-busy="true" />;

  const bookings = lead.bookings ?? [];
  const confirmation = (entry) => (
    <ParentConfirmationBadge status={entry.parent_confirmation} booked={entry.status === 'BOOKED'} />
  );
  const columns = [
    {
      key: 'when',
      header: 'When (IST)',
      className: 'font-medium whitespace-nowrap',
      cell: (entry) => (
        <>
          {slotLabel(entry)}
          <Viewing entry={entry} bookingId={booking.id} />
        </>
      ),
    },
    { key: 'type', header: 'Type', cell: (entry) => <BookingTypeBadge type={entry.booking_type} /> },
    { key: 'status', header: 'Status', cell: (entry) => <BookingStatus booking={entry} /> },
    ...(showConfirmation ? [{ key: 'confirmation', header: 'Parent confirmation', cell: confirmation }] : []),
    { key: 'tutor', header: 'Tutor', className: 'min-w-40 whitespace-normal', cell: (entry) => <Teaching booking={entry} /> },
    {
      key: 'booked',
      header: 'Booked on',
      className: 'text-muted-foreground whitespace-nowrap',
      cell: (entry) => formatDay(entry.booked_at),
    },
  ];

  const renderCard = (entry) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">
            {slotLabel(entry)}
            <Viewing entry={entry} bookingId={booking.id} />
          </p>
          <p className="text-muted-foreground text-xs">Booked on {formatDay(entry.booked_at)}</p>
        </div>
        <BookingTypeBadge type={entry.booking_type} />
      </div>
      <BookingStatus booking={entry} />
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        {showConfirmation ? (
          <div className="min-w-0">
            <p className="text-muted-foreground text-xs">Parent confirmation</p>
            {confirmation(entry)}
          </div>
        ) : null}
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">Tutor</p>
          <Teaching booking={entry} />
        </div>
      </div>
    </article>
  );

  return (
    <Panel icon={CalendarDaysIcon} title="Bookings" subtitle="Demo classes and diagnostic tests for this child, in Indian time (IST)">
      {bookings.length === 0 ? (
        <PanelEmpty icon={CalendarOffIcon} message="No bookings yet" />
      ) : (
        <ResponsiveList
          label="Bookings"
          columns={columns}
          rows={bookings}
          highlightedKey={booking.id}
          minTableWidth={MIN_TABLE_WIDTH}
          renderCard={renderCard}
        />
      )}
    </Panel>
  );
}
