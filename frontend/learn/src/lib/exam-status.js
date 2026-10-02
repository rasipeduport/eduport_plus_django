// Student-facing exam status labels (mirror of the Learn app's lib/exams.ts
// and lib/additional-exams.ts) plus the upload limits the API enforces.

export function examStatusBadge(exam) {
  switch ((exam?.status || '').toLowerCase()) {
    case 'attended':
      return {
        label: exam.score != null && exam.max_score != null ? `Scored ${exam.score}/${exam.max_score}` : 'Attended',
        className: 'border-primary/15 bg-primary-subtle text-primary-hover',
      };
    case 'cancelled':
      return { label: 'Cancelled', className: 'border-danger/15 bg-danger-subtle text-danger' };
    default:
      return { label: 'Scheduled', className: 'border-info/15 bg-info-subtle text-info' };
  }
}

export function additionalExamStatusBadge(exam) {
  switch ((exam?.status || '').toLowerCase()) {
    case 'submitted':
      return { label: 'Submitted', className: 'border-info/15 bg-info-subtle text-info' };
    case 'scored':
      return {
        label: exam.score != null && exam.max_score != null ? `Scored ${exam.score}/${exam.max_score}` : 'Scored',
        className: 'border-primary/15 bg-primary-subtle text-primary-hover',
      };
    default:
      return { label: 'To do', className: 'border-warning/15 bg-warning-subtle text-warning' };
  }
}

export const EXAM_ALLOWED_MIME = ['application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'image/heic', 'image/heif'];
export const EXAM_ACCEPT = 'image/*,application/pdf';
export const EXAM_MAX_FILE_BYTES = 25 * 1024 * 1024;
export const EXAM_MAX_FILES = 10;
export const isAllowedExamMime = (mime) => EXAM_ALLOWED_MIME.includes((mime || '').toLowerCase());

export function formatBytes(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Colour tone for a percentage (Learn scoreTone): >= 80 success, >= 60 warning, else danger. */
export function scoreTone(pct) {
  if (pct >= 80) return { key: 'success', text: 'text-primary-hover', bg: 'bg-primary-subtle', border: 'border-primary/15', stroke: 'var(--color-primary)' };
  if (pct >= 60) return { key: 'warning', text: 'text-warning', bg: 'bg-warning-subtle', border: 'border-warning/15', stroke: 'var(--color-warning)' };
  return { key: 'danger', text: 'text-danger', bg: 'bg-danger-subtle', border: 'border-danger/15', stroke: 'var(--color-danger)' };
}
