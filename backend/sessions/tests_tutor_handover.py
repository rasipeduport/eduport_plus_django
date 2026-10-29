"""
The flows that move a tutor's commitments without scheduling anything keep
the one-to-one rule too: reassigning a student (/api/students/reassign/), the
Team handover (/api/users/<id>/reassign/), and an account ceasing to be an
active tutor (Team deactivation or role change, the Django admin) while
Demo/Diagnostic bookings are assigned to it. The Django admin cannot edit a
class's schedule at all.
"""
import importlib
import threading
import time as clock
from datetime import time, timedelta
from types import SimpleNamespace
from unittest import mock, skipUnless

from django.apps import apps as django_apps
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts import team as team_module
from accounts.tests_permissions import PLAIN_STORAGES, change_form_data
from activity.models import ActivityLog
from bookings import booking_service
from bookings.booking_service import (
    TutorNotAssignable,
    TutorUnavailable,
    assign_tutor,
    cancel_booking,
    create_booking,
    unassign_tutor,
)
from bookings.models import Booking
from bookings.scheduling import indian_today
from bookings.tests_booking import request as booking_request
from students import views as student_views

from .models import Session, SessionStatusChoices
from .tests_booking_conflicts import AFTERNOON, EVENING, BookingWorld, User

SCHEDULED, ATTENDED = SessionStatusChoices.SCHEDULED, SessionStatusChoices.ATTENDED
REASSIGN_URL = '/api/students/reassign/'


def staff_reassign_url(account):
    return f'/api/users/{account.id}/reassign/'


def team_url(account, action=''):
    return f'/api/team/{account.id}/{action}'


class HandoverWorld(BookingWorld):
    def build(self):
        super().build()
        self.mentor_two = User.objects.create_user(email='bc_mentor2@eduport.com', password='x', full_name='Bc Mentor Two', role='MENTOR', is_staff=True)
        # Anu's second student, so the Team handover moves more than one.
        self.student_c = self.make_student('EDPBC4', 'Meera', self.tutor_a)
        # Anu's open classes: Rahul tomorrow-and-a-day at 10:00 and the next evening, Meera at 16:00.
        self.rahul_morning = self.existing(self.student_a, self.ist(time(10, 0)))
        self.rahul_evening = self.existing(self.student_a, self.ist(EVENING, days=1))
        self.meera_afternoon = self.existing(self.student_c, self.ist(AFTERNOON))

    def reassign_payload(self, student, tutor, mentor=None):
        return {"id": str(student.id), "mentor": str((mentor or self.mentor).id), "tutor": str(tutor.id) if tutor else None}

    def tutors_of(self, *sessions):
        return [Session.objects.get(pk=session.pk).tutor for session in sessions]


