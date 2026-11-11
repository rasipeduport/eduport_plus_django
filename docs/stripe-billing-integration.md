# Stripe Billing integration

The three P1 recovery/idempotency fixes and the current Customer identity gaps
are described in [Stripe Billing P1 recovery](stripe-billing-p1-recovery.md).
That addendum supersedes this document's original Checkout transaction and
provisioning-recovery descriptions. Its migration is also unapplied.

Implementation prepared on `feature/phase-1-sales-payments-enrollment`. **No tests,
builds, browser checks, application/migration commands, database operations or
Stripe account calls were executed for this change.** This document is a manual
verification guide, not a successful test report. Existing credentials and
environment files were not changed.

## Collection lifecycle

1. An AUTOPAY quote still fixes its collection intention, pricing and classes.
   BDE reviews the initial allocation and all future dates in the configured
   billing timezone. The existing cumulative proportional whole-AED allocation
   computes every amount, including the final rounding difference.
2. New agreements use `STRIPE_BILLING`. The existing paid Checkout remains
   `mode=payment`, card-only, with consent and `setup_future_usage=off_session`.
   It reuses the enquiry's Stripe Customer. No zero-value setup Checkout is added.
3. The signed initial-payment webhook still records the initial tuition,
   enrolls once, creates EDP/Learn invitation credentials, and credits only the
   initial paid classes. Payment success and reusable-card readiness remain
   separate. An attached card or a created agreement cannot enroll a student.
4. When both conditions are verified, an after-commit Celery task provisions a
   native Subscription Schedule. The existing minute task also discovers ready
   agreements whose provisioning callback was not delivered. This is provider
   provisioning reconciliation, not a collection/retry scheduler.
5. Stripe starts the subscription at the first agreed future collection instant,
   generates recurring invoices and collects them. Before that date the schedule
   is `not_started`, and a Subscription ID may not yet exist. Webhooks bind it
   when Stripe creates the subscription.
6. Each valid settled invoice becomes one logical Payment linked to the original
   installment. Retries have separate attempt records, not new Payments. Only
   `invoice.paid` or another invoice event whose canonical retrieved invoice is
   paid **and** has a fully succeeded Stripe InvoicePayment/PaymentIntent can
   credit its classes. Active/past-due subscription status never grants quota.
7. Failed installments remain independently outstanding. They do not block later
   invoices. Completed payments, enrollment, invitation credentials and quote
   history are not recreated. Refunds or unexpected changes to an already paid
   invoice require review; this integration does not automatically reverse quota.

No custom recurring PaymentIntent is created for a Billing agreement. Stripe's
own PaymentIntents remain settlement evidence and are retained in payment history.
The original PI collector is guarded to accept only `LEGACY_PI` agreements.

## Native schedule representation and limits

`sales.billing.phase_terms` translates every frozen future installment into one
schedule phase. Phases have exact UTC start/end timestamps, one fixed AED price,
quantity one, no additional discounts/taxes, a phase-start billing anchor and no
proration. A monthly recurring interval of 1–36 months is chosen to cover the
entire phase; the next phase starts at the next agreed instant. Thus an irregular
gap must not cause an extra renewal inside the phase. The last phase lasts one
monthly interval and `end_behavior=cancel` prevents indefinite overbilling.

The initial tuition is **outside** this recurring schedule and is not invoiced
again by Billing. Amounts sent to Stripe are whole AED multiplied by 100.

Limitations rejected during schedule review, before initial Checkout:

- At most **10 future installments** per agreement: this implementation uses
  one phase per installment and Stripe permits up to ten phases.
- Each future installment is at least **AED 2**, in whole AED.
- No gap may exceed the supported 36-month recurring interval. Dates must be
  distinct, increasing and future; timezone-free provider instants are rejected.

There is no rolling phase controller, installment merging, automatic repricing
or silent substitution of dates. Supporting larger schedules requires a separate
design decision. Manually verify the irregular-date translation with your Test
account before rollout; it has not been exercised against Stripe by the agent.
If the parent pays so late that a future due date has already passed before
provisioning, initial tuition/enrollment is preserved and the agreement is flagged
for review. The backend does not backdate or silently move that installment.

## Database and history

New unapplied migration: `sales/0014_stripe_billing.py`.

