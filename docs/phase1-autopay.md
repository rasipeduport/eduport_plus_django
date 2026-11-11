# Phase 1 initial Autopay

New agreements now use [Stripe Billing Subscriptions and native recovery](stripe-billing-integration.md).
The PaymentIntent collector and retry-policy notes below describe historical
`LEGACY_PI` agreements only; retain this document as implementation history.

BDE can agree an initial tuition payment and a complete future installment schedule from New Sale. The enhancement uses the existing quote, Purchase, payment ledger, Stripe Customer and enrollment services. Token Sale, complete payment and ordinary partial payment retain their existing behavior. Manual Mentor/Admin payment management remains for Student Financials.

## Schedule and review

Choose Autopay Setup under Enquiry → Sales & Payment → New Sale. Enter initial classes and each future installment's classes and collection date/time. There is no fixed monthly frequency. `SALES_BILLING_TIMEZONE` configures the billing zone, initially `Asia/Dubai`; BDE explicitly chooses a collection time rather than the server inventing one from a date.

The backend reads the current immutable AED quote. A conditional single-payment discount requires the existing explicit replacement quote before installments. Initial and future classes must cover exactly the purchased classes, in positive whole/half-class increments. All amounts use the existing cumulative proportional allocator against the frozen whole-AED package total; the final installment absorbs the remainder. Client amounts are never accepted.

Due instants must be future, unique and strictly increasing. Naive input is interpreted in the billing zone, then stored as an aware UTC instant. Ambiguous/nonexistent daylight-saving local times are rejected; explicit offsets can resolve an ambiguous time. Display always supplies the stored billing zone. The API accepts up to 100 future entries as a payload limit, without imposing a billing frequency.

Review complete schedule returns every calculated amount and a signed 30-minute review token scoped to the user, enquiry, quote, timezone, terms and exact schedule. Editing an allocation/date clears the UI review. Checkout creation recomputes and validates the review before collecting. Creating the agreement freezes the Purchase and schedule. Expired/failed initial Checkout can be regenerated against the same payment and terms while unenrolled; each link is a separate attempt. If a scheduled date has already passed, regeneration requires administrative review and does not change the historic date.

## Shared records and audit

- `AutopayAgreement` belongs to a Purchase and freezes creator, creator role, source, billing timezone, terms URL, consent wording and schedule digest. `BDE_INITIAL` describes the entry workflow; `creator_role` records the actual BDE/authorized Admin role. Payment success, consent verification and method readiness have separate timestamps/statuses.
- `AutopayInstallment` freezes position, classes, whole-AED amount and UTC due instant. Position zero is initial Checkout. Each installment links at most one existing-ledger Payment, created once when collection begins. Later attempts retain that allocation and payment identity.
- `AutopayAttempt` records each provider operation under an installment, with attempt number, state, Stripe Session/PaymentIntent references and non-sensitive error code. Provider references cannot be reassigned. Every state transition is also recorded in the existing append-only activity log, preserving earlier observations.

Migrations `sales.0010_autopay_agreements` and `sales.0011_autopay_integrity` add these records and PostgreSQL safeguards. Agreement terms, installment allocation and attempt origin cannot be overwritten/deleted. A deferred database check reconciles all class/money allocations and proportional rounding against the Purchase. Paid installments require a successful linked ledger payment. Safeguards cannot be reversed while agreements exist. The four original Phase 1 migrations remain unchanged.

These records carry source/creator independently of the current caller and are shared with future Mentor/Admin entry points. This enhancement adds no such payment-management entry point. Later Student Financials work must define its remaining-balance setup and amendment rules using the same records and ledger.

## Combined Stripe Checkout

The existing official Stripe 16.1.0 client creates a paid `mode=payment` Checkout Session for the exact initial amount, with the existing enquiry Customer. `payment_intent_data.setup_future_usage=off_session` requests saving the method on that Customer. Autopay Checkout offers cards only; no unsupported payment method is silently considered ready. A separate zero-AED SetupIntent/mandate link is not created.

Checkout requires active terms acceptance with `consent_collection.terms_of_service=required`, displays the frozen authorization wording and links the exact private agreed schedule and approved terms. Configure the Terms of Service URL in Stripe Dashboard as well as the application environment. The signed schedule link lets the parent review amounts, classes and dates without staff login.

