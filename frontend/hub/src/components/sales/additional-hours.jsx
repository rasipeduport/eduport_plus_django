import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ArrowLeftIcon, BanIcon, ClockPlusIcon, DownloadIcon, EyeIcon, PencilIcon, PlusIcon, Undo2Icon, WalletIcon } from 'lucide-react';

import api from '@/lib/api';
import { salesError } from '@/lib/sales';
import { wholeAed } from '@/lib/payments';
import {
  allocationStatus, allocationUrl, chapterLabel, dueLabel, hours, OPEN_STATUSES, studentAdditionalHoursUrl, VOID_KINDS,
} from '@/lib/additional-hours';
import { formatDate } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState, Notice } from '@/components/page/states';
import { ResponsiveList } from '@/components/page/responsive-list';
import { Field, Fields, WorkspaceCard } from '@/components/bookings/redemo-workspace/parts';
import { useSyllabusPdf } from '@/components/sales/syllabus-pdf';
import {
  AddHoursDialog, ChangeHoursDialog, CloseHoursDialog, RecordHoursPaymentDialog, VoidHoursPaymentDialog,
} from '@/components/sales/additional-hours-dialogs';

const dateTime = (value) => formatDate(value, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });

/** An allocation's payment status, and -- apart from it -- whether it is overdue. */
export function AllocationBadges({ row }) {
  const status = allocationStatus(row);
  return <span className="flex flex-wrap items-center gap-1.5">
    <Badge variant={status.variant}>{status.label}</Badge>
    {row.overdue ? <Badge variant="destructive">Overdue</Badge> : null}
  </span>;
}

function Stat({ label, value, tone }) {
  return <div className="bg-muted/40 min-w-0 rounded-lg px-3 py-2">
    <dt className="text-muted-foreground text-xs">{label}</dt>
    <dd className={`truncate text-lg font-semibold tabular-nums ${tone ?? ''}`}>{value}</dd>
  </div>;
}

function HoursSummary({ summary }) {
  return <dl aria-label="Additional hours summary" className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
    <Stat label="Hours added" value={hours(summary.hours_added)} />
    <Stat label="Payment pending" value={hours(summary.payment_pending_hours)} />
    <Stat label="Amount" value={wholeAed(summary.amount)} />
    <Stat label="Received" value={wholeAed(summary.received)} tone="text-success" />
    <Stat label="Outstanding" value={wholeAed(summary.outstanding)} tone={Number(summary.outstanding) > 0 ? 'text-warning' : ''} />
    <Stat label="Overdue" value={summary.overdue_count ? `${summary.overdue_count} · ${wholeAed(summary.overdue_amount)}` : 'None'}
      tone={summary.overdue_count ? 'text-destructive' : ''} />
  </dl>;
}

/**
 * The student's additional hours on their Finance tab (backend
 * sales.additional_hours), for their mentor or an administrator: hours added on
 * top of the plans -- already in the class quota -- and what is still owed for
 * them, each with its own payments. Its own card and its own figures: none of
 * it is part of the purchases, payment history or AutoPay above. An
 * administrator adds hours (can_create); each allocation opens on its details
 * (?hours=<id>, which the pending list links to). Hidden for an account the API
 * does not answer.
 */