- Agreement: engine, Customer (existing), Subscription/Schedule/Product IDs,
  provider statuses, provisioning status/message, first provisioning instant and
  frozen provider request. Provider origin is immutable once bound.
- Installment: unique Invoice ID, invoice status/number, private hosted URL and
  Stripe's next recovery instant. Original amount, date and classes stay frozen.
- Attempt: unique Charge/provider-attempt key plus InvoicePayment, PaymentIntent
  and Charge references. Failed charge history can be reconciled even when
  invoice webhooks arrive out of order.
- Payment: `collection_scope` separates initial/legacy pending payments from
  independent Billing invoices. Multiple unpaid invoices can coexist. Each
  logical Billing Payment must match exactly one frozen installment.
- SQL guards retain original schedule totals and proportional rounding, but
  reconcile successful Billing payments against their **original installments**
  rather than assuming that paid installments form a sequential prefix.
  For example, frozen amounts 33/34/33 must permit the first and third payments
  to settle at AED 66 while the middle AED 34 remains outstanding.
- Existing normal FULL/PARTIAL/Token allocation checks are retained. Existing
  agreements default to `LEGACY_PI`; no historical records are rewritten.
  Reversal is blocked while native Billing history exists.

Migration was authored directly from the current model definitions and existing
SQL guards. It has not been generated/validated by running Django or applied to
any database. Review/apply it yourself before starting the updated application.

## APIs, idempotency and security

Existing API paths remain:

- `POST /api/sales/enquiries/<uuid>/sale/autopay/preview/`
- `POST /api/sales/enquiries/<uuid>/sale/autopay/`
- `POST /api/sales/autopay/<uuid>/initial-checkout/`
- `GET /api/sales/enquiries/<uuid>/sale/`
- `GET /api/sales/students/<uuid>/initial-sale/` (authorized oversight)
- `POST /api/sales/webhooks/stripe/` (raw-body Stripe signature verification)

Agreement/history responses add subscription, schedule, invoice and recovery
fields. Hosted invoice payment URLs are returned only in authorized Admin
oversight responses. BDE can read original history but cannot manage payments
after enrollment. No Mentor/Tutor payment permissions or management endpoints
were added. Learn and Hub authentication are unchanged.

The shared webhook router retains event-ID uniqueness and transaction locks.
Billing uses enquiry → sale → agreement → installment locking and validates
customer, test/live mode, frozen references, amount, AED currency, billing period,
single invoice line and actual full provider settlement before crediting quota.
Paid rows and payments are immutable. Duplicate invoice events do not credit twice.
Unrecognized events are ignored, and mismatched invoices are quarantined for
review. Collection on a mismatched draft/open invoice is disabled using native
`auto_advance=false`; its frozen amount is never repaired silently.

Provisioning uses deterministic Product IDs, stable idempotency keys, a frozen
request and discovery of any existing matching Customer schedule before creation.
An ambiguous response is reconciled, not followed by a fresh subscription. Beyond
the safe idempotency window, an absent remote schedule requires technical review
instead of a blind new charge agreement. Provider transport errors propagate
from webhook reconciliation so Stripe can redeliver the signed event.

Subscription updates synchronize provider status and configure native saving of
the subscription's default card. A verified replacement card is propagated to
schedule defaults so future phases do not restore an obsolete card. These are
native settings updates, not application-scheduled payment retries.

## Existing agreements

No migration to native Billing happens automatically. Historical paid PI records
are retained. After inspecting an individual agreement, an authorized operator
can run the new command **manually**:

```sh
python manage.py provision_billing_subscription AGREEMENT_UUID --migrate-legacy
```

Migration requires verified initial tuition/enrollment/card readiness, future
unpaid dates, supported native terms, and **no Payment or collection attempt
history on any unpaid future installment**. Existing paid future PI installments
are retained and excluded from the new schedule. In-flight, failed or overdue
legacy collections require reconciliation; the command refuses to duplicate them.

To search/adopt an already-created matching schedule without creating one:

```sh
python manage.py provision_billing_subscription AGREEMENT_UUID --reconcile-only
```

The command reports the resulting provisioning state. `ERROR` or
`REQUIRES_REVIEW` is a technical follow-up state, not an instruction to create a
second subscription manually in the Dashboard. None of these commands were run.

## Manual Stripe/account configuration

