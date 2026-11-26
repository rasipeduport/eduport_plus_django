import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import {
  AlertTriangleIcon,
  ArrowLeftIcon,
  HandCoinsIcon,
  HistoryIcon,
  HourglassIcon,
  ListChecksIcon,
  PlusIcon,
  SlidersHorizontalIcon,
  WalletIcon,
} from 'lucide-react';

import api from '@/lib/api';
import { PERMISSIONS, can } from '@/lib/access';
import {
  EARNINGS_API,
  classSubject,
  classTypeLabel,
  countsLine,
  dayLabel,
  earningsError,
  formatInr,
  monthLabel,
  CONVERSION,
  rateLabel,
  reviewDetail,
  stampLabel,
} from '@/lib/earnings';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel } from '@/components/dashboard/dashboard-primitives';
import { Tile } from '@/components/dashboard/kpi-cards';
import { Page, PageHeader } from '@/components/page/page';
import { AccessDeniedState, ErrorState, Notice } from '@/components/page/states';
import {
  BreakdownCard,
  LedgerCard,
  MonthFilter,
  MonthsCard,
  NotCountedCard,
  PaymentsCard,
  RateSourceBadge,
  SyncNote,
} from '@/components/earnings/parts';
import {
  AdjustmentDialog,
  KeepEarningDialog,
  RecordPaymentDialog,
  ReverseEntryDialog,
  TutorRatesDialog,
  VoidPaymentDialog,
} from '@/components/earnings/dialogs';

/** The tutor's rates in effect, each with where it comes from, and the rate history. */
function RatesPanel({ data, onEdit }) {
  const history = [
    ...data.rate_history.tutor.map((version) => ({ ...version, whose: 'Tutor' })),
    ...data.rate_history.global.map((version) => ({ ...version, whose: 'Global' })),
  ].sort((a, b) => (a.effective_from < b.effective_from ? 1 : -1));
  return (
    <Panel
      icon={SlidersHorizontalIcon}
      title={`Rates for ${data.tutor.name}`}
      action={
        onEdit ? (
          <Button size="sm" variant="outline" onClick={onEdit}>
            Edit
          </Button>
        ) : null
      }
    >
      <ul className="flex flex-col divide-y text-sm">
        {data.rates.map((row) => (
          <li key={row.class_type} className="flex items-start justify-between gap-3 py-2">
            <div>
              <p className="font-medium">{classTypeLabel(row.class_type)}</p>
              <p className="text-muted-foreground text-xs">
                {row.source === 'TUTOR'
                  ? `Overrides the global ${rateLabel(row.global_amount, row.unit)}`
                  : row.amount
                    ? 'Uses the global rate'
                    : 'No rate yet'}
              </p>
              {row.class_type === CONVERSION ? (
                <p className="text-muted-foreground text-xs">In all, for a converted Demo; adds the difference over the Demo</p>
              ) : null}
            </div>
            <div className="flex flex-col items-end gap-1">
              <span className="font-medium tabular-nums">{rateLabel(row.amount, row.unit)}</span>
              <RateSourceBadge source={row.source} />
            </div>
          </li>
        ))}
      </ul>
      <details className="mt-2 text-sm">
        <summary className="flex cursor-pointer items-center gap-2 font-medium">
          <HistoryIcon className="size-4" aria-hidden="true" />
          Rate history
        </summary>
        <ul className="mt-2 flex flex-col gap-2">
          {history.map((version) => (
            <li key={version.id} className="text-xs">
              <strong>{version.whose}</strong> · {classTypeLabel(version.class_type)}:{' '}
              {version.amount ? rateLabel(version.amount, version.unit) : 'back to the global rate'} · from{' '}
              {stampLabel(version.effective_from)}
              {version.initial ? ' (initial pricing)' : ''} · {version.created_by?.name}
              {version.reason ? ` · ${version.reason}` : ''}
            </li>
          ))}
        </ul>
        <p className="text-muted-foreground mt-2 text-xs">
          A change applies to classes ending, or students enrolling, after it is saved. Earned classes and conversions keep
          the rate stored with them.
        </p>
      </details>
    </Panel>
  );
}

/**
 * One tutor's earnings, for administrators (Tutor Earnings): the period's
 * totals and outstanding balance, the breakdown by class type with the rate
 * applied and where it came from, the rates and their history, the classes
 * not counted yet, the ledger, the payments and the months. The actions --
 * the tutor's rates, an adjustment, recording or voiding a payment, reversing
 * an entry -- are each offered on their own permission; the API checks them all.
 */
