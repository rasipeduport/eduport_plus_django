# Quote collection intention

The new-quote workflow requires the BDE to record **Single / Complete Payment**, **Partial Payment**, or **Autopay** after choosing the syllabus, plan and chapters. Selecting a course never implies complete payment. All work remains uncommitted on `feature/phase-1-sales-payments-enrollment`.

## Pricing and immutable terms

- `POST /api/sales/quotes/` requires `collection_mode`: `FULL`, `PARTIAL` or `AUTOPAY`. The service rejects a missing/invalid value too. Client-supplied prices are not trusted.
- FULL uses the existing Admin-configured single-payment eligibility and discount calculation. PARTIAL and AUTOPAY remove that conditional discount from every package line. No rate, plan eligibility or chapter-count rule was added.
- The issued snapshot stores the explicit mode, its calculated line prices and discounts, and the existing rounded whole-AED `collection_amount`. It also stores `collection_intention_confirmed=True`, meaning that the BDE recorded the choice; this is not Stripe consent or a mandate.
- The example is verified through both the API and browser: AED 2,765 before the discount becomes AED 2,627 for eligible FULL payment, and remains AED 2,765 for PARTIAL/AUTOPAY.
- The existing ROUND_HALF_UP allocation, published revision, chapter mode, pricing version, quote history and `supersedes` relationships remain in use. No quote or historical financial term is rewritten.

## Sales & Payment and explicit replacement

Sales & Payment loads the issued intention and displays it as read-only. FULL requires all remaining classes; PARTIAL uses the existing allocation form; AUTOPAY opens the existing schedule review. Correctly issued PARTIAL/AUTOPAY quotes need no discount-removal replacement.

The payment and Autopay services enforce the quote intention even when its discount is zero. An AUTOPAY quote cannot be collected through the plain direct-payment or Stripe collection endpoint. The shared ledger continues to use FULL/PARTIAL internally; an Autopay agreement distinguishes automatic collections.

The existing `/api/sales/enquiries/<enquiry-id>/installment-quote/` endpoint now supports:

- **GET** with `quote_id` and the target `collection_mode`: preview a replacement using the original frozen package, chapter allocation, rates, discount eligibility and pricing version.
- **POST** with those same required fields: explicitly issue the reviewed replacement through the existing immutable quote architecture.

The Hub offers “Change collection intention,” requires an explicit target, shows the backend-calculated replacement price, then requires “Issue replacement quote.” The previous quote remains in history. Stale expected quote IDs and existing payment/plan locks still prevent replacement. The existing token positive-tuition-balance guard applies to both replacement paths.

**Existing lock limitation:** replacement remains available only before collection has pinned a purchase. An unpaid/expired link does not reopen an existing immutable purchase. This task does not introduce amendments to already-started purchases or Mentor/Admin payment management.

## New migrations

- `sales.0012_quote_collection_intention`: adds AUTOPAY to quote choices, removes the implicit FULL default, and adds the explicit-intention marker. Historical rows remain unconfirmed; their original mode, prices and history are untouched.
- `sales.0013_quote_collection_integrity`: PostgreSQL guards require newly confirmed quote/purchase modes to match and use a deferred check to require exactly the appropriate Autopay agreement lifecycle. Legacy purchases/agreements are left intact.

Both migrations were exercised in disposable PostgreSQL databases only. No shared database was migrated and no shared/deployed container was rebuilt.

## Confirmed compatibility policy

Both previously pending decisions are implemented in the UI and backend services:

1. **Historical quote without a purchase or any collection:** New Sale and Token Sale are blocked with `COLLECTION_INTENTION_REQUIRED` (HTTP 409). The BDE must explicitly issue a replacement choosing FULL, PARTIAL or AUTOPAY. The same guard covers existing empty draft sales, amount previews, direct/Stripe collection and initial Autopay preview/begin, so bypassing the start form cannot collect against an unconfirmed quote.
2. **Existing purchase or any collection:** existing terms remain frozen, including pending, failed, expired and successful collection rows. These histories do not acquire a mandatory replacement requirement. Existing purchase IDs, paid token credit, reservation dates/references, original quote financial fields and snapshots remain unchanged. Signed webhook processing for historical pending purchases still verifies and enrolls exactly once. Existing purchase/plan locks continue to apply.
3. **Token Sale with an AUTOPAY quote:** blocked with `TOKEN_AUTOPAY_NOT_ALLOWED` (HTTP 409) before creating a reservation or collection. An explicit FULL/PARTIAL replacement is required. Both quote replacement paths also reject AUTOPAY for an existing Token Sale, and old invalid Token/AUTOPAY drafts cannot collect until replaced. New Sale Autopay is unchanged. Token reservations without a selected quote remain supported at AED 100.

