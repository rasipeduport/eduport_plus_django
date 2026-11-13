# Student financial identity (Stripe)

The student is the central financial reference. Every sale, payment, Autopay
agreement, invoice, refund and dispute resolves to one **StudentAccount**
(`SA-000123`), which exists from the first sale and gains the Student and EDP ID
at enrollment. Each student account has its own Stripe Customer; the parent is
its billing contact.

Status: implemented in the working tree, **not committed**. Migrations
`sales.0016`–`0019` and `accounts.0026` are prepared and **not applied** to any
database. Stripe stays in Test mode; no Stripe object was created while
building this (all Stripe calls in tests are mocked).

## Architecture

```
Guardian ──< StudentGuardian >── StudentAccount SA-000123 ──(set once)── Student EDP00047
(contact)    relationship,          │  origin_lead (enquiry), student_name,
             billing contact,       │  identity_locked_at
             who linked it, basis   ├── StripeCustomer  one per account per Stripe account+mode
                                    ├── Sale → Purchase → Payment → Refund / Dispute
                                    │   (initial sale from the enquiry; further ADDITIONAL sales by the mentor)
                                    │            └── AutopayAgreement → Installment → Attempt
                                    └── StudentIdentityCorrection (append-only audit)
StripeEvent ── StripeReviewItem (Stripe activity Django did not create or could not validate)
```

| Model | Role |
| --- | --- |
| `StudentAccount` | Financial identity of one child. Reference `SA-` + 6 digits from its own sequence, never changes. `student` is set once at enrollment. `student_name` is Django's copy of the child's name; once a payment or link exists it changes only through an audited correction. |
| `Guardian` | Parent or guardian: name, email, phone. **No uniqueness**: contact details never identify or merge a child. |
| `StudentGuardian` | Explicit child–guardian link with relationship, one billing contact per child, who linked it and why (`NEW_FAMILY`, `EXISTING_FAMILY`, `BACKFILL`). Ended, never deleted. |
| `StudentIdentityCorrection` | Reason, before/after values, Admin who corrected. Append-only (database trigger). |
| `StripeCustomer` | Now keyed by its own ID, linked to the account. `legacy_enquiry` keeps the old enquiry key. `label_format` is `STUDENT` (new) or `LEGACY_PARENT` (created before this change; never renamed). `stripe_account_id` records the Stripe account. |
| `Sale` | Gains `account`. One initial sale (`NEW`/`TOKEN`) per enquiry and per student. An **additional purchase** is a further sale (`ADDITIONAL`) on the same account: no enquiry, its student set from the start. |
| `Quote` | Gains `account`: an additional purchase's quote belongs to the student account instead of a lead (never both). |
| `Payment` | Gains `stripe_charge_id`, `failure_code`, `failure_message` and `payer_details` (who actually paid, from Stripe; evidence only). The ledger stays immutable: these are written once. |
| `Refund`, `Dispute` | Tracked from Stripe against the original payment. Never change a payment, a sale's agreed amount or class quota (`classes_effect` is fixed to `NONE` until a refund policy exists). |
| `StripeReviewItem` | Unmatched or rejected Stripe activity. Resolved by an Admin: dismiss, or link to a student account as history (never credits classes or creates a Payment). |

Database triggers keep account references, origins, the enrolled student,
identity lock, corrections, refunds, disputes and resolved review items
immutable, and require a sale's student to be its account's student.

## Customer creation and reuse

1. **Start Sale** opens the child's account (one per enquiry). Guardians sharing
   the enquiry's phone or email are shown as *suggestions*. When there are any,
   the BDE must confirm this is a different child and choose a family:
   join a suggested family, or create a new one. Nothing is linked automatically.
2. The first Stripe collection creates a Customer row inside the collection
   transaction (no Stripe call yet) with a frozen request:
   `name` = student name, `email`/`phone` = billing guardian,
   `description` = `SA-… · Parent/guardian: …`, invoice custom fields
   *Student ref* and *Parent/guardian*, and metadata `eduport_account_id`,
   `eduport_account_ref`, `enquiry_id`, `eduport_guardian_id`.
