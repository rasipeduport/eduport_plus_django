# Phase 1 implementation verification

Phase 1 adds initial sales, verified payments and automatic enrollment to the merged syllabus, quote and Chapter Plan implementation. All changes remain uncommitted on `feature/phase-1-sales-payments-enrollment`, based on clean `main` at `fb0236b`. The merged syllabus-card commit `207873c` and Chapter Plan commit `3369eec` remain ancestors. No push, shared database migration or shared/deployed container rebuild was performed.

Implementation, endpoints, Stripe configuration, webhook setup and operational boundaries are documented in [Phase 1 sales payments and enrollment](phase1-sales-payments.md).

## Implementation details

- The enquiry Sales & Payment tab reads the issued quote snapshot automatically. It supports New Sale, Token Sale, full/partial collections, private direct receipts and Stripe-hosted links. Admin uses the same summary from the existing lead page and enrolled-student profile.
- A separate immutable Purchase freezes classes, whole-AED amount and collection mode against the existing quote. Payment identity survives conversion from enquiry to Student. No initial payment is copied.
- The final payable package amount uses Decimal ROUND_HALF_UP. Cumulative proportional allocation and the final installment conserve the whole package total; token credit covers money, never classes. Frontend amounts are only previews.
- A conditional single-payment discount blocks installments until an explicit immutable replacement quote is issued through supersedes. Existing pricing versions, chapter Regular/Revision mode, rates, selections and historical snapshots remain pinned.
- The official Stripe 16.1.0 SDK creates/reuses a Customer by enquiry UUID and creates a single-use hosted Checkout Session. Whole AED is sent as amount × 100 minor units. Signed snapshot webhooks verify amount, AED currency, Customer, linked metadata and test/live mode. Provider event and transaction IDs, transaction locks and immutable ledger triggers prevent duplicate credit.
- First verified tuition creates the Student, EDP sequence number, initial paid quota and a pending username/password invitation. Demo tutors are retained. Learn no longer uses Google or parent-email account linking; see [the updated authentication verification](learn-enrollment-credentials.md).
- BDE collection ends at enrollment, enforced by backend APIs. Admin can view initial history and use the existing mentor assignment workflow. Mentors see their assigned academic plan through existing profile scoping and have no Phase 1 payment access.
- Token reservations collect AED 100 and require an expected start date. The existing BDE follow-up feed derives one reminder, due three days before start, with upcoming/overdue status, payment status and remaining tuition balance.
- Payment-managed half-class quota is protected from Google Sheets sync. Existing session consumption and sheet-managed students retain their workflow.

## Migrations

Four migrations were created and exercised only in disposable PostgreSQL databases:

| Migration | Purpose |
| --- | --- |
| accounts 0023 | Initial-sales permission and BDE/Admin grants |
| students 0005 | Quota source and Decimal half-class quota |
| sales 0008 | Sale, Purchase, Payment, Stripe Customer/event mapping, sequences and quote collection fields |
| sales 0009 | Immutable ledger and allocation integrity triggers |

The permission migration was also reversed and reapplied in the role-permission regression suite. Removing the ledger integrity migration is refused when financial history exists.

## Tests executed

Backend tests use the existing backend image with source/dependency mounts and a separate disposable PostgreSQL 16 container. Shared application databases and containers were not rebuilt or migrated. Results below overlap and must not be added together.

| Check | Exact result |
| --- | --- |
| Untouched base: sales, students, sessions, BDE follow-ups, enquiry and admissions suites | 483/483 passed, 313.488 seconds |
| Current broad regression: same modules plus initial payment tests | 505/505 passed, 310.521 seconds |
| Payment/reminder tests after SDK request-encoding coverage | 41/41 passed, 15.245 seconds |
| Role permission catalogue, grants and migration reversals | 84/84 passed, 9.518 seconds |
| Enrollment/payment, existing authentication, permissions and reminder regression | 209/209 passed, 79.351 seconds |
| Final completed payment suite, including Learn login and parent account validation | 25/25 passed, 14.228 seconds |
| Final payment and quote regression after the token package-balance guard | 55/55 passed, 33.793 seconds, including all 26 payment tests |
| makemigrations --check --dry-run against the populated disposable database | No changes detected |
| git diff --check | Passed |
| Hub production build | Passed, 4.31 seconds; large-bundle warning remains |
| Hub lint | 0 errors, 37 warnings; untouched base also has 37 warnings |
| Hub sales | 63/64 passed; untouched base 58/59, same single WhatsApp help-text assertion failure |
| Hub reports | 30/30 passed |
| Hub access matrix | 286/480 matched; same 194 pre-existing mismatched scenarios as untouched base |
| Hub bookings | 70/139 passed; same 69 pre-existing failing cases as untouched base |
| Hub leads | 36/37 passed; same pre-existing booking-link URL assertion failure as untouched base |

