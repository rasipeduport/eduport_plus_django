import { MessageCircleIcon, PhoneIcon } from 'lucide-react';

import api from '@/lib/api';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { ShareLinkButtons } from '@/components/dashboard/share-link-buttons';
import { EnquiryStatusBadge } from '@/components/enquiries/enquiry-badges';
import { phoneLinks } from '@/lib/enquiries';
import { bookingLinkSharedUrl } from '@/lib/follow-ups';
import { getInitials } from '@/lib/utils';

/**
 * Who the enquiry is about and how to reach them: the student, where the
 * enquiry stands, the parent and their number, where it came from -- with
 * Call and WhatsApp, and the BDE's own booking links (`canShareLinks`) sent to
 * this parent's WhatsApp from their menus. A link copied or sent here tells
 * the API, which ends the reminder to call a new enquiry; one that cannot be
 * told leaves the reminder to its 24 hours.
 */
export function EnquiryHeader({ enquiry, canShareLinks }) {
  const links = phoneLinks(enquiry.phone_dial_code, enquiry.phone_number);
  const linkShared = (bookingType) => {
    api.post(bookingLinkSharedUrl(enquiry.id), { booking_type: bookingType }).catch(() => {});
  };
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 items-center gap-4">
        <Avatar className="size-14 rounded-full" aria-hidden="true">
          <AvatarFallback className="size-14 rounded-full text-lg">{getInitials(enquiry.student_name, null)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{enquiry.student_name}</h1>
            <EnquiryStatusBadge enquiry={enquiry} />
          </div>
          <p className="text-muted-foreground mt-1 flex flex-wrap gap-x-3 gap-y-1 text-sm">
            {enquiry.grade ? <span>{enquiry.grade}</span> : null}
            <span>Parent: {enquiry.parent_name}</span>
            <span className="tabular-nums">{enquiry.phone}</span>
            <span>Source: {enquiry.source_label}</span>
          </p>
        </div>
      </div>
      <div className="flex flex-col gap-2 sm:items-end">
        {links ? (
          <div className="flex flex-wrap gap-2">
            <Button asChild>
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
          </div>
        ) : null}
        {canShareLinks ? (
          <ShareLinkButtons
            recipient={{ dialCode: enquiry.phone_dial_code, number: enquiry.phone_number }}
            onShare={linkShared}
          />
        ) : null}
      </div>
    </div>
  );
}
