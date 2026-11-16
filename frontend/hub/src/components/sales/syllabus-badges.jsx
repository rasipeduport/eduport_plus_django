import { Badge } from '@/components/ui/badge';
import { planTypeLabel } from '@/lib/sales';

const STATUS_VARIANTS = { DRAFT: 'secondary', PUBLISHED: 'success', INACTIVE: 'outline' };
const STATUS_LABELS = { DRAFT: 'Draft', PUBLISHED: 'Published', INACTIVE: 'Inactive' };

/**
 * A syllabus's status -- Draft until first published, Published, Inactive --
 * and, for a published one being edited, that a draft revision waits
 * (`draftRevision`, its number): BDEs still sell the published revision.
 */
export function SyllabusStatusBadge({ status, draftRevision }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Badge variant={STATUS_VARIANTS[status] ?? 'outline'}>{STATUS_LABELS[status] ?? status}</Badge>
      {status !== 'DRAFT' && draftRevision ? <Badge variant="warning">Draft r{draftRevision}</Badge> : null}
    </span>
  );
}

/** The plan types a syllabus offers, as small outlined badges. */
export function PlanTypeBadges({ planTypes }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {planTypes.map((planType) => (
        <Badge key={planType} variant="outline" className="font-normal">
          {planTypeLabel(planType)}
        </Badge>
      ))}
    </span>
  );
}
