import { Link } from 'react-router-dom';
import { FilePenLineIcon, FilePlus2Icon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { reportActions, tutorReportPagePath } from '@/lib/reports';

/**
 * Write report -- a booked booking whose class has started and has no report
 * yet -- or Edit report, once it has one (lib/reports reportActions); nothing
 * otherwise. Either opens the booking's report page. Offering it is only a
 * label: the API decides whether the report may be saved.
 */
export function TutorReportLink({ booking, size = 'sm' }) {
  const actions = reportActions(booking);
  if (!actions.write && !actions.edit) return null;
  const label = actions.write ? 'Write report' : 'Edit report';
  const Icon = actions.write ? FilePlus2Icon : FilePenLineIcon;
  return (
    <Button asChild size={size} variant={actions.write ? 'default' : 'outline'}>
      <Link
        to={tutorReportPagePath(booking.booking_type, booking.id)}
        aria-label={`${label} for ${booking.student_name}`}
      >
        <Icon className="size-4" />
        {label}
      </Link>
    </Button>
  );
}
