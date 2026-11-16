import { useState } from 'react';
import { TicketIcon } from 'lucide-react';

import api from '@/lib/api';
import { paymentToday, TOKEN_AMOUNT, tokenDeadline, tokenSaleUrl, wholeAed } from '@/lib/payments';
import { enquiryLabel, quotePlanLabel, salesError } from '@/lib/sales';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FormDialog } from '@/components/form-dialog';
import { FamilyCandidates } from '@/components/sales/student-account';

// Refusals that mean the enquiry changed meanwhile (a sale started, a plan pinned or replaced): the page reloads.
const CONFLICTS = ['PLAN_CHANGED', 'PLAN_LOCKED', 'SALE_EXISTS', 'RESERVATION_DATES_FIXED'];

/** A Token Sale's figures for a quote preview: the package at its normal price, then what is left after the AED 100 token. */
function tokenFigures(preview) {
  const amount = Number(preview?.collection_amount);
  return { amount, balance: amount - TOKEN_AMOUNT, valid: amount > TOKEN_AMOUNT };
}

function Figure({ label, value, hint }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-muted-foreground text-xs font-medium uppercase">{label}</dt>
      <dd className="text-lg font-semibold">{value}</dd>
      <dd className="text-muted-foreground text-xs">{hint}</dd>
    </div>
  );
}

/**
 * Token Sale chosen with the plan (backend sales.token_sales): AED 100 first, then the remaining balance in one
 * payment by the deadline chosen here. No Single / Partial / AutoPay choice and no single-payment discount.
 * `reservation` is the enquiry's Token Sale when it already has one: its dates are fixed, only the plan is chosen again.
 */
export function TokenSalePanel({ preview, reservation, dates, onDates, onCreate, locked }) {
  const figures = tokenFigures(preview);
  const today = paymentToday();
  const datesReady = Boolean(reservation) || (dates.deadline >= today && dates.expected >= today);
  return (
    <div className="flex flex-col gap-4 rounded-lg border p-4">
      <div>
        <p className="font-medium">Token Sale – Payment details</p>
        <p className="text-muted-foreground text-sm">The AED 100 token first, then the remaining tuition in one payment. No Single / Partial / AutoPay choice.</p>
      </div>
      <dl className="grid gap-4 sm:grid-cols-3">
        <Figure label="First payment – fixed" value={wholeAed(TOKEN_AMOUNT)} hint="Token reservation amount" />
        <Figure label="Tuition package" value={wholeAed(figures.amount)} hint="Normal package price: no single-payment discount" />
        <Figure label="Remaining balance" value={figures.valid ? wholeAed(figures.balance) : '—'} hint="One payment, after the AED 100 token" />
      </dl>
      {!figures.valid ? (
        <p role="alert" className="text-destructive text-sm">
          A Token Sale needs a package worth more than AED 100: choose a larger plan.
        </p>
      ) : null}
      {reservation ? (
        <p className="text-sm">
          Reservation <strong>{reservation.reservation_reference}</strong> · Expected class start {reservation.expected_start_date} · Payment deadline{' '}
          {tokenDeadline(reservation)}. The reservation’s dates stay as they are: only its tuition plan is chosen again.
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="token-balance-due-date">Full payment deadline</Label>
            <Input id="token-balance-due-date" type="date" min={today} required value={dates.deadline}
              onChange={(event) => onDates({ ...dates, deadline: event.target.value })} disabled={locked} />
            <p className="text-muted-foreground text-xs">The parent pays the remaining tuition amount by this date.</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="token-start-date">Expected class start date</Label>
            <Input id="token-start-date" type="date" min={today} required value={dates.expected}
              onChange={(event) => onDates({ ...dates, expected: event.target.value })} disabled={locked} />
            <p className="text-muted-foreground text-xs">When classes are expected to begin: a separate date from the payment deadline.</p>
          </div>
        </div>
      )}
      <p className="text-muted-foreground text-xs">
        The AED 100 token alone never enrolls the student or adds class quota: enrollment follows the verified full balance. The enquiry’s parent
        details are used for payment.
      </p>
      <div>
        <Button onClick={onCreate} disabled={locked || !figures.valid || !datesReady}>
          <TicketIcon />
          {reservation ? 'Choose this plan for the reservation…' : 'Create token reservation…'}
        </Button>
      </div>
    </div>
  );
}

/**
 * Issuing the Token Sale quote for the plan chosen and -- the first time -- its token reservation, in one request.
 * Nothing about the parent is asked: the enquiry's details are the billing contact. Only when the parent's phone or
 * email already belongs to a family (`candidates`) is the family confirmed, as when a New Sale starts.
 * `onReserved({ quote, state })` gets the quote and the sale. The enquiry changed meanwhile: `onConflict()`; a revision or
 * pricing replaced, or the plan withdrawn: `onRefused(refusal)`. Any other refusal stays in the dialog.
 */
