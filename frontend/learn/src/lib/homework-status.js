// Student-facing homework labels (the Learn app's lib/homework.ts).
export function homeworkStatusBadge(hw) {
  switch ((hw?.status || '').toLowerCase()) {
    case 'submitted':
      return { label: 'Submitted', className: 'border-info/15 bg-info-subtle text-info' };
    case 'scored':
      return {
        label: hw.score != null && hw.max_score != null ? `Scored ${hw.score}/${hw.max_score}` : 'Scored',
        className: 'border-primary/15 bg-primary-subtle text-primary-hover',
      };
    default:
      return { label: 'To do', className: 'border-warning/15 bg-warning-subtle text-warning' };
  }
}