No SDK upgrade: current `stripe==16.1.0` supports Subscription Schedules and
InvoicePayments. Its API version is `2026-10-28.endive`. Ensure your existing
webhook destination's event schema is compatible; current invoice parent metadata
and InvoicePayments are used rather than assuming legacy `invoice.payment_intent`.

No new environment variables are required. Existing matching Test-mode
`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`,
`STRIPE_LIVE_MODE`, approved `AUTOPAY_TERMS_URL`, billing timezone and Celery
configuration remain in use. No credentials were viewed or modified.

You must review the following yourself:

1. Enable/configure Stripe Billing in your Test account and give the backend key
   access to Customers, Checkout, PaymentMethods, Products, Prices, Subscription
   Schedules, Subscriptions, Invoices, InvoicePayments, PaymentIntents and Charges.
2. Configure native Billing recovery (Smart Retries or Stripe's fixed retry
   rules). Choose **leave subscription past_due** after exhausted recovery if
   later installments must continue collecting. Choosing unpaid/canceled/paused
   can stop future collection. No custom three-day/month-end/Admin retry policy
   is implemented.
3. Add invoice events `invoice.created`, `invoice.finalized`, `invoice.updated`,
   `invoice.finalization_failed`, `invoice.payment_failed`,
   `invoice.payment_action_required`, `invoice.paid`, `invoice.payment_succeeded`,
   `invoice.voided`, `invoice.marked_uncollectible`; subscription events
   `customer.subscription.created`, `.updated`, `.deleted`, `.paused`, `.resumed`;
   schedule events `subscription_schedule.created`, `.updated`, `.completed`,
   `.canceled`, `.released`, `.aborted` to the existing signed webhook destination.
   Retain existing Checkout and payment-method-detached events for initial tuition
   and legacy PaymentIntent events while legacy agreements remain.
4. Review invoice finalization/grace settings. A scheduled billing instant starts
   native invoicing; Stripe can leave its first invoice draft for about an hour
   before automatic finalization/payment. The displayed agreement date does not
   guarantee a charge at that exact second.
5. Review global discounts, customer balances, tax configuration and automations.
   This integration does not authorize modifying an agreed amount via credits,
   extra invoice items, balance carry-forward or external adjustments. Unexpected
   invoice totals are flagged instead of granting incorrectly priced classes.
6. Initial paid Checkout cannot establish an India-specific recurring e-mandate.
   India-issued cards are flagged unsupported for this Billing setup path; the
   successful initial tuition/enrollment is preserved. A subscription-specific
   mandate Checkout requires a separate decision. Other unsupported methods do
   not silently activate Autopay.

Cancellation, pause/resume and native recovery updates made at Stripe are
synchronized. This change adds no new student Financials/cancellation/retry UI.
The finite schedule cancels at its last phase end; Stripe cancellation may stop
automatic recovery on older open invoices. Those remain visible for follow-up,
not silently added to another installment.

## Manual acceptance steps (for the account owner)

Use Test mode and fresh non-production enquiries. The following are **not run**:

1. Review/apply pending migrations in your own intended environment. Start the
   updated web process, Celery worker and existing Beat schedule yourself.
2. As the assigned BDE, issue an AUTOPAY quote; confirm no single-payment saving.
   Start New Sale; enter initial classes and all future dates/allocations. Review
   AED totals, half-class support, Dubai display and exact reconciliation.
   Try invalid totals/dates and >10 future rows; confirm rejection before Checkout.
3. Generate Checkout and pay using your Stripe Test card. Before payment confirm
   there is no new student/quota. After the signed verified payment confirm one
   student/EDP/invitation, initial classes only and the same Customer ID. Confirm
   BDE collection controls and backend collection permission end at enrollment.
4. Inspect the automatically created native schedule: exact phases, future dates,
   whole-AED prices, cancel end behavior, saved Customer card and no duplicated
   initial tuition. Before the first due date, a missing Subscription ID is normal.
5. At a future phase start, inspect Stripe's invoice, subscription and signed
   webhook log. Account for native draft/finalization delay. Confirm one payment
   and exactly that installment's classes after settlement. Compare Hub Admin
   student-list/profile information with Stripe invoice/subscription IDs.
6. Resend the same signed event from Stripe and resend another event for the same
   paid invoice. Confirm unchanged Payment/student/invitation/quota counts and no
   second Subscription Schedule. Do not use a frontend return URL as proof of payment.