The first broad backend run had two outdated assertions for fractional-AED PDF text and rejection of the newly supported overdue filter. Both were updated and the broad rerun passed. Existing permission tests were extended from 72 to 73 catalogue entries and now verify the new grant and migration reversal. Hub assertions for the Enrolled filter and Overdue tab were updated to the authorized behavior. No unrelated baseline failures were fixed or hidden.

The final 26 payment tests cover whole-AED rounding and allocation conservation, token credit, invalid classes, all direct methods, receipt/date requirements, first-payment enrollment, duplicate and simultaneous requests, unique concurrent EDP codes, immutable payment/purchase rows, quote replacement, BDE scope and post-enrollment refusal, Admin mentor assignment, demo tutor preservation, sheet-sync exclusion, missing/conflicting parent email, Learn sign-in continuity, Stripe Customer reuse, SDK request encoding, signed success/failure/unpaid webhooks, invalid signatures, duplicate events and amount/currency/reference mismatch. Token reservations also reject a new/replacement quote that would leave no positive tuition balance beyond the fixed token, preserving the prior quote unchanged.

## Browser verification and screenshots

Playwright used the actual Hub and API with a fresh disposable database. It verified:

- New Sale, six-class AED 300 direct payment against ten classes / AED 500; exactly one EDP student, six paid quota and four unpaid classes.
- Post-enrollment BDE payment API refusal and authenticated receipt bytes downloaded unchanged.
- AED 100 token payment without Student or quota, then AED 400 tuition conversion with the same two ledger records and ten paid classes.
- Explicit installment replacement, original quote discount preserved and replacement discount removed.
- Student appearance in Admin's list/profile, existing mentor assignment, preserved demo tutor and mentor academic access without payment access.
- No page overflow at 768, 390 and 320 pixels; no browser runtime errors.
- Paid quota labels distinct from total purchased classes in the final Admin profile.

Screenshots are development artifacts outside the repository:

| View | Artifact |
| --- | --- |
| New Sale desktop | [new-sale-desktop.png](/private/tmp/eduport-phase1/screenshots/new-sale-desktop.png) |
| New Sale mobile | [new-sale-mobile.png](/private/tmp/eduport-phase1/screenshots/new-sale-mobile.png) |
| Enrolled initial sale | [enrolled-initial-sale.png](/private/tmp/eduport-phase1/screenshots/enrolled-initial-sale.png) |
| Token reservation | [token-reservation-desktop.png](/private/tmp/eduport-phase1/screenshots/token-reservation-desktop.png) |
| Installment replacement | [installment-replacement.png](/private/tmp/eduport-phase1/screenshots/installment-replacement.png) |
| Admin student and assigned mentor | [admin-student-enrollment.png](/private/tmp/eduport-phase1/screenshots/admin-student-enrollment.png) |

Logs and browser scripts are retained under `/private/tmp/eduport-phase1/`, including `final-backend-regression.log`, `token-quote-final-tests.log`, `payments-complete-tests.log`, `enrollment-auth-final-tests.log`, `browser-results.json` and the Hub baseline/final logs.

## Remaining configuration and limits

