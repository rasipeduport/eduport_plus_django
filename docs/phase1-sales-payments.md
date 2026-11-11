# Phase 1 sales payments and enrollment

Phase 1 collects the initial enquiry sale against an existing immutable quote. A verified tuition payment creates the existing Student record, generates an EDP code and grants only paid class quota. Token payments reserve admission without academic enrollment. The [initial Autopay enhancement](phase1-autopay.md) adds BDE-agreed scheduled collections using this same ledger. Other subsequent student collections, renewals and a full Financials page remain outside this phase.

## BDE workflow

Open an owned enquiry → Sales & Payment. The latest issued quote supplies the revision, plan, chapter mode, chapters, classes and agreed price. Start New Sale, or Token Sale with its mandatory expected class start date. Enrollment requires no Learn email or existing parent account. A verified initial tuition payment creates a dedicated student username/password account and a student-linked invitation. See [Learn enrollment credentials](learn-enrollment-credentials.md).

Choose full or partial collection independently of the payment method. Partial collection requires an installment replacement if the quote has a conditional single-payment discount. The BDE explicitly confirms the replacement; it copies the original pinned academic/pricing snapshot, removes that conditional discount and uses `supersedes`. No historical quote is edited or repriced from today's catalogue.

New Sale also offers Autopay Setup. BDE enters the initial class count and all future class allocations with collection dates/times, reviews backend-calculated whole-AED amounts and generates a paid Checkout that also requests future-use consent. Autopay uses the existing partial-payment discount policy. Token Sale retains its existing options. See the enhancement guide for schedule validation, setup readiness, automatic collection and the pending retry policy.

Stripe generates a shareable hosted payment link. It stays Pending until a signed paid webhook is processed. Direct methods require the exact calculated amount, classes, receipt, payment date and confirmation of receipt. Payment dates default to today and can be backdated. Supported methods are Account Transfer, AJAS CEO UAE Account and AJAS CEO Indian Account.

The first verified tuition payment immediately enrolls the student. For a ten-class AED 500 package, six paid classes collect AED 300, grant six quota and leave four classes / AED 200 unpaid. BDE collection then ends, including further payment links and direct records. Historical records remain readable in the enquiry. This Phase 1 boundary also leaves Admin's student profile read-only for collections; existing mentor assignment remains available.

## Money and class allocation

New AED quotes freeze `collection_amount` using Decimal `ROUND_HALF_UP` once on the final payable package amount. Existing immutable quotes derive the same whole amount without a data update. Exact historical line rates and quote arithmetic remain stored. The quote UI and quote PDF display the agreed whole-AED collection total and discount.

For cumulative paid classes C, package classes N and rounded package total T, the amount due is `round_half_up(T × C / N) − successful_amount_received`. The last allocation settles the entire outstanding balance. Token credit is included in received money and covers zero classes. Pending, failed and expired records grant neither money credit nor class quota. Invalid half-class increments, overallocations, zero amounts and installments that exhaust the money before the final class are refused. The API never accepts a frontend price as authoritative. Stripe's AED minor-unit amount is `whole_AED × 100`, so AED 53 is sent as 5300.

## Data integrity and enrollment

`Sale` keeps the enquiry, original BDE, original quote, token reservation and eventual Student. `Purchase` freezes the accepted quote, total classes, whole-AED amount and collection mode. Its initial-purchase marker allows future purchases to use the same ledger without adding them in Phase 1. `Payment` retains the same identity, receipt, collector, date and allocation before and after enrollment. Stripe event IDs and PaymentIntent IDs are unique.

Collection and webhook processing lock enquiry → sale → payment inside database transactions. Database triggers freeze purchase terms and received payment records, prevent deletion and check cumulative money/class allocation at commit. Only one pending collection is allowed per sale. Each client submission uses a UUID idempotency key; retry the same request unchanged after a transport error. Received payments cannot be edited or deleted. A receipt file is removed when its database transaction fails.

Preparing the first tuition collection pins the purchase and permanently locks the existing enquiry plan. An expired or failed link can be retried against that purchase; it does not reopen quote editing. Token collection alone does not pin an academic purchase. Quote cancellation is refused once attached to a purchase.

EDP generation uses a PostgreSQL advisory lock and persistent sequence, above existing Student codes, student invitation codes and `SALES_EDP_MIN_NUMBER`. Set that floor above any externally issued EDP numbers not yet imported. Database uniqueness remains the final guard. Enquiries, quotes, unpaid links and tokens generate no EDP ID.

Enrollment preserves the latest applicable demo tutor and Meet link and creates a pending Learn credentials invitation linked directly to the Student and its dedicated account. The student must change their temporary password before using Learn; activation erases the retrievable temporary credential. Repeated payment events do not regenerate accounts or credentials. Admin uses the existing Enrolled Students list, student profile and mentor reassignment API. Assigned mentors receive the academic syllabus, plan, class mode and chapters through the existing scoped profile. They receive no payment-management endpoint. Payment-managed quota supports half classes and is excluded from both scheduled and manual Google Sheets quota sync; existing sheet-managed students retain their previous workflow. Existing session consumption continues to calculate available quota as paid quota minus used classes.

## Stripe configuration

Install `backend/requirements.txt`, including official `stripe==16.1.0`. No publishable key is needed because the browser opens Stripe-hosted Checkout.