The signed Checkout webhook verifies mode, amount, currency, Customer and all agreement/installment/attempt/quote references. A verified paid initial payment invokes the existing enrollment service, EDP generation, student-linked username/password invitation, demo tutor retention and paid quota allocation. It does this even if subsequent payment-method verification is incomplete.

Readiness verification separately retrieves the paid PaymentIntent and PaymentMethod from Stripe. It requires paid amount, `setup_future_usage=off_session`, accepted consent, a supported card, attachment to the correct Customer and matching test/live environment. Missing consent, unavailable Stripe verification, cross-customer/mode attachment or an unsupported method leaves setup incomplete/unsupported, with Admin follow-up visible. It never undoes a received tuition payment or creates extra quota. The worker can reconcile incomplete setup later by reading Stripe; that reconciliation is not another charge.

## Automatic collections

The existing Celery worker/beat runs `sales.tasks.collect_due_autopay_installments` every minute. This is polling of BDE-selected due instants, not a retry interval. Keep one beat process. The worker considers only enrolled, paid-initial, ready agreements and the earliest unpaid due installment. Any unpaid predecessor blocks later installments.

The worker locks enquiry → sale → agreement → installment and creates one Payment/attempt before contacting Stripe. The provider call uses `payment_intents.create` with the saved Customer/PaymentMethod, exact whole AED × 100 minor units, `confirm=true`, `off_session=true`, frozen metadata and an attempt-specific idempotency key. A detached/cross-customer/wrong-environment method is refused before charging. API responses never grant quota; a signed successful webhook settles the same Payment and credits only that installment's classes exactly once.

Network ambiguity resumes the same request with the same attempt ID and idempotency key. It does not create another installment/payment or a new charge attempt. An unconfirmed operation older than 23 hours requires reconciliation instead of risking reuse after Stripe's idempotency retention window. Failed charges remain failed under the original amount/classes; the agreement is not immediately paused. The UI flags the failure and all later installments remain blocked.

## Confirmed retry policy remains unimplemented

The confirmed policy is one initial scheduled attempt plus three retries, 24 hours apart. After the fourth failed attempt, pause the agreement and flag Admin follow-up. Later installments must remain blocked until the earlier installment is paid.

The current worker does **not** implement this policy. It excludes FAILED installments and only reconciles uncertain SUBMITTING/UNKNOWN attempts using the same idempotency key. That transport reconciliation is not a retry. The API still reports `retry_policy_status=AWAITING_CONFIRMATION`; that label is stale now that the policy is confirmed.

The separate acceptance audit in [the permission review](permission-regression-review.md) simulates all four scheduled collection checkpoints: it observes one failed attempt and an ACTIVE agreement, rather than four attempts and PAUSED. Paid quota remains unchanged. Existing failure attention in the Admin UI does not implement the required exhaustion/pause/follow-up operation.

The shared installment/payment/attempt architecture can support retries, but the scheduler, retry timing/cap, pause transition and exhaustion follow-up still require implementation. This review verifies and reports the gap; it does not implement a retry policy as part of changing permission fixtures.

## Customer authentication

An authentication-required PaymentIntent marks the installment `REQUIRES_CUSTOMER_ACTION`; the worker never repeatedly confirms it off-session. Admin's agreement detail includes a private parent authentication link. The signed bearer URL is scoped to one attempt and expires after seven days; reading the Admin detail produces a fresh link.

The parent page retrieves only the agreed schedule and scoped action data through `GET /api/sales/autopay/actions/<token>/`, with private/no-store response headers. For an action-required installment, the backend retrieves and validates the existing PaymentIntent, then provides its client secret and the public Stripe key to that parent page. Stripe.js `confirmCardPayment` completes authentication on that same intent. The frontend shows submission status and never records a successful ledger payment or quota. Only the verified Stripe webhook does that. The action link/secret is not persisted in browser storage or exposed through a public file URL.

There is no new outbound messaging transport. Admin can share the action link using the existing communication practices; it is not exposed as a post-enrollment BDE collection control.

## Admin visibility and permissions

The existing Admin Enrolled Students table has an Autopay column with status/attention state, creator and next date. The existing student profile's initial enrollment area renders the same agreement with package/initial/remaining amounts, billing zone, schedule, class allocations, card suffix, Stripe references and attempt history. Failed/action-required states are highlighted while preserving the underlying agreement state. Mentor/tutor payloads do not receive the Admin Autopay summary.

