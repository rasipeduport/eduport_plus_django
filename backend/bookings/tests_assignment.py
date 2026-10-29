"""
Tutor assignment (bookings.booking_service.assign_tutor / unassign_tutor).

Tuition is one-to-one: every booking is one student's class with its own
tutor, and a tutor teaches one student at a time -- checked against their
scheduled classes and their other live bookings, under the locks, including
when requests race. Slots are the booking pages' Indian times; classes are
instants, so a class booked in another zone is compared by the moment it is.
"""
import json
import threading
import time as clock
from datetime import datetime, time, timedelta
from unittest import mock, skipUnless
from zoneinfo import ZoneInfo

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from activity.models import ActivityLog
from sessions.models import Session, SessionStatusChoices
from sessions.services import lock_scheduling
from students.models import Student

from . import booking_service
from .booking_service import (
    CONFLICT_BOOKING,
    CONFLICT_SESSION,
    BookingCancelled,
    SlotStarted,
    TutorNotAssignable,
    TutorUnavailable,
    assign_tutor,
    cancel_booking,
    find_tutor_conflict,
    unassign_tutor,
)
from .models import Booking, BookingStatus, SlotTime
from .scheduling import BOOKING_TIMEZONE
from .tests_booking import DAY, DIAGNOSTIC, EVENING, MORNING, NOW, account, book, schedule

BOOKED, CANCELLED = BookingStatus.BOOKED, BookingStatus.CANCELLED
SCHEDULED, ATTENDED = SessionStatusChoices.SCHEDULED, SessionStatusChoices.ATTENDED
# Half an hour into the evening slot (19:30-20:30 IST): a Diagnostic time that overlaps it.
LATE = time(20, 0)
DUBAI = ZoneInfo('Asia/Dubai')
EVENING_LABEL = 'Demo · 28 Oct 2026, 19:30 IST'


def ist(at, day=DAY):
    return datetime.combine(day, at, tzinfo=BOOKING_TIMEZONE)


def tutor(username, **extra):
    return account(username, role='TUTOR', **extra)


def scheduled_class(teacher, starts_at, minutes=60, status=SCHEDULED, code='EDP90001'):
    """A one-to-one class of ``teacher``'s, for a student of their own."""
    student = Student.objects.create(
        profile=account(f'student_{code.lower()}', role='STUDENT'), student_code=code,
        full_name=f'Student {code}', tutor=teacher,
    )
    return Session.objects.create(
        student=student, tutor=teacher, title='Maths', status=status,
        start_time=starts_at, end_time=starts_at + timedelta(minutes=minutes),
    )


class AssignmentTestCase(TestCase):
    def setUp(self):
        schedule()
        SlotTime.objects.create(booking_type=DIAGNOSTIC, start_time=LATE)
        self.admin = account('admin_one', role='ADMIN')
        self.tutor = tutor('tutor_one')
        # A Demo on 28 Oct 2026, 19:30-20:30 IST; NOW is the day before.
        self.booking, _ = book(student='Riya')
        self.phones = iter(f'05099900{n:02d}' for n in range(50))

    def another(self, student, **kwargs):
        """Another child's booking, on its own phone number (the per-phone daily limit stays out of the way)."""
        booking, _ = book(student=student, phone=next(self.phones), **kwargs)
        return booking

    def assign(self, booking=None, who=None, now=NOW, actor=None):
        return assign_tutor(booking or self.booking, who or self.tutor, actor=actor or self.admin, now=now)

    def logs(self, action='booking.assign_tutor'):
        return ActivityLog.objects.filter(action=action)

    def assertUnassigned(self, booking):
        booking.refresh_from_db()
        self.assertEqual((booking.assigned_tutor, booking.tutor_assigned_at, booking.tutor_assigned_by), (None, None, None))


