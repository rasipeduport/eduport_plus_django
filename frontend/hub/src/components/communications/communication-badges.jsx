import { Badge } from '@/components/ui/badge';
import { messageState, parentConfirmationState, taskState } from '@/lib/communications';

/** The parent's answer to the confirmation request (`booked`: whether it is still to follow up); "—" when none is shown. */
export function ParentConfirmationBadge({ status, booked }) {
  const state = parentConfirmationState(status, booked);
  if (!state) return <span className="text-muted-foreground">—</span>;
  return <Badge variant={state.variant}>{state.label}</Badge>;
}

export function TaskStateBadge({ task }) {
  const state = taskState(task);
  return <Badge variant={state.variant}>{state.label}</Badge>;
}

export function MessageStateBadge({ message }) {
  const state = messageState(message);
  return <Badge variant={state.variant}>{state.label}</Badge>;
}