No local Stripe credentials were configured. SDK transport and signed-webhook tests passed; an actual Stripe Test Mode checkout and external webhook delivery remain unverified. Set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_LIVE_MODE=False` and the correct `HUB_URL`. The server uses hosted Checkout, so no publishable key is required. The stored provider link reference is a Checkout Session ID (`cs_…`), not a reusable Payment Link ID (`plink_…`).

Configure the webhook URL and subscribed events as described in the implementation guide. Deploy the official Stripe dependency and four migrations through the normal release process. Keep private durable media and the existing Celery worker/beat for post-enrollment Customer metadata retries. Reserve externally issued EDP numbers with `SALES_EDP_MIN_NUMBER` if they are absent from Student/invitation records.

Token reminders appear in the existing BDE feed; no external reminder transport is added. Reassignment away from the original BDE requires Admin review and suppresses that token's BDE reminder rather than revealing another owner's enquiry. Tuition collection permanently pins the quote even if its link expires; retry against the pinned purchase. Learn email validation has been replaced by enrollment-generated credentials; see the updated Learn authentication verification. Initial-history corrections, refunds and manual reconciliation require later administrative tooling.

Future student collections, full Financials, Mentor payments, additional purchases, renewals, EMI and Autopay remain outside Phase 1. Existing merged work is preserved; all Phase 1 changes below are uncommitted.

## Complete changed file list

35 tracked files modified and 17 new files, 52 total.

- Modified: `backend/.env.example`
- Modified: `backend/accounts/permission_catalogue.py`
- Modified: `backend/accounts/tests_permissions.py`
- Modified: `backend/bookings/admissions.py`
- Modified: `backend/bookings/lead_status.py`
- Modified: `backend/communications/followups.py`
- Modified: `backend/communications/tests_bde_followups.py`
- Modified: `backend/config/settings.py`
- Modified: `backend/requirements.txt`
- Modified: `backend/sales/models.py`
- Modified: `backend/sales/pdf.py`
- Modified: `backend/sales/quote_views.py`
- Modified: `backend/sales/quotes.py`
- Modified: `backend/sales/templates/sales/pdf/syllabus.html`
- Modified: `backend/sales/tests_chapter_modes.py`
- Modified: `backend/sales/tests_quotes.py`
- Modified: `backend/sales/urls.py`
- Modified: `backend/students/models.py`
- Modified: `backend/students/quota_sync.py`
- Modified: `backend/students/services.py`
- Modified: `backend/students/views.py`
- Modified: `frontend/hub/src/App.jsx`
- Modified: `frontend/hub/src/components/sales/quote-parts.jsx`
- Modified: `frontend/hub/src/components/students/profile/overview-tab.jsx`
- Modified: `frontend/hub/src/lib/access.js`
- Modified: `frontend/hub/src/lib/enquiries.js`
- Modified: `frontend/hub/src/lib/follow-ups.js`
- Modified: `frontend/hub/src/lib/sales.js`
- Modified: `frontend/hub/src/pages/EnquiryPage.jsx`
- Modified: `frontend/hub/src/pages/LeadPage.jsx`
- Modified: `frontend/hub/src/pages/StudentProfilePage.jsx`
- Modified: `frontend/hub/tests/access/approved-changes.json`
- Modified: `frontend/hub/tests/bookings/run.mjs`
- Modified: `frontend/hub/tests/leads/run.mjs`
- Modified: `frontend/hub/tests/sales/run.mjs`

- Added: `backend/accounts/migrations/0023_alter_hubpermission_options.py`
- Added: `backend/sales/enrollment.py`
- Added: `backend/sales/migrations/0008_salessequence_stripecustomer_stripeevent_and_more.py`
- Added: `backend/sales/migrations/0009_payment_integrity.py`
- Added: `backend/sales/payment_models.py`
- Added: `backend/sales/payment_uploads.py`
- Added: `backend/sales/payment_views.py`
- Added: `backend/sales/payments.py`
- Added: `backend/sales/stripe_gateway.py`
- Added: `backend/sales/tasks.py`
- Added: `backend/sales/tests_payments.py`
- Added: `backend/students/migrations/0005_student_quota_source_alter_student_total_class_quota.py`
- Added: `docs/phase1-sales-payments.md`
- Added: `docs/phase1-verification.md`
- Added: `frontend/hub/src/components/enquiries/workspace/enquiry-sales-payment.jsx`
- Added: `frontend/hub/src/lib/payments.js`
- Added: `frontend/hub/src/pages/PaymentReturnPage.jsx`