class AssignTests(AssignmentTestCase):
    def test_a_booking_starts_unassigned(self):
        self.assertUnassigned(self.booking)

    def test_an_active_tutor_is_assigned(self):
        booking, changed = self.assign()
        self.assertTrue(changed)
        booking.refresh_from_db()
        self.assertEqual((booking.assigned_tutor, booking.tutor_assigned_by), (self.tutor, self.admin))
        self.assertIsNotNone(booking.tutor_assigned_at)
        self.assertEqual(booking.status, BOOKED)
        self.assertEqual(self.logs().count(), 1)

    def test_only_an_active_tutor_account_is_assigned(self):
        refused = [
            tutor('tutor_inactive', is_active=False),
            tutor('tutor_deactivated', is_active=False, deactivated_at=timezone.now()),
            # Deactivated, though is_active was left set: still not assignable.
            tutor('tutor_half_deactivated', deactivated_at=timezone.now()),
            account('mentor_one', role='MENTOR'),
            account('admin_two', role='ADMIN'),
            account('bde_one', role='BDE'),
            account('sales_one', role='SALES_TL'),
            account('student_one', role='STUDENT'),
        ]
        for who in refused:
            with self.subTest(who=who.username), self.assertRaises(TutorNotAssignable):
                self.assign(who=who)
        self.assertUnassigned(self.booking)
        self.assertFalse(self.logs().exists())

    def test_a_cancelled_booking_takes_no_tutor(self):
        cancel_booking(self.booking, actor=self.admin, reason='Parent cancelled')
        with self.assertRaises(BookingCancelled):
            self.assign()
        self.assertUnassigned(self.booking)

    def test_a_slot_that_has_started_takes_no_tutor(self):
        starts_at = self.booking.slot.starts_at
        for moment in (starts_at, starts_at + timedelta(minutes=30), starts_at + timedelta(days=1)):
            with self.subTest(now=moment), self.assertRaises(SlotStarted):
                self.assign(now=moment)
        self.assertUnassigned(self.booking)
        self.assertTrue(self.assign(now=starts_at - timedelta(minutes=1))[1])