export function AdditionalHoursCard({ studentId }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const openId = searchParams.get('hours');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [hidden, setHidden] = useState(false);
  const [reload, setReload] = useState(0);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState('');
  const cardRef = useRef(null);

  useEffect(() => {
    let active = true;
    api.get(studentAdditionalHoursUrl(studentId))
      .then(({ data: next }) => { if (active) { setData(next); setError(null); } })
      .catch((err) => {
        if (!active) return;
        const refused = salesError(err, 'Could not load the additional hours.');
        if (refused.status === 403 || refused.status === 404) setHidden(true);
        else setError(refused);
      });
    return () => { active = false; };
  }, [studentId, reload]);

  // Opened from the pending list: bring the card into view once it has loaded.
  const loaded = Boolean(data);
  useEffect(() => {
    if (openId && loaded) cardRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }, [openId, loaded]);

  const refresh = () => setReload((key) => key + 1);
  const show = (id) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (id) next.set('hours', id); else next.delete('hours');
    return next;
  });

  if (hidden) return null;
  if (error && !data) {
    return <WorkspaceCard icon={ClockPlusIcon} title="Additional hours"><ErrorState message={error.message} onRetry={refresh} /></WorkspaceCard>;
  }
  if (!data) return <Skeleton className="h-40 w-full" aria-busy="true" />;

  return <div ref={cardRef} className="scroll-mt-6">
    {openId ? <AllocationDetail key={openId} allocationId={openId} onBack={() => show(null)} onChanged={refresh} />
      : <WorkspaceCard icon={ClockPlusIcon} title="Additional hours"
        action={data.can_create ? <Button size="sm" onClick={() => setAdding(true)}><PlusIcon />Add additional hours</Button> : null}>
        <p className="text-muted-foreground text-sm">Hours added on top of the plans: already in the student’s class quota and usable for any session, paid for separately by their due date. None of these figures is part of the purchases, payment history or AutoPay above.</p>
        {notice ? <Notice onDismiss={() => setNotice('')}>{notice}</Notice> : null}
        {error ? <ErrorState message={error.message} onRetry={refresh} /> : null}
        <HoursSummary summary={data.summary} />
        {data.allocations.length ? <AllocationList rows={data.allocations} onOpen={show} />
          : <p className="text-muted-foreground text-sm">No additional hours yet.</p>}
      </WorkspaceCard>}
    <AddHoursDialog studentId={studentId} student={data.student} open={adding} onOpenChange={setAdding}
      onCreated={(allocation) => { setNotice(`${hours(allocation.hours)} added to the quota (${allocation.reference}); ${wholeAed(allocation.amount)} due by ${formatDate(allocation.due_date)}.`); refresh(); }} />
  </div>;
}

function AllocationList({ rows, onOpen }) {
  const view = (row) => <Button size="sm" variant="outline" onClick={() => onOpen(row.id)} aria-label={`View ${row.reference}`}><EyeIcon />View</Button>;
  const columns = [
    { key: 'reference', header: 'Reference', cell: (row) => <span>{row.reference}<span className="text-muted-foreground block text-xs">{formatDate(row.created_at)}</span></span> },
    { key: 'plan', header: 'Plan / chapter', className: 'min-w-44 whitespace-normal', cell: (row) => <span>{row.plan.quote_reference} · {row.plan.syllabus}
      <span className="text-muted-foreground block text-xs">{chapterLabel(row.chapter)}</span></span> },
    { key: 'hours', header: 'Hours', cell: (row) => <span className={row.hours_status === 'WITHDRAWN' ? 'text-muted-foreground line-through' : ''}>{hours(row.hours)}</span> },
    { key: 'amount', header: 'Amount', cell: (row) => wholeAed(row.amount) },
    { key: 'paid', header: 'Paid', cell: (row) => wholeAed(row.paid_amount) },
    { key: 'due', header: 'Still due', cell: (row) => wholeAed(row.outstanding_amount) },
    { key: 'due_date', header: 'Due date', className: 'whitespace-normal', cell: (row) => <span className={row.overdue ? 'text-destructive' : ''}>{dueLabel(row, formatDate)}</span> },
    { key: 'status', header: 'Status', cell: (row) => <AllocationBadges row={row} /> },
    { key: 'actions', header: { srOnly: 'Actions' }, cell: view },
  ];
  return <ResponsiveList label="Additional hours" columns={columns} rows={rows} minTableWidth={900}
    renderCard={(row) => <article className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2"><strong>{row.reference} · {hours(row.hours)}</strong><AllocationBadges row={row} /></div>
      <p>{row.plan.quote_reference} · {row.plan.syllabus} · {chapterLabel(row.chapter)}</p>
      <p className="text-muted-foreground">{wholeAed(row.amount)} · paid {wholeAed(row.paid_amount)} · still due {wholeAed(row.outstanding_amount)} · due {dueLabel(row, formatDate)}</p>
      <div>{view(row)}</div>
    </article>} />;
}

const KIND_LABEL = Object.fromEntries(VOID_KINDS.map((kind) => [kind.value, kind.label]));

/**
 * One allocation: what was added and why, where its payment stands, and every
 * payment recorded for it (voided ones struck through, with why). The actions
 * offered are the API's to decide: recording a payment (the administrator or
 * the student's mentor), changing the due date or amount, waiving, withdrawing
 * and voiding a payment (administrators).
 */
