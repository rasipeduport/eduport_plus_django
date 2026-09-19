import { Info } from 'lucide-react';
import { useStudent } from './student-context';

// A soft notice for an 'INACTIVE' (paused) persona. Unlike 'EXPIRED' — which
// is blocked by the auth guard — an inactive student keeps full access; this
// nudges them to contact their mentor. Renders nothing for active personas.
export function EnrollmentBanner() {
  const { selectedStudent } = useStudent();
  if (!selectedStudent || selectedStudent.status !== 'INACTIVE') return null;

  return (
    <div className="bg-warning-subtle border-warning/20 text-warning mb-4 flex items-start gap-2.5 rounded-xl border px-4 py-3 text-sm">
      <Info className="mt-0.5 h-4 w-4 shrink-0" />
      <p className="leading-relaxed">
        Your enrollment is currently paused. You can still review your past
        work — please contact your mentor to resume classes.
      </p>
    </div>
  );
}
