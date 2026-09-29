# Eduport Plus (Django) — Current-State Audit

Date: 2026-09-29. Scope: `eduport_plus_django/` exactly as it sits in the working tree, including uncommitted changes.

Evidence base: every backend module, both SPAs, and the compose/env configuration were read. The full backend test suite (239 tests) was run against the working tree inside the compose backend image and passed. `makemigrations --check` reports no drift. The running Docker stack was probed anonymously. Labels used: IMPLEMENTED / PARTIAL / NOT IMPLEMENTED / UNKNOWN. Nothing here is a proposal.

---

## 1. Project overview

**Architecture.** One Django 6.0.6 project (`backend/config`) exposing a JSON API under `/api/` with Django REST Framework. No server-rendered pages except Django admin. Two independent single-page apps consume the API with cookie sessions.

**Apps.**

| App | Label | Purpose |
|---|---|---|
| `accounts` | accounts | Custom `User` (table `profiles`), Google login, `/me`, persona selection, staff directory, staff lifecycle |
| `students` | students | `Student` (table `students`), student list/update/reassign/purge, staff and student dashboards |
| `sessions` | `sessions_app` | `Session` + `SessionFile`, scheduling, series cancel, content links and uploads |
| `invitations` | invitations | `Invitation` (table `whitelisted_emails`), Google Sheets lookup, invitation CRUD, invitation email |
| `activity` | activity | `ActivityLog` (table `activity_log`), append-only audit feed |
| `core` (package, not an app) | — | permission classes, role scoping, opt-in pagination, persona cookie helpers, timezone conversion, settings guards, CSRF-exempt auth class |

**Frontend.** `frontend/hub` (staff, port 3000) and `frontend/learn` (student, port 3001). Both: Vite 6, React 19, react-router 7, axios with `withCredentials`, Tailwind 4. Hub adds shadcn/Radix, TanStack Table, recharts, date-fns, next-themes. Learn adds framer-motion. Production images are nginx with SPA fallback.

**Database.** PostgreSQL 16 (compose service `db`, host port 5433). Six application tables plus Django auth/session tables. A Postgres trigger makes `activity_log` append-only.

**Authentication.** Google Identity Services ID token → verified server-side → Django database session cookie. No JWT. App users have unusable passwords; only Django-admin superusers use a password.

**Integrations.**
- Google OAuth ID-token verification (`google-auth`).
- Google Sheets via gspread service account: reads worksheet `enrollment data`, range A3:AB, to look up a student by code (read-only).
- SMTP (Gmail app password) for the invitation email; console backend when `EMAIL_HOST_USER` is blank.
- Google Meet: a per-student URL string, not created through any API.
- Google Drive: one hard-coded "plan details" folder link in the New Session sheet.
- WhatsApp: hard-coded `wa.me` support number on Learn gateway pages; mentor deep link from the mentor's phone.
All corresponding keys are present in the local `backend/.env` (presence checked, values not read).

**Deployment / environment assumptions.** docker-compose with `db`, `backend` (gunicorn, 3 workers, 300 s timeout, whitenoise for static), `hub`, `learn`. Entry point runs `check --deploy`, waits for Postgres, `migrate`, `collectstatic`. Settings fail closed: with `DEBUG=False` the process refuses to boot on the fallback or short `SECRET_KEY` or an empty `ALLOWED_HOSTS`. Uploads live in a named `media` volume; there is no `MEDIA_URL`. Hub and Learn can share the session cookie across subdomains via optional `SESSION_COOKIE_DOMAIN`. TLS redirect, HSTS and proxy-header trust default off. Local stack runs `DEBUG=False`, `ALLOW_MOCK_AUTH=False`, `SESSION_COOKIE_SECURE=False`. No CI configuration in the repo. `docs/production-env.md` is referenced from settings but the docs folder was empty before this file.

**Working-tree state.** Uncommitted: the session file-upload feature (`SessionFile` model, migration `sessions/0002_sessionfile`, upload and download views, `content-input.jsx`, rewritten `SessionsPage.jsx`, ~350 lines of tests, compose `media` volume). Tests pass with it.

---

## 2. User roles

Roles are one `role` column on `User`: `ADMIN`, `MENTOR`, `TUTOR`, `STUDENT`. Two Django flags also matter: `is_superuser` (every permission class treats it as ADMIN) and `is_staff` (True for every non-student at provisioning; only relevant to Django admin, which still needs a password).

### Admin
- Access: every Hub page (Dashboard, Students, Sessions, Admins, Mentors, Tutors, Invitations, Activity); every API endpoint; Django admin if superuser with a password.
- Can: invite any role; edit staff name/phone; deactivate/reactivate mentors and tutors (with handover); bulk-reassign a departing staff member's students; reassign one student's mentor/tutor; purge a student without sessions; edit student profile, meet link, quota, status, timezone; create/reschedule/mark attended/cancel/edit links/upload on any session; set rating; read the whole activity log with an actor filter; read a student's history.
- Cannot: deactivate/reactivate another admin (403); delete a user (no endpoint); purge a student who has sessions (409); edit/withdraw an accepted invitation; create a session for a student without a tutor.

### Mentor
- Access: Hub Dashboard, Students, Sessions, Activity. `/admins`, `/mentors`, `/tutors`, `/invitations` redirect to `/dashboard`; sidebar hides them.
- Sees: students where `mentor = self` (all statuses); those students' sessions; own activity rows only; slim mentor/tutor dropdown lists (`?all=true` → 403); dashboard student count scoped, mentor/tutor/pending-invite counts global.
- Can, on own students only: edit profile, meet link, quota, status + note, timezone; create sessions and series; reschedule; mark attended; cancel (simple or series); edit all three links; upload any content field; set rating.
- Cannot: reassign staff, open history, purge (hidden in UI, admin-only in API); touch other mentors' students (403); see other actors' activity.
- PARTIAL: the API lets mentors look up, create, edit and withdraw student invitations (`IsAdminOrMentor`), but the Hub offers mentors no route or button for it.

### Tutor
- Access: Hub Dashboard, Students, Sessions, Activity.
- Sees: students where `tutor = self` and status ACTIVE or INACTIVE (EXPIRED hidden); a reduced student table (ID, name, grade, syllabus, mentor, meet link, "View Sessions"); those students' sessions; own activity rows; the student's meet link on the sessions table.
- Can: add or replace the notes link (URL or upload) on a non-cancelled session of an allocated student. Nothing else.
- Cannot: create, reschedule, cancel, mark attended, set recording/homework, rate (403 "Tutors can only update the notes link"); update students (403); read full staff records; see other tutors' students.
- Observation: `/api/students/` returns the full student row (mobile, email, address, remarks, quota) to tutors; only the Hub column set hides it.

