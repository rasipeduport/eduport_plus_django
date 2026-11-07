import { Link } from 'react-router-dom';
import { ChevronRightIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ResponsiveList } from '@/components/page/responsive-list';
import { slotLabel } from '@/lib/enquiries';
import { EnquiryStatusBadge } from './enquiry-badges';

const enquiryPath = (enquiry) => `/enquiries/${enquiry.id}`;
// The width the table needs with long names, statuses and dates; narrower areas show cards.
const MIN_TABLE_WIDTH = 1100;
const nextBooking = (enquiry) => (enquiry.next_booking ? slotLabel(enquiry.next_booking) : '—');

// The table's columns, in the order the administrators' Leads list shares (less its owner columns).
const COLUMNS = [
  {
    key: 'parent',
    header: 'Parent',
    cell: (enquiry) => (
      <Link to={enquiryPath(enquiry)} className="font-medium hover:underline">
        {enquiry.parent_name}
      </Link>
    ),
  },
  { key: 'phone', header: 'Phone', className: 'text-muted-foreground tabular-nums', cell: (enquiry) => enquiry.phone },
  { key: 'student', header: 'Student', cell: (enquiry) => enquiry.student_name },
  { key: 'class', header: 'Class', cell: (enquiry) => enquiry.grade || '—' },
  { key: 'source', header: 'Source', cell: (enquiry) => enquiry.source_label },
  { key: 'status', header: 'Status', cell: (enquiry) => <EnquiryStatusBadge enquiry={enquiry} /> },
  { key: 'next', header: 'Next booking', className: 'text-muted-foreground', cell: nextBooking },
  {
    key: 'open',
    header: { srOnly: 'Open' },
    headerClassName: 'w-10',
    cell: (enquiry) => (
      <Button variant="ghost" size="icon" className="size-8" asChild>
        <Link to={enquiryPath(enquiry)} aria-label={`Open the enquiry for ${enquiry.student_name}`}>
          <ChevronRightIcon className="size-4" />
        </Link>
      </Button>
    ),
  },
];

/** One enquiry on a phone: the whole card opens it, through the student's name. */
function EnquiryCard({ enquiry }) {
  return (
    <article className="bg-card hover:bg-muted/40 relative rounded-xl border p-4 transition-colors has-[a:focus-visible]:ring-[3px] has-[a:focus-visible]:ring-ring/50">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate font-medium">
            <Link to={enquiryPath(enquiry)} className="outline-none after:absolute after:inset-0 after:rounded-xl">
              {enquiry.student_name}
            </Link>
          </h2>
          <p className="text-muted-foreground truncate text-sm">
            {[enquiry.grade, enquiry.parent_name].filter(Boolean).join(' · ')}
          </p>
        </div>
        <EnquiryStatusBadge enquiry={enquiry} />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div className="min-w-0">
          <dt className="text-muted-foreground text-xs">Phone</dt>
          <dd className="truncate tabular-nums">{enquiry.phone}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-muted-foreground text-xs">Source</dt>
          <dd className="truncate">{enquiry.source_label}</dd>
        </div>
        <div className="col-span-2 min-w-0">
          <dt className="text-muted-foreground text-xs">Next booking</dt>
          <dd className="truncate">{nextBooking(enquiry)}</dd>
        </div>
      </dl>
    </article>
  );
}

/**
 * A BDE's enquiries (My Enquiries): a table where it fits, cards on a phone,
 * a tablet or beside an open sidebar on a small laptop. Each opens the
 * enquiry's page. Search, filters and paging sit around it on the page, kept
 * in the URL.
 */
export function MyEnquiriesList({ rows, pending }) {
  return (
    <ResponsiveList
      label="Your enquiries"
      columns={COLUMNS}
      rows={rows}
      pending={pending}
      minTableWidth={MIN_TABLE_WIDTH}
      renderCard={(enquiry) => <EnquiryCard enquiry={enquiry} />}
    />
  );
}