class StudentReassignTests(HandoverWorld, APITestCase):
    def setUp(self):
        self.build()
        self.client.force_authenticate(user=self.admin)

    def reassign(self, student, tutor, **kwargs):
        return self.client.post(REASSIGN_URL, self.reassign_payload(student, tutor, **kwargs), format='json')

    def assertNothingMoved(self):
        self.student_a.refresh_from_db()
        self.assertEqual((self.student_a.tutor, self.student_a.mentor), (self.tutor_a, self.mentor))
        self.assertEqual(self.tutors_of(self.rahul_morning, self.rahul_evening), [self.tutor_a, self.tutor_a])
        self.assertFalse(ActivityLog.objects.filter(action__in=('student.reassign_tutor', 'student.reassign_mentor')).exists())

    def test_refused_when_the_new_tutor_has_an_overlapping_class(self):
        # Binu teaches Tom 19:00-20:00 the evening Rahul has his 19:30 class.
        self.existing(self.student_b, self.ist(time(19, 0), days=1))
        res = self.reassign(self.student_a, self.tutor_b, mentor=self.mentor_two)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['error'], 'TUTOR_SESSION_CONFLICT')
        self.assertEqual(res.data['conflict']['moving_session_id'], str(self.rahul_evening.id))
        self.assertIn('The class "Existing" conflicts with "Existing": tutor Binu is already scheduled with Tom', res.data['message'])
        # The mentor asked for in the same request does not change either.
        self.assertNothingMoved()

    def test_refused_when_the_new_tutor_has_an_assigned_booking(self):
        booking = self.booking('Riya', at=EVENING, tutor=self.tutor_b)
        clash = self.existing(self.student_a, self.ist(time(19, 0)))  # Rahul at 19:00, the Demo at 19:30
        res = self.reassign(self.student_a, self.tutor_b)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['error'], 'TUTOR_BOOKING_CONFLICT')
        self.assertEqual((res.data['conflict']['booking_id'], res.data['conflict']['moving_session_id']), (str(booking.id), str(clash.id)))
        self.assertIn('with a Demo booking: tutor Binu is teaching it', res.data['message'])
        self.assertNotIn('Riya', str(res.data))
        self.assertNothingMoved()
        self.assertEqual(Session.objects.get(pk=clash.pk).tutor, self.tutor_a)

    def test_moves_the_open_classes_when_the_new_tutor_is_free(self):
        # Binu teaches right up to Rahul's morning class, and has a Demo after it.
        self.existing(self.student_b, self.ist(time(9, 0)))
        self.booking('Riya', at=AFTERNOON, tutor=self.tutor_b)
        # History stays with Anu and is not checked: an attended class, and an open one already past.
        attended = self.existing(self.student_a, self.ist(EVENING, days=-5), status_value=ATTENDED)
        stale = self.existing(self.student_a, self.ist(EVENING, days=-4))
        self.existing(self.student_b, self.ist(EVENING, days=-4))  # Binu was busy then
        res = self.reassign(self.student_a, self.tutor_b)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['result']['sessions_repointed'], 3)
        self.assertEqual(self.tutors_of(self.rahul_morning, self.rahul_evening, stale), [self.tutor_b] * 3)
        self.assertEqual(self.tutors_of(attended), [self.tutor_a])
        entry = ActivityLog.objects.get(action='student.reassign_tutor', entity_id=str(self.student_a.id))
        self.assertEqual((entry.context['old_tutor_id'], entry.context['new_tutor_id'], entry.context['sessions_repointed']),
                         (str(self.tutor_a.id), str(self.tutor_b.id), 3))

    def test_unassigning_the_tutor_checks_nothing(self):
        self.existing(self.student_b, self.ist(time(10, 0)))
        res = self.reassign(self.student_a, None)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(self.tutors_of(self.rahul_morning), [None])

    def test_still_needs_its_permission_and_an_active_tutor(self):
        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(self.reassign(self.student_a, self.tutor_b).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=self.admin)
        retired = User.objects.create_user(email='bc_old@eduport.com', password='x', full_name='Old', role='TUTOR',
                                           is_active=False, deactivated_at=timezone.now())
        res = self.reassign(self.student_a, retired)
        self.assertEqual((res.status_code, res.data['error']), (status.HTTP_400_BAD_REQUEST, 'INVALID_TUTOR'))
        self.assertNothingMoved()


class StaffHandoverTests(HandoverWorld, APITestCase):
    def setUp(self):
        self.build()
        self.client.force_authenticate(user=self.admin)

    def hand_over(self, tutor):
        return self.client.post(staff_reassign_url(self.tutor_a), {"new_tutor": str(tutor.id)}, format='json')

    def assertNothingMoved(self):
        for student in (self.student_a, self.student_c):
            student.refresh_from_db()
            self.assertEqual(student.tutor, self.tutor_a)
        self.assertEqual(self.tutors_of(self.rahul_morning, self.rahul_evening, self.meera_afternoon), [self.tutor_a] * 3)
        self.assertFalse(ActivityLog.objects.filter(action='staff.reassign_all').exists())

    def test_refused_when_the_new_tutor_has_an_assigned_booking(self):
        booking = self.booking('Riya', at=AFTERNOON, tutor=self.tutor_b)  # Meera's class time
        res = self.hand_over(self.tutor_b)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['error'], 'TUTOR_BOOKING_CONFLICT')
        self.assertEqual((res.data['conflict']['booking_id'], res.data['conflict']['moving_session_id']),
                         (str(booking.id), str(self.meera_afternoon.id)))
        self.assertNothingMoved()

    def test_refused_when_the_new_tutor_has_an_overlapping_class(self):
        self.existing(self.student_b, self.ist(time(10, 30)))  # half an hour into Rahul's morning class
        res = self.hand_over(self.tutor_b)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['error'], 'TUTOR_SESSION_CONFLICT')
        self.assertEqual(res.data['conflict']['moving_session_id'], str(self.rahul_morning.id))
        self.assertNothingMoved()

    def test_hands_over_every_student_when_the_new_tutor_is_free(self):
        self.booking('Riya', at=EVENING, tutor=self.tutor_b)  # clear of all three classes
        res = self.hand_over(self.tutor_b)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual((res.data['result']['students_tutor_reassigned'], res.data['result']['sessions_repointed']), (2, 3))
        self.assertEqual(self.tutors_of(self.rahul_morning, self.rahul_evening, self.meera_afternoon), [self.tutor_b] * 3)
        self.assertTrue(ActivityLog.objects.filter(action='staff.reassign_all', entity_id=str(self.tutor_a.id)).exists())

    def test_still_needs_its_permission(self):
        self.client.force_authenticate(user=self.mentor)
        self.assertEqual(self.hand_over(self.tutor_b).status_code, status.HTTP_403_FORBIDDEN)
        self.assertNothingMoved()


