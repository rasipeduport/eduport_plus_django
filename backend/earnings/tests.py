"""
Tutor Earnings activation and eligibility (earnings.eligibility).

A class counts only when its assigned tutor's own notes completed it after
its scheduled end, and only when it was scheduled to end at or after the
activation that migration 0001 records. Nothing from before the activation
is backfilled.
"""
import importlib
from datetime import timedelta

from django.apps import apps as django_apps
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status

from sessions.models import Session
from sessions.tests_session_lifecycle import ATTENDED, CANCELLED, SessionLifecycleWorld

from . import eligibility
from .models import TutorEarningsActivation


class EarningsWorld(SessionLifecycleWorld):
    def activate(self, at):
        TutorEarningsActivation.objects.update_or_create(id=1, defaults={'activated_at': at})

    def eligible(self):
        return set(eligibility.eligible_sessions().values_list('pk', flat=True))

    def assert_counts(self, session, expected):
        session.refresh_from_db()
        self.assertEqual(session.pk in self.eligible(), expected)
        self.assertEqual(eligibility.is_eligible(session), expected)


class ActivationTests(EarningsWorld):
    def test_the_migration_activated_earnings_once_when_it_was_applied(self):
        activation = TutorEarningsActivation.objects.get()
        self.assertEqual(activation.id, 1)
        self.assertLessEqual(activation.activated_at, timezone.now())
        self.assertEqual(eligibility.activated_at(), activation.activated_at)
        # Applying it again keeps the first moment.
        migration = importlib.import_module('earnings.migrations.0001_initial')
        migration.record_activation(django_apps, None)
        self.assertEqual(TutorEarningsActivation.objects.get().activated_at, activation.activated_at)

    def test_there_is_only_ever_one_activation(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TutorEarningsActivation.objects.create(id=2, activated_at=self.now)

    def test_without_an_activation_nothing_counts_and_tutors_still_complete_classes(self):
        TutorEarningsActivation.objects.all().delete()
        session = self.make(-timedelta(hours=2))
        self.assertTrue(self.notes(self.tutor, session).data['completed'])
        self.assertIsNone(eligibility.activated_at())
        self.assert_counts(session, False)


class EligibilityTests(EarningsWorld):
    def test_classes_that_ended_before_the_activation_are_never_backfilled(self):
        # Rows that exist when earnings is activated: completed by the tutor, attended by staff, never closed.
        completed = self.make(
            -timedelta(days=5), status_value=ATTENDED,
            completed_at=self.now - timedelta(days=4), completed_by=self.tutor,
        )
        staff_attended = self.make(-timedelta(days=4), status_value=ATTENDED)
        open_past = self.make(-timedelta(days=3))
        self.activate(self.now - timedelta(days=1))
        # The tutor's notes still complete the older classes after the activation...
        for session in (staff_attended, open_past):
            self.assertTrue(self.notes(self.tutor, session).data['completed'])
        # ...but none of them ever counts.
        for session in (completed, staff_attended, open_past):
            with self.subTest(start_time=session.start_time):
                self.assert_counts(session, False)
        self.assertEqual(self.eligible(), set())

    def test_a_class_ending_exactly_at_the_activation_counts(self):
        session = self.make(-timedelta(hours=2))
        self.activate(session.end_time)
        self.assertTrue(self.notes(self.tutor, session).data['completed'])
        self.assert_counts(session, True)
        self.activate(session.end_time + timedelta(seconds=1))
        self.assert_counts(session, False)

    def test_after_the_activation_only_the_tutors_own_notes_make_a_class_count(self):
        self.activate(self.now - timedelta(days=7))
        started_by_mentor = self.make(-timedelta(hours=2), started=True, starter=self.mentor)
        unstarted = self.make(-timedelta(hours=3))
        staff_attended = self.make(-timedelta(hours=4))
        staff_notes = self.make(-timedelta(hours=5))
        started_only = self.make(-timedelta(hours=6), started=True, starter=self.admin)
        cancelled = self.make(-timedelta(hours=7), status_value=CANCELLED)
        upcoming = self.make(timedelta(days=1))
        for session in (started_by_mentor, unstarted):
            self.assertTrue(self.notes(self.tutor, session).data['completed'])
        res = self.put(self.mentor, {'id': str(staff_attended.id), 'status': 'ATTENDED'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        res = self.put(self.admin, {'id': str(staff_notes.id), 'notes_link': 'https://example.com/staff'})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

        counted = {started_by_mentor.pk, unstarted.pk}
        self.assertEqual(self.eligible(), counted)
        for session in (started_by_mentor, unstarted, staff_attended, staff_notes, started_only, cancelled, upcoming):
            with self.subTest(start_time=session.start_time):
                self.assert_counts(session, session.pk in counted)

    def test_a_counted_class_counts_as_booked_however_late_its_notes(self):
        self.activate(self.now - timedelta(days=7))
        session = self.make(-timedelta(days=3), hours=1.5)
        self.assertTrue(self.notes(self.tutor, session).data['completed'])
        self.assert_counts(session, True)
        self.assertEqual(session.duration_hours, 1.5)

    def test_a_completion_no_longer_matching_the_assigned_tutor_never_counts(self):
        # A tutor swapped on a completed row outside the API (the Django admin) takes it out.
        self.activate(self.now - timedelta(days=1))
        session = self.make(-timedelta(hours=2))
        self.notes(self.tutor, session)
        self.assert_counts(session, True)
        Session.objects.filter(pk=session.pk).update(tutor=self.other_tutor)
        self.assert_counts(session, False)

    def test_a_former_tutors_completion_counts_from_the_activation(self):
        old = self.make(-timedelta(days=10))
        recent = self.make(-timedelta(days=2))
        for session in (old, recent):
            res = self.put(self.mentor, {'id': str(session.id), 'status': 'ATTENDED'})
            self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.client.force_authenticate(user=self.admin)
        res = self.client.post('/api/students/reassign/', {
            'id': str(self.student.id), 'mentor': str(self.mentor.id), 'tutor': str(self.other_tutor.id),
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.activate(self.now - timedelta(days=5))
        for session in (old, recent):
            self.assertTrue(self.notes(self.tutor, session).data['completed'])
        self.assertEqual(self.eligible(), {recent.pk})
        self.assert_counts(old, False)
        self.assert_counts(recent, True)
