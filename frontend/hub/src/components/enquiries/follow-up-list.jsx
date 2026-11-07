import { Link } from 'react-router-dom';
import { ChevronRightIcon, MessageCircleIcon, PhoneIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ResponsiveList } from '@/components/page/responsive-list';
import { BookingTypeBadge } from '@/components/enquiries/enquiry-badges';
import { istMoment, stepLabel } from '@/lib/communications';
import { phoneLinks, slotLabel } from '@/lib/enquiries';
import { communicationPath } from '@/lib/follow-ups';

/** When the follow-up is due: its moment in Indian time, or after the class for a step not timed yet. */
function due(followUp) {
  return istMoment(followUp.due_at) ?? 'After the class';
}

function Step({ followUp }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <span className="font-medium">{stepLabel(followUp)}</span>
      {followUp.overdue ? <Badge variant="warning">Overdue</Badge> : null}
    </span>
  );
}

/** Call or message the parent, and open the booking's communication, where the follow-up is done. */
function Actions({ followUp, from, className }) {
  const links = phoneLinks(followUp.enquiry.phone_dial_code, followUp.enquiry.phone_number);
  const who = followUp.enquiry.parent_name;
  return (
    <div className={className ?? 'flex justify-end gap-2'}>
      {links ? (
        <>
          <Button variant="ghost" size="icon" className="size-8" asChild>
            <a href={links.tel} aria-label={`Call ${who}`}>
              <PhoneIcon className="size-4" />
            </a>
          </Button>
          <Button variant="ghost" size="icon" className="size-8" asChild>
            <a href={links.whatsapp} target="_blank" rel="noopener noreferrer" aria-label={`WhatsApp ${who}`}>
              <MessageCircleIcon className="size-4" />
            </a>
          </Button>
        </>
      ) : null}
      <Button variant="outline" size="sm" asChild>
        <Link
          to={communicationPath(followUp.enquiry.id, followUp.booking)}
          state={from ? { from } : undefined}
          aria-label={`Open the communication for ${followUp.enquiry.student_name}'s ${stepLabel(followUp).toLowerCase()}`}
        >
          Open
          <ChevronRightIcon />
        </Link>
      </Button>
    </div>
  );
}

/**
 * Follow-ups as a list: a table where it fits, cards elsewhere. Each says what
 * is due and when, for which booking and (unless `inEnquiry`, inside the
 * enquiry's own workspace) whose, and opens that booking's communication;
 * `from` is the way back from there.
 */
export function FollowUpList({ rows, pending, inEnquiry = false, from = null }) {
  const columns = [
    { key: 'due', header: 'Due (IST)', className: 'whitespace-nowrap', cell: (followUp) => due(followUp) },
    { key: 'step', header: 'Follow-up', cell: (followUp) => <Step followUp={followUp} /> },
    ...(inEnquiry
      ? []
      : [
          {
            key: 'enquiry',
            header: 'Enquiry',
            cell: (followUp) => (
              <>
                <p className="font-medium">{followUp.enquiry.student_name}</p>
                <p className="text-muted-foreground text-xs">
                  {[followUp.enquiry.grade, followUp.enquiry.parent_name].filter(Boolean).join(' · ')}
                </p>
              </>
            ),
          },
        ]),
    {
      key: 'booking',
      header: 'Booking',
      cell: (followUp) => (
        <span className="flex flex-col items-start gap-1">
          <BookingTypeBadge type={followUp.booking.booking_type} />
          <span className="text-muted-foreground text-xs whitespace-nowrap">{slotLabel(followUp.booking)}</span>
        </span>
      ),
    },
    {
      key: 'actions',
      header: { srOnly: 'Actions' },
      headerClassName: 'w-px',
      cell: (followUp) => <Actions followUp={followUp} from={from} />,
    },
  ];

  const renderCard = (followUp) => (
    <article className="bg-card flex h-full flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Step followUp={followUp} />
          <p className="text-muted-foreground mt-0.5 text-sm">{followUp.due_at ? `Due ${due(followUp)}` : due(followUp)}</p>
        </div>
        <BookingTypeBadge type={followUp.booking.booking_type} />
      </div>
      <p className="text-sm">
        {inEnquiry ? null : (
          <>
            <span className="font-medium">{followUp.enquiry.student_name}</span>
            <span className="text-muted-foreground"> · {followUp.enquiry.parent_name} · </span>
          </>
        )}
        <span className="text-muted-foreground">{slotLabel(followUp.booking)}</span>
      </p>
      <Actions followUp={followUp} from={from} className="mt-auto flex flex-wrap items-center gap-2" />
    </article>
  );

  return (
    <ResponsiveList
      label="Follow-ups"
      columns={columns}
      rows={rows}
      pending={pending}
      minTableWidth={inEnquiry ? 720 : 900}
      renderCard={renderCard}
    />
  );
}
