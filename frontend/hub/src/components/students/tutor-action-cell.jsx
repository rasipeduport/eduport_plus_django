import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';

export function TutorActionCell({ student }) {
  return (
    <Button variant="outline" size="sm" asChild>
      <Link to={`/sessions?student_id=${student.id}`}>View Sessions</Link>
    </Button>
  );
}
