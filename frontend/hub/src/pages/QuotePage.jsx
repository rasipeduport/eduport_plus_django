import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeftIcon,
  BadgePercentIcon,
  BanIcon,
  DownloadIcon,
  FileSearchIcon,
  ListOrderedIcon,
  Loader2Icon,
  ReceiptTextIcon,
  SearchXIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can, canOpenPage } from '@/lib/access';
import { enquiryLabel, formatAmount, quotePdfUrl, quotePlanLabel, quoteUrl, salesError, structureLabel } from '@/lib/sales';
import { formatDate } from '@/lib/utils';
import { useFlashNotice } from '@/hooks/use-flash-notice';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState, Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';
import { ResponsiveList } from '@/components/page/responsive-list';
import { Field, Fields, WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { CancelQuoteDialog } from '@/components/sales/quote-dialogs';
import { QuoteFigures, QuoteStatusBadge } from '@/components/sales/quote-parts';
import { useSyllabusPdf } from '@/components/sales/syllabus-pdf';

const WHEN = { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' };

const BackToQuotes = ({ manager }) => (
  <Button variant="outline" asChild>
    <Link to="/quotes">
      <ArrowLeftIcon />
      {manager ? 'Quotes' : 'My Quotes'}
    </Link>
  </Button>
);

/** Where the enquiry a quote answers opens for `user`: their own enquiry, or the lead for whoever sees every lead. */
function enquiryPath(user, lead) {
  if (canOpenPage(user, '/enquiries')) return `/enquiries/${lead.id}`;
  if (canOpenPage(user, '/leads')) return `/leads/${lead.id}`;
  return null;
}

/**
 * One quote, as it was issued (the API keeps it so): the plan and revision it
 * quoted, the enquiry it answers, its rates, packages and figures, the
 * chapters or days it covers, and its PDF -- drawn from the quote alone, so
 * it reads as it did that day whatever has changed since. Whoever manages
 * quotes (`user`) may cancel an issued one, saying why; a cancelled quote
 * stays cancelled, its PDF marked CANCELLED on every page.
 */
export default function QuotePage({ user }) {
  const { quoteId } = useParams();
  const manager = can(user, PERMISSIONS.manageSalesQuotes);
  const [quote, setQuote] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [cancelling, setCancelling] = useState(false);
  const [notice, setNotice] = useFlashNotice();
  const pdf = useSyllabusPdf({ snapshot: true });

  useEffect(() => {
    let active = true;
    api
      .get(quoteUrl(quoteId))
      .then((response) => {
        if (!active) return;
        setQuote(response.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load the quote.'));
      });
    return () => {
      active = false;
    };
  }, [quoteId, reloadKey]);

  const reload = () => setReloadKey((key) => key + 1);

  if (failure?.status === 403) {
    return (
      <Page>
        <AccessDeniedState title="You don't have access to quotes." message={failure.message} />
      </Page>
    );
  }
  if (failure?.status === 404) {
    return (
      <Page>
        <EmptyState
          icon={SearchXIcon}
          title="Quote not found"
          description="It may not be one of yours, or the link may be wrong."
          action={<BackToQuotes manager={manager} />}
        />
      </Page>
    );
  }
  if (failure && !quote) {
    return (
      <Page>
        <ErrorState message={failure.message} onRetry={reload} />
      </Page>
    );
  }
  if (!quote) {
    return (
      <Page>
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </Page>
    );
  }

  const cancelled = quote.status === 'CANCELLED';
  const bridge = quote.syllabus.structure === 'BRIDGE_COURSE';
  const { currency } = quote;
  const leadPath = quote.lead ? enquiryPath(user, quote.lead) : null;
  const noun = bridge ? 'Day' : 'Chapter';
  const columns = [
    { key: 'number', header: bridge ? 'Day' : 'No.', className: 'w-16 tabular-nums', cell: (row) => row.position },
    { key: 'name', header: 'Chapter name', className: 'whitespace-normal', cell: (row) => row.name },
    { key: 'classes', header: 'Classes', className: 'w-24 tabular-nums', cell: (row) => row.classes },
  ];
  const renderCard = (row) => (
    <div className="bg-card flex items-start gap-3 rounded-xl border p-3 text-sm">
      <span className="min-w-0 flex-1">
        <span className="text-muted-foreground block text-xs tabular-nums">
          {noun} {row.position}
        </span>
        <span className="block">{row.name}</span>
      </span>
      <span className="text-muted-foreground shrink-0 tabular-nums">{row.classes}</span>
    </div>
  );

  return (
    <Page className="max-w-5xl">
      <PageHeader
        title={`Quote ${quote.reference}`}
        description={`${quote.syllabus.title} · ${quotePlanLabel(quote)}`}
        actions={
          <>
            <BackToQuotes manager={manager} />
            <Button variant="outline" onClick={() => pdf.preview(quotePdfUrl(quote.id))} disabled={Boolean(pdf.pending)}>
              {pdf.pending === 'preview' ? <Loader2Icon className="size-4 animate-spin" /> : <FileSearchIcon />}
              Preview PDF
            </Button>
            <Button onClick={() => pdf.download(quotePdfUrl(quote.id), `${quote.reference}.pdf`)} disabled={Boolean(pdf.pending)}>
              {pdf.pending === 'download' ? <Loader2Icon className="size-4 animate-spin" /> : <DownloadIcon />}
              Download PDF
            </Button>
            {manager && !cancelled ? (
              <Button variant="destructive" onClick={() => setCancelling(true)}>
                <BanIcon />
                Cancel quote…
              </Button>
            ) : null}
          </>
        }
        actionsClassName="items-center"
      />

      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}
      {quote.lead ? (
        <p className="text-muted-foreground rounded-lg border p-3 text-sm">
          {quote.is_current
            ? 'Current selected plan for this enquiry.'
            : quote.status === 'CANCELLED'
              ? 'Cancelled quote. It is not the current selected plan.'
              : 'Previous quote. It remains available as a historical record.'}
          {leadPath ? (
            <>
              {' '}
              <Link className="font-medium underline" to={`${leadPath}?tab=plan-choosing`}>
                View Plan Choosing
              </Link>
            </>
          ) : null}
        </p>
      ) : null}
      {pdf.error ? <ErrorState message={pdf.error} /> : null}
      {cancelled ? (
        <div role="note" className="border-destructive/30 bg-destructive/5 flex items-start gap-3 rounded-xl border px-4 py-3 text-sm">
          <BanIcon className="text-destructive mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <p className="font-medium">
              Cancelled on {formatDate(quote.cancelled_at, WHEN)}
              {quote.cancelled_by ? ` by ${quote.cancelled_by.name}` : ''}. It is no longer valid.
            </p>
            {quote.cancel_reason ? <p className="text-muted-foreground break-words">Reason: {quote.cancel_reason}</p> : null}
            <p className="text-muted-foreground">Its PDF is marked CANCELLED on every page; its figures are kept as issued.</p>
          </div>
        </div>
      ) : null}

      <WorkspaceCard icon={ReceiptTextIcon} title="Quote" action={<QuoteStatusBadge status={quote.status} />}>
        <Fields>
          <Field label="Reference">
            <span className="tabular-nums">{quote.reference}</span>
          </Field>
          <Field label="Issued">{formatDate(quote.created_at, WHEN)}</Field>
          <Field label="Issued by">{quote.created_by?.name}</Field>
          <Field label="For enquiry">
            {quote.lead ? (
              leadPath ? (
                <Link to={leadPath} className="hover:underline">
                  {enquiryLabel(quote.lead)}
                </Link>
              ) : (
                enquiryLabel(quote.lead)
              )
            ) : (
              <span className="text-muted-foreground font-normal">No enquiry named</span>
            )}
          </Field>
          <Field label="Plan">
            {quote.syllabus.title}
            <p className="text-muted-foreground text-xs font-normal">
              {[`Grade ${quote.syllabus.grade}`, quote.syllabus.board, quote.syllabus.syllabus_version, structureLabel(quote.syllabus.structure)]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </Field>
          <Field label="Quoted as">
            {quotePlanLabel(quote)}
            <p className="text-muted-foreground text-xs font-normal">
              Revision {quote.revision} · pricing version {quote.pricing_version}
            </p>
          </Field>
          <Field label="Fee per class">
            <span className="tabular-nums">{formatAmount(quote.offer_fee, currency)}</span>
            <span className="text-muted-foreground font-normal tabular-nums"> (standard {formatAmount(quote.standard_fee, currency)})</span>
          </Field>
        </Fields>
      </WorkspaceCard>

      <WorkspaceCard icon={BadgePercentIcon} title={quote.lines.length === 1 ? 'Package' : 'Packages'}>
        <QuoteFigures figures={quote} currency={currency} />
      </WorkspaceCard>

      <WorkspaceCard icon={ListOrderedIcon} title={`${bridge ? 'Days' : 'Chapters'} covered (${quote.chapters.length})`}>
        <ResponsiveList
          label={bridge ? 'Days covered' : 'Chapters covered'}
          columns={columns}
          rows={quote.chapters}
          minTableWidth={480}
          renderCard={renderCard}
        />
      </WorkspaceCard>

      {manager && !cancelled ? (
        <CancelQuoteDialog
          open={cancelling}
          onOpenChange={setCancelling}
          quote={quote}
          onCancelled={(updated) => {
            setQuote(updated);
            setNotice(`Quote ${updated.reference} is cancelled.`);
          }}
          onChanged={reload}
        />
      ) : null}
      {pdf.dialog}
    </Page>
  );
}
