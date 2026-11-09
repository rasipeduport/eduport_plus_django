import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeftIcon, FileTextIcon, ReceiptTextIcon } from 'lucide-react';

import api from '@/lib/api';
import { catalogueUrl, chapterPlanError, enquiryPlanUrl, quotePdfUrl, quotePlanLabel, quotePreview, salesError } from '@/lib/sales';
import { formatDate } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState, Notice } from '@/components/page/states';
import { Field, Fields, WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { QuotePlanCard } from '@/components/sales/quote-builder';
import { CreateQuoteDialog } from '@/components/sales/quote-dialogs';
import { QuoteChapters, QuoteFigures, QuoteStatusBadge } from '@/components/sales/quote-parts';
import { SyllabusActions } from '@/components/sales/syllabus-actions';
import { useSyllabusPdf } from '@/components/sales/syllabus-pdf';
import PlansPage from '@/pages/PlansPage';

function SavedPlan({ quote, locked, onEdit }) {
  const pdf = useSyllabusPdf({ snapshot: true });
  return (
    <WorkspaceCard icon={ReceiptTextIcon} title="Current selected plan" action={<Badge variant="success">Current quote</Badge>}>
      <Fields>
        <Field label="Syllabus">{quote.syllabus.title}</Field>
        <Field label="Plan">
          {quotePlanLabel(quote)}
          {quote.full_course ? ' · All chapters' : ''}
        </Field>
        <Field label="Quote">
          {quote.reference} · <QuoteStatusBadge status={quote.status} />
        </Field>
        <Field label="Created">
          {formatDate(quote.created_at, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })}
        </Field>
        <Field label="Version">
          Syllabus revision {quote.revision} · Pricing v{quote.pricing_version}
        </Field>
      </Fields>
      <QuoteFigures figures={quote} currency={quote.currency} />
      <QuoteChapters quote={quote} />
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => pdf.preview(quotePdfUrl(quote.id))} disabled={Boolean(pdf.pending)}>
          Preview quote PDF
        </Button>
        <Button variant="outline" onClick={() => pdf.download(quotePdfUrl(quote.id), `${quote.reference}.pdf`)} disabled={Boolean(pdf.pending)}>
          Download quote PDF
        </Button>
        <Button onClick={onEdit} disabled={locked}>
          Edit / change plan
        </Button>
      </div>
      {pdf.error ? <ErrorState message={pdf.error} /> : null}
      <p className="text-muted-foreground text-sm">Review this quote with the parent before proceeding to Sales &amp; Payment.</p>
      {pdf.dialog}
    </WorkspaceCard>
  );
}

/** One selected syllabus only; all selection and pricing helpers are shared with Sales. */
function PlanConfiguration({ syllabusId, enquiry, initialQuote, replaces, locked, onBack, onIssued, onConflict }) {
  const [detail, setDetail] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [planType, setPlanType] = useState(null);
  const [bridgeMode, setBridgeMode] = useState(null);
  const [classMode, setClassMode] = useState('REGULAR');
  const [chapterIds, setChapterIds] = useState([]);
  const [quoting, setQuoting] = useState(false);
  const [refusal, setRefusal] = useState(null);

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(catalogueUrl(syllabusId))
      .then(({ data }) => {
        if (!active) return;
        setDetail(data);
        const restore =
          reloadKey === 0 &&
          initialQuote?.syllabus.id === data.id &&
          initialQuote.revision === data.revision &&
          data.plan_types.includes(initialQuote.plan_type);
        setPlanType(restore ? initialQuote.plan_type : null);
        setClassMode(restore && initialQuote.plan_type === 'CHAPTER_PLAN' ? initialQuote.class_mode ?? 'REGULAR' : 'REGULAR');
        setBridgeMode(restore && initialQuote.plan_type === 'BRIDGE_COURSE' ? (initialQuote.full_course ? 'full' : 'selected') : null);
        const known = new Set(data.chapters.map((chapter) => chapter.id));
        setChapterIds(restore ? initialQuote.chapters.map((chapter) => chapter.id).filter((id) => known.has(id)) : []);
        setRefusal(null);
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load this syllabus.'));
      });
    return () => {
      active = false;
    };
  }, [syllabusId, initialQuote, reloadKey]);

  const reload = () => {
    setDetail(null);
    setReloadKey((key) => key + 1);
  };
  if (failure)
    return (
      <div className="flex flex-col gap-3">
        <Button variant="outline" onClick={onBack}>
          Back to syllabuses
        </Button>
        <ErrorState message={failure.message} onRetry={reload} />
      </div>
    );
  if (!detail) return <Skeleton className="h-64 w-full" aria-busy="true" />;
  const bridge = detail.structure === 'BRIDGE_COURSE';
  const plan = bridge && bridgeMode && detail.plan_types.includes('BRIDGE_COURSE') ? 'BRIDGE_COURSE' : planType;
  const partial = plan === 'CHAPTER_PLAN' || (bridge && bridgeMode === 'selected');
  const ids = partial ? chapterIds : [];
  const selectionError = plan === 'CHAPTER_PLAN' ? chapterPlanError(detail.chapters, ids, classMode) : null;
  const preview = plan && (!partial || ids.length) ? quotePreview(plan, detail.chapters, ids, detail.pricing, classMode) : null;
  const disabled = locked || Boolean(refusal);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Button variant="outline" onClick={onBack}>
          <ArrowLeftIcon /> Change syllabus
        </Button>
      </div>
      <WorkspaceCard icon={FileTextIcon} title={detail.title}>
        <p className="text-muted-foreground text-sm">
          {detail.subtitle} · Grade {detail.grade} · {detail.board} · Revision {detail.revision}
        </p>
        <SyllabusActions
          key={`${detail.id}:${detail.revision}`}
          syllabus={detail}
          enquiry={enquiry}
          disabled={!detail.pricing || Boolean(refusal)}
          onRefused={setRefusal}
        />
      </WorkspaceCard>
      {initialQuote?.syllabus.id === detail.id && initialQuote.revision !== detail.revision ? (
        <Notice>The syllabus was republished. Choose a plan from this revision before issuing a replacement.</Notice>
      ) : null}
      {refusal ? (
        <ErrorState message={refusal.message ?? 'This plan changed. Reload the syllabus and select the plan again.'} onRetry={reload} />
      ) : null}
      {!detail.pricing ? (
        <p role="status" className="text-muted-foreground text-sm">
          Pricing is not set up yet. A quote cannot be issued.
        </p>
      ) : null}
      <QuotePlanCard
        detail={detail}
        planType={plan}
        onPlanType={setPlanType}
        bridgeMode={bridgeMode}
        onBridgeMode={setBridgeMode}
        chapterIds={chapterIds}
        onChapterIds={setChapterIds}
        classMode={classMode}
        onClassMode={setClassMode}
        selectionError={selectionError}
        preview={preview}
        onCreate={() => setQuoting(true)}
        locked={disabled}
      />
      <CreateQuoteDialog
        open={quoting}
        onOpenChange={setQuoting}
        syllabusId={syllabusId}
        detail={detail}
        planType={plan}
        classMode={classMode}
        chapterIds={ids}
        preview={preview}
        coverage={preview?.fullCourse ? 'full course' : `${ids.length} selected chapters`}
        enquiry={enquiry}
        replaces={replaces}
        onIssued={onIssued}
        onRefused={(reason) => {
          if (['PLAN_CHANGED', 'PLAN_LOCKED'].includes(reason.code)) onConflict();
          else setRefusal(reason);
        }}
      />
    </div>
  );
}

