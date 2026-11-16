// A Re-Demo's slots on the student's own clock (backend bookings.redemos.student_clock): each slot the
// API offers by its Indian date carries the student's date and time of the same instant, which the
// scheduling picker reads first (components/bookings/redemo-slot-picker).
import { slotParts } from '@/lib/enquiries';

/**
 * Every slot of `dates` (the API's, by Indian date) regrouped by the
 * student's own date (`student_date`), each date's slots soonest first: what
 * the student's calendar reads, which may be a day before or after India's.
 */
export function byStudentDate(dates) {
  const days = new Map();
  for (const entry of dates ?? []) {
    for (const slot of entry.slots) {
      const key = slot.student_date ?? entry.date;
      if (!days.has(key)) days.set(key, []);
      days.get(key).push({ ...slot, date: entry.date });
    }
  }
  return [...days.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([date, slots]) => ({ date, slots: slots.sort((a, b) => (a.starts_at < b.starts_at ? -1 : 1)) }));
}

/** The student's clock of a slot, as the picker reads it first: "5:00 PM UAE". */
export function studentSlotTime(slot) {
  if (!slot?.student_time) return '';
  return `${slotParts(slot.student_date, slot.student_time).time} ${slot.student_label ?? ''}`.trim();
}

/** The student's day of a slot with its time: "Sat, 31 Oct · 5:00 PM UAE". */
export function studentSlotLabel(slot) {
  if (!slot?.student_date) return '';
  return `${slotParts(slot.student_date, slot.student_time).day} · ${studentSlotTime(slot)}`;
}