3. After commit, `sales.customers.customer_for` resolves the Customer for the
   **current Stripe account and mode** (read once from `GET /v1/account`):
   reuse the bound Customer; verify a legacy mapping once with
   `GET /v1/customers/<id>`; otherwise create with idempotency key
   `eduport-customer-<row id>`. Lost responses are recovered by the frozen
   marker, never by email. Customers are never merged, replaced or renamed.
4. Every later payment, link, additional purchase and the Autopay schedule of
   that student reuse it.
   A Session on a sibling's Customer can never settle this child's payment.
5. At enrollment the Customer's labels gain the EDP ID (Celery beat retries
   `sync_stripe_student_metadata`). Legacy Customers only receive the
   historical `student_id`/`edp_student_id` metadata, as before.

### Parent email

A missing parent email never blocks a link.

- **Django has it**: it is on the student's Customer, so Checkout shows it
  prefilled and not editable.
- **Django has none**: the Customer has no email, so Checkout asks the parent
  for one and Stripe saves it on that Customer. Only after the **verified**
  successful payment (signed webhook, all checks passed) does Django save it:
  validated, written only where empty (the billing guardian's email and the
  enquiry's parent email), never overwriting an existing address, then the
  Customer labels are queued for resync. Activity: `student_account.email_from_checkout`.
- Expired, failed or unverified sessions save nothing, whatever was typed.

This needs only the `customer` parameter (Stripe API `2026-10-28`):
`customer_email` applies only when Checkout creates the Customer, and
`customer_update` covers name, address and shipping only. A custom field would
duplicate the email, so none is used.

## Normal payment (one-time Checkout)

- Full or partial, as fixed by the quote. Amounts are always calculated on the
  server from the class allocation (`round_half_up(total × cumulative classes ÷
  package classes) − received`); the last allocation settles the balance.
- **Partial payments:** each payment is its own `Payment` and its own Stripe
  Checkout Session on the **same** Sale, purchase and student account. The
  agreed package amount never changes; the sale shows each payment, the amount
  received and the outstanding balance. After the first verified tuition payment
  enrolls the student, the BDE owner or an Admin can generate another one-time
  link for the remaining balance. No new Sale or purchase is created. Tokens
  remain pre-enrollment only; a sale with an Autopay agreement is collected by
  its schedule only.
- **Class credit is unchanged:** the first verified tuition payment enrolls the
  student with the classes it paid for, and Autopay installments credit theirs.
  A later one-time payment (a remaining balance) **records money only**: it is
  shown as `classes_credited: false`, and the sale reports `class_quota` and
  `classes_not_credited`. Paying the rest of the package never credits classes
  by itself; how those classes are credited is a pending decision.
- More than the outstanding classes or amount is refused. Only one pending link
  per sale can exist (database constraint), and links are created under the
  sale lock, so concurrent requests cannot collect twice.
- Every payment carries `payment_id`, `sale_id`, `purchase_id`, `quote_id`,
  `enquiry_id`, `eduport_account_id`, `eduport_account_ref` (and `student_id`,
  `edp_student_id` after enrollment) on the Session and PaymentIntent.
- Outstanding balance = agreed sale amount − successful payments. Refunds are
  shown separately (`refunded_amount`, `net_collected`) and do **not** change the
  outstanding balance or classes until a refund policy is approved.

## Additional purchases (Mentor)

A student's own mentor (or an Admin) adds a further purchase from the student
profile's **Purchases** tab. BDEs hold no permission for it.

- It is a **new Sale** (`ADDITIONAL`) on the student's existing account, with its
  own quote (on the account, not a lead), purchase and payments. Earlier sales,
  purchases and payments are never changed. No new account or Customer is
  created: links use the student's one Stripe Customer.
- It is priced exactly as any quote (catalogue on sale, current pricing; the
  single-payment discount applies to Complete Payment where the pricing allows).
  The reviewed `pricing_version` is checked when it is created
  (`PRICING_CHANGED`). Creation is idempotent on `request_id`.
- Collection: one-time Stripe links (complete or partial), with the same
  allocation, amount checks and single-pending-link rule as the initial sale.
  Token does not apply (it reserves admission before enrollment).
- Refused until decided: Autopay (`AUTOPAY_PENDING_DECISION`), an earlier sale
  with an outstanding balance (`EARLIER_BALANCE_OUTSTANDING`) or a running
  Autopay (`EARLIER_AUTOPAY_ACTIVE`), and a student without an account
  (`NO_STUDENT_ACCOUNT`, e.g. sheet-managed). Direct receipts (bank transfer)
  are not offered for additional purchases.
- Its payments **record money only** (`classes_not_credited`): no existing rule
  credits an additional purchase's classes.

## Checkout experience and field restrictions

Sessions use the student's Customer, `allowed_payment_method_types: ['card']`,
`wallet_options: {link: {display: 'never'}}`, a reusable product
(`eduport_plus_tuition` / `eduport_plus_token`), a payment description and a
submit message naming the student and billing contact, and **no**
`customer_update`, `customer_email`, `phone_number_collection`,
`name_collection`, `billing_address_collection`, `tax_id_collection` or custom
fields. Both one-time and Autopay Checkout use these settings.
`checkout.PAYMENT_METHOD_TYPES` and `checkout.WALLET_OPTIONS` are the only places to
change when more methods are approved.

| What the parent sees | Source |
| --- | --- |
| Email | Prefilled and not editable when Django has it. Otherwise the parent enters it, and Django keeps it only after a verified payment (see *Parent email*). It is the only contact detail the parent can enter. |
| Name, phone, address, student details, package, classes, amount | Not asked. Shown read-only via the line item, amount and submit message. |
| Card number, expiry, CVC, name on card, country (and postcode for US, UK and Canadian cards) | **Required by Stripe for card payments** and cannot be prefilled through the API. These are payment-method fields, never used for identity. |
| Apple Pay / Google Pay | Card wallets: no per-Session switch exists. They appear when enabled in the Stripe Dashboard payment-method settings (the Test account's default configuration enables Apple Pay). To keep the card form only until Apple Pay is approved, turn it off there. |
| Link | Hidden (`wallet_options.link.display = never`; also outside `['card']`). |
| Autopay consent | Terms-of-service checkbox (required for saving the card); not identity data. |

Checkout cannot rename the student Customer (`customer_update` defaults to
`never`). A Checkout redirect never changes a payment: only the signed webhook does.

## Autopay (fixed installments)

The existing, hardened flow is kept because it already gives a finite schedule
with a single authorization:

1. BDE reviews the initial installment and every future dated installment
   (≤10, whole AED, server-calculated). Equal monthly EMIs are one valid schedule.
2. Initial **paid** Checkout on the student's Customer, card only, with consent
   and `setup_future_usage=off_session`: the parent authorizes once, on-session
   (SCA), and the first installment is collected. This enrolls the student.
3. The webhook verifies payment, consent and the saved card; Celery provisions a
   **Subscription Schedule**: one phase per installment, exact start/end
   instants, no proration, `end_behavior=cancel`. It uses the shared
   `eduport_plus_tuition` product and carries the account, student and EDP
   references in schedule and phase metadata and a phase description.
4. Stripe invoices and collects each installment (native Smart Retries).
   `invoice.paid` with a fully succeeded payment credits that installment's
   classes once; failures keep the installment outstanding.
5. The schedule cancels after its last phase; the agreement completes when every
   installment is paid.

Checked against the approved fixed Autopay: the amount, number and dates of
installments are fixed in the schedule's phases. The parent authorizes once and
Stripe collects automatically (`charge_automatically`). Collection ends after
the last installment (`end_behavior=cancel`). Everything uses the student's
Customer, and schedule metadata maps to the account, sale, purchase and
installments. Failure, retry, cancellation and completion handling are
unchanged. Django never changes an agreed schedule's amounts or dates. Two
existing automatic card-settings updates remain (decision pending):

- Django sets `payment_settings` (save the card on the subscription, card only)
  on Django-created subscriptions.
- Django sets the schedule's default card to the subscription's current card.

Neither collects money or changes any amount or date.

Updating a scheduled subscription makes Stripe restart its running phase at that
moment, so a phase that has already started may start later than agreed. The
schedule check accepts that, strictly inside the phase's own window and matching
Stripe's current phase. End dates, phases yet to start, metadata, installment
references, amounts, products, prices and intervals stay exact.

**Cancellation:** Admin action (reason required; *administrator decision* or
*parent's request*). Stripe cancels the schedule first
(`invoice_now=false, prorate=false`); if Stripe cannot confirm, nothing changes.
Future installments without an invoice become `CANCELLED`; paid history, classes
and open invoices are kept (open invoices are not voided automatically). A stop
made in the Stripe Dashboard is recorded as `STRIPE` and flagged for review.

A setup-only Checkout followed by a subscription that charges the first
installment off-session was not chosen: it adds an SCA failure point on the
first charge and would move enrollment to an off-session invoice.

## Webhook event mapping

All events: signature verified on the raw body (missing or invalid → 400, nothing
stored), event ID stored once, test/live mode checked, lock order enquiry (when
the sale has one) → sale → payment. Students are never matched by email or phone.

| Event | Mapped by | Effect |
| --- | --- | --- |
| `checkout.session.completed`, `.async_payment_succeeded` | Session ID → Payment; checks Customer, amount, AED, `client_reference_id`, metadata, account | Payment received (+ charge, payer snapshot, missing parent email saved); first tuition enrolls with its classes; a later one-time payment records money only. Unknown Session → review (`PAYMENT_LINK_PAYMENT` / `UNMATCHED_CHECKOUT`). Mismatch → 400 + review (`INCONSISTENT`). |
| `checkout.session.expired`, `.async_payment_failed` | Session ID | Pending payment → expired / failed. Never downgrades a received payment. |
| `payment_intent.payment_failed` | `metadata.payment_id` + Customer | Records the decline on the still-payable link (status unchanged). |
| `payment_intent.succeeded` | `metadata.payment_id` + Customer | Fills the charge ID once. |
| `invoice.*` (paid, payment_failed, finalized, …) | Subscription metadata `autopay_id` + `installment_id` | Installment settlement / failure / retry state. Paid invoice outside an agreement → review (`UNMATCHED_INVOICE`). |
| `customer.subscription.*`, `subscription_schedule.*` | `autopay_id` metadata | Status sync, card readiness, completion, Stripe-side stops. Unknown subscription → review. |
| `charge.refunded`, `refund.created/updated/failed` | Refund's PaymentIntent or charge → Payment | Refund row (re-read from Stripe; order-independent). Unknown → review (`UNMATCHED_REFUND`). |
| `charge.dispute.*` | Dispute's PaymentIntent or charge → Payment | Dispute row and status. Unknown → review. |
| `payment_link.created/updated` | — | Review (`PAYMENT_LINK_CREATED`); never credited. |
| `payment_method.detached` | Saved method | Autopay setup flagged for follow-up. |
| `setup_intent.*`, `product.*`, other | — | Ignored (200). Product events carrying Autopay metadata are no longer misrouted and rejected. |

## Reconciliation

`manage.py reconcile_stripe_ledger --days 30` lists completed Sessions, paid
invoices, succeeded PaymentIntents, refunds and disputes that the Django ledger
does not account for, and Django payments missing at Stripe. Its Stripe client
refuses every non-GET request. It also reports an invoice already linked to an
installment whose outcome differs (paid, void or uncollectible on one side
only) as `MISMATCH INCONSISTENT`, for example a payment Stripe took while a
webhook was missed. Nothing is credited. `--record-review` queues the findings.
Admin review API: `GET /api/sales/stripe-review/?status=OPEN`,
`POST /api/sales/stripe-review/<id>/resolve/` (`DISMISS` or `LINK` + note).

## API

| Endpoint | Who |
| --- | --- |
| `GET/POST /api/sales/enquiries/<id>/sale/` | BDE owner / Admin. POST accepts `family`, `billing_contact`, `relationship`, `confirm_distinct_child`. GET adds `account`, `family_candidates`, `can_cancel_autopay`, outstanding/refund totals. |
| `PUT /api/sales/enquiries/<id>/sale/billing-contact/` | BDE owner / Admin |
| `POST /api/sales/accounts/<id>/identity-correction/` | Admin (`student_name`, `reason` ≥ 10 characters) |
| `POST /api/sales/autopay/<id>/cancel/` | Admin (`reason`, `source` = `ADMIN` / `PARENT_REQUEST`) |
| `GET /api/sales/stripe-review/`, `POST …/<id>/resolve/` | Admin |
| `GET/POST /api/sales/students/<id>/purchases/` | The student's mentor, or an Admin (`accounts.create_additional_purchases`). GET: the account's sales, blockers, the catalogue on sale (`?syllabus=` adds its detail). POST: `preview: true` prices; otherwise creates (`request_id`, optional `pricing_version`). |
| `GET /api/sales/purchases/<sale id>/`, `GET …/amount/?classes=` | Same |
| `POST /api/sales/purchases/<sale id>/payments/` (`request_id`, `classes`), `POST …/payments/<payment id>/expire/` | Same |

"Admin" here is the existing financial-oversight pair
`accounts.manage_initial_sales` + `accounts.manage_sales_quotes`. The Admin lead
edit and the student Edit Profile refuse to change a locked child's name
(`IDENTITY_LOCKED`).

## Migration and backfill

1. Back up the database.
2. Read-only report (works before or after migrating; runs in a read-only
   transaction): `manage.py backfill_student_accounts`.
3. With approval: `manage.py migrate sales` applies 0016 (schema, Customer
   re-key, trigger updates), 0017 (one account and one guardian per enquiry with
   a sale or Customer; possible siblings reported, never linked; stops on any
   ambiguity) and 0018 (account required).
4. Existing Customers, payments, subscriptions, schedules and Stripe IDs are
   kept as they are; existing Customers are labelled `LEGACY_PARENT` and never
   renamed. Links in progress keep their original metadata and still settle
   (matched by Session ID; their account comes from the backfilled sale).
5. Reversal is possible while no account, Customer or correction was created
   after the backfill (`manage.py migrate sales 0015`).

Dry run on the local Test database (2026-11-13): 4 enquiries → SA-000001…004,
all enrolled (EDP00045–48), all identity-locked, Customers kept as
`LEGACY_PARENT`, no ambiguous mappings. Two guardians have no email in Django
(the parent typed it on Stripe). Their Customers already hold it, so Checkout
prefills it. Django keeps it once a new verified payment arrives.

`accounts.0026` grants `accounts.create_additional_purchases` to the MENTOR and
ADMIN role groups. `sales.0019` adds the `ADDITIONAL` sale kind and its
constraints, plus database triggers. The triggers require an additional
purchase's quote to belong to its own account and its student to be the
account's (enrolled) student. 0019 cannot be reversed once additional
purchases exist.

## Manual Stripe Test configuration

1. Webhook destination (when not using the local listener, which forwards all
   events): add `payment_intent.succeeded`, `payment_intent.payment_failed`,
   `charge.refunded`, `refund.created`, `refund.updated`, `refund.failed`,
   `charge.dispute.created`, `charge.dispute.updated`, `charge.dispute.closed`,
   `charge.dispute.funds_withdrawn`, `charge.dispute.funds_reinstated`,
   `payment_link.created`, `payment_link.updated` to the existing Checkout,
   invoice, subscription, schedule and `payment_method.detached` events.
2. Billing → revenue recovery: Smart Retries, and *leave the subscription past
   due* after the last retry so later installments still collect.
3. Products `eduport_plus_tuition` and `eduport_plus_token` are created on first
   use (metadata `eduport_product`); do not archive them.
4. Optionally enable successful-payment receipts (sent to the parent's email).
5. Restrict who can create Payment Links in Dashboard team roles; tuition must
   be collected only through Eduport Plus links.

## Known limitations

- An additional purchase's payments record money only: no class-credit rule
  exists for them yet. Autopay, purchases while an earlier sale has an
  outstanding balance or a running Autopay, and sheet-managed students
  (no account) are refused with explicit codes until decided.
- A parent email typed on Checkout is kept only after a verified payment and
  only where Django has none. A different address typed later is not merged
  into Django.
- Refunds and disputes never reverse classes or change the outstanding balance
  (no approved policy). Cancelling Autopay does not void open invoices.
- Payment Links cannot be blocked technically; they are detected and never credited.
- Manual Dashboard charges without Checkout or an invoice are found by the
  reconciliation command, not at webhook time (a PaymentIntent no longer names
  its invoice in this API version).
- The first Autopay installment is a Checkout payment, not an invoice.
- The review queue has an API and command; there is no Hub page for it yet.