class ConflictTests(AssignmentTestCase):
    def test_an_overlapping_scheduled_class_blocks_the_tutor(self):
        overlapping = {
            'starts half an hour before': (ist(time(19, 0)), 60),
            'inside the slot': (ist(time(19, 45)), 30),
            'covers the slot': (ist(time(19, 0)), 120),
            'starts half an hour in': (ist(LATE), 60),
            # 18:00 in Dubai is 19:30 in India: the same moment as the slot.
            'booked in Dubai time': (datetime.combine(DAY, time(18, 0), tzinfo=DUBAI), 60),
        }
        for index, (name, (starts_at, minutes)) in enumerate(overlapping.items()):
            with self.subTest(name):
                session = scheduled_class(self.tutor, starts_at, minutes, code=f'EDP9000{index}')
                with self.assertRaises(TutorUnavailable) as caught:
                    self.assign()
                self.assertEqual((caught.exception.conflict.kind, caught.exception.conflict.id), (CONFLICT_SESSION, session.id))
                session.delete()
        self.assertUnassigned(self.booking)

    def test_classes_that_do_not_overlap_leave_the_tutor_free(self):
        # Touching windows do not overlap, as in sessions.services.find_conflict.
        scheduled_class(self.tutor, ist(time(18, 30)), code='EDP90001')
        scheduled_class(self.tutor, ist(time(20, 30)), code='EDP90002')
        # Attended and cancelled classes block nothing.
        scheduled_class(self.tutor, ist(EVENING), status=ATTENDED, code='EDP90003')
        scheduled_class(self.tutor, ist(EVENING), status=SessionStatusChoices.CANCELLED, code='EDP90004')
        # 19:30 in Dubai is 21:00 in India, after the slot.
        scheduled_class(self.tutor, datetime.combine(DAY, EVENING, tzinfo=DUBAI), code='EDP90005')
        # Another tutor's class, and this tutor's class the next evening.
        scheduled_class(tutor('tutor_other'), ist(EVENING), code='EDP90006')
        scheduled_class(self.tutor, ist(EVENING, DAY + timedelta(days=1)), code='EDP90007')
        self.assertIsNone(find_tutor_conflict(self.tutor, self.booking.slot.starts_at, self.booking.slot.ends_at))
        self.assertTrue(self.assign()[1])

    def test_an_overlapping_live_booking_blocks_the_tutor(self):
        # Diagnostic slots are separate slot rows, but a tutor teaching one
        # cannot teach a Demo at the same time -- or half an hour into it.
        for name, at in (('same time', EVENING), ('half an hour in', LATE)):
            with self.subTest(name):
                other = self.another(f'Child {name}', booking_type=DIAGNOSTIC, at=at)
                self.assign(booking=other)
                with self.assertRaises(TutorUnavailable) as caught:
                    self.assign()
                self.assertEqual((caught.exception.conflict.kind, caught.exception.conflict.id), (CONFLICT_BOOKING, other.id))
                unassign_tutor(other, actor=self.admin, now=NOW)
        self.assertUnassigned(self.booking)

    def test_one_tutor_never_takes_two_bookings_in_one_slot(self):
        second = self.another('Ali')
        self.assertEqual(second.slot_id, self.booking.slot_id)
        self.assign()
        with self.assertRaises(TutorUnavailable) as caught:
            self.assign(booking=second)
        self.assertEqual((caught.exception.conflict.kind, caught.exception.conflict.id), (CONFLICT_BOOKING, self.booking.id))
        # The slot still has a free seat; the tutor is still taken.
        self.assertEqual(Booking.objects.filter(slot=self.booking.slot, status=BOOKED).count(), 2)
        self.assertUnassigned(second)

    def test_each_booking_in_a_slot_takes_its_own_tutor(self):
        bookings = [self.booking, self.another('Ali'), self.another('Sara')]
        tutors = [self.tutor, tutor('tutor_two'), tutor('tutor_three')]
        for booking, who in zip(bookings, tutors):
            self.assertTrue(self.assign(booking=booking, who=who)[1])
        self.assertEqual(
            sorted(Booking.objects.filter(slot=self.booking.slot).values_list('assigned_tutor__username', flat=True)),
            ['tutor_one', 'tutor_three', 'tutor_two'],
        )

    def test_bookings_that_do_not_overlap_leave_the_tutor_free(self):
        self.assign(booking=self.another('Morning child', at=MORNING))
        cancelled = self.another('Cancelled child', booking_type=DIAGNOSTIC)
        self.assign(booking=cancelled)
        cancel_booking(cancelled, actor=self.admin)
        self.assertTrue(self.assign()[1])


