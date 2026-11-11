# Permission regression review

> Historical verification report: the results, counts, pass/fail findings and
> artifact paths below belong to the original pre-Billing permission review.
> They do not verify the subsequently implemented Stripe Billing P1 fixes or
> later manual Stripe testing. The former custom retry-policy findings are
> superseded by the Stripe Billing architecture decision. See the
> [historical evidence guide](verification/README.md) for scope and the
> [current Billing integration](stripe-billing-integration.md) for current behavior.

The eight failed assertions/subtests and 91 authorization differences from the Learn report are resolved. The original baseline from `3d56003` and the existing approved decisions were preserved. Production permissions, role groups, API guards and pricing/enrollment implementations were not changed by this review. The corrected expectations are explicit test contracts in `backend/core/phase1_authz_expectations.py`.

At the time of this review, the former custom PaymentIntent retry acceptance audit failed. That policy has since been superseded by Stripe Billing's native retry/recovery architecture; it is not a current Billing completion blocker. The strict Hub UI snapshot failures recorded in this historical run were not blanket-approved.

## Baseline comparison and the 91 differences

| Group | Cases | Intended change and retained boundary |
| --- | ---: | --- |
| Admin and existing superuser `/me/` results | 4 | Add only `manage_initial_sales`, already granted by accounts.0023; ordinary Mentor/Tutor gain no capability. Superuser authority remains the earlier D1 decision, independent of role label. |
| Lead responses | 12 | Add `original_source` to the same scoped CRM records. No status, ownership or returned record set changes. |
| Quote responses | 16 | Add `class_mode` and whole-AED collection amount/discount/mode/subtotal to existing immutable quotes. No new quote visibility or pricing authority. |
| Academic student responses | 21 | Add `quota_source` to the same permitted students, distinguishing payment-ledger quota from Sheets. Teaching roles receive no payment ledger or Autopay details. |
| Quota sync message | 5 | Decimal class quota renders `40.0` rather than `40`; the value, record scope and permissions are unchanged. Half classes remain supported. |
| Previously unrecorded notes scenarios | 33 | Eleven callers across three note endpoints. Admin reads all-lead notes; BDE reads its own enquiry context; Tutor reads assigned-booking context. Anonymous/unauthorized callers remain refused. An unassigned booking is 404 for eligible Tutor/superuser callers. Non-BDE superusers entering the BDE-only context get explicit NOT_A_BDE rather than a grant. |
| Total | **91** | **58 narrowly defined modifications and 33 new note expectations.** |

The review does not calculate expected permissions from current production permissions or copy observed responses into a new baseline. Each field addition, grant and per-caller refusal is defined explicitly. A dedicated test checks the exact 58/33 change counts and preserves existing status/record sets for all 58 modified cases. All unnamed baseline results remain part of the equality comparison.

The [per-case ledger](verification/permission-review-results.json) lists every one of the original 91 cases, its reason, added fields, status and scope comparison. It also records the unchanged original baseline hash. No existing entry in `approved_changes.json` was overwritten during this review.

The matrix in this run covered **239 scenarios**, **2,559 original-caller comparisons** and **696 new-role-world comparisons**. All API routes present at that time were exercised. The fourteen new transport scenarios contributed 154 original-caller comparisons.

## The eight original failed assertions

| Assertion or subtest | Cause | Correction |
| --- | --- | --- |
| Account basics, BDE `/me/` | Permission fixture predates the initial-sales grant | Add only manage_initial_sales to the two BDE expectation lists. |
| Every API route appears in the matrix | Twelve implemented Phase 1/Autopay routes were omitted | Add fourteen method/scoping scenarios, exercising all twelve routes. |
| Every endpoint matches its recorded authorization answer | The 91 reviewed deltas above | Layer explicit reviewed expectations over the preserved original baseline. |
| New roles, BDE `/me/` | Same missing BDE permission | Keep all prior BDE capabilities and add only the existing initial-sales capability. |
| New roles, BDE quote creation | Fixture lacks five Chapter Plan/collection fields | Add those response fields; keep ownership, pricing and quote record expectations. |
| Every view declares an authorization guard | Two signed external transports were treated as staff-session views | Recognize only StripeWebhookView and ParentAutopayActionView as signed transports; assert exact AllowAny and empty session-authentication classes. |
| Staff session requirement, Stripe webhook | Provider signatures authorize this endpoint, not Hub cookies | Keep raw-body signature verification and add behavior tests showing missing/forged proof fails regardless of staff identity. |
| Staff session requirement, parent action | A bounded signed attempt token authorizes this endpoint | Keep token/age verification, private/no-store response and exact payment binding; add tampering/expiry/valid-token tests. |

