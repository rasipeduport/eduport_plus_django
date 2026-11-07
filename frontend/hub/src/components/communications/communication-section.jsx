import { MessagesSquareIcon } from 'lucide-react';

import { Panel } from '@/components/dashboard/dashboard-primitives';
import { CommunicationPanel } from './communication-panel';

/**
 * A booking's parent communication in the administrators' booking workspace
 * (GET /api/communications/bookings/<type>/<id>/, read by the workspace with
 * useBookingCommunication and handed in as `state`): the parent's answer --
 * when and by whom it was recorded -- the five steps with their moments and
 * where each stands, and every WhatsApp message (Phase 3.1), with asking for
 * confirmation and recording the answer where the API offers them (3.2,
 * CommunicationPanel; `onChanged` after either). Shown to holders of
 * accounts.view_all_communications; the API enforces it.
 */
export function CommunicationSection({ state, onChanged }) {
  return (
    <Panel icon={MessagesSquareIcon} title="Parent communication" subtitle="Every moment in Indian time (IST)">
      <CommunicationPanel state={state} onChanged={onChanged} />
    </Panel>
  );
}
