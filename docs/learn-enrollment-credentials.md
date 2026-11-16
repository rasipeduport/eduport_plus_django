# Learn enrollment credentials

**Permission review update:** The eight assertions and 91 differences described below are historical results from the Learn implementation. They are resolved by the subsequent [permission regression review](permission-regression-review.md), which preserves the original baseline and uses reviewed expectations plus live-object security tests. That report contains the current exact results and separately records the unimplemented confirmed Autopay retry policy.

Learn uses student usernames and passwords issued at enrollment. BDE collection requires no Learn email. The initial verified tuition payment creates one Student, one dedicated student account and one invitation in the existing payment transaction. Token payments and unpaid Checkout sessions issue no academic account or credentials. Pricing, immutable quotes, Autopay, quota, demo tutor retention and mentor assignment keep their existing services.

## Authentication and invitation lifecycle

Previously, tuition collection required a parent email, reused an email-matched parent account, and created an accepted Google-login whitelist invitation. Learn verified Google identity tokens and could provision academic records during login.

Now enrollment generates an EDP ID, derives a lower-case username from it (a random suffix resolves a username collision), generates a 192-bit random temporary password, hashes it with Django, and creates a PENDING invitation linked directly to Student and User. Each newly enrolled student has a separate account; siblings and matching staff/contact emails never select their identity.

`POST /api/auth/learn/login/` authenticates an existing issued student account with Django's shared lockout backend, IP throttle and CSRF checks. It rotates the Django session and returns `must_change_password`. No login creates a Student. `/api/auth/google/` is removed and returns 404. Hub's staff login endpoint and its student-account refusal remain intact. Google Sheets service-account authentication, Meet links and fonts remain independent integrations.

Learn redirects a temporary-password session to `/change-password`. The existing server middleware refuses normal APIs until the password changes. `/me/` withholds student academic payloads during this stage. `POST /api/auth/change-password/` validates the current password, rejects reuse, applies Django password validators, updates the hash and session, marks the invitation ACCEPTED (shown as Activated), timestamps activation and erases the encrypted temporary credential atomically. Other sessions issued against the old hash are invalidated.

## Credential delivery and configuration

Set `LEARN_INVITATION_KEYS` to a comma-separated list of Fernet keys in backend environment configuration. Generate a key with `cryptography.fernet.Fernet.generate_key()` in a secure operational environment; place its output in the secret store, never source control, application logs or the frontend. The new explicit dependency is `cryptography==50.0.2`.

The first key encrypts; retained older keys decrypt pending invitations during staged key rotation. Keep the keys outside the database and back them up securely. Removing the only key able to decrypt a pending invitation makes its initial password unrecoverable. Database backups can still contain older encrypted copies after live activation; protect key access and backups accordingly. No SECRET_KEY fallback or development credential key is built in. Missing/invalid key configuration refuses tuition collection before creating a payment. Signed webhooks whose enrollment cannot complete must be retried after correcting configuration; the transaction does not partially enroll.

The User table stores only Django's password hash. Invitation stores authenticated ciphertext containing the initial password, bound to that invitation, student and account. Credentials are neither returned in list/sale responses nor placed in audit payloads, notification jobs, URLs or browser storage.

The Admin Invitation list shows student name, EDP ID, username, Pending/Activated status, creation date and inviter. An explicit **Reveal temporary password** action calls `POST /api/invitations/<id>/credentials/`, requiring both view and change-invitation permissions. The response is `no-store, private`, CSRF protected and audited without recording the secret. A modal permits private copying/sharing and clears its state on close. No credentials are automatically sent to another person. After activation, retrieval returns 409 and the action disappears. Share credentials privately and close the modal afterward; clipboard contents and a recipient's copy remain outside application control.

## Existing accounts and invitations

The migrations add nullable student-account email and direct invitation relationships without remapping existing users or generating secrets during schema migration. Email stays required by staff account creation; optional CRM parent contact email remains available for Stripe correspondence and historical records.

Existing Google-only accounts cannot use the new login endpoint until a student-specific invitation is issued. Admin can choose **Issue Learn credentials** on an existing student's legacy invitation. This locks the Student, creates a dedicated account, reassigns only Student.profile and links/reuses the historical invitation. Repeated issuance returns the existing invitation without rotating credentials, including activated accounts. Academic IDs, mentors, tutors, quote/purchase/payment history and quota are unchanged. Any former parent session loses access to that student once its profile relationship moves; siblings remain untouched until their own transition.

For existing students without legacy invitation rows, or a controlled bulk cutover, use the same idempotent service through:

