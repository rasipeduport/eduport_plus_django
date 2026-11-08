import { Link } from 'react-router-dom';
import { FilePenLineIcon, FilePlus2Icon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { reportActions, reportWords, tutorReportPagePath } from '@/lib/reports';

/**
 * Write feedback / Enter results -- a booked booking its tutor has started
 * and has no report yet -- or Edit feedback / Edit results, once it has one
 * (lib/reports reportActions, worded by reportWords); nothing otherwise.
 * Either opens the booking's report page, with `state` (its way back) passed
 * on. Offering it is only a label: the API decides whether the report may be
 * saved.
 */
export function TutorReportLink({ booking, size = 'sm', state, className }) {
  const actions = reportActions(booking);
  if (!actions.write && !actions.edit) return null;
  const words = reportWords(booking.booking_type);
  const label = actions.write ? words.write : words.edit;
  const Icon = actions.write ? FilePlus2Icon : FilePenLineIcon;
  return (
    <Button asChild size={size} variant={actions.write ? 'default' : 'outline'} className={className}>
      <Link
        to={tutorReportPagePath(booking.booking_type, booking.id)}
        state={state}
        aria-label={`${label} for ${booking.student_name}`}
      >
        <Icon className="size-4" />
        {label}
      </Link>
    </Button>
  );
}
