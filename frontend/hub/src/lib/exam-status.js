// Exam status vocabulary and file limits, mirroring backend/exams (services.py,
// settings EXAM_FILE_MAX_BYTES / EXAM_MAX_FILES_PER_UPLOAD). Keep in step.

export const EXAM_STATUS_LABEL = { scheduled: 'Scheduled', attended: 'Attended', cancelled: 'Cancelled' };
export const EXAM_STATUS_VARIANT = { scheduled: 'secondary', attended: 'success', cancelled: 'destructive' };

/** Short label for a chapter exam's state, including the score once attended. */
export function examStatusLabel(exam) {
  const status = (exam?.status || '').toLowerCase();
  if (status === 'attended' && exam.score != null && exam.max_score != null) {
    return `Scored ${exam.score}/${exam.max_score}`;
  }
  return EXAM_STATUS_LABEL[status] || 'Scheduled';
}

export const ADDITIONAL_STATUS_LABEL = { assigned: 'Awaiting answer', submitted: 'Awaiting review', scored: 'Scored' };
export const ADDITIONAL_STATUS_VARIANT = { assigned: 'info', submitted: 'warning', scored: 'success' };

export function additionalExamStatusLabel(exam) {
  const status = (exam?.status || '').toLowerCase();
  if (status === 'scored' && exam.score != null && exam.max_score != null) {
    return `Scored ${exam.score}/${exam.max_score}`;
  }
  return ADDITIONAL_STATUS_LABEL[status] || 'Awaiting answer';
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