7. Exercise a failing Test payment method and an authentication-required case.
   Confirm failure reason, executed-attempt history and native next recovery date,
   no extra Payment per retry, and no unpaid class credits. Use the authorized
   hosted invoice URL to complete parent action; then confirm signed settlement
   grants classes once and card replacement is retained by future phases.
8. Leave an older invoice unpaid while a later phase invoices and successfully
   pays. Confirm separate balances, no roll-forward and paid-only quota. Include
   unequal rounded amounts to verify frozen rounding is independent of pay order.
9. Exercise subscription pause/cancel and void/uncollectible invoice events on
   disposable agreements. Confirm history retained, unpaid classes unavailable,
   and Admin follow-up indicated. Manually marking an invoice paid out of band,
   adding credit or changing its amount must not silently grant classes.
10. Check that unrelated BDEs cannot see the sale; Mentor/Tutor cannot see/manage
    payments; Admin retains oversight and mentor assignment. Verify FULL, PARTIAL,
    Token, quote replacement/PDF, Learn first login and quota source regressions
    manually. No changes to those workflows are intended by this integration.
11. If migrating a legacy agreement, run the explicit command only after reviewing
    its attempts. Confirm old IDs/history retained and no future custom PI calls
    occur for that agreement. Unsafe migrations must refuse rather than recharge.

Native schedule timing, recovery settings, webhook delivery, schema compatibility,
SQL migration correctness and UI behavior still require your verification.
There is no claim that these acceptance steps have passed.

## Source map and prepared tests

- `backend/sales/billing.py`: schedule compiler, provider provisioning,
  Subscription/Invoice reconciliation, provider attempt history and migration gate.
- `backend/sales/autopay.py`, `autopay_stripe.py`, `tasks.py`, `stripe_gateway.py`:
  initial Checkout continuity, engine routing and signed event dispatch.
- `backend/sales/autopay_models.py`, `payment_models.py`, `payments.py`,
  `students/services.py`: shared mappings, ledger and authorized Admin summaries.
- `backend/sales/management/commands/provision_billing_subscription.py`: explicit
  operational migration/provisioning; not a payment retry endpoint.
- `frontend/hub/src/components/enquiries/workspace/autopay-builder.jsx`,
  `sales/autopay-summary.jsx`, `students/columns.jsx`: review limits and read-only
  native subscription/invoice/recovery information using existing permissions.
- `backend/sales/tests_billing.py`: prepared mocked-provider/native allocation,
  initial-gate, idempotency, invalid amount, SCA, permissions and history tests.
  `tests_autopay.py` explicitly retains legacy-engine coverage. Native Hub
  history regression added to `frontend/hub/tests/sales/run.mjs`. **All unrun.**

Complete file manifest for this integration (existing unrelated uncommitted files
are deliberately not included):

```text
backend/sales/autopay.py
backend/sales/autopay_models.py
backend/sales/autopay_stripe.py
backend/sales/billing.py                                  (new)
backend/sales/management/commands/provision_billing_subscription.py  (new)
backend/sales/migrations/0014_stripe_billing.py            (new, unapplied)
backend/sales/payment_models.py
backend/sales/payments.py
backend/sales/stripe_gateway.py
backend/sales/tasks.py
backend/sales/tests_autopay.py
backend/sales/tests_billing.py                            (new, unrun)
backend/students/services.py
frontend/hub/src/components/enquiries/workspace/autopay-builder.jsx
frontend/hub/src/components/sales/autopay-summary.jsx
frontend/hub/src/components/students/columns.jsx
frontend/hub/tests/sales/run.mjs                          (updated, unrun)
docs/phase1-autopay.md
docs/stripe-billing-integration.md                        (new)
```

Official references: [Subscription Schedules](https://docs.stripe.com/billing/subscriptions/subscription-schedules),
[schedule creation API](https://docs.stripe.com/api/subscription_schedules/create),
[subscription invoice lifecycle](https://docs.stripe.com/billing/invoices/subscription),
[native recovery settings](https://docs.stripe.com/billing/revenue-recovery/smart-retries),
[InvoicePayments](https://docs.stripe.com/api/invoice-payment/list),
[India recurring mandates](https://docs.stripe.com/india-recurring-payments).