All initial setup/restart endpoints require the existing `manage_initial_sales` permission and enquiry ownership/authorized Admin oversight. BDE cannot start/edit/collect after enrollment. Automatic subsequent payments run as system operations against the frozen agreement. The ledger retains the initiating user for attribution and marks the collection source as Autopay; audit entries identify automatic collection rather than attributing a new user action to BDE. Existing mentor assignment is unchanged.

## Endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/sales/enquiries/<id>/sale/autopay/preview/` | Validate and calculate the full schedule |
| POST | `/api/sales/enquiries/<id>/sale/autopay/` | Confirm the review and create initial paid Checkout |
| POST | `/api/sales/autopay/<id>/initial-checkout/` | Restart a failed/expired initial Checkout, same payment/schedule |
| GET | `/api/sales/autopay/actions/<token>/` | Parent's signed schedule/authentication action |

Existing sale/student-initial-sale responses include the shared agreement. Student list/profile responses include an Admin-only summary. No Mentor/Admin manual-payment management endpoint was added.

## Environment and webhook setup

| Variable | Requirement |
| --- | --- |
| `STRIPE_SECRET_KEY` | Matching `sk_test_…` initially |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for this environment/endpoint |
| `STRIPE_PUBLISHABLE_KEY` | Matching `pk_test_…`; used for parent authentication |
| `STRIPE_LIVE_MODE` | `False` initially; both keys, objects and events must agree |
| `AUTOPAY_TERMS_URL` | Approved public HTTPS terms URL; localhost HTTP is permitted only in DEBUG |
| `SALES_BILLING_TIMEZONE` | IANA billing timezone, default `Asia/Dubai` |
| `HUB_URL` | Correct publicly reachable Hub origin |

Use the existing `/api/sales/webhooks/stripe/` snapshot-event endpoint. In addition to the four Checkout events documented in the Phase 1 guide, subscribe to `payment_intent.succeeded`, `payment_intent.payment_failed`, `payment_intent.requires_action`, `payment_intent.processing` and `payment_method.detached`. An attachment event alone is never sufficient for enrollment/readiness. Event IDs and received payment transaction IDs are idempotent, and cross-linked provider data is rejected.

Local Stripe CLI example:

```sh
stripe listen --events checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,checkout.session.expired,payment_intent.succeeded,payment_intent.payment_failed,payment_intent.requires_action,payment_intent.processing,payment_method.detached --forward-to localhost:8000/api/sales/webhooks/stripe/
```

Set the CLI signing secret in the intended local process. A generic Stripe trigger has no agreement metadata and cannot credit this ledger. Generate a real test agreement from an owned enquiry and complete its hosted payment, then verify the attached card and later due collection in the ledger. The return page is never proof of payment.

