# Stripe Billing: three P1 fixes and Customer architecture

Scope: the three P1 defects only. Existing P2 findings, additional purchases,
renewals, Admin/Mentor payment management and new collection screens are not
implemented here. No tests, builds, browser checks, Django commands, migrations or
Stripe account operations were run. Credentials and environment files were not
accessed or changed. All code remains uncommitted.

## P1: durable initial Checkout

Previously, provider calls ran inside the transaction that created Payment,
AutopayAgreement and installment records. A lost response rolled those records
back; a replay regenerated UUIDs and timestamped consent URLs under the old key.

The new flow is:

1. Under the enquiry/sale lock, validate quote intention, frozen pricing, class
   allocation, ownership and pre-enrollment scope as before.
2. Commit the Purchase, Payment, optional agreement/installments/initial attempt,
   pending enquiry Customer mapping and `StripeCheckoutOperation` in a durable
   transaction. There is no provider IO in this step.
3. The operation freezes its ID, idempotency key, all Checkout parameters and the
   signed parent schedule URL once. The Customer creation body is also frozen.
   Parent-name, Hub URL or configuration changes cannot rebuild that request on
   transport retries. The operation's Customer parameter comes from the mapping
   whose Customer ID is immutable once bound.
4. After commit, create/recover the Customer, persist its verified ID, then
   discover any matching Checkout Session for that Customer before creation.
   When creation is needed, resend the same frozen parameters and original key.
5. Bind the verified response to the operation, initial attempt and first Payment
   origin. Existing bound provider IDs and historical restart origins cannot be
   rewritten. Explicit restart attempts retain the same Payment and create a new
   durable operation under their own attempt ID.
6. A signed Checkout event may bind a lost response before the normal settlement
   handler runs. It must match the frozen amount, AED currency, Customer, mode,
   client reference and metadata. Merely creating/adopting a Session does not
   grant classes or enroll a student.

The public collection/begin/restart services place Stripe preparation in a
`transaction.atomic(durable=True)` boundary. They must not be wrapped in an
additional application transaction. Direct payment submission retains its
original transaction and receipt-cleanup path.

The existing minute task reconciles pending initial Checkout operations before
the existing readiness/provisioning work. This is transport reconciliation, not
a recurring payment or business-retry engine. Definitively rejected requests are
failed and retained; uncertain requests remain pending with their frozen origin.
An in-flight conflict is uncertain, not proof of rejection.

Unknown Customer/Checkout creation is never retried under a fresh key. Beyond a
conservative 23-hour window, discovery/adoption of a positively matching remote
record remains safe, but absence does not authorize another creation. Ambiguous
or multiple matches require manual review. A signed matching Checkout webhook
can still resolve a previously unbound operation. There is no automatic merge,
email-based reuse or replacement of historical Customers.

Local pending/error records are intentional, linked transaction history; they
are not successful payments. Existing unrecorded requests from before this fix
cannot be reconstructed safely and still require manual review.

## P1: current payment-method readiness

Before provisioning, readiness still verifies the initial paid Checkout consent,
PaymentIntent future usage and attached payment method.

Once a Subscription Schedule or Subscription is bound, readiness instead reads
the current native configuration while holding the agreement lock:

- Current Subscription default payment method takes precedence.
- Before subscription start, the first phase/default schedule configuration is
  used. When Stripe's current configuration uses a Customer default, that default
  is retrieved explicitly; the original Checkout PaymentIntent is never used as
  a fallback.
- Customer, environment, PaymentMethod ID, attachment, supported card type and
  existing India-mandate limitation are verified. Detached/missing/unsupported
  methods do not mark the agreement ready.
- A verified current subscription card may update **that agreement's schedule
  defaults**. Customer-wide defaults, prices, allocation dates and other
  agreements are not changed. Unexpected remaining phase-specific card overrides
  require review rather than silent phase rewriting.
- Replacing a card does not reuse a card-specific idempotency key across repeated
  A→B→A transitions. Updating a default is an idempotent native setting change;
  it creates no payment.

The minute reconciliation and subscription webhook path share this logic. An
older Checkout card remaining attached cannot make a detached replacement card
look ready. Existing P2 presentation issues are unchanged.

## P1: explicit provisioning recovery

After correcting a provisioning problem, the existing command supports:

```sh
python manage.py provision_billing_subscription AGREEMENT_UUID --recover
```

This command was not executed. It is not a payment retry command.

- ERROR/permanent-review states do not enter an automatic recovery loop.
- `--recover` and `--reconcile-only` are mutually exclusive. Reconciliation-only
  never creates a schedule.
- Remote schedule discovery is performed before any schedule creation. One
  matching schedule is validated/adopted; multiple matches, an absent previously
  bound schedule or mismatched frozen terms remain under review.
- The frozen provisioning request is retained. Prices, classes, dates and quote
  history are never rebuilt from current catalogue configuration.
- A persisted **verified rejection of the actual schedule-create request** can
  authorize a new durable idempotency-key generation on explicit recovery. This
  avoids replaying Stripe's cached rejection forever. Concurrent/in-flight,
  unknown, expired ambiguous or merely historical unclassified errors do not
  authorize a new generation.
- An unknown request can reuse its original key within the conservative window
  or adopt a discovered remote schedule. Beyond that window, unresolved remote
  state stays manual even with `--recover`.
- Historical ERROR states without rejection evidence cannot safely gain a fresh
  key simply because their status says ERROR. Within the original safe window,
  recovery may retry the original request; a newly received definitive rejection
  establishes evidence for a subsequent explicit recovery. Expired unclassified
  cases require technical review.
- Adoption clears provisioning-only flags after frozen schedule/origin validation
  and current-method verification. Invoice/payment review flags are kept;
  provisioning recovery is not an invoice reconciliation facility.
- Generation checks prevent delayed failure responses from an older operation
  overwriting a newer recovery or verified bound schedule. SQL guards prevent
  silently extending an idempotency window or resetting a generation.

The original first provisioning time is retained. Each explicit rejected-request
recovery records a separate generation/window and an audit entry. The command
reports an error exit for unresolved ERROR/UNKNOWN/REQUIRES_REVIEW states.

## Unapplied migration

`sales/0015_durable_checkout_recovery.py` was authored without running Django:

- New immutable Checkout-operation origin/request records.
- Pending Customer mappings with frozen creation requests and first-call times;
  established Customer IDs become immutable and are not rewritten.
- Classified Billing issue scope, key generation/window and verified-rejection
  evidence.
- First provider-reference binding on an existing initial Payment is allowed only
  when it matches its durable operation and enquiry Customer. Once bound, those
  references remain immutable. Successful payments remain immutable.
- Recurring installments cannot use this initial Checkout operation mechanism.
- Reversal is refused while Checkout history, pending Customers or recovery-key
  history exists. Existing `0014` and earlier migrations are unchanged.

Schema execution and upgrade compatibility are unverified. Web processes,
workers and Beat must use compatible code/schema; older collectors must not run
against native Billing agreements. No migration was applied by the agent.

## Customer architecture: supported now

Current local identity chain:

```text
Student ← Sale.student (one-to-one) → Sale.enquiry (one-to-one)
                                      ↓
                              StripeCustomer.enquiry (one-to-one)
                                      ↓
                              unique Stripe Customer ID
```

Before enrollment, Customer reuse is by this verified enquiry mapping, not email.
After enrollment, the same mapping is reachable from the Student's initial sale.
The existing metadata synchronization adds the Student UUID/EDP ID to that same
remote Customer. Payment and AutopayAgreement preserve their original Customer
references; Subscriptions/Invoices are checked against those references.

The P1 fix adds pending creation durability and prevents changing an established
mapping. It does not create a new Customer when a known ID is missing/deleted at
Stripe, merge historical identities, or turn an email into an identity key.

For the implemented initial-sale lifecycle, the Customer is reused by initial
Checkout and native Billing. This does **not** demonstrate that every future
student payment feature already resolves the same canonical Customer.

## Customer architecture: exact gaps and smallest future change

There is no direct canonical Student→StripeCustomer relation or shared
student-based resolver. Historical students without an initial sale have no
guaranteed mapping. Future code starting from another enquiry could create
another Customer if it copied the current enquiry-only creation approach.