| Environment variable | Value |
| --- | --- |
| `STRIPE_SECRET_KEY` | Server-side `sk_test_…` initially |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` for this endpoint/environment |
| `STRIPE_LIVE_MODE` | `False` initially; secret-key prefix and signed event mode must agree |
| `HUB_URL` | Public Hub origin used by the neutral return page |
| `SALES_EDP_MIN_NUMBER` | Optional reserved external EDP floor, default 0 |
| `PAYMENT_PROOF_MAX_MB` | Private receipt size limit, default 10 |
| `MEDIA_ROOT` | Existing durable private upload directory |

The integration creates a Stripe Customer using the enquiry UUID and an idempotency key. Tuition reuses a Customer created for a token. After enrollment, the same Customer metadata receives the Student UUID and EDP ID. A failed metadata update cannot roll back a received payment; `sales.tasks.sync_stripe_student_metadata` retries every 15 minutes through the existing Celery worker/beat setup.

The shareable link is a **single-use Checkout Session URL**, with stored `cs_…` session ID, customer ID and later `pi_…` transaction ID. This deliberately uses the Checkout API rather than a reusable `plink_…` Payment Link because Checkout can bind the existing Customer explicitly. The API persists enquiry, quote, purchase and payment metadata on the Session and PaymentIntent. Generated links do not mark payments successful.

Configure a Stripe **snapshot event** webhook at:

`https://YOUR_API_HOST/api/sales/webhooks/stripe/`

Subscribe to `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed` and `checkout.session.expired`. Use the Stripe API version supported by the pinned SDK (16.1.0 defaults to 2026-10-28.endive). The endpoint verifies the signature against the raw request body and validates mode, exact amount, currency, Customer and all linked references. A completed Session must report `payment_status=paid` and a PaymentIntent ID. Duplicate events/transactions grant no additional credit. Unknown Sessions and unrelated event types are ignored; mismatched ledger payments are recorded as rejected and return HTTP 400 for investigation.

For local Test Mode, use the official Stripe CLI with your test account:

```sh
stripe listen --events checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,checkout.session.expired --forward-to localhost:8000/api/sales/webhooks/stripe/
```

Put the CLI's signing secret in the local backend environment and restart only your intended local process. Generate a link from a real test enquiry and pay through the hosted test checkout. A generic `stripe trigger` Session has no ledger references and is intentionally ignored. Confirm payment history, one EDP code, paid quota and the Admin student record. Production uses live secrets and `STRIPE_LIVE_MODE=True` in a separate production database; test Customers must not be reused across modes.

Official references: [Checkout Session creation](https://docs.stripe.com/api/checkout/sessions/create), [webhook signatures and testing](https://docs.stripe.com/webhooks), [currency minor units](https://docs.stripe.com/currencies), [Stripe Python SDK](https://github.com/stripe/stripe-python).

## Token reminders

Tokens always collect AED 100 and zero classes. A successful token payment confirms its unique TOK reference and is credited against the chosen package. If no quote exists yet, choose one before tuition collection. The package must leave a positive qualifying tuition balance; tokens do not automatically grant classes even when their credit could cover an installment.

The existing BDE follow-up feed derives one `TOKEN_TUITION` item per paid, unenrolled reservation. It becomes due three days before the expected start date at 09:00 IST and overdue after the start date. The feed displays reservation reference, payment status and balance with a Sales & Payment link. Deriving the item from the reservation prevents duplicate reminder records. There is no outbound reminder transport added in this phase. If an enquiry is reassigned away from its original BDE, its token reminder is withheld from BDE feeds pending Admin review; attribution remains preserved and existing owner access controls still apply.

## API surface

All staff endpoints require `accounts.manage_initial_sales`. By default only BDE and Admin role groups receive it. BDE enquiry scope is the current responsible BDE; Admin oversight also requires the existing quote-management permission. Student initial history additionally requires `accounts.view_all_students`. The provider webhook has no staff-session requirement and authenticates by Stripe signature.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET / POST | `/api/sales/enquiries/<id>/sale/` | Summary or start initial sale |
| GET | `/api/sales/enquiries/<id>/sale/amount/` | Authoritative amount for purpose, mode and classes |
| POST | `/api/sales/enquiries/<id>/sale/payments/` | Stripe link or confirmed direct receipt; UUID request ID required |
| POST | `/api/sales/enquiries/<id>/installment-quote/` | Explicit replacement of the named current quote |
| GET | `/api/sales/payments/<id>/proof/` | Private attachment for authorized collector/Admin |
| POST | `/api/sales/payments/<id>/expire/` | Confirm expiry with Stripe before releasing pending link |
| GET | `/api/sales/students/<id>/initial-sale/` | Admin initial enrollment and ledger history |
| POST | `/api/sales/webhooks/stripe/` | Signed provider events |

Quote creation additionally accepts `collection_mode=FULL` or `PARTIAL`; PARTIAL excludes conditional single-payment discounts at issuance. Quote responses add the frozen/derived `collection_amount`, whole `collection_subtotal`, `collection_discount` and collection mode while preserving historical raw figures. Student profile responses add `quota_source` and, for payment-managed students, academic `learning_plan`. Existing BDE follow-up/status APIs include token reminders and enrolled enquiries.

## Migration and operational requirements

Review and deploy these migrations through the normal release process: accounts 0023 (permission grant), students 0005 (quota source and half classes), sales 0008 (ledger and quote collection fields), sales 0009 (PostgreSQL integrity triggers). They have only been applied to disposable local test databases during development. The integrity migration refuses reversal once financial history exists.

Receipts use the existing private media infrastructure with random paths, size/type checks and authenticated attachment downloads. Do not serve `payment-proofs/` through a public media route. Sales and payment actions are recorded in the existing append-only activity log.

Keep one Celery beat and an active worker for Stripe metadata retries. Token reminders are request-derived and need neither cron nor an external notification provider. Webhook failures must be monitored and retried from Stripe after resolving the cause; Phase 1 adds no reconciliation dashboard or refund workflow. Collected money that cannot be enrolled because account data was changed concurrently requires administrative investigation rather than fabricated success.