Official references: [Checkout Session creation](https://docs.stripe.com/api/checkout/sessions/create), [PaymentIntent creation](https://docs.stripe.com/api/payment_intents/create), [PaymentIntent confirmation and customer authentication](https://docs.stripe.com/api/payment_intents/confirm), [Stripe webhooks](https://docs.stripe.com/webhooks).

## Verification and external limitations

No local Stripe secret, webhook or publishable key is configured. Production code uses the actual Stripe SDK and fails closed without configuration. Official SDK request-encoding and signed-webhook tests use isolated test transport; they are not external Test Mode payments or mandates. A real initial Checkout, saved card, issuer authentication and subsequent off-session payment still require external Test Mode verification.

The implementation was exercised only in disposable local databases/containers. Shared databases were not migrated and shared/deployed images were not rebuilt. Existing Phase 1 verification remains recorded separately in `phase1-verification.md`.


## Final verification

All work remains uncommitted on `feature/phase-1-sales-payments-enrollment`. A SHA-256 inventory was captured before enhancement work: all 52 original Phase 1 files remain present; 40 are byte-for-byte unchanged and 12 were extended. Two additional previously unchanged tracked files and 11 new files bring the complete working tree to 65 changed files. Nothing was committed or pushed.

| Check | Exact final result |
| --- | --- |
| Backend: sales, students, sessions, role permissions, authentication, BDE reminders, enquiries and admissions | 700/700 passed in 370.661 seconds |
| New backend Autopay coverage within that suite | 24 tests passed |
| Hub sales, including four new Autopay/parent-action tests | 67/68 passed; same pre-existing WhatsApp help-text assertion failure as Phase 1 |
| Hub reports | 30/30 passed |
| Hub access matrix | 286/480 matched, same 194 pre-existing mismatches; no new failing scenarios |
| Hub bookings | 70/139 passed, same 69 pre-existing failing cases |
| Hub leads | 36/37 passed, same pre-existing booking-link assertion failure |
| Hub lint | 0 errors, 37 existing warnings |
| Hub production build | Passed in 4.42 seconds; large-bundle warning remains |
| makemigrations --check --dry-run | No changes detected |
| git diff --check | Passed |
| Playwright against isolated actual API | Passed; no runtime errors or page overflow at 768, 390 or 320 pixels |

Backend coverage includes schedule reconciliation, half classes, frozen whole-AED totals/rounding, invalid and duplicate due instants, Dubai/UTC conversion and DST ambiguity, review-token validation, paid Checkout plus consent, actual SDK request encoding, independent readiness verification, missing/unsupported/cross-customer/cross-mode methods, signed success/failure/duplicate events, enrollment once, subsequent quota once, sequential collections, unchanged pricing after Admin rate changes, network reconciliation using the same idempotency key, customer authentication, initial Checkout restart with one payment, multiple attempts under one allocation, immutable history, Admin visibility and post-enrollment permissions. The existing Phase 1 Google Sheets/quote/Bridge/Chapter Plan/enrollment/authentication suites also passed.

Browser checks exercised the actual server preview of 2/3/3/2 classes with AED 100/150/150/100, complete review before Checkout, clearing review after edits, over-allocation refusal, Dubai-to-UTC conversion, the three New Sale choices, the Admin Autopay column and invalid parent-link refusal. Missing credentials left Checkout disabled and created no payment, agreement or student. No Stripe payment or mandate was simulated in this browser run.

Screenshots: [desktop schedule review](/private/tmp/eduport-autopay/screenshots/autopay-review-desktop.png), [mobile schedule review](/private/tmp/eduport-autopay/screenshots/autopay-review-mobile.png).

Logs and test scripts are retained under `/private/tmp/eduport-autopay/`, including `backend-regression-final.log`, `hub-sales-final.log`, `browser-results.json`, `lint-final.log` and `build-final.log`. The original Phase 1 artifacts remain under `/private/tmp/eduport-phase1/`.

## Enhancement file list

These 25 files were added or extended for Autopay. The previous Phase 1 file manifest remains in `phase1-verification.md`.

- Extended existing Phase 1 work: `backend/.env.example`
- Extended existing Phase 1 work: `backend/config/settings.py`
- Extended existing Phase 1 work: `backend/sales/models.py`
- Extended existing Phase 1 work: `backend/sales/urls.py`
- Extended existing Phase 1 work: `backend/students/services.py`
- Extended existing Phase 1 work: `frontend/hub/src/App.jsx`
- Extended existing Phase 1 work: `frontend/hub/tests/sales/run.mjs`
- Extended existing Phase 1 work: `backend/sales/payments.py`
- Extended existing Phase 1 work: `backend/sales/stripe_gateway.py`
- Extended existing Phase 1 work: `backend/sales/tasks.py`
- Extended existing Phase 1 work: `docs/phase1-sales-payments.md`
- Extended existing Phase 1 work: `frontend/hub/src/components/enquiries/workspace/enquiry-sales-payment.jsx`

- Added or newly modified for Autopay: `backend/sales/autopay.py`
- Added or newly modified for Autopay: `backend/sales/autopay_models.py`
- Added or newly modified for Autopay: `backend/sales/autopay_stripe.py`
- Added or newly modified for Autopay: `backend/sales/autopay_views.py`
- Added or newly modified for Autopay: `backend/sales/migrations/0010_autopay_agreements.py`
- Added or newly modified for Autopay: `backend/sales/migrations/0011_autopay_integrity.py`
- Added or newly modified for Autopay: `backend/sales/tests_autopay.py`
- Added or newly modified for Autopay: `docs/phase1-autopay.md`
- Added or newly modified for Autopay: `frontend/hub/src/components/enquiries/workspace/autopay-builder.jsx`
- Added or newly modified for Autopay: `frontend/hub/src/components/sales/autopay-summary.jsx`
- Added or newly modified for Autopay: `frontend/hub/src/components/students/columns.jsx`
- Added or newly modified for Autopay: `frontend/hub/src/pages/AutopayActionPage.jsx`
- Added or newly modified for Autopay: `frontend/hub/tests/sales/harness.jsx`