export function EnquiryPlanChoosing({ enquiry }) {
  const [saved, setSaved] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [view, setView] = useState('saved');
  const [selected, setSelected] = useState(null);
  const [notice, setNotice] = useState(null);
  const reload = () => {
    setSaved(null);
    setView('saved');
    setSelected(null);
    setReloadKey((key) => key + 1);
  };

  useEffect(() => {
    let active = true;
    api
      .get(enquiryPlanUrl(enquiry.id))
      .then(({ data }) => {
        if (!active) return;
        setSaved(data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(salesError(err, 'Could not load this student’s plan.'));
      });
    return () => {
      active = false;
    };
  }, [enquiry.id, reloadKey]);

  if (failure) return <ErrorState message={failure.message} onRetry={reload} />;
  if (!saved) return <Skeleton className="h-64 w-full" aria-busy="true" />;
  const configuring = view === 'configure';
  const browsing = view === 'catalogue' || (view === 'saved' && !saved.current);

  return (
    <div className="flex flex-col gap-5">
      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}
      {saved.locked ? (
        <p role="status" className="text-muted-foreground rounded-lg border p-3 text-sm">
          This enquiry is locked against plan changes. Its saved quote remains available.
        </p>
      ) : null}
      {view === 'saved' && saved.current ? (
        <SavedPlan
          quote={saved.current}
          locked={saved.locked}
          onEdit={() => {
            setSelected(saved.current.syllabus.id);
            setView('configure');
          }}
        />
      ) : null}
      {view !== 'saved' && saved.current ? (
        <div>
          <Button variant="ghost" onClick={() => setView('saved')}>
            Return to saved plan
          </Button>
        </div>
      ) : null}
      {browsing && !saved.locked ? (
        <PlansPage
          enquiry={enquiry}
          onSelect={(row) => {
            setSelected(row.id);
            setView('configure');
          }}
        />
      ) : null}
      {/* Keep a valid configuration when browsing back or viewing the saved plan. */}
      {selected ? (
        <div hidden={!configuring}>
          <PlanConfiguration
            key={`${selected}:${reloadKey}`}
            syllabusId={selected}
            enquiry={enquiry}
            initialQuote={saved.current}
            replaces={saved.latest_quote}
            locked={saved.locked}
            onBack={() => setView('catalogue')}
            onConflict={reload}
            onIssued={(quote) => {
              setSaved({
                ...saved,
                current: quote,
                latest_quote: quote.id,
                history: [
                  quote,
                  ...saved.history.map((row) => ({
                    ...row,
                    is_current: false,
                    selection_status: row.status === 'CANCELLED' ? 'CANCELLED' : 'PREVIOUS',
                  })),
                ],
              });
              setSelected(null);
              setView('saved');
              setNotice(`Quote ${quote.reference} is now the current selected plan.`);
            }}
          />
        </div>
      ) : null}
      {saved.history.length ? (
        <WorkspaceCard icon={ReceiptTextIcon} title="Quote history">
          <ul className="divide-y">
            {saved.history.map((quote) => (
              <li key={quote.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
                <div>
                  <Link className="font-medium hover:underline" to={`/quotes/${quote.id}`}>
                    {quote.reference}
                  </Link>{' '}
                  · {quote.syllabus.title} · {quotePlanLabel(quote)}
                  <p className="text-muted-foreground text-xs">
                    {formatDate(quote.created_at)} · {quote.currency} {quote.payable_amount}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Badge variant={quote.is_current ? 'success' : 'secondary'}>
                    {quote.is_current ? 'Current' : quote.status === 'CANCELLED' ? 'Cancelled' : 'Previous'}
                  </Badge>
                  <QuoteStatusBadge status={quote.status} />
                </div>
              </li>
            ))}
          </ul>
        </WorkspaceCard>
      ) : null}
    </div>
  );
}