function AllocationDetail({ allocationId, onBack, onChanged }) {
  const [row, setRow] = useState(null);
  const [error, setError] = useState(null);
  const [reload, setReload] = useState(0);
  const [dialog, setDialog] = useState(null);
  const [notice, setNotice] = useState('');
  const files = useSyllabusPdf();

  useEffect(() => {
    let active = true;
    api.get(allocationUrl(allocationId))
      .then(({ data }) => { if (active) { setRow(data); setError(null); } })
      .catch((err) => { if (active) setError(salesError(err, 'Could not load these additional hours.')); });
    return () => { active = false; };
  }, [allocationId, reload]);

  const back = <Button variant="outline" size="sm" onClick={onBack}><ArrowLeftIcon />Back to additional hours</Button>;
  if (error && !row) return <WorkspaceCard icon={ClockPlusIcon} title="Additional hours" action={back}>
    <ErrorState message={error.message} onRetry={error.status === 404 ? undefined : () => setReload((key) => key + 1)} /></WorkspaceCard>;
  if (!row) return <Skeleton className="h-64 w-full" aria-busy="true" />;

  const saved = (message) => (next) => { setRow(next); setNotice(message(next)); onChanged(); };
  const open = OPEN_STATUSES.includes(row.status);
  const closing = row.withdrawn ?? row.waived;
  const payment = dialog?.payment ?? null;
  return <WorkspaceCard icon={ClockPlusIcon} title={`Additional hours ${row.reference}`} action={back}>
    <div className="flex flex-wrap items-center gap-2"><AllocationBadges row={row} />
      <Badge variant="outline">{row.hours_status === 'WITHDRAWN' ? 'Hours withdrawn' : 'Hours in the quota'}</Badge></div>
    {notice ? <Notice onDismiss={() => setNotice('')}>{notice}</Notice> : null}
    <div className="grid gap-6 lg:grid-cols-2">
      <Fields>
        <Field label="Plan">{row.plan.quote_reference} · {row.plan.syllabus} · {row.plan.plan_type_label}</Field>
        <Field label="Chapter">{chapterLabel(row.chapter)}<span className="text-muted-foreground block text-xs font-normal">For reference: the hours belong to the overall quota.</span></Field>
        <Field label="Hours">{hours(row.hours)}<span className="text-muted-foreground block text-xs font-normal">Quota {hours(row.quota_before)} → {hours(row.quota_after)} when added</span></Field>
        <Field label="Reason">{row.reason}</Field>
        <Field label="Added by">{row.created_by?.name} · {dateTime(row.created_at)}</Field>
      </Fields>
      <Fields>
        <Field label="Amount">{wholeAed(row.amount)}</Field>
        <Field label="Paid">{wholeAed(row.paid_amount)}</Field>
        <Field label={row.status === 'WAIVED' ? 'Waived' : 'Still due'}>{wholeAed(row.status === 'WAIVED' ? row.waived_amount : row.outstanding_amount)}</Field>
        <Field label="Due date"><span className={row.overdue ? 'text-destructive' : ''}>{dueLabel(row, formatDate)}</span></Field>
        <Field label="Last payment">{row.last_payment_date ? formatDate(row.last_payment_date) : null}</Field>
        {closing ? <Field label={row.withdrawn ? 'Withdrawn' : 'Waived'}>{closing.by?.name} · {dateTime(closing.at)}
          <span className="text-muted-foreground block text-xs font-normal">{closing.reason}</span></Field> : null}
      </Fields>
    </div>
    {row.can_record_payment || row.can_manage ? <div className="flex flex-wrap gap-2">
      {row.can_record_payment ? <Button size="sm" onClick={() => setDialog({ name: 'pay' })}><WalletIcon />Record payment</Button> : null}
      {row.can_manage ? <Button size="sm" variant="outline" onClick={() => setDialog({ name: 'change' })}><PencilIcon />Change due date or amount</Button> : null}
      {row.can_manage && open ? <Button size="sm" variant="outline" onClick={() => setDialog({ name: 'waive' })}><BanIcon />Waive what is due</Button> : null}
      {row.can_manage ? <Button size="sm" variant="outline" onClick={() => setDialog({ name: 'withdraw' })}><Undo2Icon />Withdraw hours</Button> : null}
    </div> : null}
    <HoursPayments row={row} files={files} onVoid={(item) => setDialog({ name: 'void', payment: item })} />
    {files.error ? <p role="alert" className="text-destructive text-sm">{files.error}</p> : null}
    {files.dialog}
    <RecordHoursPaymentDialog allocation={row} open={dialog?.name === 'pay'} onOpenChange={(next) => !next && setDialog(null)}
      onSaved={saved((next) => `Payment recorded. ${wholeAed(next.outstanding_amount)} still due.`)} />
    <ChangeHoursDialog allocation={row} open={dialog?.name === 'change'} onOpenChange={(next) => !next && setDialog(null)}
      onSaved={saved(() => 'Change saved.')} />
    <CloseHoursDialog allocation={row} closing={dialog?.name === 'withdraw' ? 'withdraw' : 'waive'} open={['waive', 'withdraw'].includes(dialog?.name)}
      onOpenChange={(next) => !next && setDialog(null)}
      onSaved={saved((next) => (next.withdrawn ? `${hours(next.hours)} withdrawn from the quota.` : `${wholeAed(next.waived_amount)} waived; the hours stay.`))} />
    <VoidHoursPaymentDialog allocation={row} payment={payment} open={dialog?.name === 'void'} onOpenChange={(next) => !next && setDialog(null)}
      onSaved={saved((next) => `Payment voided. ${wholeAed(next.outstanding_amount)} still due.`)} />
  </WorkspaceCard>;
}

