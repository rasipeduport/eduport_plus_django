import { useBookingCommunication } from '@/hooks/use-booking-communication';
import { CommunicationPanel } from './communication-panel';

/**
 * A booking's parent communication in the administrators' booking sheet
 * (GET /api/communications/bookings/<type>/<id>/): the parent's answer, the
 * five steps and every WhatsApp message (Phase 3.1), with asking for
 * confirmation and recording the answer where the API offers them (3.2,
 * CommunicationPanel; `onChanged` after either). Shown to holders of
 * accounts.view_all_communications; the API enforces it.
 */
export function CommunicationSection({ bookingType, bookingId, reloadKey, onChanged }) {
  const state = useBookingCommunication(bookingType, bookingId, reloadKey);
  return (
    <section className="rounded-lg border p-4">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Communication</h3>
      </div>
      <CommunicationPanel state={state} onChanged={onChanged} />
    </section>
  );
}