The Sales & Payment summary and quote figures display “Not recorded (historical quote)” rather than interpreting an old FULL default as a recorded intention. The start button and empty-sale collection controls are blocked with an actionable replacement dialog; Token Sale dialogs offer FULL/PARTIAL only. The existing `can_collect` response reflects compatibility. No permission, schema, ledger model or backend endpoint was added for this follow-up.

The two earlier schema migrations remain as described above. **No additional migrations were created for compatibility enforcement.**

## Verification

Final complete backend result: **1,366/1,366 tests passed in 285.136 seconds**, with zero failures/errors. This includes all 13 new compatibility tests and the complete authorization matrix, which reports **zero differences**. The previous 1,353-test verification is retained in the JSON report's `before_compatibility_confirmation` record.

| Check | Result |
| --- | --- |
| Complete backend: accounts, invitations, students, sales, bookings, sessions and core; four workers | 1,366 passed in 285.136 seconds |
| Complete authorization matrix | Zero differences across 240 scenarios / 3,269 comparisons; original baseline/approved decisions retained |
| Hub Sales, including mandatory intention, all three prices and explicit replacement | 79/79 passed |
| Hub Leads | 37/37 passed |
| Hub Learn/Invitation authentication | 10/10 passed |
| Hub Reports | 30/30 passed |
| Real local API + Chromium browser runner | 32 checks passed; 16 screenshots; no page errors |
| Browser responsiveness | No page overflow at 320, 390 or 768 pixels for each intention, the Autopay schedule and both compatibility notices |
| Hub lint | 0 errors; 37 existing warnings |
| Hub production build | Passed; existing large-chunk warning remains |
| Django system check | No issues |
| Migration consistency | `makemigrations --check --dry-run`: no changes detected |
| Guarded repeatable browser seed | Passed against a new disposable database |
| Whitespace validation | `git diff --check` passed |

The browser verifies both confirmed compatibility decisions, all three explicit historical replacement intentions, preserved historical purchase/token payment continuity, mandatory selection, FULL 2,627 / PARTIAL 2,765 / AUTOPAY 2,765 pricing through the real API, PDF generation for all modes, fixed Sales & Payment intention, explicit replacement history, successful full/partial direct-payment enrollment, paid-only quota and post-enrollment BDE denial. It reviews the existing Autopay schedule as initial AED 553 plus remaining AED 2,212. No fake Stripe success or mandate is generated.

Backend compatibility cases cover historical snapshots with no purchase or collection, empty-sale API bypasses, purchase-only histories, all collection statuses, paid token continuity, signed historical Stripe webhook idempotency, both Token/AUTOPAY quote replacement paths, existing invalid Token/AUTOPAY drafts, unquoted token reservations and foreign-BDE denial. The earlier backend cases cover missing/invalid intention, tampered frontend prices, immutable mode/marker, each price, mode mismatch with no discount, direct/ordinary Stripe bypass of AUTOPAY, replacement in each direction using frozen original pricing, database-level agreement checks, quote PDF/summary, half-class allocation, mixed Regular/Revision packages and the token balance guard. Existing signed Stripe webhook, Autopay, enrollment, Learn, permissions, chapter/Bridge Course and Sheets quota regressions remain part of the complete suite.

Current verification artifacts are in `/private/tmp/eduport-collection-compatibility/`; earlier attempts are retained in `/private/tmp/eduport-collection-intention/`. The first new compatibility fixtures violated existing supersedes/reference-length guards; after correcting them, two success fixtures still lacked required receipt/provider evidence. Those fixtures were corrected without disabling database triggers. The first expanded Hub run had one assertion using a cumulative request count across three cases; it now checks exactly one new request per case. The final complete backend and Hub Sales runs pass without suppressed or expected failures. The first payment run had five stale fixture assertions (full collection against a PARTIAL quote and a replacement missing its intention); those fixtures now explicitly record the intended mode. A new PDF test initially called the existing context helper with the wrong signature, then was corrected. The final token guard test expected HTTP 400 although the established `SalesError` contract returns 409; its expected status was corrected without weakening the guard. The browser runner initially used an obsolete button selector for the tab; its corrected route navigation passes. No production permission was relaxed to make these checks pass.

## Pre-existing failures and external limitations

The broader Hub suites were rerun and compared with `verification/permission-review-results.json`:

- Strict access snapshots: **283/480 match**, with the **same 197 differing case keys**. No access-denied outcome changed. The original authorization baseline and approved-decision file are unchanged.
- Bookings: **70/139 pass**, with the **same 69 failed test names** as the earlier Phase 1/permission review. Their existing per-case explanations remain in that review ledger.

