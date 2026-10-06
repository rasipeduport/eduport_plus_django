// Exam status vocabulary and file limits, mirroring backend/exams (services.py,
// settings EXAM_FILE_MAX_BYTES / EXAM_MAX_FILES_PER_UPLOAD). Keep in step.

export const EXAM_STATUS_LABEL = { scheduled: 'Scheduled', attended: 'Attended', cancelled: 'Cancelled' };
export const EXAM_STATUS_VARIANT = { scheduled: 'secondary', attended: 'success', cancelled: 'destructive' };

/**
 * Status-only label for a chapter exam. The marks never appear here -- the
 * tables have their own Score column. An attended exam with a recorded
 * result reads "Scored" (the backend status stays ATTENDED).
 */
export function examStatusLabel(exam) {
  const status = (exam?.status || '').toLowerCase();
  if (status === 'attended' && exam.score != null && exam.max_score != null) {
    return 'Scored';
  }
  return EXAM_STATUS_LABEL[status] || 'Scheduled';
}

export const ADDITIONAL_STATUS_LABEL = { assigned: 'Assigned', submitted: 'Submitted', scored: 'Scored' };
export const ADDITIONAL_STATUS_VARIANT = { assigned: 'info', submitted: 'warning', scored: 'success' };

/**
 * Performance colour for an X/Y result, on the Learn app's thresholds:
 * >= 80% success, >= 60% warning, else destructive. Null when there is no
 * usable score, so the caller keeps its empty display.
 */
export function scoreToneClass(score, maxScore) {
  if (score == null || maxScore == null || Number(maxScore) <= 0) return null;
  const pct = (Number(score) / Number(maxScore)) * 100;
  if (pct >= 80) return 'text-success';
  if (pct >= 60) return 'text-warning';
  return 'text-destructive';
}

/** Status-only label for an additional exam; the Score column carries the marks. */
export function additionalExamStatusLabel(exam) {
  const status = (exam?.status || '').toLowerCase();
  return ADDITIONAL_STATUS_LABEL[status] || 'Assigned';
}

export const EXAM_ALLOWED_MIME = [
  'application/pdf',
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/heic',
  'image/heif',
];
export const EXAM_ACCEPT = EXAM_ALLOWED_MIME.join(',');
export const EXAM_MAX_FILE_BYTES = 25 * 1024 * 1024;
export const EXAM_MAX_FILES = 10;

export const isAllowedExamMime = (mime) => EXAM_ALLOWED_MIME.includes((mime || '').toLowerCase());
export const isHttpsUrl = (value) => /^https:\/\/\S+$/i.test((value || '').trim());

export function formatBytes(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Score form rule shared by the result dialog and the grade sheet. */
export function isScoreValid(score, maxScore) {
  const s = Number(score);
  const m = Number(maxScore);
  return (
    String(score).trim() !== '' &&
    String(maxScore).trim() !== '' &&
    Number.isInteger(s) &&
    Number.isInteger(m) &&
    m > 0 &&
    s >= 0 &&
    s <= m
  );
}
