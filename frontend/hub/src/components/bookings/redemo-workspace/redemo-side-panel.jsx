import { useState } from 'react';
import { CopyIcon, DownloadIcon, MessageCircleIcon, UserRoundIcon, ZapIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useLinkCopy } from '@/hooks/use-link-copy';
import { whatsAppUrl } from '@/lib/enquiries';
import { bookingReportUrl, reportPdfFallbackName, reportPdfUrl } from '@/lib/reports';
import { savedTimezoneLabel } from '@/lib/timezone';
import { CopyStatus } from '@/components/dashboard/share-link-buttons';
import { PdfDownloadButton } from '@/components/reports/pdf-download-button';
import { EditLeadDetailsAction } from '@/components/leads/edit-lead-details-action';
import { Field, Fields, WorkspaceCard } from './parts';

/**
 * The parent message for the scheduled Re-Demo, as the API fills it in
 * (`parent_messages`): the confirmation request, or the class details once
 * the parent has confirmed. Shown to read, copy, or open in WhatsApp with
 * the parent's number -- sent by hand: nothing is sent automatically.
 */
function MessageDialog({ redemo, message, confirmed, open, onOpenChange }) {
  const lead = redemo.lead ?? {};
  const { copy, copied, manual, urlRef } = useLinkCopy();
  const url = message?.text ? whatsAppUrl(lead.phone_dial_code, lead.phone_number, message.text) : null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{confirmed ? 'Class details for the parent' : 'Ask the parent to confirm'}</DialogTitle>
          <DialogDescription>
            {redemo.owner_bde
              ? `${redemo.owner_bde.full_name} tells the parent the time. Nothing is sent automatically.`
              : 'No BDE owns this lead: tell the parent the time yourself. Nothing is sent automatically.'}
          </DialogDescription>
        </DialogHeader>
        {message?.text ? (
          <p className="bg-muted/40 max-h-[50vh] overflow-y-auto rounded-md border p-3 text-sm whitespace-pre-wrap">
            {message.text}
          </p>
        ) : (
          <p className="text-muted-foreground text-sm">
            The message needs: {(message?.missing ?? []).join(', ').replace(/_/g, ' ')}.
          </p>
        )}
        <CopyStatus manual={manual} urlRef={urlRef} copiedLabel={copied ? 'Message' : null} />
        <DialogFooter>
          <Button variant="outline" disabled={!message?.text} onClick={() => copy('message', message.text)}>
            <CopyIcon />
            Copy text
          </Button>
          {url ? (
            <Button asChild>
              <a href={url} target="_blank" rel="noopener noreferrer">
                <MessageCircleIcon />
                Open in WhatsApp
              </a>
            </Button>
          ) : (
            <Button disabled>
              <MessageCircleIcon />
              Open in WhatsApp
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The workspace's right-hand panel: who the student is -- class, syllabus,
 * school, country and time zone -- with the parent and their phone as the
 * API gives them, and the lead's BDE; then the quick actions: the parent's
 * WhatsApp text for the scheduled Re-Demo (the API's `parent_messages`, there
 * once one is booked) and the original Demo's report as a PDF.
 */
export function RedemoSidePanel({ redemo, user, onDetailsSaved }) {
  const [messageOpen, setMessageOpen] = useState(false);
  const lead = redemo.lead ?? {};
  const original = redemo.original;
  const messages = redemo.parent_messages;
  const confirmed = redemo.booking?.parent_confirmation === 'CONFIRMED';
  const message = messages ? (confirmed ? messages.confirmed : messages.confirmation_request) : null;

  return (
    <div className="flex flex-col gap-4">
      <WorkspaceCard
        icon={UserRoundIcon}
        title="Student details"
        action={
          <div className="flex flex-wrap gap-2">
            <EditLeadDetailsAction user={user} leadId={lead.id} section="parent" label="Edit parent" onSaved={onDetailsSaved} />
            <EditLeadDetailsAction user={user} leadId={lead.id} section="student" label="Edit student" onSaved={onDetailsSaved} />
          </div>
        }
      >
        <Fields>
          <Field label="Student">{redemo.student_name}</Field>
          <Field label="Class">{lead.grade ?? redemo.grade}</Field>
          <Field label="Syllabus">{lead.syllabus ?? redemo.syllabus}</Field>
          <Field label="School">{lead.school_name}</Field>
          <Field label="Country">{lead.country}</Field>
          <Field label="Time zone">
            <span className={lead.student_timezone ? undefined : 'text-muted-foreground font-normal'}>
              {lead.student_timezone ? savedTimezoneLabel(lead.student_timezone) : 'Not set (times read in IST)'}
            </span>
          </Field>
          <Field label="Parent">{redemo.parent_name}</Field>
          {redemo.phone ? (
            <Field label="Phone">
              <span className="tabular-nums">{redemo.phone}</span>
            </Field>
          ) : null}
          <Field label="Lead BDE">{redemo.owner_bde?.full_name ?? 'No BDE'}</Field>
        </Fields>
      </WorkspaceCard>

      <WorkspaceCard icon={ZapIcon} title="Quick actions">
        <div className="flex flex-col gap-2">
          <Button variant="outline" className="justify-start" disabled={!message} onClick={() => setMessageOpen(true)}>
            <MessageCircleIcon />
            {confirmed ? 'WhatsApp text: class details' : 'WhatsApp text: confirm with parent'}
          </Button>
          {messages ? null : (
            <p className="text-muted-foreground text-xs">The parent&apos;s message is ready once the Re-Demo is scheduled.</p>
          )}
          {original?.has_report ? (
            <PdfDownloadButton
              url={reportPdfUrl(bookingReportUrl('DEMO', original.id))}
              fallbackName={reportPdfFallbackName('DEMO', original.report_version)}
              label="Download the original Demo report"
              className="w-full justify-start"
              size="default"
            >
              Download original report
            </PdfDownloadButton>
          ) : (
            <Button variant="outline" className="justify-start" disabled>
              <DownloadIcon />
              No original report
            </Button>
          )}
        </div>
      </WorkspaceCard>

      {messages ? (
        <MessageDialog
          redemo={redemo}
          message={message}
          confirmed={confirmed}
          open={messageOpen}
          onOpenChange={setMessageOpen}
        />
      ) : null}
    </div>
  );
}