class DepartingTutorBookingTests(BookingWorld, APITestCase):
    """An account assigned upcoming bookings stays an active tutor until they are reassigned."""

    def setUp(self):
        self.build()
        self.client.force_authenticate(user=self.admin)
        # Chitra has no students (nothing to hand over) and teaches a Demo.
        self.tutor_c = User.objects.create_user(email='bc_chitra@eduport.com', password='x', full_name='Chitra', role='TUTOR')
        self.demo = self.booking('Riya', tutor=self.tutor_c)

    def deactivate(self, account):
        return self.client.post(team_url(account, 'deactivate/'), {"reason": "Left"}, format='json')

    def test_deactivation_waits_for_upcoming_bookings(self):
        res = self.deactivate(self.tutor_c)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['error'], 'BOOKING_HANDOVER_REQUIRED')
        self.assertIn('assigned 1 upcoming Demo/Diagnostic booking(s). Assign them to another tutor, or unassign them, before deactivating.', res.data['message'])
        self.tutor_c.refresh_from_db()
        self.assertTrue(self.tutor_c.is_active)
        self.assertFalse(ActivityLog.objects.filter(action='user.deactivate', entity_id=str(self.tutor_c.id)).exists())
        # Once the booking is someone else's, the account deactivates as before, audited.
        assign_tutor(self.demo, self.tutor_b, actor=self.admin)
        res = self.deactivate(self.tutor_c)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.tutor_c.refresh_from_db()
        self.assertIsNotNone(self.tutor_c.deactivated_at)
        self.assertTrue(ActivityLog.objects.filter(action='user.deactivate', entity_id=str(self.tutor_c.id)).exists())

    def test_a_role_change_waits_for_upcoming_bookings(self):
        res = self.client.patch(team_url(self.tutor_c), {"role": "MENTOR"}, format='json')
        self.assertEqual((res.status_code, res.data['error']), (status.HTTP_409_CONFLICT, 'BOOKING_HANDOVER_REQUIRED'))
        self.tutor_c.refresh_from_db()
        self.assertEqual(self.tutor_c.role, 'TUTOR')
        unassign_tutor(self.demo, actor=self.admin)
        self.assertEqual(self.client.patch(team_url(self.tutor_c), {"role": "MENTOR"}, format='json').status_code, status.HTTP_200_OK)

    def test_cancelled_and_past_bookings_do_not_hold_the_account(self):
        cancel_booking(self.demo, actor=self.admin)
        # A Demo taught last week: booked, assigned, and over.
        last_week = timezone.now() - timedelta(days=7)
        past_day = indian_today(last_week) + timedelta(days=1)
        past, _ = create_booking(booking_request(student='Ali', phone='0508880099', day=past_day, at=EVENING), now=last_week)
        assign_tutor(past, self.tutor_c, actor=self.admin, now=last_week)
        self.assertEqual(self.deactivate(self.tutor_c).status_code, status.HTTP_200_OK)
        # Both keep their tutor as history.
        self.assertEqual(set(Booking.objects.values_list('assigned_tutor', flat=True)), {self.tutor_c.id})

    def test_a_tutor_without_bookings_deactivates_as_before(self):
        self.assertEqual(self.deactivate(self.tutor_b).status_code, status.HTTP_409_CONFLICT)  # Tom is still Binu's: HANDOVER_REQUIRED
        free = User.objects.create_user(email='bc_free@eduport.com', password='x', full_name='Free', role='TUTOR')
        self.assertEqual(self.deactivate(free).status_code, status.HTTP_200_OK)

    def test_a_deactivated_tutor_is_never_assigned(self):
        free = User.objects.create_user(email='bc_free@eduport.com', password='x', full_name='Free', role='TUTOR')
        self.assertEqual(self.deactivate(free).status_code, status.HTTP_200_OK)
        with self.assertRaises(TutorNotAssignable):
            assign_tutor(self.booking('Ali', at=AFTERNOON), free, actor=self.admin)