### Student (the parent/guardian account)
- Access: Learn only; Hub redirects STUDENT to the Learn URL.
- Model: one `User` with role STUDENT owns one or more `Student` rows ("personas"). The active one is stored in the `ep-student-id` cookie.
- Sees: selected persona's dashboard, sessions, library, profile; mentor name/email/phone; tutor name; meet link; uploaded files of own sessions.
- Can: select a persona; rate a session 1–5; log out.
- Cannot: any staff endpoint (403); create or modify sessions; see another persona without switching; see the activity log.
- Persona status: EXPIRED cannot be selected and is invisible to student endpoints; all-expired → "Access ended". INACTIVE keeps full access plus a banner.

### Superuser
`createsuperuser` sets role ADMIN. Any `is_superuser` passes `IsAdminUser`/`IsStaffUser` regardless of role. Django admin exposes CRUD for User, Student, Session, SessionFile, Invitation; ActivityLog is read-only there.

---

## 3. Authentication & authorization

**Login method.** `POST /api/auth/google/` with `{credential}`; the credential is the Google ID token from the GSI button or One Tap (`https://accounts.google.com/gsi/client` is loaded in both `index.html` files).

**Server flow** (`accounts/views.py`, `GoogleLoginView`):
1. Verify the token against `GOOGLE_OAUTH_CLIENT_ID` (10 s clock skew). Failure → 401 `INVALID_CREDENTIAL`. Missing client id → 401.
2. Whitelist gate: an `Invitation` with this email in any status must exist → otherwise 403 `ACCESS_RESTRICTED`.
3. No `User` yet → `UserProvisioningService.provision_user` (atomic): takes the first PENDING invitation, creates the `User` with that role, Google name (fallback sheet name), avatar, `invited_by`, `is_staff = role != STUDENT`, unusable password. For STUDENT it creates one `Student` per PENDING student invitation (code, profile fields, mentor/tutor ids, quota, meet link from `extra_data`) and marks them ACCEPTED; a staff invitation is marked ACCEPTED. Logs `user.onboarded`. No PENDING invitation → 403 `INVITATION_REQUIRED`.
4. `is_active=False` → 403 `USER_DISABLED`.
5. Existing STUDENT accounts: attach any new PENDING student invitations for the email.
6. `login()` → DB session; `ensure_csrf_cookie` sets `csrftoken`.
7. Avatar refreshed; `user.sign_in` logged for existing users.
8. Response `{status, is_new_user, user}` plus, for students, `{student_profiles, student_profile, selected_student_id}`.

**Mock auth.** Credential `mock:<email>:<name>:<avatar>` skips Google. Available only when `DEBUG` and `ALLOW_MOCK_AUTH` are both True (`core/settings_guards.py`). Both are False locally, so it is off. Both login pages still ship a hidden mock form (double-click the logo) and a prompt fallback used when the GSI script never loads; both hit the same endpoint and are refused while mock auth is off.

**User ↔ Django user.** The custom `accounts.User` is the Django auth user (`AUTH_USER_MODEL`). Students are linked through `Student.profile`.

**Role assignment.** Copied from the invitation at provisioning. No endpoint changes a role afterwards (Django admin can).

**Session handling.** Django DB sessions. Cookie HttpOnly, SameSite=Lax, Secure = `not DEBUG` (overridable), optional shared domain. `POST /api/auth/logout/` logs `user.sign_out`, flushes the session, deletes `ep-student-id`. `GET /api/auth/me/` returns user + persona payload. `POST /api/auth/select-student/` validates ownership and usability, sets the persona cookie (one year, HttpOnly).

**Permission classes** (`core/permissions.py`): `IsStaffUser`, `IsAdminUser`, `IsStudentUser`, `IsAdminOrMentor`, `IsStaffOrSelfStudent` (staff any method; students GET and PUT only). DRF default `IsAuthenticated`. Object-level scoping is done inside views with `core/querysets.py` (`scope_students_by_role`, `scope_sessions_by_role`, `scope_activity_by_role`) plus explicit ownership checks.

**CSRF.** DRF's `SessionAuthentication` checks CSRF only on the read-only views that use it. Every mutating view uses `CSRFExemptSessionAuthentication`, so CSRF tokens are never verified on writes (see §15).

**Route/API guards.** Per-view permission classes plus in-view role checks (§14). Anonymous requests to every API path return 403 `{"detail":"Authentication credentials were not provided."}` (verified live).

**Frontend access control.**
- Hub `AuthProvider`: calls `/me` on every route change; failure → `/login`; STUDENT → full redirect to Learn. Admin-only routes render `<Navigate to="/dashboard">`; sidebar filtered for MENTOR/TUTOR. Pages call `/me` again to choose column sets and menus.
- Learn `AuthProvider`: calls `/me`; non-STUDENT → Hub; then `/waiting-room` (no personas), `/access-ended` (all expired), `/select-profile` (several usable, none selected), else loads `/api/student/dashboard/` and enters.
- Both axios clients redirect to `/login` on HTTP 401. DRF answers 403 for anonymous, so this interceptor never fires; the AuthProvider catch handles it.
- nginx serves `index.html` for every path; SPA routes are not protected server-side (all data is behind the API).

**Inactive users.** Login refused with `USER_DISABLED`. Existing sessions die on the next request because Django's `ModelBackend` rejects `is_active=False` (test `test_deactivated_staff_session_is_locked_out`). API deactivation exists only for MENTOR/TUTOR; Django admin can flip `is_active` for anyone and `UserAdmin.save_model` keeps `deactivated_at` consistent.

**Unauthorized direct access.** API: 403 JSON. Wrong role: 403 `{error, message}`. Unknown id: 404. SPA deep links: client-side redirect after `/me`.

---

## 4. User / student management

**User** (`profiles`): id UUID, email (unique), full_name, avatar_url, role, mobile_number, invited_by → User, created_at, updated_at, is_active, is_staff, is_superuser, deactivated_at, deactivated_by → User, deactivation_reason, password (unusable).

**Student** (`students`): id UUID, profile → User (CASCADE), student_code (unique), full_name, mobile_number, country, state, school_name, grade, syllabus, admission_date, mentor → User (SET_NULL), tutor → User (SET_NULL), meet_link (URLField, not validated on save), timezone (IANA, nullable, IST fallback), total_class_quota (int, default 0), remarks_for_mentor, status ACTIVE/INACTIVE/EXPIRED, status_note, created_at, updated_at.