export default function TutorEarningsDetailPage({ user }) {
  const { tutorId } = useParams();
  const [params, setParams] = useSearchParams();
  const month = params.get('month') || '';
  const [classType, setClassType] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [entries, setEntries] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const [dialog, setDialog] = useState(null);

  const canRates = can(user, PERMISSIONS.manageTutorRates);
  const canPay = can(user, PERMISSIONS.manageTutorPayments);
  const canCorrect = can(user, PERMISSIONS.correctTutorEarnings);
  const query = month ? { month } : {};

  useEffect(() => {
    let active = true;
    setPending(true);
    Promise.all([
      api.get(`${EARNINGS_API}/tutors/${tutorId}/`, { params: query }),
      api.get(`${EARNINGS_API}/tutors/${tutorId}/entries/`, {
        params: { ...query, page, ...(classType ? { class_type: classType } : {}) },
      }),
    ])
      .then(([detail, ledger]) => {
        if (!active) return;
        setData(detail.data);
        setEntries(ledger.data);
        setFailure(null);
      })
      .catch((err) => {
        if (active) setFailure(earningsError(err, "Could not load the tutor's earnings."));
      })
      .finally(() => {
        if (active) setPending(false);
      });
    return () => {
      active = false;
    };
    // `query` is derived from `month`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tutorId, month, classType, page, reloadKey]);

  const reload = (message) => {
    if (message) setNotice(message);
    setReloadKey((key) => key + 1);
  };
  const pickMonth = (value) => {
    const next = new URLSearchParams(params);
    if (value) next.set('month', value);
    else next.delete('month');
    setParams(next, { replace: true });
    setPage(1);
  };

  let content;
  if (failure?.status === 403) {
    content = <AccessDeniedState title="You don't have access to Tutor Earnings." message={failure.message} />;
  } else if (failure?.status === 404) {
    content = <AccessDeniedState title="No such tutor." message="This account is not a tutor and has no earnings." />;
  } else if (failure && !data) {
    content = <ErrorState message={failure.message} onRetry={() => reload()} pending={pending} />;
  } else if (!data) {
    content = (
      <div className="flex flex-col gap-4" aria-busy="true">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-72 rounded-xl" />
      </div>
    );
  } else {
    const summary = data.summary;
    const owed = Number(summary.outstanding);
    const overpaid = summary.balance_state === 'overpaid';
    const period = month ? monthLabel(month) : 'All time';
    content = (
      <div className="flex flex-col gap-4">
        {notice ? <Notice onDismiss={() => setNotice(null)}>{notice}</Notice> : null}
        {failure ? <ErrorState message={failure.message} onRetry={() => reload()} pending={pending} /> : null}
        {!data.pricing ? (
          <p role="status" className="border-warning/40 bg-warning/10 rounded-xl border px-4 py-3 text-sm">
            Pricing has not started: this tutor's eligible classes are counted but not priced, and nothing is owed yet.
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <MonthFilter months={data.months} value={month} onChange={pickMonth} />
          <p className="text-muted-foreground text-xs">
            The period filters earnings, classes and payments. The outstanding balance is always all-time.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Tile icon={WalletIcon} tone="info" label="Total earned" value={formatInr(summary.earned)} hint={`${period} · ${summary.classes} eligible classes`} />
          <Tile
            icon={HandCoinsIcon}
            tone="success"
            label="Total paid"
            value={formatInr(summary.paid)}
            hint={`${period} · ${summary.payments} ${summary.payments === 1 ? 'payment' : 'payments'}${
              summary.voided_payments ? ` · ${summary.voided_payments} voided, not counted` : ''
            }${summary.last_paid_on ? ` · last ${dayLabel(summary.last_paid_on)}` : ''}`}
          />
          <Tile
            icon={HourglassIcon}
            tone={overpaid ? 'destructive' : 'warning'}
            label={overpaid ? 'Overpaid' : 'Outstanding balance'}
            value={formatInr(Math.abs(owed))}
            hint={overpaid ? 'Paid more than earned; no payment until new earnings cover it' : 'Earned − paid, all time'}
          />
          <Tile icon={ListChecksIcon} label="Eligible classes" value={summary.classes} hint={countsLine(summary)} />
        </div>

        {data.review.length ? (
          <div role="alert" className="border-warning/40 bg-warning/5 grid gap-2 rounded-xl border px-4 py-3 text-sm">
            <p className="flex items-center gap-2 font-medium">
              <AlertTriangleIcon className="text-warning size-4" aria-hidden="true" />
              {data.review.length} {data.review.length === 1 ? 'earning needs' : 'earnings need'} review
            </p>
            {data.review.map((item) => (
              <div key={item.entry.id} className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {classTypeLabel(item.entry.class_type, { singular: true })} · {classSubject(item.entry)} ·{' '}
                  {dayLabel(item.entry.class_start)} · earned {formatInr(item.entry.amount)}. {reviewDetail(item)}
                </span>
                {canCorrect ? (
                  <span className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" onClick={() => setDialog({ kind: 'reverse', entry: item.entry })}>
                      Reverse earning…
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setDialog({ kind: 'keep', item })}>
                      Keep as earned…
                    </Button>
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        <div className="grid gap-4 xl:grid-cols-3">
          <div className="min-w-0 xl:col-span-2">
            <BreakdownCard breakdown={data.breakdown} adjustments={data.adjustments} total={summary.earned} admin />
          </div>
          <RatesPanel data={data} onEdit={canRates && data.pricing && data.tutor.is_tutor ? () => setDialog({ kind: 'rates' }) : null} />
        </div>

        <NotCountedCard items={data.not_counted} />

        <LedgerCard
          data={entries}
          admin
          classType={classType}
          onClassType={(value) => {
            setClassType(value);
            setPage(1);
          }}
          onPage={setPage}
          onReverse={canCorrect ? (entry) => setDialog({ kind: 'reverse', entry }) : null}
          pending={pending}
        />

        <PaymentsCard
          payments={data.payments}
          admin
          onVoid={canPay ? (payment) => setDialog({ kind: 'void', payment }) : null}
          action={
            canPay ? (
              <Button size="sm" variant="outline" onClick={() => setDialog({ kind: 'pay' })} disabled={!data.pricing || owed <= 0}>
                Record payment
              </Button>
            ) : null
          }
        />

        <MonthsCard months={data.months_breakdown} onPick={pickMonth} />
        <SyncNote lastSync={data.last_sync} />
      </div>
    );
  }

  const owed = data ? Number(data.summary.outstanding) : 0;
  const payDisabledWhy = data && (!data.pricing ? 'Pricing has not started.' : owed <= 0 ? 'Nothing is outstanding.' : null);

  return (
    <Page>
      <Button variant="ghost" size="sm" className="-mb-2 self-start" asChild>
        <Link to="/tutor-earnings">
          <ArrowLeftIcon />
          All tutors
        </Link>
      </Button>
      <PageHeader
        title={data ? data.tutor.name : 'Tutor earnings'}
        description={
          data ? (
            <span className="flex flex-wrap items-center gap-2">
              {data.tutor.email}
              {data.tutor.active ? null : <Badge variant="secondary">Inactive</Badge>}
              {data.own_rates ? <Badge variant="info">Tutor-specific rates</Badge> : <Badge variant="outline">Global rates</Badge>}
            </span>
          ) : null
        }
        actions={
          data ? (
            <>
              {canRates && data.pricing && data.tutor.is_tutor ? (
                <Button variant="outline" onClick={() => setDialog({ kind: 'rates' })}>
                  Edit tutor rates
                </Button>
              ) : null}
              {canCorrect && data.activated_at ? (
                <Button variant="outline" onClick={() => setDialog({ kind: 'adjust' })}>
                  Add adjustment
                </Button>
              ) : null}
              {canPay ? (
                <Button onClick={() => setDialog({ kind: 'pay' })} disabled={Boolean(payDisabledWhy)} title={payDisabledWhy || undefined}>
                  <PlusIcon />
                  Record payment
                </Button>
              ) : null}
            </>
          ) : null
        }
      />
      {content}
      {data ? (
        <>
          <RecordPaymentDialog
            tutor={data.tutor}
            outstanding={data.summary.outstanding}
            open={dialog?.kind === 'pay'}
            onOpenChange={(next) => !next && setDialog(null)}
            onSaved={(answer) => reload(`Payment of ${formatInr(answer.payment.amount)} recorded for ${data.tutor.name}.`)}
          />
          <VoidPaymentDialog
            payment={dialog?.kind === 'void' ? dialog.payment : null}
            tutorName={data.tutor.name}
            open={dialog?.kind === 'void'}
            onOpenChange={(next) => !next && setDialog(null)}
            onSaved={(answer) => reload(`Payment of ${formatInr(answer.payment.amount)} voided.`)}
          />
          <ReverseEntryDialog
            entry={dialog?.kind === 'reverse' ? dialog.entry : null}
            tutorName={data.tutor.name}
            open={dialog?.kind === 'reverse'}
            onOpenChange={(next) => !next && setDialog(null)}
            onSaved={(answer) => reload(`Reversed: ${formatInr(answer.entry.amount, { signed: true })}.`)}
          />
          <KeepEarningDialog
            item={dialog?.kind === 'keep' ? dialog.item : null}
            tutorName={data.tutor.name}
            open={dialog?.kind === 'keep'}
            onOpenChange={(next) => !next && setDialog(null)}
            onSaved={() => reload('Kept as earned.')}
            onStale={() => reload()}
          />
          <AdjustmentDialog
            tutor={data.tutor}
            months={data.months}
            entries={entries?.results}
            open={dialog?.kind === 'adjust'}
            onOpenChange={(next) => !next && setDialog(null)}
            onSaved={(answer) => reload(`Adjustment of ${formatInr(answer.entry.amount, { signed: true })} added.`)}
          />
          <TutorRatesDialog
            tutor={data.tutor}
            rates={data.rates}
            open={dialog?.kind === 'rates'}
            onOpenChange={(next) => !next && setDialog(null)}
            onSaved={() => reload(`Rates for ${data.tutor.name} saved.`)}
          />
        </>
      ) : null}
    </Page>
  );
}