class ChangeTests(AssignmentTestCase):
    def test_the_same_tutor_again_changes_nothing(self):
        first, _ = self.assign()
        booking, changed = self.assign(actor=account('admin_two', role='ADMIN'))
        self.assertFalse(changed)
        booking.refresh_from_db()
        self.assertEqual((booking.tutor_assigned_at, booking.tutor_assigned_by), (first.tutor_assigned_at, self.admin))
        self.assertEqual(self.logs().count(), 1)

    def test_reassigning_checks_the_new_tutor_and_frees_the_old_one(self):
        self.assign()
        busy = tutor('tutor_busy')
        scheduled_class(busy, ist(EVENING))
        with self.assertRaises(TutorUnavailable):
            self.assign(who=busy)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.assigned_tutor, self.tutor)

        second, other_admin = tutor('tutor_two'), account('admin_two', role='ADMIN')
        booking, changed = self.assign(who=second, actor=other_admin)
        self.assertTrue(changed)
        booking.refresh_from_db()
        self.assertEqual((booking.assigned_tutor, booking.tutor_assigned_by), (second, other_admin))
        self.assertTrue(self.logs().filter(context__old_tutor_id=str(self.tutor.pk), context__new_tutor_id=str(second.pk)).exists())
        # The first tutor is free for this slot again.
        self.assertTrue(self.assign(booking=self.another('Ali'))[1])

    def test_unassigning_clears_the_assignment(self):
        self.assign()
        booking, changed = unassign_tutor(self.booking, actor=self.admin, now=NOW)
        self.assertTrue(changed)
        self.assertUnassigned(booking)
        entry = self.logs('booking.unassign_tutor').get()
        self.assertEqual((entry.context['old_tutor_id'], entry.context['new_tutor_id']), (str(self.tutor.pk), None))

        self.assertFalse(unassign_tutor(self.booking, actor=self.admin, now=NOW)[1])
        self.assertEqual(self.logs('booking.unassign_tutor').count(), 1)
        # The tutor is free for this slot again.
        self.assertTrue(self.assign(booking=self.another('Ali'))[1])

    def test_unassigning_follows_the_assignment_rules(self):
        self.assign()
        with self.assertRaises(SlotStarted):
            unassign_tutor(self.booking, actor=self.admin, now=self.booking.slot.starts_at)
        cancel_booking(self.booking, actor=self.admin)
        with self.assertRaises(BookingCancelled):
            unassign_tutor(self.booking, actor=self.admin, now=NOW)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.assigned_tutor, self.tutor)

    def test_cancelling_keeps_the_tutor_as_history(self):
        assigned, _ = self.assign()
        cancel_booking(self.booking, actor=self.admin, reason='Parent cancelled')
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, CANCELLED)
        self.assertEqual(
            (self.booking.assigned_tutor, self.booking.tutor_assigned_at, self.booking.tutor_assigned_by),
            (self.tutor, assigned.tutor_assigned_at, self.admin),
        )
        with self.assertRaises(BookingCancelled):
            self.assign(who=tutor('tutor_two'))
        # Kept as a record, it no longer holds the tutor's time.
        self.assertTrue(self.assign(booking=self.another('Ali'))[1])


class LogTests(AssignmentTestCase):
    def test_the_activity_log_holds_ids_only(self):
        second = tutor('tutor_two')
        self.assign()
        self.assign(who=second)
        unassign_tutor(self.booking, actor=self.admin, now=NOW)

        entries = ActivityLog.objects.filter(action__in=('booking.assign_tutor', 'booking.unassign_tutor'))
        moves = {(entry.action, entry.context['old_tutor_id'], entry.context['new_tutor_id']) for entry in entries}
        first_id, second_id = str(self.tutor.pk), str(second.pk)
        self.assertEqual(moves, {
            ('booking.assign_tutor', None, first_id),
            ('booking.assign_tutor', first_id, second_id),
            ('booking.unassign_tutor', second_id, None),
        })
        for entry in entries:
            self.assertEqual((entry.entity_type, entry.entity_id, entry.entity_label), ('booking', str(self.booking.id), EVENING_LABEL))
            self.assertEqual(entry.actor, self.admin)
            self.assertEqual(entry.changes, {})
            self.assertEqual(entry.context, {
                'booking_type': 'DEMO',
                'slot_starts_at': self.booking.slot.starts_at.isoformat(),
                'lead_id': str(self.booking.lead_id),
                'old_tutor_id': entry.context['old_tutor_id'],
                'new_tutor_id': entry.context['new_tutor_id'],
            })
            recorded = json.dumps([entry.entity_label, entry.changes, entry.context])
            for private in ('Riya', 'Asha', '501234567', 'Delhi', self.tutor.full_name, self.tutor.email, second.full_name, second.email):
                self.assertNotIn(private, recorded)


class ConstraintTests(AssignmentTestCase):
    def assertRefused(self, **fields):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.filter(pk=self.booking.pk).update(**fields)

    def test_a_tutor_comes_with_the_moment_it_was_assigned(self):
        now = timezone.now()
        self.assertRefused(assigned_tutor=self.tutor)
        self.assertRefused(tutor_assigned_at=now)
        self.assertRefused(tutor_assigned_by=self.admin)
        self.assertRefused(tutor_assigned_at=now, tutor_assigned_by=self.admin)
        self.assertRefused(assigned_tutor=self.tutor, tutor_assigned_by=self.admin)
        # Who assigned them may be unknown; the tutor and the moment may not.
        Booking.objects.filter(pk=self.booking.pk).update(assigned_tutor=self.tutor, tutor_assigned_at=now)

    def test_an_assigned_tutor_is_protected_and_the_assigner_is_not(self):
        self.assign()
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.tutor.delete()
        self.admin.delete()
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.assigned_tutor, self.tutor)
        self.assertIsNotNone(self.booking.tutor_assigned_at)
        self.assertIsNone(self.booking.tutor_assigned_by)


