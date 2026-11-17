import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeftIcon, FileTextIcon, ReceiptTextIcon, TicketIcon } from 'lucide-react';

import api from '@/lib/api';
import { can, PERMISSIONS } from '@/lib/access';
import { saleUrl, tokenDeadline, tokenStatusLabel } from '@/lib/payments';
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
import { TokenSaleDialog, TokenSalePanel } from './token-sale';

// How an enquiry's sale starts, chosen with its plan (backend sales.token_sales). Fixed once the sale exists.
const SALE_TYPES = [
  { value: 'NEW', label: 'New Sale', hint: 'Purchase the tuition package.', detail: 'Single / Complete, Partial or AutoPay.' },
  { value: 'TOKEN', label: 'Token Sale', hint: 'Reserve with a token: AED 100 first.', detail: 'Then the remaining balance in one payment by a deadline. No AutoPay.' },
];
const FIXED_TYPE = {
  NEW: 'This enquiry’s New Sale has started: the sale type is fixed.',
  TOKEN: 'This enquiry’s token reservation exists: the sale type is fixed.',
};
const saleTypesFor = (kind) =>
  SALE_TYPES.map((option) => (kind && option.value !== kind ? { ...option, disabled: true, note: FIXED_TYPE[kind] } : option));

/** The enquiry's token reservation (its sale state): the tuition plan chosen here is what the token is credited against. */
function TokenReservation({ state }) {
  const { sale } = state;
  return (
    <WorkspaceCard icon={TicketIcon} title="Token reservation">
      <Fields>
        <Field label="Reservation">{sale.reservation_reference}</Field>
        <Field label="Expected start">{sale.expected_start_date}</Field>
        <Field label="Payment deadline">{tokenDeadline(sale)}</Field>
        <Field label="Token (AED 100)">{tokenStatusLabel(sale, state.payments)}</Field>
      </Fields>
      <p className="text-muted-foreground text-sm">
        The plan chosen here is the tuition package, quoted as a Token Sale: no single-payment discount, the AED 100 token credited against it,
        and the remaining balance paid in one payment. It must be worth more than AED 100.
      </p>
    </WorkspaceCard>
  );
}

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

/**
 * One selected syllabus only; all selection and pricing helpers are shared with Sales. With the enquiry's `sale`
 * state (read only with initial-sales access), the plan is followed by its sale type: New Sale, or Token Sale.
 */
