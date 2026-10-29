"""
One tutor, one student at a time, across both kinds of commitment: a regular
class (sessions) and a Demo or Diagnostic booking assigned to the tutor
(bookings.booking_service.assign_tutor). Scheduling, rescheduling, reinstating
or re-tutoring a class is refused over a live booking the tutor teaches, as
assigning a booking is refused over the tutor's classes -- the same half-open
rule, on instants, under the same tutor lock, including when the two race.
"""
import importlib
import threading
import time as clock
import uuid
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest import mock, skipUnless

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from bookings import booking_service
from bookings.booking_service import CONFLICT_SESSION, TutorUnavailable, assign_tutor, cancel_booking, create_booking
from bookings.models import Booking, BookingType, SlotTime
from bookings.scheduling import BOOKING_TIMEZONE, indian_today
from bookings.tests_booking import request as booking_request
from students.models import StatusChoices, Student

from . import views as session_views
from .models import Session, SessionStatusChoices

User = get_user_model()

DEMO, DIAGNOSTIC = BookingType.DEMO, BookingType.DIAGNOSTIC
SCHEDULED, CANCELLED = SessionStatusChoices.SCHEDULED, SessionStatusChoices.CANCELLED
EVENING, AFTERNOON = time(19, 30), time(16, 0)


class BookingWorld:
    """A mentor's two students, each with their own tutor, and the booking pages' slots two days out (IST)."""

    def build(self):
        self.admin = User.objects.create_user(email='bc_admin@eduport.com', password='x', full_name='Bc Admin', role='ADMIN', is_staff=True)
        self.mentor = User.objects.create_user(email='bc_mentor@eduport.com', password='x', full_name='Bc Mentor', role='MENTOR', is_staff=True)
        self.tutor_a = User.objects.create_user(email='bc_anu@eduport.com', password='x', full_name='Anu', role='TUTOR')
        self.tutor_b = User.objects.create_user(email='bc_binu@eduport.com', password='x', full_name='Binu', role='TUTOR')
        self.student_a = self.make_student('EDPBC1', 'Rahul', self.tutor_a)
        self.student_b = self.make_student('EDPBC2', 'Tom', self.tutor_b)
        for booking_type in (DEMO, DIAGNOSTIC):
            for at in (AFTERNOON, EVENING):
                SlotTime.objects.create(booking_type=booking_type, start_time=at)
        # Inside the booking window (tomorrow through six days on) and in the future.
        self.day = indian_today() + timedelta(days=2)
        self.phones = iter(f'05088800{n:02d}' for n in range(50))
        self.sessions_url = reverse('sessions:sessions-list-create-update')
        self.cancel_url = reverse('sessions:cancel-series')

    def make_student(self, code, name, tutor):
        return Student.objects.create(
            profile=User.objects.create_user(email=f'{code.lower()}@eduport.com', password='x', full_name=name, role='STUDENT'),
            student_code=code, full_name=name, mentor=self.mentor, tutor=tutor,
            total_class_quota=30, status=StatusChoices.ACTIVE,
        )

    def ist(self, at, days=0):
        return datetime.combine(self.day + timedelta(days=days), at, tzinfo=BOOKING_TIMEZONE)

    def booking(self, child, booking_type=DEMO, at=EVENING, tutor=None):
        """A parent's booking through the public pages (a BDE's lead), assigned to ``tutor`` when given."""
        booking, _ = create_booking(booking_request(
            student=child, phone=next(self.phones), booking_type=booking_type, day=self.day, at=at,
        ))
        if tutor is not None:
            booking, _ = assign_tutor(booking, tutor, actor=self.admin)
        return booking

    def class_payload(self, student, local_time, hours=1, zone='Asia/Kolkata', days=0):
        return {
            "student_id": str(student.id), "base_title": "Maths", "series": False, "timezone": zone,
            "items": [{"local_date": (self.day + timedelta(days=days)).isoformat(), "local_time": local_time, "duration_hours": hours}],
        }

    def existing(self, student, start, hours=1, status_value=SCHEDULED):
        return Session.objects.create(
            student=student, tutor=student.tutor, title='Existing', status=status_value,
            start_time=start, end_time=start + timedelta(hours=hours),
        )


