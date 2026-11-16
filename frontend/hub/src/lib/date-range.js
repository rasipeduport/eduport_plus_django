// Plain YYYY-MM-DD dates (a slot's Indian date, say) as a calendar picks and names them.
import { format } from 'date-fns';

const pad = (value) => String(value).padStart(2, '0');

/** A plain date as the calendar's Date: that day in this device's zone, for showing it, never for an instant. */
export function toPickerDate(iso) {
  if (!iso) return undefined;
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(year, month - 1, day);
}

/** The calendar's Date back as a plain date. */
export function fromPickerDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** A range of plain dates in words: "2 Nov 2026 – 8 Nov 2026", one day alone, or `anyLabel` for none. */
export function rangeLabel(from, to, anyLabel) {
  if (!from && !to) return anyLabel;
  const label = (iso) => format(toPickerDate(iso), 'd MMM yyyy');
  if (from && to) return from === to ? label(from) : `${label(from)} – ${label(to)}`;
  return from ? `From ${label(from)}` : `Until ${label(to)}`;
}