export function TokenSaleDialog({ open, onOpenChange, enquiry, detail, planType, classMode = 'REGULAR', chapterIds, preview, coverage, replaces,
  reservation, dates, candidates = [], onReserved, onRefused, onConflict }) {
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [family, setFamily] = useState({ family: { mode: 'NEW_FAMILY' }, confirm_distinct_child: false });
  // Families the API found when it refused (FAMILY_CONFIRMATION_REQUIRED): newer than the ones the page read.
  const [found, setFound] = useState(null);
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setFailure(null);
      setFamily({ family: { mode: 'NEW_FAMILY' }, confirm_distinct_child: false });
      setFound(null);
    }
  }
  const families = found ?? candidates;
  const choosing = !reservation && families.length > 0;
  const figures = tokenFigures(preview);

  const reserve = async () => {
    setPending(true);
    setFailure(null);
    try {
      const { data } = await api.post(tokenSaleUrl(enquiry.id), {
        syllabus: detail.id,
        revision: detail.revision,
        plan_type: planType,
        ...(planType === 'CHAPTER_PLAN' ? { class_mode: classMode } : {}),
        chapter_ids: chapterIds,
        replaces: replaces ?? null,
        pricing_version: detail.pricing.version,
        ...(reservation ? {} : { expected_start_date: dates.expected, balance_due_date: dates.deadline }),
        ...(choosing ? { family: family.family, confirm_distinct_child: family.confirm_distinct_child } : {}),
      });
      onOpenChange(false);
      onReserved(data);
    } catch (err) {
      const refused = salesError(err, 'Could not create the token reservation.');
      if (refused.code === 'FAMILY_CONFIRMATION_REQUIRED' && Array.isArray(err.response?.data?.candidates)) setFound(err.response.data.candidates);
      if (CONFLICTS.includes(refused.code)) {
        onOpenChange(false);
        onConflict();
      } else if (['REVISION_CHANGED', 'PRICING_CHANGED'].includes(refused.code) || refused.status === 404) {
        onOpenChange(false);
        onRefused({ status: refused.status, code: refused.code, message: refused.message, revision: err.response?.data?.revision ?? null });
      } else {
        setFailure(refused);
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={reservation ? 'Choose the tuition plan for the token reservation' : 'Create token reservation'}
      description={`${detail.title} · ${quotePlanLabel({ plan_type: planType, class_mode: classMode, full_course: preview?.fullCourse })} · ${coverage}`}
      error={failure ? failure.message : null}
      onConfirm={reserve}
      confirmLabel={reservation ? 'Issue Token Sale quote' : 'Create token reservation'}
      pendingLabel="Creating…"
      confirmDisabled={!figures.valid || (choosing && !family.confirm_distinct_child)}
      pending={pending}
      size="lg"
      contentClassName="max-h-[90vh] overflow-y-auto"
    >
      <div className="flex flex-col gap-4">
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div><dt className="text-muted-foreground">Tuition package (Token Sale)</dt><dd className="font-medium">{wholeAed(figures.amount)}</dd></div>
          <div><dt className="text-muted-foreground">Token, paid first</dt><dd className="font-medium">{wholeAed(TOKEN_AMOUNT)}</dd></div>
          <div><dt className="text-muted-foreground">Remaining balance, one payment</dt><dd className="font-medium">{figures.valid ? wholeAed(figures.balance) : '—'}</dd></div>
          <div><dt className="text-muted-foreground">Payment deadline</dt><dd className="font-medium">{reservation ? tokenDeadline(reservation) : dates.deadline}</dd></div>
          <div><dt className="text-muted-foreground">Expected class start</dt><dd className="font-medium">{reservation ? reservation.expected_start_date : dates.expected}</dd></div>
          {reservation ? <div><dt className="text-muted-foreground">Reservation</dt><dd className="font-medium">{reservation.reservation_reference}</dd></div> : null}
        </dl>
        {enquiry ? <p className="text-sm font-medium">For {enquiryLabel(enquiry)}</p> : null}
        {choosing ? <FamilyCandidates candidates={families} value={family} onChange={setFamily} /> : null}
        {replaces ? <p className="text-muted-foreground text-sm">This becomes the current plan. The previous quote remains in history.</p> : null}
        <p className="text-muted-foreground text-xs">
          The quote is priced at the pricing in effect now, without the single-payment discount, and kept exactly as issued. The sale type is fixed once
          the reservation exists, and the reservation’s dates cannot be changed later.
        </p>
      </div>
    </FormDialog>
  );
}