**Invitation** (`whitelisted_emails`): id, email (non-unique), role, status PENDING/ACCEPTED/EXPIRED (EXPIRED is never set by code), extra_data JSON (student: student_code, full_name, mobile_number, country, state, school_name, grade, syllabus, admission_date, remarks, mentor_id, tutor_id, meet_link; staff: full_name, mobile_number), invited_by, created_at, updated_at.

**Assignments / relationships.** User 1→N Student (parent); Student N→1 mentor; Student N→1 tutor; Session N→1 Student and N→1 tutor; SessionFile N→1 Session, N→1 uploaded_by; Invitation N→1 invited_by; ActivityLog → actor and student without DB constraints.

**Student management (Hub).**
- Create: only via invitation (admin UI): verify student code against the Google Sheet → pick mentor, tutor, Meet link → tick "WhatsApp group created" → POST. The `Student` row materialises on the parent's first Google login.
- Edit profile (admin/owning mentor): name, mobile, country, state, school, grade, syllabus, admission date, remarks. Code and email immutable. Logs `student.update_details` with a diff.
- Edit demo link: stores `https://meet.google.com/<code>`. Logs `student.update_meet_link`.
- Top-up quota: adds N to `total_class_quota`. Logs `student.update_quota`.
- Change status: ACTIVE/INACTIVE/EXPIRED; note required for INACTIVE/EXPIRED, cleared on ACTIVE. Logs `student.update_status`.
- Timezone: written by the New Session sheet when a different zone is picked. Logs `student.update_timezone`.
- Reassign mentor/tutor (admin): both final values sent (null = unassign); replacements must be active staff of the right role; SCHEDULED sessions follow the new tutor. Logs `student.reassign_mentor` / `student.reassign_tutor`.
- View history (admin): activity rows for the student.
- Delete permanently (admin): retype the student code; refused with 409 if any session exists. Logs `student.purge`. The parent `User` is untouched.
- Expired students sit in a collapsed "Expired Students" table for admin/mentor and are hidden from tutors.

**Staff management (Hub, admin).** Admins/Mentors/Tutors pages list accounts plus PENDING invitations as "ghost" rows. Actions: edit name/phone; deactivate (optional reason ≤ 500 chars; blocked with 409 `HANDOVER_REQUIRED` while ACTIVE students are assigned — the dialog runs the bulk reassign first); reactivate; ghost rows: edit email / withdraw. Admin rows have no status actions. Deactivated staff hidden by default ("Show deactivated"), excluded from assignment dropdowns.

**User status.** Staff: `deactivated_at` is the source of truth mirrored into `is_active`. Students: status lives on `Student`; the parent `User` is never deactivated via the API.

**Parent information.** PARTIAL (structural only). No parent name/phone/relationship fields. The login account is the parent account by construction; the only phone on record is `Student.mobile_number`.

**Other user fields.** `avatar_url` is refreshed from Google on each login. `invited_by` is shown on staff tables. Groups/permissions tables exist but are unused.

---

## 5. Session management

**Model** (`sessions`): id UUID; student → Student (CASCADE); tutor → User (SET_NULL; snapshot at creation); title; start_time, end_time (UTC); status SCHEDULED/ATTENDED/CANCELLED (default SCHEDULED); cancellation_reason; recording_link, notes_link, homework_link (text, null when blank); rating 1–5 nullable; series_id nullable; class_number nullable; created_at, updated_at. Derived, never stored: `missing_content`, `content_complete`, `display_status` (`pending` = ATTENDED with any link missing).

**Student ↔ tutor.** A session can only be created for a student who has a tutor; that tutor is copied onto the row. Reassigning the student's tutor moves only SCHEDULED sessions. `PUT` also lets admin/mentor set `tutor` to any existing user id (no role/active check).

