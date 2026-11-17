"""
Where a normal session stands and what is recorded about it once it is over
(sessions.lifecycle): the derived class state, the tutor's notes completing a
started class whenever they come in after its end (no deadline, no approval),
No-show / Not Conducted recorded by an administrator or the student's mentor,
an administrator's audited correction or revocation of it, the credit each
outcome leaves used, and the cut-off for cancelling.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework import status

from homework.models import Homework
from students.models import StatusChoices, Student
from students.services import build_profile_stats

from . import lifecycle
from .lifecycle import ClassState
from .models import Session, SessionOutcomeReason
from .services import apply_state_filter, calculate_credits_used, state_q
from .tests_session_lifecycle import ATTENDED, CANCELLED, SCHEDULED, SessionLifecycleWorld

User = get_user_model()

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

    def correct(self, user, session, reason, note=None, correction_note='Recorded against the wrong class'):
        return self.post(user, 'session-outcome-correct', session,
                         {'reason': reason, 'note': note, 'correction_note': correction_note})

    def revoke(self, user, session, correction_note='Recorded against the wrong class'):
        return self.post(user, 'session-outcome-revoke', session, {'correction_note': correction_note})

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
                # No deadline and no late notes: nothing about either is served.
                self.assertFalse({'notes_due_by', 'late_notes_status', 'late_notes_submitted_at',
                                  'late_notes_reviewed_at', 'late_notes_reviewed_by_profile'} & set(row))
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


class NotesWithoutDeadlineTests(OutcomeWorld):
    def mode_at(self, session, now):
        with transaction.atomic():
            return lifecycle.tutor_notes_target(session, self.tutor, now, 'cancelled')[1]

    def test_notes_complete_a_started_class_whenever_they_come_in_after_its_end(self):
        session = self.make(-timedelta(days=40), started=True)
        for after in (timedelta(0), timedelta(hours=48), timedelta(hours=48, microseconds=1), timedelta(days=30)):
            with self.subTest(after=after):
                self.assertEqual(self.mode_at(session, session.end_time + after), lifecycle.NOTES_COMPLETE)

    def test_notes_weeks_after_the_class_complete_it_with_no_approval(self):
        session = self.make(-timedelta(days=21), started=True, homework_link='https://hw.example/1')
        res = self.notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertTrue(res.data['completed'])
        self.assertNotIn('late_notes', res.data)
        session.refresh_from_db()
        self.assertEqual((session.status, session.completed_by), (ATTENDED, self.tutor))
        self.assertGreater(session.completed_at, session.end_time + timedelta(days=20))
        self.assertEqual(lifecycle.class_state(session, timezone.now()), ClassState.COMPLETED)
        self.assertEqual(self.logs(session, 'session.complete').count(), 1)
        self.assertFalse(self.logs(session, 'session.submit_late_notes').exists())
        self.assertEqual(Homework.objects.get(session=session).status, 'ASSIGNED')
        self.assertEqual(self.row(self.mentor, session)['class_state'], 'completed')

    def test_uploaded_notes_days_later_complete_it_too(self):
        session = self.make(-timedelta(days=3), started=True)
        res = self.upload_notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertTrue(res.data['completed'])
        self.assertNotIn('late_notes', res.data)
        session.refresh_from_db()
        self.assertEqual((session.status, session.completed_by), (ATTENDED, self.tutor))
        self.assertEqual(session.files.count(), 1)

    def test_a_class_staff_marked_attended_is_completed_by_its_tutors_later_notes(self):
        session = self.make(-timedelta(days=3), started=True, status_value=ATTENDED)
        self.assertTrue(self.notes(self.tutor, session).data['completed'])
        session.refresh_from_db()
        self.assertEqual((session.status, session.completed_by), (ATTENDED, self.tutor))

    def test_an_unstarted_class_still_takes_no_notes_however_long_after(self):
        session = self.make(-timedelta(days=5))
        res = self.notes(self.tutor, session)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['code'], lifecycle.SESSION_NOT_STARTED)
        session.refresh_from_db()
        self.assertIsNone(session.completed_at)

    def test_the_late_notes_approval_is_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse('sessions:session-late-notes-approve', args=[self.make(-timedelta(days=3), started=True).id])
        session = self.make(-timedelta(days=3), started=True)
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.post(f'/api/sessions/{session.id}/late-notes/approve/').status_code,
                         status.HTTP_404_NOT_FOUND)
        for name in ('NOTES_LATE', 'NOTES_LATE_UPDATE', 'approve_late_notes', 'NO_LATE_NOTES'):
            self.assertFalse(hasattr(lifecycle, name), name)


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

    def test_a_class_its_tutors_notes_completed_days_later_is_not_recorded(self):
        session = self.make(-timedelta(days=4), started=True)
        self.assertTrue(self.notes(self.tutor, session).data['completed'])
        res = self.record(self.mentor, session, TUTOR_ABSENT)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['code'], lifecycle.SESSION_COMPLETED)

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
        # The started class takes its tutor's notes again, completing it.
        self.assertTrue(self.notes(self.tutor, cases['scheduled']).data['completed'])

    def test_after_a_revocation_the_tutors_notes_complete_the_class_however_late(self):
        session = self.make(-timedelta(days=6), started=True)
        self.record(self.mentor, session, TUTOR_ABSENT)
        self.assertEqual(self.notes(self.tutor, session).data['code'], lifecycle.OUTCOME_RECORDED)
        self.assertEqual(self.revoke(self.admin, session).status_code, status.HTTP_200_OK)
        self.assertNotIn('late_notes_status', self.logs(session, 'session.revoke_outcome').get().changes)
        self.assertTrue(self.notes(self.tutor, session).data['completed'])
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
            for hidden in ('outcome_reason', 'outcome_note', 'outcome_recorded_by_profile', 'outcome_corrected_at'):
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

    def test_the_database_holds_the_outcome_rules(self):
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
        # A sound recorded outcome is held.
        self.make(-timedelta(hours=3), **recorded)

    def test_the_database_holds_a_completion_long_after_the_end_but_never_without_a_start(self):
        weeks_later = dict(status_value=ATTENDED, completed_at=self.now + timedelta(days=30), completed_by=self.tutor)
        self.refused(**weeks_later)
        self.make(-timedelta(hours=3), started=True, **weeks_later)


class NotesDeadlineMigrationTests(TransactionTestCase):
    """
    sessions_app.0005 completes late notes still awaiting approval -- with the
    homework row an approval made -- and reverses: a class its tutor's notes
    completed days after its end comes back as late notes approved, so the
    deadline's checks hold again.
    """

    def people(self):
        tutor = User.objects.create_user(email='nd_tutor@eduport.com', password='x', full_name='Nd Tutor', role='TUTOR',
                                         is_staff=True)
        student = Student.objects.create(
            profile=User.objects.create_user(email='nd_stu@eduport.com', password='x', full_name='Nd Stu', role='STUDENT'),
            student_code='EDPND1', full_name='Nd Stu', tutor=tutor, total_class_quota=10, status=StatusChoices.ACTIVE,
        )
        return tutor, student

    def test_late_notes_awaiting_approval_complete_their_class(self):
        tutor, student = self.people()
        end = timezone.now().replace(microsecond=0) - timedelta(days=10)
        submitted = end + timedelta(days=3)
        executor = MigrationExecutor(connection)
        try:
            before = [('sessions_app', '0004_session_outcomes_and_late_notes')]
            executor.migrate(before)
            OldSession = executor.loader.project_state(before).apps.get_model('sessions_app', 'Session')

            def awaiting(**fields):
                return OldSession.objects.create(
                    student_id=student.pk, tutor_id=tutor.pk, title='Algebra', start_time=end - timedelta(hours=1),
                    end_time=end, status='SCHEDULED', started_at=end - timedelta(hours=1), started_by_id=tutor.pk,
                    late_notes_status='PENDING', late_notes_submitted_at=submitted, **fields,
                ).pk

            with_notes = awaiting(notes_link='https://example.com/notes', homework_link='https://example.com/homework')
            no_notes = awaiting(notes_link='  ')
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes('sessions_app'))
        done = Session.objects.get(pk=with_notes)
        self.assertEqual((done.status, done.completed_at, done.completed_by_id), (ATTENDED, submitted, tutor.pk))
        homework = Homework.objects.get(session_id=with_notes)
        self.assertEqual((homework.status, homework.assigned_at, homework.assigned_by_id), ('ASSIGNED', submitted, None))
        untouched = Session.objects.get(pk=no_notes)
        self.assertEqual((untouched.status, untouched.completed_at), (SCHEDULED, None))
        self.assertFalse(Homework.objects.filter(session_id=no_notes).exists())

    def test_reverse_and_reapply(self):
        tutor, student = self.people()
        end = timezone.now().replace(microsecond=0) - timedelta(days=10)

        def completed(after):
            return Session.objects.create(
                student=student, tutor=tutor, title='Algebra', start_time=end - timedelta(hours=1), end_time=end,
                status=ATTENDED, started_at=end - timedelta(hours=1), started_by=tutor, completed_at=end + after,
                completed_by=tutor, notes_link='https://example.com/notes',
            )

        late, on_time = completed(timedelta(days=5)), completed(timedelta(hours=3))
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([('sessions_app', '0004_session_outcomes_and_late_notes')])
            with connection.cursor() as cursor:
                cursor.execute('SELECT id, late_notes_status, late_notes_submitted_at, late_notes_reviewed_at, '
                               'late_notes_reviewed_by_id FROM sessions')
                rows = {row[0]: row[1:] for row in cursor.fetchall()}
            self.assertEqual(rows[late.pk], ('APPROVED', late.completed_at, late.completed_at, None))
            self.assertEqual(rows[on_time.pk], (None, None, None, None))
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes('sessions_app'))
        late.refresh_from_db()
        self.assertEqual((late.status, late.completed_at), (ATTENDED, end + timedelta(days=5)))