## Additional catalogue seed fixture corrected

The first full backend run found one further outdated expectation: `CatalogueTests.test_the_migrations_seed_what_the_catalogue_declares` combined the immutable historical seeds without applying the 0025 display-label rename. The seed still correctly says "Change an invitation's email"; the current catalogue correctly says "Retrieve initial Learn credentials".

The fixture now applies that one explicit label change before comparing the complete final catalogue. An additional test runs the label migration forward/backward and verifies the same permission ID/codename/content type and unchanged group/user grant rows. No historical migration, production grant or permission ceiling was edited.

## Security boundaries verified in the original run

- BDE can read/manage an assigned enquiry's initial sale; every tested staff transport returns 404 for another BDE's real enquiry/payment. No unassigned or foreign enquiry becomes accessible by guessing an ID.
- After enrollment, fresh payment allocation, payment collection, Autopay setup and Checkout expiry/restart are denied. Quote replacement remains blocked by the existing immutable-plan conflict. Historical sale/receipt reads and unchanged idempotent replays remain available, without creating another purchase, payment, student, invitation or quota credit.
- Admin retains initial-sale, receipt, enrolled-student, invitation/credential and initial Autopay oversight. The later Student Financials/payment-management workflow was not added.
- Ordinary Mentor, Tutor, Sales TL and Student accounts cannot obtain initial-sales access even through an attempted direct database permission grant: the existing role ceiling rejects it. Assigned teaching staff retain academic profile access while financial/Autopay payloads and endpoints are denied.
- Stripe callbacks require a valid raw-body signature and matching event/payment references. A staff session is insufficient. Signed success, failure, duplicates and wrong amount/currency/customer/environment remain exercised by the existing ledger/Autopay suites.
- Parent action links require a signed attempt token, expire after seven days and expose a reusable PaymentIntent secret only for the valid corresponding authentication-required collection. Reading a link grants no quota. Failed/pending/authentication-required collections remain uncredited.
- Learn username/password invitations remain separate from Hub staff login. Hub refuses Student credentials, Learn refuses staff/legacy unissued identities, Google login stays removed, and CSRF/first-login activation tests remain in the full backend regression run.

## Historical custom PaymentIntent retry finding (superseded)

The former custom PaymentIntent policy required an initial scheduled attempt plus **three retries**, **24 hours apart**, then **pause and Admin follow-up** after the fourth failed attempt. These are historical requirements, not the current Stripe Billing acceptance criteria.

The separate acceptance audit deliberately expects that behavior. It advances the clock through all four collection checkpoints and delivers a signed failure after each actual charge. Observed result:

| Observation | Expected | Actual |
| --- | --- | --- |
| Scheduled installment attempts | 4 | **1** |
| Agreement after failed retry budget | PAUSED | **ACTIVE** |
| Paid class quota after all failed collections | 2.0 | **2.0**, unchanged |

This audit **failed** in its original run, rather than being skipped or marked expected-failure. Its source is preserved byte-for-byte as an [archived historical script](verification/archive/custom-paymentintent/autopay_retry_acceptance.py). It is not a current acceptance test; its fixture imports have since changed, so executing it against the current checkout would not reproduce the old environment.

In that pre-Billing implementation, `collect_due()` excluded FAILED installments and `prepare_due()` only resumed SUBMITTING/UNKNOWN transport operations with the same attempt/idempotency key. Neither path implemented the former retry budget or exhaustion follow-up, and the API still labeled the policy AWAITING_CONFIRMATION. Those were the gaps recorded by this audit. Current Billing agreements instead delegate recurring invoice collection and retry/recovery to Stripe; the old findings must not be applied to that engine as current acceptance requirements.

## Hub regressions retained for review

The strict UI access golden suite remains failing. The [per-case ledger](verification/permission-review-results.json) identifies every remaining case and its differing dimensions. No access-denied result changed across the full 480-result matrix, and ordinary Mentor/Tutor/Student/unknown/Sales TL scenarios make no initial-sales/Autopay financial API request. This observation is supported by the backend live-object tests; the UI snapshot alone does not prove object authorization.

The remaining UI differences include the existing Academics Dashboard/Tutor navigation, controls/headers, booking-history/notes/feed calls and seven compatibility redirects to the current Demo list/detail routes. Correcting the Admin/BDE initial-sales capability fixtures also exposes the current Admin initial-history reads that older fixtures did not exercise. These full UI expectations need a separate fixture/design review before the strict suite can be declared green; no broad golden-file regeneration or assertion suppression was used.