@override_settings(STORAGES=PLAIN_STORAGES)
class DjangoAdminTests(BookingWorld, APITestCase):
    def setUp(self):
        self.build()
        self.root = User.objects.create_user(email='bc_root@eduport.com', password='x', full_name='Root', role='ADMIN',
                                             is_staff=True, is_superuser=True)
        self.browser = Client()
        self.browser.force_login(self.root)

    def test_a_class_schedule_cannot_be_edited_or_added_in_the_admin(self):
        mine = self.existing(self.student_a, self.ist(time(10, 0)))
        self.assertEqual(self.browser.get('/admin/sessions_app/session/add/').status_code, status.HTTP_403_FORBIDDEN)
        url = f'/admin/sessions_app/session/{mine.pk}/change/'
        page = self.browser.get(url)
        self.assertEqual(page.status_code, status.HTTP_200_OK)
        form = page.context['adminform'].form
        for field in ('student', 'tutor', 'start_time', 'end_time', 'status'):
            self.assertNotIn(field, form.fields)
        # A schedule change posted anyway is ignored; the editable fields still save.
        data = change_form_data(page)
        data.update({
            'tutor': str(self.tutor_b.id), 'start_time_0': self.ist(EVENING).date().isoformat(), 'start_time_1': '19:30:00',
            'status': 'CANCELLED', 'notes_link': 'https://notes.example/maths',
        })
        self.assertEqual(self.browser.post(url, data).status_code, 302)
        mine.refresh_from_db()
        self.assertEqual((mine.tutor, mine.start_time, mine.status), (self.tutor_a, self.ist(time(10, 0)), SCHEDULED))
        self.assertEqual(mine.notes_link, 'https://notes.example/maths')

    def test_the_user_admin_keeps_a_tutor_with_upcoming_bookings_active(self):
        self.booking('Riya', tutor=self.tutor_b)
        url = f'/admin/accounts/user/{self.tutor_b.pk}/change/'
        data = change_form_data(self.browser.get(url))
        data.pop('is_active', None)  # unticked
        response = self.browser.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('before deactivating', str(response.context['adminform'].form.errors['is_active']))
        self.tutor_b.refresh_from_db()
        self.assertTrue(self.tutor_b.is_active)

    def test_the_user_admin_keeps_the_role_of_a_tutor_with_upcoming_bookings(self):
        tutor_c = User.objects.create_user(email='bc_chitra@eduport.com', password='x', full_name='Chitra', role='TUTOR')
        self.booking('Riya', tutor=tutor_c)
        url = f'/admin/accounts/user/{tutor_c.pk}/change/'
        data = change_form_data(self.browser.get(url))
        data['role'] = 'MENTOR'
        response = self.browser.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('before changing their role', str(response.context['adminform'].form.errors['role']))
        tutor_c.refresh_from_db()
        self.assertEqual(tutor_c.role, 'TUTOR')

    def test_the_user_admin_deactivates_a_tutor_without_bookings(self):
        free = User.objects.create_user(email='bc_free@eduport.com', password='x', full_name='Free', role='TUTOR')
        url = f'/admin/accounts/user/{free.pk}/change/'
        data = change_form_data(self.browser.get(url))
        data.pop('is_active', None)
        self.assertEqual(self.browser.post(url, data).status_code, 302)
        free.refresh_from_db()
        self.assertIsNotNone(free.deactivated_at)