```sh
python manage.py issue_learn_credentials --student-code EDP00018
python manage.py issue_learn_credentials --student-code EDP00018 --execute
python manage.py issue_learn_credentials --all
python manage.py issue_learn_credentials --all --execute
```

The default is a dry run. The command prints counts only; Admin retrieves initial credentials through the authorized UI. No legacy student data was transitioned in a shared database during implementation. Before enabling this release for existing users, configure the key, apply migrations through the normal deployment process, issue invitations and privately distribute credentials. Old email-only pending invitations no longer create students at login. The existing authorized Sheets import remains available; it creates the student account/invitation immediately and seeds quota from the server-read paid-class column.

Automatic temporary-password expiry, password recovery after activation and automated credential delivery are outside this change. Pending credentials remain retrievable until activation. Permanent passwords are never recoverable from the invitation list.

## Schema and API changes

- `accounts/0024_alter_user_email.py`: student accounts can have no email; existing email values are retained.
- `accounts/0025_learn_invitation_permission_label.py`: relabels the existing change-invitation permission as credential retrieval, preserving its codename and grants.
- `invitations/0004_invitation_account_invitation_activated_at_and_more.py`: one-to-one Student and User links, encrypted initial credential, activation timestamp and optional historical contact email. Unique constraints prevent duplicate linked invitations. PROTECT retains linked student/account history.
- `POST /api/auth/learn/login/`: student username/password session authentication.
- `POST /api/auth/google/`: removed, 404.
- `POST /api/auth/change-password/`: also activates the linked invitation and erases initial ciphertext under an account lock.
- `GET /api/invitations/`: adds direct student/account display information; never includes credentials or ciphertext.
- `POST /api/invitations/<uuid>/credentials/`: explicit authorized, audited initial credential retrieval.
- `POST /api/invitations/students/<uuid>/issue/`: explicit authorized legacy student transition.
- Existing invitation creation imports authorized Sheets students and immediately issues credentials; email-based PATCH/resend is retired with 410. Linked/accepted invitations cannot be deleted.
- Sale/payment/Autopay request serializers no longer accept a Learn email field. Enrollment never searches for or links users by email.