The booking-page suite has 69 failures with the **same failed test names** as the earlier Phase 1 run. They include obsolete side-sheet/query URL expectations, old assignment button/selectors and text/layout assertions. The ledger preserves every test name and first error, with the full assertion context in hub-bookings.log. Its production UI and test suite were not changed here.

Two focused obsolete assertions were safely corrected: the Lead booking link now targets the existing direct detail route, and the PDF-sharing test checks the actual safe new-window link behavior instead of a removed help paragraph. The authenticated/local/blob URL prohibition, preview and authenticated download assertions remain intact. No sharing integration or production route was changed.

## Recorded verification results (original run)

| Check | Final result |
| --- | --- |
| Full backend: accounts, invitations, students, sales, bookings, sessions, core; four isolated workers | **1,341 tests passed**, 306.370 seconds, zero failures/errors |
| Focused complete matrix, scoping and live sales/Autopay authorization tests | **25 passed**, 37.411 seconds |
| Complete matrix | **0 differences**, 239 scenarios, 3,255 caller comparisons; all API routes exercised |
| Hub Sales | **70/70 passed**, including two new denial cases and retained authenticated sharing checks |
| Hub Leads | **37/37 passed** |
| Hub Learn/Invitation authentication | **10/10 passed** |
| Hub Reports | **30/30 passed** |
| Hub Bookings | **70/139 passed**, 69 unchanged earlier failures, individually listed in the ledger |
| Hub strict UI access snapshots | **283/480 match**; 197 unapproved UI differences, individually listed in the ledger; zero changed access-denied outcomes |
| Hub lint | **0 errors**, 37 existing warnings |
| Confirmed Autopay retry acceptance audit | **1 test failed**, explicitly observed one attempt/ACTIVE instead of four/PAUSED; no unearned quota |
| Whitespace validation | `git diff --check` passed |

The initial full run executed 1,340 tests in 680.921 seconds with one failure (the stale 0025 label fixture described above). After correcting that expectation and adding the migration-identity test, the full 1,341-test rerun passed. No remaining backend authorization baseline failure was excluded, skipped or marked expected-failure.

The original run recorded raw logs and before/after reports under `/private/tmp/eduport-permission-review/`: `backend-final.log`, `authorization-tests.log`, `matrix-full-differences.json`, the `hub-*.log` files, `hub-access-all-results.json`, `hub-access-final-differences.json` and `retry-policy-audit.log`. These are historical paths whose continued availability is not guaranteed. The retained review ledger is [permission-review-results.json](verification/permission-review-results.json).

The retry audit uses signed webhook fixtures and mocked Stripe transport. No external Stripe charge or live-credential test was performed. Test databases and their four clones were disposable and separate from shared services.

## Historical outstanding findings

1. **Former custom Autopay retry implementation:** this was a blocker at the time of the original audit. It is superseded by the later Stripe Billing/native recovery decision and is not a current Billing P1 acceptance criterion.
2. **Strict Hub UI regression baselines:** the original run left 197 access snapshot differences and 69 booking interaction failures for deliberate UI/fixture review. Each case is retained in the ledger; none was approved away. This cleanup did not rerun those suites or establish their current results.

## Changed files for this review

- backend/core/authz_matrix.py: fourteen additional transport scenarios.
- backend/core/phase1_authz_expectations.py: explicit reviewed field/grant/role contracts.
- backend/core/tests_authz_matrix.py: reviewed comparison layer and delta-scope test.
- backend/core/tests_role_scoping.py: correct BDE capability fixture and tightly named signed-transport checks.
- backend/sales/tests_authorization.py: nine live-object boundary tests.
- backend/accounts/tests_permissions.py: migration-aware label fixture and grant/identity preservation check.
- frontend/hub/tests/access/run.mjs: current Admin/BDE initial-sales fixture capability and optional full-result audit export; default strict UI comparison retained.
- frontend/hub/tests/sales/run.mjs: two additional financial-denial cases and updated sharing behavior assertion.
- frontend/hub/tests/leads/run.mjs: existing direct booking-detail URL expectation.
- docs/learn-enrollment-credentials.md and docs/phase1-autopay.md: current review/retry status.
- This report, verification/permission-review-results.json and verification/archive/custom-paymentintent/autopay_retry_acceptance.py: historical audit trail and archived source for the superseded retry acceptance check.

No new database migrations were created. Shared databases/containers were not migrated or rebuilt. The current feature branch and all prior uncommitted work were preserved; nothing was committed or pushed.