@skipUnless(connection.vendor == 'postgresql', 'the scheduling locks are PostgreSQL advisory and row locks')
class ConcurrentHandoverTests(HandoverWorld, TransactionTestCase):
    """
    A handover racing a class or a booking assignment for the same tutor, each
    on its own connection, ends with one of them refused, never with
    overlapping commitments. Every check is slowed down so that, without the
    locks, both writers would pass theirs before either writes.
    """

    def setUp(self):
        for migration in ('0008_role_groups', '0009_hub_roles_bde_sales_tl'):
            importlib.import_module(f'accounts.migrations.{migration}').seed_role_groups(
                django_apps, SimpleNamespace(connection=connection)
            )
        self.build()
        self.demo = self.booking('Riya', at=EVENING)  # unassigned, the evening Rahul has no class

    @staticmethod
    def slow(check):
        def wrapper(*args, **kwargs):
            found = check(*args, **kwargs)
            clock.sleep(0.5)
            return found
        return wrapper

    def run_together(self, **calls):
        barrier = threading.Barrier(len(calls))
        results = {}

        def run(name, call):
            try:
                barrier.wait(timeout=10)
                results[name] = call()
            except TutorUnavailable:
                results[name] = 'unavailable'
            except TutorNotAssignable:
                results[name] = 'not assignable'
            except Exception as exc:  # reported in the assertion, not lost in the thread
                results[name] = f'error: {exc!r}'
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=item) for item in calls.items()]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return results

    def as_admin(self, method, url, body):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return getattr(client, method)(url, body, format='json').status_code

    def assign_demo_to_binu(self):
        assign_tutor(self.demo, self.tutor_b, actor=self.admin)
        return 'assigned'

    def test_a_student_reassignment_racing_a_booking_assignment(self):
        # Rahul's class at 19:00 today-plus-two clashes with the evening Demo.
        clash = self.existing(self.student_a, self.ist(time(19, 0)))
        with mock.patch.object(student_views, 'find_handover_conflict', self.slow(student_views.find_handover_conflict)), \
                mock.patch.object(booking_service, 'find_tutor_conflict', self.slow(booking_service.find_tutor_conflict)):
            results = self.run_together(
                reassign=lambda: self.as_admin('post', REASSIGN_URL, self.reassign_payload(self.student_a, self.tutor_b)),
                assign=self.assign_demo_to_binu,
            )
        self.assertIn(results, ({'reassign': 200, 'assign': 'unavailable'}, {'reassign': 409, 'assign': 'assigned'}), results)
        binu_class = Session.objects.filter(pk=clash.pk, tutor=self.tutor_b).exists()
        binu_demo = Booking.objects.filter(pk=self.demo.pk, assigned_tutor=self.tutor_b).exists()
        self.assertNotEqual(binu_class, binu_demo)

    def test_a_student_reassignment_racing_a_class_for_the_new_tutor(self):
        from sessions import views as session_views
        payload = self.class_payload(self.student_b, '10:00')  # Tom with Binu, over Rahul's morning class

        def schedule_toms_class():
            client = APIClient()
            client.force_authenticate(user=self.mentor)
            return client.post(self.sessions_url, payload, format='json').status_code

        with mock.patch.object(student_views, 'find_handover_conflict', self.slow(student_views.find_handover_conflict)), \
                mock.patch.object(session_views, 'find_conflict', self.slow(session_views.find_conflict)):
            results = self.run_together(
                reassign=lambda: self.as_admin('post', REASSIGN_URL, self.reassign_payload(self.student_a, self.tutor_b)),
                schedule=schedule_toms_class,
            )
        self.assertIn(results, ({'reassign': 200, 'schedule': 409}, {'reassign': 409, 'schedule': 200}), results)
        morning = (self.ist(time(10, 0)), self.ist(time(11, 0)))
        overlapping = Session.objects.filter(tutor=self.tutor_b, status=SCHEDULED, start_time__lt=morning[1], end_time__gt=morning[0])
        self.assertEqual(overlapping.count(), 1)

    def test_a_deactivation_racing_a_booking_assignment(self):
        with mock.patch.object(team_module, 'upcoming_booking_refusal', self.slow(team_module.upcoming_booking_refusal)), \
                mock.patch.object(booking_service, 'find_tutor_conflict', self.slow(booking_service.find_tutor_conflict)):
            free = User.objects.create_user(email='bc_free@eduport.com', password='x', full_name='Free', role='TUTOR')

            def assign_to_free():
                assign_tutor(self.demo, free, actor=self.admin)
                return 'assigned'

            results = self.run_together(
                deactivate=lambda: self.as_admin('post', team_url(free, 'deactivate/'), {"reason": "Left"}),
                assign=assign_to_free,
            )
        self.assertIn(results, ({'deactivate': 200, 'assign': 'not assignable'}, {'deactivate': 409, 'assign': 'assigned'}), results)
        free.refresh_from_db()
        # Never a deactivated account holding an upcoming booking.
        self.assertFalse(free.deactivated_at is not None and Booking.objects.filter(pk=self.demo.pk, assigned_tutor=free).exists())