@skipUnless(connection.vendor == 'postgresql', 'reads the PostgreSQL catalogue')
class MigrationReversalTests(TransactionTestCase):
    """0004 reverses to 0003 with bookings in the table and applies again, leaving every booking unassigned."""

    ADDED_COLUMNS = {'assigned_tutor_id', 'tutor_assigned_at', 'tutor_assigned_by_id'}

    def catalogue(self, query):
        with connection.cursor() as cursor:
            cursor.execute(query)
            return {row[0] for row in cursor.fetchall()}

    def schema(self):
        return (
            self.catalogue("SELECT column_name FROM information_schema.columns WHERE table_name = 'bookings'"),
            self.catalogue("SELECT conname FROM pg_constraint WHERE conrelid = 'bookings'::regclass"),
            self.catalogue("SELECT indexname FROM pg_indexes WHERE tablename = 'bookings'"),
        )

    def migrate(self, target):
        MigrationExecutor(connection).migrate([('bookings', target)])

    def test_reverse_and_reapply(self):
        schedule()
        unassigned, _ = book(student='Riya')
        assigned, _ = book(student='Ali', phone='0509876543')
        assign_tutor(assigned, tutor('tutor_one'), actor=account('admin_one', role='ADMIN'), now=NOW)

        columns, constraints, indexes = self.schema()
        self.assertLessEqual(self.ADDED_COLUMNS, columns)
        self.assertIn('bookings_tutor_assignment_fields', constraints)
        self.assertIn('bookings_tutor_slot_idx', indexes)
        try:
            self.migrate('0003_lead_source')
            columns, constraints, indexes = self.schema()
            self.assertFalse(self.ADDED_COLUMNS & columns)
            self.assertNotIn('bookings_tutor_assignment_fields', constraints)
            self.assertNotIn('bookings_tutor_slot_idx', indexes)
            self.assertEqual(self.catalogue('SELECT count(*) FROM bookings'), {2})
        finally:
            self.migrate('0004_booking_tutor_assignment')  # back to the leaf, whatever happened

        columns, constraints, indexes = self.schema()
        self.assertLessEqual(self.ADDED_COLUMNS, columns)
        self.assertIn('bookings_tutor_assignment_fields', constraints)
        self.assertIn('bookings_tutor_slot_idx', indexes)
        # The bookings that were there before 0004 applied are unassigned.
        self.assertEqual(
            set(Booking.objects.values_list('id', 'assigned_tutor', 'tutor_assigned_at', 'tutor_assigned_by')),
            {(unassigned.id, None, None, None), (assigned.id, None, None, None)},
        )


