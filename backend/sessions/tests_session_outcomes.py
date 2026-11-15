"""
Where a normal session stands and what is recorded about it once it is over
(sessions.lifecycle): the derived class state, the tutor's notes deadline and
late notes awaiting approval, No-show / Not Conducted recorded by an
administrator or the student's mentor, an administrator's audited correction
or revocation of it, the credit each outcome leaves used, and the cut-off
for cancelling.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from homework.models import Homework
from students.services import build_profile_stats

from . import lifecycle
from .lifecycle import ClassState
from .models import NOTES_DEADLINE, LateNotesStatus, Session, SessionOutcomeReason
from .services import apply_state_filter, calculate_credits_used, state_q
from .tests_session_lifecycle import ATTENDED, CANCELLED, SCHEDULED, SessionLifecycleWorld

NOT_CONDUCTED = 'NOT_CONDUCTED'
NO_SHOW = SessionOutcomeReason.STUDENT_NO_SHOW
TUTOR_ABSENT = SessionOutcomeReason.TUTOR_ABSENT
TECHNICAL = SessionOutcomeReason.TECHNICAL_ISSUE
OTHER = SessionOutcomeReason.OTHER


class OutcomeWorld(SessionLifecycleWorld):
    def post(self, user, name, session, payload=None):
        self.client.force_authenticate(user=user)
        return self.client.post(reverse(f'sessions:{name}', args=[session.id]), payload or {}, format='json')

    def record(self, user, session, reason=NO_SHOW, note=None):
        return self.post(user, 'session-outcome', session, {'reason': reason, 'note': note})

    def approve(self, user, session):
        return self.post(user, 'session-late-notes-approve', session)

    def correct(self, user, session, reason, note=None, correction_note='Recorded against the wrong class'):
        return self.post(user, 'session-outcome-correct', session,
                         {'reason': reason, 'note': note, 'correction_note': correction_note})

    def revoke(self, user, session, correction_note='Recorded against the wrong class'):
        return self.post(user, 'session-outcome-revoke', session, {'correction_note': correction_note})

    def late(self, days=4, **fields):
        """A started class whose notes deadline has passed, with its tutor's late notes in."""
        session = self.make(-timedelta(days=days), started=True, **fields)
        res = self.notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        session.refresh_from_db()
        return session

    def row(self, user, session, **params):
        self.client.force_authenticate(user=user)
        rows = self.client.get(self.sessions_url, params).data['sessions']
        return next((r for r in rows if r['id'] == str(session.id)), None)