class SessionsAgainstBookingsTests(BookingWorld, APITestCase):
    def setUp(self):
        self.build()
        self.client.force_authenticate(user=self.mentor)
        # Anu teaches a Demo booking, 19:30-20:30 IST.
        self.demo = self.booking('Riya', tutor=self.tutor_a)

    def post_class(self, student, local_time, **kwargs):
        return self.client.post(self.sessions_url, self.class_payload(student, local_time, **kwargs), format='json')

    def put(self, payload):
        return self.client.put(self.sessions_url, payload, format='json')

    def assertBookingConflict(self, res, booking):
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['code'], 'TUTOR_BOOKING_CONFLICT')
        conflict = res.data['conflict']
        self.assertEqual((conflict['type'], conflict['booking_id'], conflict['booking_type']), ('tutor_booking', str(booking.id), booking.booking_type))
        self.assertEqual((conflict['start_time'], conflict['end_time']), (booking.slot.starts_at.isoformat(), booking.slot.ends_at.isoformat()))
        self.assertIn('tutor Anu is teaching it', res.data['error'])
        # The booking's child and parent are a BDE's lead: never named to the scheduler.
        for private in ('Riya', 'Ali', 'Asha', '508880'):
            self.assertNotIn(private, str(res.data))

    # --------------------------------------------------- scheduling a class

    def test_an_assigned_demo_booking_blocks_an_overlapping_class(self):
        self.assertBookingConflict(self.post_class(self.student_a, '19:00'), self.demo)
        self.assertIn('This session conflicts with a Demo booking', self.post_class(self.student_a, '20:00').data['error'])
        # A series is refused as a whole, naming the class that clashes.
        payload = self.class_payload(self.student_a, '10:00')
        payload.update(series=True, items=[
            {"local_date": self.day.isoformat(), "local_time": '10:00', "duration_hours": 1},
            {"local_date": self.day.isoformat(), "local_time": '19:45', "duration_hours": 0.5},
        ])
        res = self.client.post(self.sessions_url, payload, format='json')
        self.assertBookingConflict(res, self.demo)
        self.assertIn('Class 2 conflicts with a Demo booking', res.data['error'])
        self.assertFalse(Session.objects.filter(student=self.student_a).exists())

    def test_an_assigned_diagnostic_booking_blocks_an_overlapping_class(self):
        diagnostic = self.booking('Ali', booking_type=DIAGNOSTIC, at=AFTERNOON, tutor=self.tutor_a)
        res = self.post_class(self.student_a, '16:30', hours=0.5)
        self.assertBookingConflict(res, diagnostic)
        self.assertIn('Diagnostic booking', res.data['error'])
        self.assertFalse(Session.objects.filter(student=self.student_a).exists())

    def test_classes_clear_of_the_booking_are_allowed(self):
        for local_time, days in (('10:00', 0), ('19:30', 1)):
            with self.subTest(at=local_time, days=days):
                res = self.post_class(self.student_a, local_time, days=days)
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        # Another tutor is free at the booking's time.
        self.assertEqual(self.post_class(self.student_b, '19:30').status_code, status.HTTP_200_OK)

    def test_touching_the_booking_is_allowed_and_one_minute_over_is_not(self):
        # First, while the student has no class of their own to clash with.
        self.assertBookingConflict(self.post_class(self.student_a, '20:29', hours=0.5), self.demo)
        self.assertBookingConflict(self.post_class(self.student_a, '18:31'), self.demo)
        self.assertEqual(self.post_class(self.student_a, '18:30').status_code, status.HTTP_200_OK)  # ends 19:30
        self.assertEqual(self.post_class(self.student_a, '20:30').status_code, status.HTTP_200_OK)  # starts 20:30

    def test_overlap_is_judged_on_instants_across_time_zones(self):
        # 18:00 in Dubai and 23:00 in Tokyo are both 19:30 in India (neither zone has DST).
        res = self.post_class(self.student_a, '18:00', zone='Asia/Dubai')
        self.assertBookingConflict(res, self.demo)
        # The window is shown in the zone the mentor schedules in.
        self.assertEqual(res.data['conflict']['timezone'], 'Asia/Dubai')
        self.assertIn('from 6:00 PM to 7:00 PM', res.data['error'])
        self.assertBookingConflict(self.post_class(self.student_a, '23:00', zone='Asia/Tokyo'), self.demo)
        # 19:00 in Dubai is 20:30 in India: it starts as the booking ends.
        self.assertEqual(self.post_class(self.student_a, '19:00', zone='Asia/Dubai').status_code, status.HTTP_200_OK)

    def test_cancelled_and_unassigned_bookings_do_not_block(self):
        # Nobody is assigned to this one, so it holds no tutor's time.
        self.booking('Ali', booking_type=DIAGNOSTIC, at=AFTERNOON)
        self.assertEqual(self.post_class(self.student_a, '16:00').status_code, status.HTTP_200_OK)
        # Cancelled, the Demo keeps Anu as its record but no longer holds her time.
        cancel_booking(self.demo, actor=self.admin, reason='Parent cancelled')
        self.assertEqual(self.post_class(self.student_a, '19:30').status_code, status.HTTP_200_OK)

    # ------------------------------------------------- changing a class

    def test_a_class_cannot_be_rescheduled_into_a_booking(self):
        mine = self.existing(self.student_a, self.ist(time(10, 0)))
        res = self.put({"id": str(mine.id), "start_time": self.ist(EVENING).isoformat(), "duration_hours": 1})
        self.assertBookingConflict(res, self.demo)
        mine.refresh_from_db()
        self.assertEqual(mine.start_time, self.ist(time(10, 0)))
        # Up to the booking's start is fine.
        res = self.put({"id": str(mine.id), "start_time": self.ist(time(18, 30)).isoformat(), "duration_hours": 1})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    def test_a_class_cannot_be_handed_to_a_tutor_teaching_a_booking(self):
        theirs = self.existing(self.student_b, self.ist(EVENING))
        res = self.put({"id": str(theirs.id), "tutor": str(self.tutor_a.id)})
        self.assertBookingConflict(res, self.demo)
        theirs.refresh_from_db()
        self.assertEqual(theirs.tutor, self.tutor_b)

    def test_a_cancelled_class_is_not_reinstated_over_a_booking(self):
        cancelled = self.existing(self.student_a, self.ist(EVENING), status_value=CANCELLED)
        res = self.put({"id": str(cancelled.id), "status": "SCHEDULED"})
        self.assertBookingConflict(res, self.demo)
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, CANCELLED)
        # Clear of the booking, it may be reinstated.
        clear = self.existing(self.student_a, self.ist(time(10, 0)), status_value=CANCELLED)
        self.assertEqual(self.put({"id": str(clear.id), "status": "SCHEDULED"}).status_code, status.HTTP_200_OK)

    def test_a_make_up_class_is_not_placed_over_a_booking(self):
        series = [self.existing(self.student_a, self.ist(time(10, 0), days=days)) for days in (0, 1)]
        series_id = uuid.uuid4()
        for number, session in enumerate(series, start=1):
            Session.objects.filter(pk=session.pk).update(series_id=series_id, class_number=number, title=f'Maths - Class {number}')
        res = self.client.post(self.cancel_url, {
            "session_id": str(series[0].id), "cancellation_reason": "Unwell",
            "new_last_start_time": self.ist(EVENING).isoformat(), "new_last_duration_hours": 1,
        }, format='json')
        self.assertBookingConflict(res, self.demo)
        self.assertIn('The make-up class conflicts', res.data['error'])
        series[0].refresh_from_db()
        self.assertEqual(series[0].status, SCHEDULED)

    # ---------------------------------------------- tutors that are not active

    def test_a_class_is_scheduled_only_with_an_active_tutor(self):
        # An inactive student may keep a deactivated tutor (Team hands over active students only).
        retired = User.objects.create_user(
            email='bc_retired@eduport.com', password='x', full_name='Retired', role='TUTOR',
            is_active=False, deactivated_at=timezone.now(),
        )
        student = self.make_student('EDPBC3', 'Lena', retired)
        res = self.post_class(student, '10:00')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.data)
        self.assertEqual(res.data['code'], 'INACTIVE_TUTOR')
        # Nor rescheduled while its tutor is inactive.
        kept = self.existing(student, self.ist(time(10, 0)))
        res = self.put({"id": str(kept.id), "start_time": self.ist(time(11, 0)).isoformat(), "duration_hours": 1})
        self.assertEqual((res.status_code, res.data.get('code')), (status.HTTP_400_BAD_REQUEST, 'INACTIVE_TUTOR'))
        # Handing it to an active tutor is how it moves on.
        res = self.put({"id": str(kept.id), "tutor": str(self.tutor_b.id)})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

    # ---------------------------------------------- the booking side

    def test_booking_assignment_refuses_a_tutor_with_a_class_scheduled_through_the_api(self):
        self.assertEqual(self.post_class(self.student_b, '19:00').status_code, status.HTTP_200_OK)
        other = self.booking('Ali')
        with self.assertRaises(TutorUnavailable) as caught:
            assign_tutor(other, self.tutor_b, actor=self.admin)
        self.assertEqual(caught.exception.conflict.kind, CONFLICT_SESSION)


