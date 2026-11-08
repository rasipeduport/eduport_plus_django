import { ListChecksIcon, MessagesSquareIcon } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsCount, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Panel } from '@/components/dashboard/dashboard-primitives';
import { EmptyState } from '@/components/page/page';
import { CommunicationBody } from './communication-details';
import { CallOutcomes, Empty, MessageRow, ParentConfirmationCard, TaskDetails, WorkflowTimeline } from './communication-workspace';

function SectionSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <Skeleton className="h-20 rounded-xl" />
      <div className="grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <Skeleton className="h-80 rounded-xl" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
    </div>
  );
}

/**
 * A booking's parent communication in the administrators' booking workspace,
 * laid out as the BDE's communication sheet lays it out and built from its
 * parts (components/communications/communication-workspace), to read only
 * (GET /api/communications/bookings/<type>/<id>/, read by the workspace with
 * useBookingCommunication and handed in as `state`): the parent's answer to
 * the confirmation request -- where it stands, when and by whom it was
 * recorded, and why not -- then, side by side on a wide screen, the
 * communication workflow (each step, where it stands and its moments) and
 * the records: every WhatsApp message, each opening onto its text, moments,
 * attempts and the provider's reports; the call before the class and its
 * outcome; and each step's task in full. Every moment is in Indian time.
 * Asking for the parent's confirmation and recording their answer are the
 * BDE's (their communication sheet): nothing here acts. Shown to holders of
 * accounts.view_all_communications; the API enforces it.
 */
export function CommunicationSection({ state }) {
  const { communication, failure, retry } = state;
  if (failure) {
    return (
      <Panel icon={MessagesSquareIcon} title="Parent communication">
        <CommunicationBody communication={null} failure={failure} retry={retry} />
      </Panel>
    );
  }
  if (!communication) return <SectionSkeleton />;

  const { tasks, messages } = communication;
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <ParentConfirmationCard communication={communication} />
      {communication.planned ? (
        <div className="grid min-w-0 gap-4 lg:grid-cols-[22rem_minmax(0,1fr)] lg:items-start">
          <Panel icon={ListChecksIcon} title="Communication workflow" subtitle="Each step and where it stands, in IST">
            <WorkflowTimeline communication={communication} />
          </Panel>
          <Panel icon={MessagesSquareIcon} title="Communication records" subtitle="Messages, the call and each step's task">
            <Tabs defaultValue="messages" className="gap-4">
              <TabsList>
                <TabsTrigger value="messages">
                  Messages
                  <TabsCount value={messages.length} />
                </TabsTrigger>
                <TabsTrigger value="calls">Call Outcomes</TabsTrigger>
                <TabsTrigger value="tasks">
                  Task Details
                  <TabsCount value={tasks.length} />
                </TabsTrigger>
              </TabsList>
              <TabsContent value="messages">
                {messages.length ? (
                  <ol className="flex flex-col gap-2">
                    {messages.map((message) => (
                      <MessageRow key={message.id} message={message} />
                    ))}
                  </ol>
                ) : (
                  <Empty>No messages yet.</Empty>
                )}
              </TabsContent>
              <TabsContent value="calls">
                <CallOutcomes communication={communication} />
              </TabsContent>
              <TabsContent value="tasks">
                <TaskDetails communication={communication} />
              </TabsContent>
            </Tabs>
          </Panel>
        </div>
      ) : (
        <EmptyState
          icon={MessagesSquareIcon}
          title="No parent messages for this booking"
          description={
            communication.redemo
              ? // A Re-Demo (backend bookings.redemos) has no plan: nothing is ever sent to its parent.
                'No messages are sent for a Re-Demo: the BDE contacts the parent directly with its date, time and tutor.'
              : 'No messages were planned for this booking: it was made before parent communication began.'
          }
        />
      )}
    </div>
  );
}