class ClassStateTests(OutcomeWorld):
    def states(self):
        """One class in every state, as of self.now."""
        return {
            ClassState.UPCOMING: self.make(timedelta(days=1)),
            # Under way with nobody having started it yet: still Upcoming.
            'UNDER_WAY_NOT_STARTED': self.make(-timedelta(minutes=10)),
            ClassState.IN_PROGRESS: self.make(-timedelta(minutes=10), started=True),
            ClassState.NOTES_DUE: self.make(-timedelta(hours=3), started=True),
            'STAFF_ATTENDED_STARTED': self.make(-timedelta(hours=5), started=True, status_value=ATTENDED),
            ClassState.NOT_STARTED: self.make(-timedelta(hours=7)),
            'STAFF_ATTENDED_NOT_STARTED': self.make(-timedelta(hours=9), status_value=ATTENDED),
            ClassState.COMPLETED: self.make(
                -timedelta(hours=11), started=True, status_value=ATTENDED,
                completed_at=self.now - timedelta(hours=9), completed_by=self.tutor,
            ),
            ClassState.NOT_CONDUCTED: self.make(
                -timedelta(hours=13), status_value=NOT_CONDUCTED, outcome_reason=NO_SHOW,
                outcome_recorded_at=self.now, outcome_recorded_by=self.mentor, outcome_prior_status=SCHEDULED,
            ),
            ClassState.CANCELLED: self.make(timedelta(days=2), status_value=CANCELLED, cancellation_reason='Sick'),
        }

    EXPECTED = {
        ClassState.UPCOMING: ClassState.UPCOMING,
        'UNDER_WAY_NOT_STARTED': ClassState.UPCOMING,
        ClassState.IN_PROGRESS: ClassState.IN_PROGRESS,
        ClassState.NOTES_DUE: ClassState.NOTES_DUE,
        'STAFF_ATTENDED_STARTED': ClassState.NOTES_DUE,
        ClassState.NOT_STARTED: ClassState.NOT_STARTED,
        # Staff attendance is operational: nobody started it, so it stays Not Started.
        'STAFF_ATTENDED_NOT_STARTED': ClassState.NOT_STARTED,
        ClassState.COMPLETED: ClassState.COMPLETED,
        ClassState.NOT_CONDUCTED: ClassState.NOT_CONDUCTED,
        ClassState.CANCELLED: ClassState.CANCELLED,
    }

    def test_every_class_is_in_exactly_one_state_and_the_query_agrees(self):
        sessions = self.states()
        for label, session in sessions.items():
            with self.subTest(label):
                expected = self.EXPECTED[label]
                self.assertEqual(lifecycle.class_state(session, self.now), expected)
                matching = [state for state in ClassState.values
                            if Session.objects.filter(state_q(state, self.now), pk=session.pk).exists()]
                self.assertEqual(matching, [expected])

    def test_the_scheduled_end_moves_a_class_on_and_nothing_else_does(self):
        started = self.make(timedelta(hours=1), started=True)
        unstarted = self.make(timedelta(hours=3))
        for session, after in ((started, ClassState.NOTES_DUE), (unstarted, ClassState.NOT_STARTED)):
            with self.subTest(after=after):
                just_before = session.end_time - timedelta(microseconds=1)
                self.assertIn(lifecycle.class_state(session, just_before), (ClassState.IN_PROGRESS, ClassState.UPCOMING))
                self.assertEqual(lifecycle.class_state(session, session.end_time), after)
                self.assertTrue(Session.objects.filter(state_q(after, session.end_time), pk=session.pk).exists())
                # Days later it is still where the end left it: nothing changes it on its own.
                self.assertEqual(lifecycle.class_state(session, session.end_time + timedelta(days=30)), after)

    def test_the_api_gives_each_class_its_state_and_filters_by_it(self):
        sessions = self.states()
        for label, session in sessions.items():
            with self.subTest(label):
                row = self.row(self.admin, session)
                self.assertEqual(row['class_state'], self.EXPECTED[label].lower())
                self.assertEqual(row['notes_due_by'], (session.end_time + NOTES_DEADLINE).isoformat())
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.sessions_url, {'state': 'notes_due,NOT_STARTED'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        expected = {str(sessions[label].id) for label, state in self.EXPECTED.items()
                    if state in (ClassState.NOTES_DUE, ClassState.NOT_STARTED)}
        self.assertEqual({r['id'] for r in res.data['sessions']}, expected)
        for bad in ('missed', 'upcoming,nope', ','):
            with self.subTest(bad=bad):
                self.assertEqual(self.client.get(self.sessions_url, {'state': bad}).status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_state_filter_stays_inside_the_callers_scope(self):
        mine = self.make(-timedelta(hours=3))
        self.client.force_authenticate(user=self.other_mentor)
        rows = self.client.get(self.sessions_url, {'state': 'not_started'}).data['sessions']
        self.assertNotIn(str(mine.id), {r['id'] for r in rows})

    def test_unknown_states_are_refused_by_the_helper(self):
        with self.assertRaises(ValueError):
            apply_state_filter(Session.objects.all(), 'attended', self.now)


class NotesDeadlineTests(OutcomeWorld):
    def mode_at(self, session, now):
        with transaction.atomic():
            return lifecycle.tutor_notes_target(session, self.tutor, now, 'cancelled')[1]

    def test_notes_complete_until_exactly_48_hours_after_the_scheduled_end(self):
        session = self.make(-timedelta(days=5), started=True)
        self.assertEqual(session.notes_due_by, session.end_time + timedelta(hours=48))
        self.assertEqual(self.mode_at(session, session.end_time), lifecycle.NOTES_COMPLETE)
        self.assertEqual(self.mode_at(session, session.notes_due_by), lifecycle.NOTES_COMPLETE)
        self.assertEqual(self.mode_at(session, session.notes_due_by + timedelta(microseconds=1)), lifecycle.NOTES_LATE)

    def test_late_notes_are_kept_awaiting_approval_and_complete_nothing(self):
        session = self.make(-timedelta(days=3), started=True)
        res = self.notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual((res.data['completed'], res.data['late_notes']), (False, True))
        session.refresh_from_db()
        self.assertEqual((session.status, session.notes_link), (SCHEDULED, 'https://example.com/notes'))
        self.assertIsNone(session.completed_at)
        self.assertEqual(session.late_notes_status, LateNotesStatus.PENDING)
        self.assertGreater(session.late_notes_submitted_at, session.notes_due_by)
        self.assertEqual(lifecycle.class_state(session, timezone.now()), ClassState.NOTES_DUE)
        self.assertEqual(self.logs(session, 'session.submit_late_notes').count(), 1)
        self.assertFalse(self.logs(session, 'session.complete').exists())
        row = self.row(self.mentor, session)
        self.assertEqual((row['late_notes_status'], row['class_state']), ('PENDING', 'notes_due'))

    def test_late_notes_may_be_replaced_while_they_await_approval(self):
        session = self.late()
        first = session.late_notes_submitted_at
        res = self.notes(self.tutor, session, link='https://example.com/notes-v2')
        self.assertEqual((res.data['completed'], res.data['late_notes']), (False, True))
        session.refresh_from_db()
        self.assertEqual(session.notes_link, 'https://example.com/notes-v2')
        self.assertEqual((session.late_notes_status, session.late_notes_submitted_at), (LateNotesStatus.PENDING, first))
        self.assertEqual(self.logs(session, 'session.submit_late_notes').count(), 1)

    def test_uploaded_late_notes_wait_too(self):
        session = self.make(-timedelta(days=3), started=True)
        res = self.upload_notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual((res.data['completed'], res.data['late_notes']), (False, True))
        session.refresh_from_db()
        self.assertEqual(session.late_notes_status, LateNotesStatus.PENDING)
        self.assertEqual(session.files.count(), 1)

    def test_a_class_staff_marked_attended_waits_for_approval_too(self):
        session = self.make(-timedelta(days=3), started=True, status_value=ATTENDED)
        self.assertTrue(self.notes(self.tutor, session).data['late_notes'])
        session.refresh_from_db()
        self.assertEqual((session.status, session.late_notes_status), (ATTENDED, LateNotesStatus.PENDING))


class LateNotesApprovalTests(OutcomeWorld):
    def test_the_students_mentor_or_an_administrator_approves_them(self):
        for approver in (self.mentor, self.admin):
            with self.subTest(role=approver.role):
                session = self.late(homework_link='https://hw.example/1')
                res = self.approve(approver, session)
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
                session.refresh_from_db()
                self.assertEqual(session.status, ATTENDED)
                self.assertEqual((session.completed_by, session.completed_at), (self.tutor, session.late_notes_submitted_at))
                self.assertEqual(session.late_notes_status, LateNotesStatus.APPROVED)
                self.assertEqual(session.late_notes_reviewed_by, approver)
                self.assertEqual(res.data['session']['class_state'], 'completed')
                self.assertEqual(self.logs(session, 'session.approve_late_notes').get().actor, approver)
                completion = self.logs(session, 'session.complete').get()
                self.assertTrue(completion.context['approved_late_notes'])
                self.assertEqual(Homework.objects.get(session=session).status, 'ASSIGNED')

    def test_nobody_else_approves_them(self):
        session = self.late()
        for user, code in ((self.other_mentor, status.HTTP_403_FORBIDDEN), (self.tutor, status.HTTP_403_FORBIDDEN),
                           (self.bde, status.HTTP_403_FORBIDDEN), (self.student_user, status.HTTP_403_FORBIDDEN)):
            with self.subTest(role=user.role, email=user.email):
                self.assertEqual(self.approve(user, session).status_code, code)
        session.refresh_from_db()
        self.assertEqual(session.late_notes_status, LateNotesStatus.PENDING)

    def test_only_late_notes_awaiting_approval_can_be_approved(self):
        on_time = self.make(-timedelta(hours=3), started=True)
        self.notes(self.tutor, on_time)
        for session in (on_time, self.make(-timedelta(days=3), started=True)):
            res = self.approve(self.mentor, session)
            self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
            self.assertEqual(res.data['code'], lifecycle.NO_LATE_NOTES)
        approved = self.late()
        self.approve(self.mentor, approved)
        self.assertEqual(self.approve(self.mentor, approved).data['code'], lifecycle.NO_LATE_NOTES)
        self.assertEqual(self.logs(approved, 'session.complete').count(), 1)

    def test_late_notes_staff_removed_are_not_approved(self):
        session = self.late()
        self.assertEqual(self.put(self.mentor, {'id': str(session.id), 'notes_link': None}).status_code, status.HTTP_200_OK)
        res = self.approve(self.mentor, session)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], lifecycle.LATE_NOTES_MISSING)

    def test_an_unknown_session_is_404(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse('sessions:session-late-notes-approve', args=['00000000-0000-0000-0000-000000000000'])
        self.assertEqual(self.client.post(url).status_code, status.HTTP_404_NOT_FOUND)


class RecordOutcomeTests(OutcomeWorld):
    def test_the_students_mentor_or_an_administrator_records_it_once_the_class_ended(self):
        for recorder, reason in ((self.mentor, NO_SHOW), (self.admin, TECHNICAL)):
            with self.subTest(role=recorder.role):
                session = self.make(-timedelta(hours=3))
                res = self.record(recorder, session, reason, note='  Parent called at 4pm  ')
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
                session.refresh_from_db()
                self.assertEqual(session.status, NOT_CONDUCTED)
                self.assertEqual((session.outcome_reason, session.outcome_note), (reason, 'Parent called at 4pm'))
                self.assertEqual((session.outcome_recorded_by, session.outcome_prior_status), (recorder, SCHEDULED))
                self.assertEqual(res.data['session']['class_state'], 'not_conducted')
                self.assertEqual(res.data['session']['status'], 'not_conducted')
                log = self.logs(session, 'session.record_outcome').get()
                self.assertEqual(log.changes['status'], {'old': SCHEDULED, 'new': NOT_CONDUCTED})
                self.assertEqual(log.changes['outcome_reason'], {'old': None, 'new': reason})

    def test_whether_started_or_not_and_after_staff_attendance(self):
        cases = (
            (self.make(-timedelta(hours=3), started=True), SCHEDULED),
            (self.make(-timedelta(hours=5), status_value=ATTENDED), ATTENDED),
        )
        for session, prior in cases:
            with self.subTest(prior=prior):
                self.assertEqual(self.record(self.mentor, session, TUTOR_ABSENT).status_code, status.HTTP_200_OK)
                session.refresh_from_db()
                self.assertEqual((session.status, session.outcome_prior_status), (NOT_CONDUCTED, prior))

    def test_nobody_else_records_it(self):
        session = self.make(-timedelta(hours=3))
        for user in (self.other_mentor, self.tutor, self.other_tutor, self.bde, self.student_user):
            with self.subTest(email=user.email):
                self.assertEqual(self.record(user, session).status_code, status.HTTP_403_FORBIDDEN)
        session.refresh_from_db()
        self.assertEqual(session.status, SCHEDULED)

    def test_never_before_the_scheduled_end_and_never_on_its_own(self):
        for session in (self.make(timedelta(days=1)), self.make(-timedelta(minutes=10), started=True)):
            res = self.record(self.mentor, session)
            self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
            self.assertEqual(res.data['code'], lifecycle.CLASS_NOT_ENDED)
        # Exactly at the end it may be recorded.
        session = self.make(-timedelta(hours=3))
        with transaction.atomic():
            lifecycle.record_outcome(session, self.mentor, NO_SHOW, now=session.end_time)
        # A class long past with nothing recorded stays as it was.
        old = self.make(-timedelta(days=60))
        self.assertEqual(lifecycle.class_state(old, timezone.now()), ClassState.NOT_STARTED)
        self.assertEqual(Session.objects.get(pk=old.pk).status, SCHEDULED)

    def test_never_on_a_completed_cancelled_or_recorded_class(self):
        completed = self.make(-timedelta(hours=3), started=True)
        self.notes(self.tutor, completed)
        cancelled = self.make(-timedelta(hours=5), status_value=CANCELLED, cancellation_reason='Sick')
        recorded = self.make(-timedelta(hours=7))
        self.record(self.mentor, recorded)
        for session, code in ((completed, lifecycle.SESSION_COMPLETED), (cancelled, lifecycle.SESSION_CANCELLED),
                              (recorded, lifecycle.OUTCOME_RECORDED)):
            with self.subTest(code=code):
                res = self.record(self.admin, session, TUTOR_ABSENT)
                self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
                self.assertEqual(res.data['code'], code)
        recorded.refresh_from_db()
        self.assertEqual(recorded.outcome_reason, NO_SHOW)

    def test_never_on_a_class_whose_homework_is_under_way(self):
        session = self.make(-timedelta(hours=3), started=True, status_value=ATTENDED)
        Homework.objects.create(session=session, student=self.student)
        res = self.record(self.mentor, session)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], lifecycle.HOMEWORK_EXISTS)

    def test_the_reason_is_one_of_the_list_and_other_needs_its_note(self):
        session = self.make(-timedelta(hours=3))
        for payload in ({'reason': 'SICK'}, {}, {'reason': OTHER}, {'reason': OTHER, 'note': '   '},
                        {'reason': NO_SHOW, 'note': 'x' * 501}, {'reason': NO_SHOW, 'note': 5}):
            with self.subTest(payload=payload):
                res = self.post(self.mentor, 'session-outcome', session, payload)
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.data)
                self.assertEqual(res.data['code'], lifecycle.INVALID_OUTCOME)
        self.assertEqual(self.record(self.mentor, session, OTHER, note='Power cut').status_code, status.HTTP_200_OK)

    def test_it_rejects_late_notes_awaiting_approval(self):
        session = self.late()
        self.assertEqual(self.record(self.mentor, session, TUTOR_ABSENT).status_code, status.HTTP_200_OK)
        session.refresh_from_db()
        self.assertEqual((session.late_notes_status, session.late_notes_reviewed_by), (LateNotesStatus.REJECTED, self.mentor))
        self.assertIsNone(session.completed_at)
        log = self.logs(session, 'session.record_outcome').get()
        self.assertEqual(log.changes['late_notes_status'], {'old': 'PENDING', 'new': 'REJECTED'})

    def test_a_recorded_outcome_is_final(self):
        session = self.make(-timedelta(hours=3), started=True)
        self.record(self.mentor, session)
        refusals = [
            self.put(self.admin, {'id': str(session.id), 'status': 'SCHEDULED'}),
            self.put(self.admin, {'id': str(session.id), 'status': 'ATTENDED'}),
            self.put(self.admin, {'id': str(session.id), 'recording_link': 'https://rec.example/1'}),
            self.put(self.mentor, {'id': str(session.id), 'title': 'Renamed'}),
            self.notes(self.tutor, session),
            self.upload_notes(self.tutor, session),
        ]
        for res in refusals:
            self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
            self.assertEqual(res.data['code'], lifecycle.OUTCOME_RECORDED)
        self.client.force_authenticate(user=self.mentor)
        upload = self.client.post(reverse('sessions:session-file-upload', args=[session.id, 'recording']), {}, format='multipart')
        self.assertEqual(upload.status_code, status.HTTP_409_CONFLICT)
        with self.assertRaises(lifecycle.SessionStateError) as refused, transaction.atomic():
            lifecycle.start_session(session, self.tutor, now=session.start_time)
        self.assertEqual(refused.exception.code, lifecycle.OUTCOME_RECORDED)
        session.refresh_from_db()
        self.assertEqual((session.status, session.outcome_reason, session.title), (NOT_CONDUCTED, NO_SHOW, 'Algebra'))

    def test_it_is_never_set_through_the_session_edit(self):
        session = self.make(-timedelta(hours=3))
        res = self.put(self.admin, {'id': str(session.id), 'status': 'NOT_CONDUCTED'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Session.objects.get(pk=session.pk).status, SCHEDULED)


class OutcomeCorrectionTests(OutcomeWorld):
    def recorded(self, reason=NO_SHOW, **fields):
        session = self.make(-timedelta(hours=3), **fields)
        self.assertEqual(self.record(self.mentor, session, reason).status_code, status.HTTP_200_OK)
        session.refresh_from_db()
        return session

    def test_an_administrator_corrects_the_reason_saying_why(self):
        session = self.recorded()
        res = self.correct(self.admin, session, TUTOR_ABSENT, note='Tutor was ill')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertTrue(res.data['changed'])
        session.refresh_from_db()
        self.assertEqual((session.outcome_reason, session.outcome_note), (TUTOR_ABSENT, 'Tutor was ill'))
        self.assertEqual((session.outcome_corrected_by, session.outcome_recorded_by), (self.admin, self.mentor))
        log = self.logs(session, 'session.correct_outcome').get()
        self.assertEqual(log.changes['outcome_reason'], {'old': NO_SHOW, 'new': TUTOR_ABSENT})
        self.assertEqual(log.context['correction_note'], 'Recorded against the wrong class')
        self.assertEqual(log.actor, self.admin)

    def test_a_correction_changing_nothing_is_not_logged(self):
        session = self.recorded()
        res = self.correct(self.admin, session, NO_SHOW)
        self.assertFalse(res.data['changed'])
        self.assertFalse(self.logs(session, 'session.correct_outcome').exists())

    def test_an_administrator_revokes_it_and_the_class_is_as_it_was(self):
        cases = {
            'scheduled': self.recorded(started=True),
            'staff attended': self.recorded(status_value=ATTENDED),
        }
        for label, session in cases.items():
            with self.subTest(label):
                prior = session.outcome_prior_status
                res = self.revoke(self.admin, session)
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
                session.refresh_from_db()
                self.assertEqual(session.status, prior)
                for field in ('outcome_reason', 'outcome_note', 'outcome_recorded_at', 'outcome_recorded_by',
                              'outcome_prior_status', 'outcome_corrected_at'):
                    self.assertIsNone(getattr(session, field), field)
                log = self.logs(session, 'session.revoke_outcome').get()
                self.assertEqual(log.changes['status'], {'old': NOT_CONDUCTED, 'new': prior})
                self.assertEqual(log.context['correction_note'], 'Recorded against the wrong class')
                self.assertEqual(log.context['recorded_by_id'], str(self.mentor.id))
        # The started class takes its tutor's notes again (completing it within the deadline).
        self.assertTrue(self.notes(self.tutor, cases['scheduled']).data['completed'])

    def test_revoking_brings_rejected_late_notes_back_for_approval(self):
        session = self.late()
        self.record(self.mentor, session, TUTOR_ABSENT)
        self.assertEqual(self.revoke(self.admin, session).status_code, status.HTTP_200_OK)
        session.refresh_from_db()
        self.assertEqual(session.late_notes_status, LateNotesStatus.PENDING)
        self.assertIsNone(session.late_notes_reviewed_at)
        self.assertEqual(self.approve(self.admin, session).status_code, status.HTTP_200_OK)
        session.refresh_from_db()
        self.assertEqual((session.status, session.completed_by), (ATTENDED, self.tutor))

    def test_only_an_administrator_corrects_or_revokes(self):
        session = self.recorded()
        for user in (self.mentor, self.tutor, self.bde, self.student_user):
            with self.subTest(email=user.email):
                self.assertEqual(self.correct(user, session, TUTOR_ABSENT).status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(self.revoke(user, session).status_code, status.HTTP_403_FORBIDDEN)
        session.refresh_from_db()
        self.assertEqual((session.status, session.outcome_reason), (NOT_CONDUCTED, NO_SHOW))

    def test_every_correction_says_why_and_needs_an_outcome(self):
        session = self.recorded()
        for blank in ('', '  ', None):
            with self.subTest(correction_note=blank):
                self.assertEqual(self.correct(self.admin, session, TUTOR_ABSENT, correction_note=blank).status_code,
                                 status.HTTP_400_BAD_REQUEST)
                self.assertEqual(self.revoke(self.admin, session, correction_note=blank).status_code,
                                 status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.correct(self.admin, session, OTHER).status_code, status.HTTP_400_BAD_REQUEST)
        open_class = self.make(-timedelta(hours=5))
        for res in (self.correct(self.admin, open_class, TUTOR_ABSENT), self.revoke(self.admin, open_class)):
            self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(res.data['code'], lifecycle.NO_OUTCOME)


class CreditTests(OutcomeWorld):
    def test_only_a_students_no_show_keeps_its_credit_used(self):
        used = {}
        for reason in (NO_SHOW, TUTOR_ABSENT, TECHNICAL, OTHER):
            session = self.make(-timedelta(hours=3 + 2 * len(used)), hours=1.5)
            before = calculate_credits_used(self.student)
            self.record(self.mentor, session, reason, note='Note')
            used[reason] = calculate_credits_used(self.student) - before
            row = self.row(self.mentor, session)
            self.assertEqual(row['consumes_credit'], reason == NO_SHOW, reason)
        self.assertEqual(used, {NO_SHOW: 0, TUTOR_ABSENT: -1.5, TECHNICAL: -1.5, OTHER: -1.5})

    def test_classes_with_nothing_recorded_keep_their_credit_used_whatever_the_clock(self):
        for starts_in in (timedelta(days=1), -timedelta(minutes=10), -timedelta(hours=3), -timedelta(days=40)):
            self.make(starts_in)
        completed = self.make(-timedelta(hours=6), started=True)
        self.notes(self.tutor, completed)
        self.make(timedelta(days=3), status_value=CANCELLED, cancellation_reason='Sick')
        self.assertEqual(calculate_credits_used(self.student), 5.0)

    def test_the_quota_and_its_corrections_follow_the_reason(self):
        session = self.make(-timedelta(hours=3), hours=2)
        quota = lambda: build_profile_stats(self.student, self.admin)['quota']['used_hours']  # noqa: E731
        self.assertEqual(quota(), 2.0)
        self.record(self.mentor, session, TUTOR_ABSENT)
        self.assertEqual(quota(), 0.0)
        self.correct(self.admin, session, NO_SHOW)
        self.assertEqual(quota(), 2.0)
        self.revoke(self.admin, session)
        self.assertEqual(quota(), 2.0)

    def test_the_profile_counts_classes_by_where_they_stand(self):
        self.make(-timedelta(hours=3), started=True)
        self.make(-timedelta(hours=5))
        self.make(-timedelta(hours=7))
        recorded = self.make(-timedelta(hours=9))
        self.record(self.mentor, recorded)
        sessions = build_profile_stats(self.student, self.admin)['sessions']
        self.assertEqual((sessions['notes_due'], sessions['not_started'], sessions['not_conducted']), (1, 2, 1))


class CancelCutOffTests(OutcomeWorld):
    def test_a_class_is_cancelled_only_until_its_scheduled_end(self):
        for session in (self.make(-timedelta(hours=3)), self.make(-timedelta(hours=5), started=True)):
            res = self.put(self.mentor, {'id': str(session.id), 'status': 'CANCELLED', 'cancellation_reason': 'Sick'})
            self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
            self.assertEqual(res.data['code'], lifecycle.SESSION_ENDED)
            self.client.force_authenticate(user=self.mentor)
            res = self.client.post(reverse('sessions:cancel-series'),
                                   {'session_id': str(session.id), 'cancellation_reason': 'Sick'}, format='json')
            self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
            self.assertEqual(res.data['code'], lifecycle.SESSION_ENDED)
            self.assertEqual(Session.objects.get(pk=session.pk).status, SCHEDULED)
        # Under way, it may still be cancelled.
        under_way = self.make(-timedelta(minutes=10), started=True)
        res = self.put(self.mentor, {'id': str(under_way.id), 'status': 'CANCELLED', 'cancellation_reason': 'Sick'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)


class StudentViewTests(OutcomeWorld):
    def test_a_student_is_told_only_whether_it_was_their_no_show(self):
        no_show = self.make(-timedelta(hours=3))
        not_held = self.make(-timedelta(hours=5))
        self.record(self.mentor, no_show, NO_SHOW, note='Mentor-only remark')
        self.record(self.mentor, not_held, OTHER, note='Mentor-only remark')
        for session, kind in ((no_show, 'no_show'), (not_held, 'not_conducted')):
            row = self.row(self.student_user, session)
            self.assertEqual((row['class_state'], row['outcome_kind']), ('not_conducted', kind))
            for hidden in ('outcome_reason', 'outcome_note', 'outcome_recorded_by_profile', 'late_notes_status'):
                self.assertNotIn(hidden, row)
            self.assertEqual(self.row(self.mentor, session)['outcome_note'], 'Mentor-only remark')

    def test_a_student_cannot_rate_a_class_not_conducted(self):
        session = self.make(-timedelta(hours=3))
        self.record(self.mentor, session)
        res = self.put(self.student_user, {'id': str(session.id), 'rating': 5})
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIsNone(Session.objects.get(pk=session.pk).rating)


class OutcomeIntegrityTests(OutcomeWorld):
    def refused(self, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(-timedelta(hours=3), **fields)

    def test_the_database_holds_the_outcome_and_late_notes_rules(self):
        recorded = dict(status_value=NOT_CONDUCTED, outcome_reason=NO_SHOW, outcome_recorded_at=self.now,
                        outcome_prior_status=SCHEDULED)
        # Not conducted without its outcome, or an outcome on another status.
        self.refused(status_value=NOT_CONDUCTED)
        self.refused(status_value=NOT_CONDUCTED, outcome_reason=NO_SHOW, outcome_prior_status=SCHEDULED)
        self.refused(outcome_reason=NO_SHOW, outcome_recorded_at=self.now, outcome_prior_status=SCHEDULED)
        # Before the scheduled end, from a status other than scheduled/attended, or OTHER without its note.
        self.refused(**{**recorded, 'outcome_recorded_at': self.now - timedelta(hours=3)})
        self.refused(**{**recorded, 'outcome_prior_status': CANCELLED})
        self.refused(**{**recorded, 'outcome_reason': OTHER})
        # Late notes before the deadline, without a start, or approved without a completion.
        self.refused(started=True, late_notes_status=LateNotesStatus.PENDING, late_notes_submitted_at=self.now)
        late = self.now + timedelta(days=3)
        self.refused(late_notes_status=LateNotesStatus.PENDING, late_notes_submitted_at=late)
        self.refused(started=True, late_notes_status=LateNotesStatus.APPROVED, late_notes_submitted_at=late,
                     late_notes_reviewed_at=late)
        # Rejected late notes only with a recorded outcome.
        self.refused(started=True, late_notes_status=LateNotesStatus.REJECTED, late_notes_submitted_at=late,
                     late_notes_reviewed_at=late)
        # A sound recorded outcome is held.
        self.make(-timedelta(hours=3), **recorded)