The encryption uses [Fernet authenticated encryption and MultiFernet rotation](https://cryptography.io/en/latest/fernet/). Session authentication and hash-based invalidation follow [Django authentication](https://docs.djangoproject.com/en/6.0/topics/auth/default/).

## Verification

Results and the feature-specific changed-file list follow below. All databases and browser services used for this verification were isolated from shared containers. No commits, pushes, shared migrations or shared container rebuilds were performed.

| Check | Result |
| --- | --- |
| Final `manage.py test invitations sales.tests_payments sales.tests_autopay students.tests accounts.tests accounts.tests_auth accounts.tests_team core.tests_csrf` | **366 passed**, 194.293 seconds |
| Enrollment credential tests, included above and rerun after the final migration | **25 tests passed**: direct/Stripe enrollment, signed duplicates, concurrent allocation regressions, separate identities, hashing/encryption, no-email collection, CSRF, first-login gate, activation, erased credentials, session invalidation, legacy transition, key rotation, rollback and protected retained history |
| `npm run test:learn-auth` in Hub | **10/10 passed**, real Learn and Invitation components with API fixtures |
| Existing `npm run test:sales` | **67/68 passed**; the known catalogue WhatsApp-help-text assertion remains (`Catalogue sharing never sends an authenticated or localhost link; preview and download still work`) |
| Hub lint | **0 errors, 37 existing warnings** |
| Modified Learn files lint | **0 errors, 1 existing AuthProvider dependency warning** |
| Full Learn lint | Two existing unused-variable errors in unchanged WaitingRoomPage.jsx, plus two warnings; repaired the incompatible hooks-preset configuration to enable this check |
| Hub and Learn production builds | Both passed; existing bundle-size advisory remains |
| Legacy-transition management command | Dry run passed against the activated student: zero new invitations; existing credentials retained |
| Django system check and migration consistency | No issues; `makemigrations --check --dry-run` reports no changes |
| Real Chromium workflow | **12 checks passed**, real API and disposable PostgreSQL; zero page errors |
| Desktop and narrow layouts | 1536px desktop; no page overflow at 768px, 390px or 320px for New Sale, Invitations, Learn login and password change |

The broader run (`accounts invitations students sales bookings sessions core`) executed **1325 tests in 682.077 seconds**, reporting nine failures and nine errors before updating obsolete Google assertions and related test fixtures. Those affected authentication/invitation tests subsequently passed in the 366-test run. The final focused integrity run executed **40 tests in 56.829 seconds**, with **eight failed assertions/subtests confined to the older Phase 1 permission fixtures** and no errors. It also reran all 25 credential tests successfully after the new migrations.

The remaining permission checks assume BDE has no initial-sales access, omit twelve existing sale/payment/Autopay routes, and expect signed Stripe/parent-action endpoints to require a staff session. Their snapshot report also differs on existing Phase 1 lead, quote and student fields. There are **91 remaining snapshot differences**. No remaining difference concerns Learn login or Invitations. Only the forty expectations authorized by this feature were added to approved_changes.json; unrelated expectations were retained.

Browser verification covered a BDE New Sale without any parent email, a confirmed AED 300 direct payment for six of ten classes, one enrolled student, retained demo tutor/Admin mentor assignment, post-enrollment BDE refusal, authorized initial credential retrieval, invalid login, first-login redirect and server refusal, password change, activated Learn dashboard, erased credential retrieval and removed Google endpoint. No real Stripe charge was performed for this authentication change; signed mocked Stripe events and existing Autopay tests exercised the shared enrollment path. Existing shared Google accounts/databases were not changed.

Verification artifacts are in `/private/tmp/eduport-learn-auth/`: `final-backend.log`, `final-integrity-tests.log`, `frontend-tests.log`, `hub-sales.log`, build/lint logs, `authz-final-differences.json`, `browser-results.json` and `screenshots/`. Browser artifacts contain no generated passwords. The isolated browser script keeps retrieved credentials only in memory; screenshots were taken with credential fields empty or the reveal modal closed.

## Files changed for this feature

This list covers this authentication request only and does not inventory the earlier uncommitted Phase 1 work.

- `.env.example`
- `backend/.env.example`
- `backend/requirements.txt`
- `backend/config/settings.py`
- `backend/accounts/models.py`
- `backend/accounts/services.py`
- `backend/accounts/views.py`
- `backend/accounts/urls.py`
- `backend/accounts/middleware.py`
- `backend/accounts/permission_catalogue.py`
- `backend/accounts/migrations/0024_alter_user_email.py`
- `backend/accounts/migrations/0025_learn_invitation_permission_label.py`
- `backend/accounts/tests.py`
- `backend/accounts/tests_auth.py`
- `backend/accounts/tests_team.py`
- `backend/invitations/models.py`
- `backend/invitations/credentials.py`
- `backend/invitations/views.py`
- `backend/invitations/urls.py`
- `backend/invitations/admin.py`
- `backend/invitations/emails.py`
- `backend/invitations/migrations/0004_invitation_account_invitation_activated_at_and_more.py`
- `backend/invitations/management/__init__.py`
- `backend/invitations/management/commands/__init__.py`
- `backend/invitations/management/commands/issue_learn_credentials.py`
- `backend/invitations/tests.py`
- `backend/invitations/tests_credentials.py`
- `backend/sales/enrollment.py`
- `backend/sales/payments.py`
- `backend/sales/payment_views.py`
- `backend/sales/autopay.py`
- `backend/sales/autopay_views.py`
- `backend/sales/tests_payments.py`
- `backend/sales/tests_autopay.py`
- `backend/students/tests.py`
- `backend/students/views.py`
- `backend/core/authz_matrix.py`
- `backend/core/tests_authz_matrix.py`
- `backend/core/tests_csrf.py`
- `backend/core/tests_role_scoping.py`
- `backend/core/authz_matrix_data/approved_changes.json`
- `frontend/learn/.env.example`
- `frontend/learn/eslint.config.js`
- `frontend/learn/index.html`
- `frontend/learn/src/App.jsx`
- `frontend/learn/src/context/AuthProvider.jsx`
- `frontend/learn/src/lib/api.js`
- `frontend/learn/src/pages/LoginPage.jsx`
- `frontend/learn/src/pages/ChangePasswordPage.jsx`
- `frontend/hub/package.json`
- `frontend/hub/src/pages/InvitationsPage.jsx`
- `frontend/hub/src/components/invitations/invitations-table.jsx`
- `frontend/hub/src/components/invitations/invitation-action-cell.jsx`
- `frontend/hub/src/components/invitations/new-invitation.jsx`
- `frontend/hub/src/components/enquiries/workspace/enquiry-sales-payment.jsx`
- `frontend/hub/src/components/enquiries/workspace/autopay-builder.jsx`
- `frontend/hub/tests/learn-auth/api-stub.js`
- `frontend/hub/tests/learn-auth/harness.jsx`
- `frontend/hub/tests/learn-auth/run.mjs`
- `docs/phase1-sales-payments.md`
- `docs/phase1-autopay.md`
- `docs/phase1-verification.md`
- `docs/learn-enrollment-credentials.md`