@skipUnless(connection.vendor == 'postgresql', 'the locks need PostgreSQL')
class ConcurrentAssignmentTests(TransactionTestCase):
    """Real threads, each with its own database connection, starting together."""

    def setUp(self):
        schedule()
        self.admin = account('admin_one', role='ADMIN')
        self.tutor = tutor('tutor_one')
        self.booking, _ = book(student='Riya')

    def race(self, calls):
        barrier = threading.Barrier(len(calls))
        outcomes = [None] * len(calls)

        def run(index, call):
            try:
                barrier.wait(timeout=10)
                outcomes[index] = call()
            except TutorUnavailable:
                outcomes[index] = 'unavailable'
            except BookingCancelled:
                outcomes[index] = 'cancelled'
            except Exception as exc:  # reported in the assertion, not lost in the thread
                outcomes[index] = f'error: {exc!r}'
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return outcomes

    def assigner(self, booking):
        def call():
            assign_tutor(booking, self.tutor, actor=self.admin, now=NOW)
            return 'assigned'
        return call

    def slowed_conflict_check(self):
        """find_tutor_conflict made slow, so that without the locks both racers would pass it before either writes."""
        check = booking_service.find_tutor_conflict

        def slow(*args, **kwargs):
            found = check(*args, **kwargs)
            clock.sleep(0.3)
            return found

        return mock.patch.object(booking_service, 'find_tutor_conflict', slow)

    def test_two_bookings_in_one_slot_racing_for_one_tutor(self):
        second, _ = book(student='Ali', phone='0509876543')
        with self.slowed_conflict_check():
            outcomes = self.race([self.assigner(self.booking), self.assigner(second)])
        self.assertEqual(sorted(outcomes), ['assigned', 'unavailable'], outcomes)
        self.assertEqual(Booking.objects.filter(assigned_tutor=self.tutor).count(), 1)

    def test_two_overlapping_slots_racing_for_one_tutor(self):
        # Separate slot rows (Demo and Diagnostic at 19:30): only the tutor's locks keep them apart.
        diagnostic, _ = book(student='Ali', phone='0509876543', booking_type=DIAGNOSTIC)
        self.assertNotEqual(diagnostic.slot_id, self.booking.slot_id)
        with self.slowed_conflict_check():
            outcomes = self.race([self.assigner(self.booking), self.assigner(diagnostic)])
        self.assertEqual(sorted(outcomes), ['assigned', 'unavailable'], outcomes)
        self.assertEqual(Booking.objects.filter(assigned_tutor=self.tutor).count(), 1)

    def test_an_assignment_waits_for_a_class_being_scheduled(self):
        # A class for the tutor is being booked (sessions take lock_scheduling,
        # check, then insert). The assignment must wait for it and then see it.
        student = Student.objects.create(
            profile=account('student_edp90001', role='STUDENT'), student_code='EDP90001', full_name='Student EDP90001',
            tutor=self.tutor,
        )
        locked, outcome = threading.Event(), []

        def schedule_a_class():
            try:
                with transaction.atomic():
                    lock_scheduling(student.id, self.tutor.id)
                    locked.set()
                    clock.sleep(0.5)  # the assignment starts meanwhile and must queue
                    Session.objects.create(
                        student=student, tutor=self.tutor, title='Maths', status=SCHEDULED,
                        start_time=ist(time(19, 0)), end_time=ist(LATE),
                    )
            finally:
                connection.close()

        def assign():
            try:
                outcome.append(self.assigner(self.booking)())
            except TutorUnavailable as exc:
                outcome.append(exc.conflict.kind)
            except Exception as exc:  # reported in the assertion, not lost in the thread
                outcome.append(f'error: {exc!r}')
            finally:
                connection.close()

        scheduler = threading.Thread(target=schedule_a_class)
        scheduler.start()
        self.assertTrue(locked.wait(timeout=10))
        assigner = threading.Thread(target=assign)
        assigner.start()
        scheduler.join(timeout=15)
        assigner.join(timeout=15)
        self.assertEqual(outcome, [CONFLICT_SESSION])
        self.assertFalse(Booking.objects.filter(assigned_tutor=self.tutor).exists())

    def test_an_assignment_racing_a_cancellation(self):
        def cancel():
            cancel_booking(self.booking, actor=self.admin, reason='Parent cancelled')
            return 'cancel'

        outcomes = self.race([self.assigner(self.booking), cancel])
        self.assertIn(outcomes, (['assigned', 'cancel'], ['cancelled', 'cancel']), outcomes)
        booking = Booking.objects.get(pk=self.booking.pk)
        # Cancelled either way; it keeps the tutor only if the assignment came first.
        self.assertEqual(booking.status, CANCELLED)
        if outcomes[0] == 'assigned':
            self.assertEqual((booking.assigned_tutor, booking.tutor_assigned_by), (self.tutor, self.admin))
        else:
            self.assertEqual((booking.assigned_tutor, booking.tutor_assigned_at), (None, None))