function HoursPayments({ row, files, onVoid }) {
  const receipt = (item) => <Button variant="outline" size="icon" onClick={() => files.download(item.proof_url, item.proof_name)}
    disabled={Boolean(files.pending)} aria-label={`Download receipt ${item.proof_name}`}><DownloadIcon /></Button>;
  const status = (item) => (item.voided
    ? <span><Badge variant="outline">Voided</Badge><span className="text-muted-foreground block text-xs">{KIND_LABEL[item.void.kind] ?? item.void.kind_label} · {item.void.reason}</span></span>
    : <Badge variant="success">Received</Badge>);
  const columns = [
    { key: 'date', header: 'Payment date', className: 'whitespace-normal', cell: (item) => <span>{formatDate(item.payment_date)}
      <span className="text-muted-foreground block text-xs">Recorded by {item.recorded_by?.name} · {dateTime(item.recorded_at)}</span></span> },
    { key: 'amount', header: 'Amount', cell: (item) => <span className={item.voided ? 'text-muted-foreground line-through' : ''}>{wholeAed(item.amount)}</span> },
    { key: 'method', header: 'Method / reference', className: 'whitespace-normal', cell: (item) => <span className="block max-w-48">{item.method_label}
      <span className="text-muted-foreground block truncate text-xs" title={item.transaction_reference || undefined}>{item.transaction_reference || 'No reference'}</span></span> },
    { key: 'status', header: 'Status', className: 'whitespace-normal', cell: status },
    { key: 'receipt', header: 'Receipt', cell: receipt },
    ...(row.can_void_payments ? [{ key: 'void', header: { srOnly: 'Void' }, cell: (item) => (item.voided ? null
      : <Button size="sm" variant="outline" onClick={() => onVoid(item)} aria-label={`Void payment of ${wholeAed(item.amount)}`}>Void</Button>) }] : []),
  ];
  return <section aria-label="Payments" className="flex flex-col gap-2">
    <h3 className="text-sm font-semibold">Payments</h3>
    {row.payments.length ? <ResponsiveList label="Payments" columns={columns} rows={row.payments} minTableWidth={720}
      renderCard={(item) => <article className="flex flex-col gap-1.5 rounded-lg border p-3 text-sm">
        <div className="flex flex-wrap items-start justify-between gap-2"><strong className={item.voided ? 'line-through' : ''}>{wholeAed(item.amount)}</strong>{status(item)}</div>
        <p>{formatDate(item.payment_date)} · {item.method_label} · {item.transaction_reference || 'No reference'}</p>
        <p className="text-muted-foreground">Recorded by {item.recorded_by?.name} · {dateTime(item.recorded_at)}</p>
        <div className="flex gap-2">{receipt(item)}{row.can_void_payments && !item.voided
          ? <Button size="sm" variant="outline" onClick={() => onVoid(item)} aria-label={`Void payment of ${wholeAed(item.amount)}`}>Void</Button> : null}</div>
      </article>} />
      : <p className="text-muted-foreground text-sm">No payments yet{OPEN_STATUSES.includes(row.status) ? `: ${wholeAed(row.outstanding_amount)} due by ${formatDate(row.due_date)}.` : '.'}</p>}
  </section>;
}