Those failures were not hidden, regenerated or approved away. The exact current results and baseline hashes are in `verification/quote-collection-intention-results.json`.

External Stripe Test Mode checkout was not performed: the disposable browser environment has no Stripe credentials. Existing backend tests exercise the SDK transport and signed/idempotent webhook behavior using fixtures; this does not establish an external charge or reusable-payment-method verification. Actual Stripe configuration and verification remain required.

The previously documented Autopay retry policy gap also remains: initial attempt plus three retries, 24 hours apart, then pause/Admin follow-up is **not implemented**. This quote-only change neither adds nor claims retry scheduling.

## Files changed for this enhancement

Backend:

- `backend/sales/models.py`
- `backend/sales/quotes.py`
- `backend/sales/quote_views.py`
- `backend/sales/payments.py`
- `backend/sales/payment_views.py`
- `backend/sales/autopay.py`
- `backend/sales/templates/sales/pdf/syllabus.html`
- `backend/sales/migrations/0012_quote_collection_intention.py` (new)
- `backend/sales/migrations/0013_quote_collection_integrity.py` (new)
- `backend/sales/tests_collection_intention.py` (new)
- `backend/sales/tests_collection_compatibility.py` (new)
- `backend/sales/tests_quotes.py`
- `backend/sales/tests_chapter_modes.py`
- `backend/sales/tests_student_plans.py`
- `backend/sales/tests_payments.py`
- `backend/sales/tests_autopay.py`
- `backend/sales/tests_authorization.py`
- `backend/core/authz_matrix.py`
- `backend/core/phase1_authz_expectations.py`
- `backend/core/tests_authz_matrix.py`

Hub:

- `frontend/hub/src/lib/sales.js`
- `frontend/hub/src/lib/payments.js`
- `frontend/hub/src/components/sales/quote-builder.jsx`
- `frontend/hub/src/components/sales/quote-dialogs.jsx`
- `frontend/hub/src/components/sales/quote-parts.jsx`
- `frontend/hub/src/components/sales/collection-replacement-dialog.jsx` (new)
- `frontend/hub/src/components/enquiries/workspace/enquiry-plan-choosing.jsx`
- `frontend/hub/src/components/enquiries/workspace/enquiry-sales-payment.jsx`
- `frontend/hub/src/components/enquiries/workspace/autopay-builder.jsx`
- `frontend/hub/tests/sales/run.mjs`
- `frontend/hub/tests/sales/browser/collection-intention.mjs` (new)
- `frontend/hub/tests/sales/browser/seed.py` (new)
- `frontend/hub/tests/sales/browser/README.md` (new)
- `frontend/hub/package.json`

Documentation:

- `docs/quote-collection-intention.md` (new)
- `docs/verification/quote-collection-intention-results.json` (new)

The browser runner is invoked with `npm run test:sales:browser`; its README describes the guarded disposable environment. Current raw logs, browser results and screenshots are retained in `/private/tmp/eduport-collection-compatibility/`; the earlier quote-only verification remains in `/private/tmp/eduport-collection-intention/`. Existing unrelated uncommitted Phase 1, Autopay, Learn and permission work remains preserved. Nothing was committed or pushed.

## Files changed for the confirmed compatibility follow-up

- `backend/sales/payments.py`: shared historical-history and Token/AUTOPAY guards, consistent start/collection enforcement and `can_collect` status.
- `backend/sales/quotes.py`: Token/AUTOPAY rejection for both immutable replacement paths.
- `backend/sales/autopay.py`: historical intention guard on initial schedule review.
- `backend/sales/tests_collection_compatibility.py`: 13 new backend cases and the guarded historical snapshot fixture.
- `backend/sales/tests_autopay.py`: explicitly use a PARTIAL quote for the existing Token Sale exclusion fixture.
- `frontend/hub/src/lib/payments.js`: UI compatibility predicate using existing quote/purchase/payment data.
- `frontend/hub/src/components/enquiries/workspace/enquiry-sales-payment.jsx`: disabled incompatible actions, replacement recovery and frozen-history labels.
- `frontend/hub/src/components/sales/quote-parts.jsx`: explicit unrecorded historical intention label.
- `frontend/hub/src/components/sales/collection-replacement-dialog.jsx`: historical label and FULL/PARTIAL options for Token Sale.
- `frontend/hub/tests/sales/run.mjs`: seven new frontend cases, including all replacement modes.
- `frontend/hub/tests/sales/browser/collection-intention.mjs`, `seed.py` and `README.md`: 32 repeatable real-API browser checks and ten guarded disposable enquiry fixtures.
- This report and `docs/verification/quote-collection-intention-results.json`: exact results and preservation evidence.
