import { Eye } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/**
 * Row actions for the tutor students table. A tutor has no action menu -- the
 * two things they do with a student are open their classes and look them up --
 * so the profile sits beside the existing "View Sessions" button.
 */
export function TutorActionCell({ student }) {
  return (
    <div className="flex items-center justify-end gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon" className="size-8" asChild>
            <Link to={`/students/${student.id}`}>
              <Eye className="size-4" />
              <span className="sr-only">View profile</span>
            </Link>
          </Button>
        </TooltipTrigger>
        <TooltipContent>View profile</TooltipContent>
      </Tooltip>
      <Button variant="outline" size="sm" asChild>
        <Link to={`/sessions?student_id=${student.id}`}>View Sessions</Link>
      </Button>
    </div>
  );
}