For students with an initial sale, the smallest future extension is a nullable,
unique Student association on the existing Customer mapping, populated
transactionally during enrollment, plus one shared resolver that takes a Student
for post-enrollment operations. To cover historical students without an enquiry,
the existing mapping also needs an independent primary key and an optional,
unique enquiry association: enquiry is currently its required primary key.
Adding only a Student field would not remove that constraint. Existing
initial-sale mappings can be associated only when unambiguous; conflicts require
explicit review. Keep historical Payment/Agreement Customer IDs unchanged and
validate every new purchase against the canonical mapping. If multiple Stripe
accounts/environments are supported, uniqueness must be scoped to account and
mode: Test and Live Customers are separate identities. Account identity is not
currently recorded in the mapping.

That student association/resolver and any historical backfill are **proposals,
not implemented in this task**.

## Failed invoices and additional purchases

- Existing Admin oversight exposes the original Stripe hosted invoice URL. A
  parent paying that original invoice stays with its existing Customer and
  installment. Existing signed invoice reconciliation is the sole authority for
  settling the logical Payment and crediting its allocated classes once.
- No generic Payment Link is used to recover an installment. A separate
  post-enrollment manual-payment API, fresh-link generation and expanded recovery
  management are not implemented. Existing P2 URL-expiration and event-reprocessing
  limitations remain.
- Purchase already has a Student foreign key; multiple purchases are structurally
  possible. Agreement is one-to-one with Purchase, so separate purchases can have
  independent agreements. The current initial-sale APIs block further collection
  after enrollment and do not implement additional purchases.
- Sale has a one-to-one Student link. Creating another Sale for the same Student
  would require a future model/service decision; using an additional Purchase on
  the existing sale is a different possible design. Neither workflow is added.
- Separate agreements can conceptually share the canonical Customer because each
  has its own purchase, schedule, subscription, invoice bindings and metadata.
  Current Billing operations target an agreement's own schedule/subscription;
  they do not cancel all subscriptions for a Customer or rewrite other agreements.
  Future additional-purchase setup must use the shared resolver and existing
  Billing lifecycle. This architecture has not been exercised with real multiple
  subscriptions in this task.

## Verification status and manual acceptance

Prepared tests: `backend/sales/tests_stripe_p1.py`. Existing mocked transport
fixtures were adjusted for full Customer/Checkout responses and current schedule
configuration. **No tests were executed.** Existing P2 test assertion defects
were deliberately left unchanged.

Manual Stripe Test verification still needs to cover:

1. Loss of Customer/Checkout responses, exact payload/key replay and adoption of
   existing remote records without creating duplicates.
2. A valid signed Checkout webhook arriving before the response is persisted:
   one Student, one invitation and only the initial paid quota.
3. Replacing card A with B, detaching B while A remains attached, and confirming
   that current readiness does not fall back to A. Check not-started schedules,
   Customer-default fallback, wrong Customer/mode and repeated card changes.
4. Correctable native schedule rejection followed by explicit recovery; discovery
   precedes creation, a verified rejected generation changes key, and remote
   adoption clears only the appropriate flags.
5. Concurrent/repeated requests, late old-generation failures, ambiguous expired
   outcomes, unrelated invoice reviews and duplicate webhook delivery.
6. Existing FULL/PARTIAL/direct/Token/quote/enrollment/permission regressions and
   native paid-only invoice allocation. BDE post-enrollment restrictions remain.

Use matching existing Test configuration and valid Learn invitation encryption
keys. No new credentials/environment variables were introduced. Schema and
provider behavior remain unverified until the account owner performs those checks.

## Files changed for the three P1 fixes

```text
backend/sales/checkout.py                                      (new)
backend/sales/payment_models.py
backend/sales/autopay_models.py
backend/sales/models.py
backend/sales/payments.py
backend/sales/autopay.py
backend/sales/autopay_stripe.py
backend/sales/stripe_gateway.py
backend/sales/billing.py
backend/sales/tasks.py
backend/sales/management/commands/provision_billing_subscription.py
backend/sales/migrations/0015_durable_checkout_recovery.py      (new, unapplied)
backend/sales/tests_stripe_p1.py                               (new, unrun)
backend/sales/tests_payments.py                                (mock fixture only)
backend/sales/tests_billing.py                                 (mock fixture only)
docs/stripe-billing-p1-recovery.md                              (new)
docs/stripe-billing-integration.md                             (P1 addendum link)
```
