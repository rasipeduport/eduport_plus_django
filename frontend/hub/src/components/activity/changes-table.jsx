import { formatValue } from '@/lib/activity-format';

const FIELD_LABELS = {
  total_class_quota: 'Class quota',
  meet_link: 'Meet link',
  status_note: 'Status note',
  start_time: 'Start time',
  end_time: 'End time',
  recording_link: 'Recording link',
  notes_link: 'Notes link',
  score: 'Score',
  max_score: 'Max score',
  feedback: 'Feedback',
  chapter_name: 'Chapter',
  title: 'Title',
  cancellation_reason: 'Cancellation reason',
  mentor: 'Mentor',
  tutor: 'Tutor',
  student_timezone: 'Student timezone',
  // A pricing version (backend sales.services): what changed from the version before.
  standard_fee: 'Standard fee',
  offer_fee: 'Offer fee',
  single_payment_percent: 'Single-payment %',
  single_payment_plan_types: 'Single-payment plans',
};

function fieldLabel(key) {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key];
  const text = key.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Renders an activity entry's before -> after diff. */
export function ChangesTable({ changes }) {
  const entries = Object.entries(changes ?? {});
  if (entries.length === 0) {
    return <p className="text-muted-foreground text-sm">No field changes recorded.</p>;
  }
  return (
    <div className="divide-y rounded-md border text-sm">
      {entries.map(([key, change]) => (
        <div key={key} className="grid grid-cols-[6.5rem_1fr] gap-3 sm:grid-cols-[130px_1fr] px-3 py-2">
          <span className="text-muted-foreground">{fieldLabel(key)}</span>
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted-foreground line-through">{formatValue(change.old)}</span>
            <span aria-hidden>→</span>
            <span className="font-medium">{formatValue(change.new)}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
