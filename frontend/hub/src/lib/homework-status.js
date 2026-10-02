// Homework status vocabulary (the Hub's lib/homework.ts labels), mirroring
// backend/homework: ASSIGNED -> SUBMITTED -> SCORED.
export const HOMEWORK_STATUS_LABEL = { assigned: 'Assigned', submitted: 'Awaiting review', scored: 'Scored' };
export const HOMEWORK_STATUS_VARIANT = { assigned: 'info', submitted: 'warning', scored: 'success' };

export function homeworkStatusLabel(hw) {
  const status = (hw?.status || '').toLowerCase();
  if (status === 'scored' && hw.score != null && hw.max_score != null) {
    return `Scored ${hw.score}/${hw.max_score}`;
  }
  return HOMEWORK_STATUS_LABEL[status] || 'Assigned';
}