function PlanConfiguration({ syllabusId, enquiry, initialQuote, replaces, locked, sale = null, saleRefused = false, onBack, onIssued, onReserved, onConflict }) {
  const [detail, setDetail] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [planType, setPlanType] = useState(null);
  const [bridgeMode, setBridgeMode] = useState(null);
  const [classMode, setClassMode] = useState('REGULAR');
  const [collectionMode, setCollectionMode] = useState(null);
  const [chapterIds, setChapterIds] = useState([]);
  const [quoting, setQuoting] = useState(false);
  const [refusal, setRefusal] = useState(null);
  const [saleType, setSaleType] = useState(null);
  const [dates, setDates] = useState({ deadline: '', expected: '' });
  const [reserving, setReserving] = useState(false);

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
        setCollectionMode(restore && initialQuote.collection_intention_confirmed && initialQuote.collection_mode !== 'TOKEN' ? initialQuote.collection_mode : null);
        // A saved New Sale quote reopens as a New Sale; a Token Sale's type comes from its reservation.
        setSaleType(restore && initialQuote.collection_intention_confirmed && initialQuote.collection_mode !== 'TOKEN' ? 'NEW' : null);
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
  // The sale type: the enquiry's sale fixes it; before one starts, the BDE chooses it here.
  const kind = sale?.sale?.kind ?? null;
  const reservation = kind === 'TOKEN' ? sale.sale : null;
  const type = sale ? kind ?? saleType : 'NEW';
  const mode = type === 'TOKEN' ? 'TOKEN' : collectionMode;
  const preview = plan && (!partial || ids.length) ? quotePreview(plan, detail.chapters, ids, detail.pricing, classMode, mode) : null;
  const disabled = locked || Boolean(refusal);
  const coverage = preview?.fullCourse ? 'full course' : `${ids.length} selected chapters`;

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
      {saleRefused ? (
        <Notice>
          This enquiry’s sale could not be read, so Token Sale is not offered here. If it has a token reservation, an administrator chooses its
          plan; otherwise a New Sale quote can still be chosen.
        </Notice>
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
        collectionMode={collectionMode}
        onCollectionMode={setCollectionMode}
        saleTypes={sale ? saleTypesFor(kind) : null}
        saleType={type}
        onSaleType={setSaleType}
        tokenPanel={<TokenSalePanel preview={preview} reservation={reservation} dates={dates} onDates={setDates} onCreate={() => setReserving(true)} locked={disabled} />}
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
        collectionMode={collectionMode}
        classMode={classMode}
        chapterIds={ids}
        preview={preview}
        coverage={coverage}
        enquiry={enquiry}
        replaces={replaces}
        onIssued={onIssued}
        onRefused={(reason) => {
          if (['PLAN_CHANGED', 'PLAN_LOCKED'].includes(reason.code)) onConflict();
          else setRefusal(reason);
        }}
      />
      {sale ? (
        <TokenSaleDialog
          open={reserving}
          onOpenChange={setReserving}
          enquiry={enquiry}
          detail={detail}
          planType={plan}
          classMode={classMode}
          chapterIds={ids}
          preview={preview}
          coverage={coverage}
          replaces={replaces}
          reservation={reservation}
          dates={dates}
          candidates={sale.family_candidates ?? []}
          onReserved={onReserved}
          onRefused={setRefusal}
          onConflict={onConflict}
        />
      ) : null}
    </div>
  );
}

export function EnquiryPlanChoosing({ enquiry, user }) {
  const [saved, setSaved] = useState(null);
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [view, setView] = useState('saved');
  const [selected, setSelected] = useState(null);
  const [notice, setNotice] = useState(null);
  // The enquiry's sale as Sales & Payment reads it, kept with the enquiry it was read for.
  const [sale, setSale] = useState(null);
  const readsSale = can(user, PERMISSIONS.manageInitialSales);
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

  // The enquiry's sale: a started sale fixes the sale type; without one the BDE chooses it with the plan. Without
  // the read (no access, not read yet, or refused) only a New Sale quote is offered, which the API refuses for a
  // Token Sale either way; a refused read says so.
  useEffect(() => {
    if (!readsSale) return undefined;
    let active = true;
    api
      .get(saleUrl(enquiry.id))
      .then(({ data }) => {
        if (active) setSale({ enquiryId: enquiry.id, state: data });
      })
      .catch(() => {
        if (active) setSale({ enquiryId: enquiry.id, state: null, refused: true });
      });
    return () => {
      active = false;
    };
  }, [enquiry.id, readsSale, reloadKey]);

  if (failure) return <ErrorState message={failure.message} onRetry={reload} />;
  if (!saved) return <Skeleton className="h-64 w-full" aria-busy="true" />;
  const configuring = view === 'configure';
  const browsing = view === 'catalogue' || (view === 'saved' && !saved.current);
  // Never another enquiry's sale: the admin's LeadPage keeps this mounted from one lead to the next.
  const saleState = readsSale && sale?.enquiryId === enquiry.id ? sale.state : null;
  const saleRefused = readsSale && sale?.enquiryId === enquiry.id && Boolean(sale.refused);
  const tokenSale = saleState?.sale?.kind === 'TOKEN';
  // A newly issued quote becomes the current plan; the earlier ones stay in its history.
  const adopt = (quote) => {
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
  };

  return (
    <div className="flex flex-col gap-5">
      {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}
      {tokenSale && !saleState.sale.student ? <TokenReservation state={saleState} /> : null}
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
            sale={saleState}
            saleRefused={saleRefused}
            onBack={() => setView('catalogue')}
            onConflict={reload}
            onIssued={(quote) => {
              adopt(quote);
              setNotice(`Quote ${quote.reference} is now the current selected plan.`);
            }}
            onReserved={({ quote, state }) => {
              adopt(quote);
              setSale({ enquiryId: enquiry.id, state });
              setNotice(
                tokenSale
                  ? `Quote ${quote.reference} is now the token reservation’s tuition plan.`
                  : `Token reservation ${state.sale.reservation_reference} is created with quote ${quote.reference}. Collect the AED 100 token in Sales & Payment.`
              );
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