**Date/time.** UTC instants. Creation accepts `local_date` + `local_time` + request-level `timezone` (student's IANA zone; DST gaps rejected; ambiguous fall-back times resolve to the earlier instant) or a legacy ISO `start_time`. The Hub New Session sheet always sends the student's wall time (zone defaults to Asia/Kolkata) and shows a mentor-time (IST) reference. Reschedule and make-up inputs use the browser's local `datetime-local` and send UTC. The Hub sessions table and every Learn screen display times in the browser's local zone.

**Duration.** `duration_hours` ∈ {0.5, 1, 1.5, 2}; `end_time = start_time + duration`. Series: up to 20 classes; non-series must contain exactly one item.

**Scheduling flow** (`POST /api/sessions/`; admin or owning mentor): validate title (Title-Cased), zone, items, durations → resolve instants → quota check (`total_class_quota − hours of all non-cancelled sessions ≥ requested`) → per-class conflict check (any SCHEDULED session of the same student or the same tutor overlapping → 409) → create rows in one transaction → log `session.create` / `session.create_series` (title "Base - Class N", `class_number`, shared `series_id`).

**Rescheduling** (`PUT` with `start_time` + `duration_hours`): admin/owning mentor; conflict check excluding itself; no status guard; no quota re-check; logs `session.reschedule`.

**Cancellation.**
- Simple: `PUT {status: "CANCELLED", cancellation_reason}`; reason mandatory; logs `session.cancel`.
- Series-aware: `POST /api/sessions/cancel/` (alias `cancel-series/`); only SCHEDULED; admin/owning mentor. When later SCHEDULED classes exist in the series, `new_last_start_time` + `new_last_duration_hours` are required: the target is cancelled, later classes are renumbered down with titles rewritten, and a make-up class is appended with the old last number (conflict-checked, not quota-checked). Without later classes it is a plain cancel. Logs `session.cancel_series` (or `session.cancel`).
- Hub cancel dialog: reason textarea; series members get a "Shift series and schedule make-up class" checkbox.

**Completion.** `PUT {status: "ATTENDED"}` by admin/owning mentor; recording/homework optional at that moment. Logs `session.mark_attended`. Nothing transitions a session automatically when its time passes.

**Pending.** Derived: ATTENDED with any of notes/recording/homework empty. Shown as a Pending badge (Hub) and as "Missing" tiles (Learn); selectable through `?content=`. Adding the last link flips it to Attended.

**Status transitions.** The API accepts any of the three statuses from admin/mentor on any session; the only guard is the reason on CANCELLED. The Hub only offers Mark Attended / Reschedule / Cancel on the Scheduled tab.

**Meeting URL.** Not on the session. `Student.meet_link` is nested in every session payload (`students.meet_link`); rendered as "Join Meet" on Hub Scheduled/Cancelled tabs and as the Join button on the Learn dashboard.

**Chapter/topic.** `title` only. No subject, chapter, curriculum or lesson-plan entity; the plan is an external Drive folder linked from the sheet.

**Who can do what.** Create: admin, owning mentor. Update schedule/status/links/tutor/title/rating: admin, owning mentor. Notes link only: owning tutor. Rating only: the parent account for its own persona. Delete: nobody via API (Django admin only). Read: admin all; mentor/tutor their students' sessions; student the selected persona's sessions (all statuses returned).

**Lifecycle as implemented.** Invitation → Student row → mentor books one session or a series (SCHEDULED, tutor snapshot, hours counted against quota) → optional reschedule → either cancel (CANCELLED, hours released; series may shift and add a make-up) or mark ATTENDED → reads Pending until notes (tutor) plus recording and homework (mentor) exist → Attended → student may rate.

---

## 6. Session content

**Content types.** Exactly three per session: notes, recording, homework. Each is a link column. Each can be filled by pasting a URL or by uploading a file; an upload stores the bytes and writes the authenticated download URL into the same column, so completion and filters treat both alike. The upload half is in the working tree, uncommitted.

**Storage.** `SessionFile` (id, session, field, file, file_name, content_type, size_bytes, extension, uploaded_by, created_at; unique per session+field), bytes under `MEDIA_ROOT/session-content/<session_id>/<field>/<file_id><ext>` via `FileSystemStorage`. Docker: named `media` volume. No cloud storage, no CDN, no public media URL.

**Upload flow.** `POST /api/sessions/<session_id>/files/<notes|recording|homework>/`, multipart `file`. Checks: known field; session exists; role/ownership; session not CANCELLED; declared MIME in the allow list; non-empty; per-kind size ceiling; magic-number sniff matches the declared type. Replaces a previous upload for that field, sets the link, logs `session.update_links` with file name/type/size in `context`.

**Supported types / limits.** PDF (document, 50 MB); PNG, JPEG, WebP, GIF, HEIC, HEIF (image, 50 MB); MP4, WebM, QuickTime/MOV, Matroska/MKV (video, 500 MB). Env-overridable. Text, Office, audio, archives: rejected.

**Who can upload.** Admin: any field, any session. Mentor: any field on own students' sessions. Tutor: notes only, own students' sessions. Student: never.

**Who can view/download.** `GET /api/sessions/files/<file_id>/`: authenticated caller whose scope contains the session — admin; the student's mentor or tutor; the parent account when the persona is usable. Inline disposition, single byte-range support (seekable video), `nosniff`, private caching. Others → 403; unknown → 404. Students open it as an ordinary link from Learn; the session cookie accompanies the top-level navigation.

**Edit/delete.** No delete endpoint. Overwriting the link with another URL, clearing it, or re-uploading removes the previous file row and bytes (`drop_stale_files`, `post_delete` signal). Tutors can do this only for notes. Deleting a session in Django admin cascades to its files.

**UI.** Hub Mark Attended (recording, homework; shows tutor-notes availability), tutor Add/Update Notes, and Edit Resource Links dialogs each use a per-field "Enter URL | Upload File" switch with client pre-checks and a file card (name, type, size, Open). Table cells show Open buttons (file metadata on hover) or a red "Missing" badge on attended rows. Learn attended cards list all three items with "Missing" placeholders; Library groups attended sessions by Recordings/Notes/Homework; Last Class card shows present links only. No inline viewer or player.

**Not present.** Server-side URL validation beyond blank→null; per-student or standalone attachments; multiple files per field; versioning; a separate homework or exam module ("Manage Exams" is a disabled placeholder menu item).

---

## 7. Activity / activity log

**Meaning.** A server-written, append-only audit trail of changes made through the API. Not user-authored content, not a notification feed.

**Schema** (`activity_log`): id, created_at, actor (FK, no DB constraint), actor_email, actor_name, actor_role (snapshots), action, entity_type (profile | student | session | invitation), entity_id, entity_label, student (FK, no DB constraint), changes JSON `{field: {old, new}}`, context JSON (ip, user_agent, plus action-specific keys: reason, series_id, counts, uploaded_file, …).

**Actions written by the backend.** user.onboarded, user.sign_in, user.sign_out, user.update_details, user.deactivate, user.reactivate, staff.reassign_all, invitation.create, invitation.update_email, invitation.withdraw, student.update_details, student.update_meet_link, student.update_quota, student.update_timezone, student.update_status, student.reassign_mentor, student.reassign_tutor, student.purge, session.create, session.create_series, session.update, session.update_links, session.reschedule, session.mark_attended, session.cancel, session.cancel_series, session.rate. (The Hub label map also lists `student.create`, which no backend path writes.)

**Who creates.** Server code only: `activity.utils.log_activity` (best-effort, swallows errors, captures IP and user agent) and direct `ActivityLog.objects.create` in the auth views (no IP). No user can author an entry; Django admin is read-only; the Postgres trigger rejects UPDATE/DELETE for every role. Rows survive deletion of the actor or the student.

**Visibility.**
- Admin: every row; actor dropdown lists every account.
- Mentor / Tutor: only rows where `actor_id = self`, applied before any query parameter (`?actor=`, `?student_id=` can only narrow). No actor options returned. Covered by tests. Consequence: a mentor does not see a tutor's notes update on the mentor's own student.
- Student: 403.
- Default feed hides user.sign_in / user.sign_out / user.onboarded unless `?action=` names one.

**Filters.** student_id, action, entity/entity_type, actor/actor_id, from, to, q (icontains on actor_name, actor_email, entity_label), page, page_size (default 25). Always paginated: `{results, count, page, page_size, actor_options}`.

**UI.** Hub `/activity`: search, action, entity type, actor (admin), date range, Clear; table When / Who / Action / Details; row expands to a before→after diff; page controls. Hub "View History" sheet (admin, per student, up to 200 rows). Learn: none.

**Attachments on activities.** None; JSON only. Upload events record file name, type and size in `context`.

---

## 8. Dashboards / UI

### Hub (staff)
Layout: collapsible sidebar, breadcrumb header, theme toggle, user menu with Log out.
- **Dashboard** (`/dashboard`, all staff): cards Total Enrollments, Active Households (both the same students count), Pending Invites; 7-day new-student bar chart; last five sign-ups (ID, name, joined). Mentors/tutors get their scoped student count; invite count is global.
- **Students** (`/students`): name filter, column toggles, sort by student ID, pinned actions. Admin columns: avatar, email, ID, name, status badge (note on hover), mobile, remarks (expandable), mentor, tutor, country, state, school, grade, syllabus, admission date, joined, meet link, class quota, actions. Mentor: same minus email, mentor, state and the admin-only actions. Tutor: avatar, ID, name, grade, syllabus, mentor, meet link, "View Sessions". "New Student" (admin) links to the invitation form. Collapsed "Expired Students" table (admin/mentor).
- **Student profile page**: none; editing happens in a side sheet from the row menu.
- **Sessions** (`/sessions`, legacy dark styling): optional `?student_id=` banner; filter bar (title, date range, tutor multi-select except for tutors, Content filter on Attended, Clear, Columns); tabs Scheduled / Attended / Cancelled; columns title (+ series class number), date, time, status badge (reason or missing items on hover), student (name + code), tutor, student's mentor, Meeting (Scheduled/Cancelled), and on Attended: recording, notes, homework, rating. Row menu: admin/mentor — Mark Attended, Reschedule, Edit Resource Links, Cancel Session (all but links only on Scheduled); tutor — Add/Update Notes (not on Cancelled). "New Session" drawer (admin/mentor, when a student is selected): title with normalised preview, series toggle (≤ 20 rows), timezone select, date/hour/minute/AM-PM/duration, quota balance line, student-time and mentor-time reference, Drive plan link.
- **Calendar**: none.
- **Activity** (`/activity`): §7.
- **Admins / Mentors / Tutors** (admin only): staff table with email filter; columns avatar, name, email, phone, joined, invited by, status badge, assigned students (mentor/tutor), actions; ghost rows; "Show deactivated"; "New …" button.
- **Invitations** (admin only): table email, role, invited at, invited by, actions (edit email, withdraw; hidden for accepted); "New Invitation" dialog/drawer: role, staff email or student-code Verify (Sheets), mentor/tutor dropdowns (tutor pre-matched by sheet name), Meet link, WhatsApp-group checkbox.
- **Login**: Google button / One Tap; "Access restricted" state; hidden mock form.

### Learn (student)
Layout: desktop sidebar (Home, Sessions, Library, Profile, selected persona), mobile bottom nav, INACTIVE banner.
- **Dashboard**: greeting; tiles Purchased (`total_class_quota`), Scheduled count, Attended count; "Your Next Live Class" (title, Today/Tomorrow/date, time range, tutor, meet link, Join Meeting; empty state); "Last Class Recap" (title, time, tutor, star rating / thanks state, present resource links).
- **Sessions**: tabs Scheduled / Attended (cancelled sessions are never shown though the API returns them); cards with title, date/time, tutor, mentor, status pill; attended cards expand to the three resources (Missing states) and the rating control.
- **Library**: tabs Recordings / Notes / Homework listing attended sessions that have that link (title, date, tutor), opening in a new tab.
- **Profile**: header (name, grade, initials avatar), Student Information (mobile, account email, school, region), Your Mentor (name, phone, WhatsApp), Switch Student (if > 1 persona), Sign Out.
- **Gateways**: Select profile, Waiting room (Check Status, WhatsApp support), Access ended (Check Again), Login.
- Calendar, activity, notifications: none.

---

## 9. Ratings / feedback

IMPLEMENTED (minimal).
- Who submits: the parent account for its selected persona's sessions (`PUT /api/sessions/ {id, rating}`); admin and owning mentor may also set `rating` through the same PUT; tutors cannot.
- Scale: integer 1–5 (model validators + view checks).
- When: the API checks neither session status nor time; the Learn UI only shows stars on attended sessions and hides them once a rating exists (client-side; the API accepts re-rating).
- Stored: `Session.rating`.
- Visible to: Hub sessions Attended tab ("n/5"); Learn card; Django admin.
- Aggregation: none. No text feedback field on sessions. Logged as `session.rate` with old/new.

---

## 10. Credit / payment

| Item | Status | Detail |
|---|---|---|
| Session credits | PARTIAL | `Student.total_class_quota` (int hours). Used credits are computed on demand as the summed duration of all non-cancelled sessions (SCHEDULED + ATTENDED). Creation refused beyond the remaining balance. Cancel releases hours. Reschedule duration changes and make-up classes are not quota-checked. No ledger, no per-session credit record. |
| Credit balance | PARTIAL | Shown in the Hub New Session drawer ("Quota balance: X / Y credits left"). Learn shows Purchased / Scheduled / Attended counts, not a remaining balance. |
| Credit deduction | PARTIAL | Implicit through the computation; no deduction event or history. |
| Top-up | IMPLEMENTED | Admin/mentor adds N to the quota (Hub "Top-up Class Quota"); logged. |
| Payment gateway | NOT IMPLEMENTED | No code, settings or dependency. |
| Purchase flow | NOT IMPLEMENTED | — |
| Refunds / invoices / pricing | NOT IMPLEMENTED | — |
| Payment models | NOT IMPLEMENTED | — |

---

## 11. Notifications

- Email: PARTIAL — a single transactional email, the invitation (on create and on email change), HTML + text, linking to `/login?email=` on Hub or Learn by role. Sent synchronously; failures logged and ignored.
- Session reminders: NOT IMPLEMENTED.
- Push: NOT IMPLEMENTED.
- In-app notifications: NOT IMPLEMENTED (no model, endpoint or UI).
- Infrastructure: no task queue, scheduler, cron or Celery. WhatsApp only as static links.

---

## 12. Search / filter / sort / export

- Backend search: activity `q` only.
- Backend filters: activity (student, action, entity, actor, date range); sessions `?content=` (complete / missing_notes / missing_recording / missing_homework / missing_content; attended rows only).
- Backend sorting: fixed (students by code, sessions by start desc, activity by created desc); no `ordering` parameter.
- Pagination: opt-in `?page=&page_size=` (default 25, max 200) on students and sessions; always on for activity. Both SPAs load students and sessions unpaginated.
- Hub: table text filter (students by name, staff by email), sort (ID / email), column toggles; sessions page filters by title, date range, tutor, content, tab, student; activity filters mirror the API.
- Learn: tabs only.
- CSV export: NOT IMPLEMENTED. PDF export: NOT IMPLEMENTED. Calendar filters: NOT IMPLEMENTED (no calendar).
- Django admin: list filters and search on every registered model.

---

## 13. Database / important entities

| Table | Model | Key columns | Relations |
|---|---|---|---|
| `profiles` | accounts.User | email, role, is_active, deactivated_at/by/reason, mobile_number, avatar_url | invited_by → User; deactivated_by → User |
| `students` | students.Student | student_code, status, status_note, total_class_quota, meet_link, timezone, profile fields | profile → User (CASCADE); mentor → User (SET_NULL); tutor → User (SET_NULL) |
| `sessions` | sessions.Session | title, start_time, end_time, status, cancellation_reason, notes/recording/homework_link, rating, series_id, class_number | student → Student (CASCADE); tutor → User (SET_NULL) |
| `session_files` | sessions.SessionFile | field, file, file_name, content_type, size_bytes | session → Session (CASCADE); uploaded_by → User (SET_NULL); unique(session, field) |
| `whitelisted_emails` | invitations.Invitation | email, role, status, extra_data | invited_by → User (SET_NULL) |
| `activity_log` | activity.ActivityLog | action, entity_type, entity_id, entity_label, changes, context, actor_* snapshots | actor → User, student → Student (no DB constraint); append-only trigger |
| Django tables | django_session, auth_group, auth_permission, … | — | groups/permissions unused by the app |

Cardinality: User 1:N Student (parent), User 1:N Student (mentor), User 1:N Student (tutor), Student 1:N Session, Session 1:0..3 SessionFile, User 1:N Invitation (inviter), everything 1:N ActivityLog.

---

## 14. API overview (business endpoints)

**Authentication** (`/api/auth/`)
- `POST google/` — login / provisioning (AllowAny)
- `POST logout/`
- `GET me/`
- `POST select-student/` — set persona cookie

**Users / staff**
- `GET /api/mentors/`, `GET /api/tutors/` — slim active list (staff); `?all=true` full records + ghosts (admin)
- `GET /api/admins/` — admin; full records + ghosts
- `PATCH /api/users/<id>/` — admin: full_name, mobile_number
- `POST /api/users/<id>/status/` — admin: deactivate / reactivate mentor or tutor
- `POST /api/users/<id>/reassign/` — admin: bulk handover of active students (+ scheduled sessions)

**Students**
- `GET /api/students/` — staff, role-scoped, optional pagination
- `PUT /api/students/` — admin / owning mentor: meet_link, total_class_quota, timezone, status (+note), profile fields, admission_date
- `POST /api/students/reassign/` — admin: one student's mentor / tutor
- `DELETE /api/students/<id>/` — admin: purge (confirm_code; no sessions)
- `GET /api/dashboard/stats/` — staff dashboard
- `GET /api/student/dashboard/` — student dashboard (selected persona)

**Sessions**
- `GET /api/sessions/` — role-scoped; `?content=`; optional pagination
- `POST /api/sessions/` — admin / owning mentor: one session or a series
- `PUT /api/sessions/` — admin/mentor full update; tutor notes only; student rating only
- `POST /api/sessions/cancel/` (alias `cancel-series/`) — series-aware cancel
- `POST /api/sessions/<id>/files/<field>/` — staff upload
- `GET /api/sessions/files/<file_id>/` — scoped download / stream

**Activity**
- `GET /api/activity/` — staff, scoped, filtered, paginated

**Invitations** (`/api/invitations/`, admin or mentor)
- `POST lookup-student/` — Google Sheets lookup by code
- `GET` — list all
- `POST` — create / refresh (mentors: students only)
- `PATCH` — change email (by id or old_email)
- `DELETE` — withdraw (by id or email)

**Other**: `/admin/` Django admin.

---

## 15. Security / access control (as observed)

In place:
- Every endpoint requires a session; anonymous → 403. Role classes plus in-view ownership checks; mentors/tutors scoped to allocated students for students, sessions, files and stats; activity scoped to own rows for non-admins; students scoped to the selected usable persona.
- Staff soft-deactivation locks sessions immediately; handover guard; deactivated staff not assignable; lifecycle consistency enforced even from Django admin.
- Uploads: MIME allow-list, size ceilings, magic-number sniff, UUID storage keys, no public media URL, scoped streaming with `nosniff` and private caching.
- Append-only audit log with IP / user agent, surviving deletions; Django admin cannot alter it.
- Settings fail closed on SECRET_KEY / ALLOWED_HOSTS; browsable API only in DEBUG; mock login double-gated; cookies HttpOnly, SameSite=Lax, Secure by default in production; CORS allow-list with credentials.
- Purge requires retyping the code and is refused when history exists; cancel requires a reason; status downgrades require a note; UUID inputs validated on reassign/purge paths.

Observed characteristics (facts, not recommendations):
- Every state-changing endpoint uses `CSRFExemptSessionAuthentication`; CSRF tokens are never verified. Protection rests on SameSite=Lax and the CORS origin list.
- `/api/students/` returns full student rows (contact details, remarks, quota) to tutors; the narrower tutor view is UI-only.
- `Student.meet_link` and the three session links are stored without server-side URL validation.
- Session `PUT` has no status-transition rules for admin/mentor; its `tutor` field accepts any user id without a role/active check.
- Rating can be set on non-attended sessions and re-set; once-only is client-side.
- Activity `?student_id=`, `?actor=`, `?from=`, `?to=` reach the ORM unvalidated (behaviour on malformed values UNKNOWN, untested).
- The login whitelist passes on an invitation of any status; provisioning then requires a PENDING one.
- Every staff role carries `is_staff=True`; Django admin remains blocked by the unusable password unless a superuser sets one.
- No rate limiting or brute-force protection; no password auth to protect.
- TLS redirect, HSTS and proxy-header trust are off by default.

---

## 16. Current workflows (end to end)

**A. Login.** Open Hub or Learn `/login` → Google button / One Tap → SPA posts the ID token → backend verifies, checks the whitelist, provisions on first login, checks active, logs in, sets cookies → Hub goes to `/dashboard`; students are sent to Learn, which routes to waiting room / access ended / select profile / dashboard.

**B. Admin creates / manages a user.** Invitations → New Invitation → role + email (or the student flow) → invitation email → ghost row on the matching staff page → the person signs in with Google → account created with that role. Later: edit name/phone; deactivate (with handover) or reactivate mentors/tutors. Mentors can create student invitations via the API only.

**C. Student assignment.** Mentor and tutor are chosen on the invitation (tutor pre-matched from the sheet). Afterwards: admin "Reassign Mentor / Tutor" per student (scheduled sessions follow the new tutor), or bulk "Reassign & deactivate" when a staff member leaves. Mentors cannot reassign.

**D. Session scheduling.** Admin/mentor → Students → Manage Sessions (or Sessions with a student filter) → New Session → title, optional series rows, timezone, date/time/duration → local validation, persist a changed timezone, POST → backend re-validates quota, tutor, conflicts → rows created SCHEDULED → logged. Reschedule / cancel from the row menu.

**E. Tutor "completes" a session.** Tutors cannot mark attendance. The mentor or admin marks Attended (optionally with recording/homework). The tutor's part is the notes link (URL or upload), before or after attendance. Until notes, recording and homework all exist the class reads Pending.

**F. Uploading recording / notes / content.** Mentor/admin → Mark Attended or Edit Resource Links → per field URL or file → each file POSTs to the upload endpoint; URL fields go in one PUT. Tutor → Add/Update Notes → same, notes only.

**G. Student accesses session / content.** Parent logs into Learn → selects persona → Dashboard shows the next class (Join Meeting via the student's Meet link) and the last class recap → Sessions / Library show attended sessions' recording, notes, homework → links open the external URL or the authenticated file stream.

**H. Activity.** Every listed action is logged server-side. Admin reads the global feed or a student's history; mentors/tutors read their own entries.

**I. Rating.** Once a session is Attended the student sees stars on the session card / last-class card → one click PUTs the rating → "Thanks for rating" → read-only stars. Staff see the value in the Hub Attended tab.

---

## 17. Implementation status

| Feature | Status | Evidence / location | Notes |
|---|---|---|---|
| Google sign-in (ID token → session) | IMPLEMENTED | `accounts/views.py` GoogleLoginView; login pages | GSI button + One Tap |
| Invitation whitelist + auto-provisioning | IMPLEMENTED | `accounts/services.py` | Role from PENDING invitation |
| Multi-persona parent account | IMPLEMENTED | `core/students.py`, SelectStudentView, Learn SelectProfilePage | Cookie-based selection |
| Mock login | IMPLEMENTED (gated) | `core/settings_guards.py` | Off locally (DEBUG False) |
| Role model ADMIN/MENTOR/TUTOR/STUDENT | IMPLEMENTED | `accounts/models.py` | Plus superuser flag |
| Role-based API permissions | IMPLEMENTED | `core/permissions.py` + views | — |
| Object-level scoping (mentor/tutor/student) | IMPLEMENTED | `core/querysets.py`, view checks | Tested |
| Staff soft-deactivation / reactivation | IMPLEMENTED | StaffStatusView, migration 0002 | Mentors/tutors only |
| Bulk staff handover | IMPLEMENTED | StaffReassignView | Moves SCHEDULED sessions |
| Staff edit (name/phone) | IMPLEMENTED | UserDetailView | Email immutable |
| Staff/user deletion | NOT IMPLEMENTED | UserDetailView comment | Deliberate |
| Staff directory with pending "ghosts" | IMPLEMENTED | BaseRoleListView, staff-table.jsx | Admin full mode |
| Student create via Sheets-verified invitation | IMPLEMENTED | invitations views/sheets, new-invitation.jsx | Admin UI; mentor API only |
| Student profile edit | IMPLEMENTED | StudentListView.put, edit-student-profile-sheet.jsx | — |
| Student meet link / quota / status / timezone | IMPLEMENTED | StudentListView.put + dialogs | Status note required |
| Single-student reassign | IMPLEMENTED | StudentReassignView | Admin |
| Student purge | IMPLEMENTED | StudentDetailView.delete | Only without sessions |
| Expired student lockout in Learn | IMPLEMENTED | `core/students.py`, Learn AuthProvider | INACTIVE = soft pause |
| Parent/guardian fields | PARTIAL | — | Account = parent; no dedicated fields |
| Session create (single) | IMPLEMENTED | SessionsView.post | Admin/mentor |
| Session series (≤ 20) | IMPLEMENTED | SessionsView.post | Numbered titles |
| Student-timezone scheduling | IMPLEMENTED | `core/timezones.py`, new-session-sheet.jsx | DST gap rejection |
| Quota check on create | IMPLEMENTED | `sessions/services.py` calculate_credits_used | Not on reschedule/make-up |
| Conflict detection (student or tutor) | IMPLEMENTED | find_conflict | SCHEDULED only |
| Reschedule | IMPLEMENTED | SessionsView.put | Browser-local input |
| Cancel (simple) | IMPLEMENTED | SessionsView.put | Reason required |
| Cancel with series shift + make-up | IMPLEMENTED | CancelSeriesView | — |
| Mark attended | IMPLEMENTED | SessionsView.put | Admin/mentor |
| Derived Pending status | IMPLEMENTED | Session.display_status | Not stored |
| Tutor notes-only editing | IMPLEMENTED | `_tutor_update_notes` | URL or upload |
| Session links (URL) | IMPLEMENTED | link columns | No URL validation server-side |
| Session file uploads (PDF/image/video) | IMPLEMENTED (uncommitted) | SessionFile, upload/download views, content-input.jsx | Tests pass |
| Scoped file streaming with Range | IMPLEMENTED (uncommitted) | SessionFileDownloadView | — |
| Session delete via API | NOT IMPLEMENTED | — | Django admin only |
| Session status state machine | NOT IMPLEMENTED | SessionsView.put | Any status accepted |
| Automatic status change after class time | NOT IMPLEMENTED | — | — |
| Per-session meeting link | NOT IMPLEMENTED | — | Per-student link only |
| Chapter / subject / plan entity | NOT IMPLEMENTED | — | Title only |
| Student rating 1–5 | IMPLEMENTED | SessionsView.put, useSessionRating.js | No aggregation |
| Text feedback | NOT IMPLEMENTED | — | — |
| Class quota / credits | PARTIAL | Student.total_class_quota, calculate_credits_used | Computed, no ledger |
| Payments / purchase / refunds | NOT IMPLEMENTED | — | — |
| Invitation email | IMPLEMENTED | `invitations/emails.py` | Only email in system |
| Session reminders / push / in-app notifications | NOT IMPLEMENTED | — | — |
| Activity log (append-only) | IMPLEMENTED | activity app, migration 0002 trigger | Tested |
| Activity scope: mentors/tutors own rows | IMPLEMENTED | scope_activity_by_role | Tested |
| Activity filters + pagination | IMPLEMENTED | ActivityLogListView | — |
| Activity UI (feed, diff, history sheet) | IMPLEMENTED | activity-feed.jsx, student-history-sheet.jsx | — |
| Staff dashboard | IMPLEMENTED | StaffDashboardStatsView, DashboardPage | Two cards show same number |
| Student dashboard | IMPLEMENTED | StudentDashboardView, Learn DashboardPage | — |
| Learn Sessions / Library / Profile | IMPLEMENTED | Learn pages | Cancelled never listed |
| Hub Sessions filters (title/date/tutor/content/columns) | IMPLEMENTED | SessionsPage.jsx | Client-side except content |
| Calendar view | NOT IMPLEMENTED | — | — |
| CSV / PDF export | NOT IMPLEMENTED | — | — |
| Pagination (opt-in) | IMPLEMENTED | `core/pagination.py` | SPAs do not use it |
| Exams / homework module | NOT IMPLEMENTED | disabled "Manage Exams" item | Placeholder only |
| Django admin for all models | IMPLEMENTED | `*/admin.py` | ActivityLog read-only |
| Docker deployment | IMPLEMENTED | docker-compose.yml, Dockerfiles, entrypoint | Local stack healthy |
| Production TLS/HSTS config | PARTIAL | settings.py env switches | All default off |
| Automated tests | IMPLEMENTED | 239 tests, all passing | Backend only; no frontend tests |
| CI pipeline | NOT IMPLEMENTED | none in repo | — |
| Project docs | NOT IMPLEMENTED | docs/ was empty; production-env.md missing | — |

---

## 18. Business rules extracted from code

**Access & accounts**
- Only an invited email can sign in; the account's role is the invitation's role.
- One email may hold many student invitations (children) but only one staff role; a staff email cannot receive a student invitation and vice versa.
- Accepted invitations cannot be edited or withdrawn.
- A deactivated user cannot log in and loses existing sessions; mentors/tutors can only be deactivated after every ACTIVE student is handed over; admins cannot be deactivated.
- Deactivated staff never appear in assignment dropdowns and cannot be chosen as replacements.
- A student's status may be ACTIVE, INACTIVE or EXPIRED; INACTIVE and EXPIRED need a note; EXPIRED is the only status that blocks the persona in Learn.
- A student can be hard-deleted only when it has no sessions and the caller retypes its code.

**Scope**
- Mentors see and edit only students assigned to them; tutors see only their assigned ACTIVE/INACTIVE students.
- Sessions, files and dashboards follow the same student scope; students see only the selected persona.
- Mentors and tutors see only their own activity entries; admins see everything.

**Scheduling**
- Only admins and the student's own mentor can create, reschedule, mark attended or cancel sessions; tutors never can.
- A session requires the student to have a tutor; that tutor is snapshotted on the session.
- Durations are 0.5, 1, 1.5 or 2 hours; a series holds at most 20 classes.
- Total non-cancelled hours may not exceed `total_class_quota` at creation time.
- A new or moved session may not overlap another SCHEDULED session of the same student or the same tutor; attended and cancelled sessions never block.
- Cancelling requires a reason; cancelling a series member with later scheduled classes renumbers them and requires a make-up class.
- Reassigning a tutor moves only SCHEDULED sessions; attended/cancelled history keeps the old tutor.
- Times are entered in the student's timezone (IST when unset) and stored in UTC; DST gaps are rejected.

**Post-session content**
- An attended class is Pending until notes, recording and homework all exist.
- Tutors own the notes link; mentors/admins own recording and homework (and may also set notes).
- Content cannot be attached to a cancelled session.
- One upload per content field; a new upload or a different URL replaces and deletes the previous file.
- Uploads must be PDF/image/video within 50 MB (documents, images) or 500 MB (video) and must match their declared type.
- Files are readable only by admins, the student's mentor/tutor, and the student's usable parent account.

**Ratings & credits**
- Ratings are integers 1–5; the student may rate own sessions; staff may set a rating via PUT.
- Credits are hours; cancelled sessions refund them; top-ups add to the quota.

**Audit**
- Every listed change writes an activity row with a before/after diff; rows can never be updated or deleted.

---

## 19. Current limitations / gaps (observed, no solutions)

- The session file-upload feature exists only in the uncommitted working tree.
- No calendar view anywhere; no CSV/PDF export; no notification system beyond the invitation email; no session reminders.
- No payment, purchase, refund or pricing capability; credits have no ledger and are not re-checked on reschedule or make-up classes.
- No session status state machine: admins/mentors can set any status from any status via the API; past scheduled sessions never expire automatically.
- No per-session meeting link, no chapter/subject/plan entity, no exam or homework module (placeholder menu only).
- Ratings: no aggregation, no text feedback, no server-side once-only or attended-only rule.
- Mentors can create student invitations through the API but have no UI for it.
- Tutors receive full student PII in the API; the restriction is presentational.
- CSRF is not verified on any write endpoint.
- Server-side URL validation is absent for meet links and session links; the `tutor` field on session update is not validated for role or active state.
- Activity feed for mentors/tutors is self-only, so a mentor cannot see tutor actions on their students in the feed.
- Times in the Hub sessions table and in Learn render in the browser's zone, not the student's; reschedule and make-up inputs are browser-local.
- Learn never shows cancelled sessions; the Sessions page in Hub is still on legacy styling.
- The dashboard shows the same number under two labels ("Total Enrollments", "Active Households").
- Both SPAs load students and sessions without pagination.
- No frontend tests, no CI, empty docs folder, missing `docs/production-env.md`.
- Invitation status EXPIRED exists in the enum but nothing ever sets it.
- Parent/guardian details beyond the login email are not modelled.
- Three URL namespaces are registered twice (with and without trailing slash), producing Django `urls.W005` warnings.

---

## 20. Final current-state summary

**A. What it IS.** A Django + DRF API with two React SPAs (staff Hub, student Learn), Google-login only, invitation-gated, backed by PostgreSQL and deployed with docker-compose. It is a faithful port of the earlier Hub/Learn behaviour for accounts, students, 1-to-1 session scheduling, post-session content and an audit log.

**B. What it DOES.** Onboards staff and parent accounts from invitations (students verified against a Google Sheet); manages student profiles, status, quota, Meet link, timezone, mentor/tutor assignment and staff lifecycle; schedules single sessions and up-to-20-class series in the student's timezone with quota and conflict checks; reschedules and cancels (with series shifting); marks attendance; collects notes/recording/homework as URLs or uploaded PDF/image/video files behind scoped download URLs; derives a Pending state until content is complete; lets students see next/last classes, sessions, a library of materials, their profile and mentor contact, and rate sessions 1–5; records every change in an append-only activity log with role-scoped visibility.

**C. What it DOES NOT DO.** Payments or purchases; notifications or reminders; calendars; exports; exams or standalone homework; per-session meeting links; automatic session state changes; rating aggregation or written feedback; role changes or user deletion via API; server-verified CSRF; parent/guardian data beyond the login email.

**D. Main entities.** User (profiles), Student (personas), Invitation, Session, SessionFile, ActivityLog.

**E. Main workflows.** Invite → Google sign-in → provision; assign mentor/tutor; schedule → (reschedule) → attend or cancel; tutor adds notes, mentor adds recording/homework → Pending → Attended; student joins via Meet link, reviews materials, rates; admin audits via the activity log; staff exit via handover + deactivation.

**F. Main permission boundaries.** Admin: everything except peer-admin deactivation and hard deletes. Mentor: own students only, full session control, no staff or invitation UI. Tutor: own students read-only plus the notes link. Student: own selected persona, read-only plus rating. Anonymous: nothing (403). Superuser flag equals admin.