@skipUnless(connection.vendor == 'postgresql', 'the tutor lock is a PostgreSQL advisory lock')
class ConcurrentCommitmentTests(BookingWorld, TransactionTestCase):
    """
    A class and a booking assignment racing for one tutor, each on its own
    connection, end with one commitment, never two overlapping ones. Both
    checks are slowed down so that, without the shared tutor lock, both
    writers would pass their check before either writes.
    """

    def setUp(self):
        # A TransactionTestCase empties the database between tests, the role
        # groups seeded by migrations included; seed them again (a no-op if present).
        for migration in ('0008_role_groups', '0009_hub_roles_bde_sales_tl'):
            importlib.import_module(f'accounts.migrations.{migration}').seed_role_groups(
                django_apps, SimpleNamespace(connection=connection)
            )
        self.build()
        self.demo = self.booking('Riya')  # 19:30-20:30 IST, nobody assigned yet

    def slowed(self):
        session_check = session_views.find_booking_conflict
        assignment_check = booking_service.find_tutor_conflict

        def slow(check):
            def wrapper(*args, **kwargs):
                found = check(*args, **kwargs)
                clock.sleep(0.5)
                return found
            return wrapper

        return (
            mock.patch.object(session_views, 'find_booking_conflict', slow(session_check)),
            mock.patch.object(booking_service, 'find_tutor_conflict', slow(assignment_check)),
        )

    def race(self, session_write):
        barrier = threading.Barrier(2)
        results = {}

        def write_session():
            try:
                client = APIClient()
                client.force_authenticate(user=self.mentor)
                barrier.wait(timeout=10)
                results['session'] = session_write(client).status_code
            except Exception as exc:  # reported in the assertion, not lost in the thread
                results['session'] = f'error: {exc!r}'
            finally:
                connection.close()

        def assign():
            try:
                barrier.wait(timeout=10)
                assign_tutor(self.demo, self.tutor_a, actor=self.admin)
                results['assignment'] = 'assigned'
            except TutorUnavailable:
                results['assignment'] = 'unavailable'
            except Exception as exc:
                results['assignment'] = f'error: {exc!r}'
            finally:
                connection.close()

        session_patch, assignment_patch = self.slowed()
        with session_patch, assignment_patch:
            threads = [threading.Thread(target=write_session), threading.Thread(target=assign)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
        return results

    def assertOneCommitment(self, results, session_ok):
        self.assertIn(results, ({'session': 200, 'assignment': 'unavailable'}, {'session': 409, 'assignment': 'assigned'}), results)
        assigned = Booking.objects.filter(pk=self.demo.pk, assigned_tutor=self.tutor_a).exists()
        self.assertEqual(assigned, results['assignment'] == 'assigned')
        self.assertEqual(session_ok(), results['session'] == 200)

    def test_a_new_class_and_a_booking_assignment_racing_for_one_tutor(self):
        results = self.race(lambda client: client.post(self.sessions_url, self.class_payload(self.student_a, '19:00'), format='json'))
        self.assertOneCommitment(results, lambda: Session.objects.filter(tutor=self.tutor_a, status=SCHEDULED).exists())

    def test_a_tutor_change_and_a_booking_assignment_racing_for_one_tutor(self):
        theirs = self.existing(self.student_b, self.ist(EVENING))
        results = self.race(lambda client: client.put(self.sessions_url, {"id": str(theirs.id), "tutor": str(self.tutor_a.id)}, format='json'))
        self.assertOneCommitment(results, lambda: Session.objects.filter(pk=theirs.pk, tutor=self.tutor_a).exists())
