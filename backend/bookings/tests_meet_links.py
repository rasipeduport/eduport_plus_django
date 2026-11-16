"""
Each booking's own copy of its tutor's Google Meet link (bookings.booking_service):
copied when a tutor is assigned, the new tutor's on a reassignment and on a
reschedule that carries the tutor over, dropped when the tutor is unassigned,
and kept in step with the tutor's link only while the booking is live --
booked, its slot not yet ended. Once its slot has ended, or it is completed,
cancelled or moved, it keeps the link it had. A tutor without a link gives a
booking none: nothing is ever made up. The Admin, the lead's owner BDE and the
tutor read it; the history and the activity log never hold it.
"""
import json
import threading
import time as clock
from datetime import time, timedelta

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from activity.models import ActivityLog

from . import booking_service
from .booking_service import (
    NotATutor,
    assign_tutor,
    cancel_booking,
    reschedule_booking,
    set_tutor_meet_link,
    unassign_tutor,
)
from .models import (
    BookingEvent,
    BookingEventKind,
    BookingSlot,
    BookingStatus,
    CancelReason,
    DemoBooking,
    DiagnosticBooking,
    Lead,
    ReferralStatus,
    RescheduleReason,
)
from .scheduling import BOOKING_TIMEZONE, slot_instants
from .tests_booking import DAY, EVENING, NOW, account, book, schedule

LINK = 'https://meet.google.com/abc-defg-hij'
OTHER_LINK = 'https://meet.google.com/xyz-wxyz-xyz'
NEW_LINK = 'https://meet.google.com/kln-opqr-stu'
BOOKED, COMPLETED, CANCELLED = BookingStatus.BOOKED, BookingStatus.COMPLETED, BookingStatus.CANCELLED


def tutor(username, link=None, **extra):
    return account(username, role='TUTOR', tutor_meet_link=link, **extra)


_phones = iter(range(1, 10_000))


def booking_at(teacher, local_date, at, status=BOOKED, link=None, model=DemoBooking, owner=None):
    """A booking written straight to its table, at ``local_date`` ``at`` IST, assigned to ``teacher`` with ``link``."""
    starts_at, ends_at = slot_instants(local_date, at)
    slot, _ = BookingSlot.objects.get_or_create(
        booking_type=model.BOOKING_TYPE, local_date=local_date, local_time=at,
        defaults={'starts_at': starts_at, 'ends_at': ends_at},
    )
    phone = f'5098{next(_phones):05d}'
    lead = Lead.objects.create(
        parent_name='Asha Nair', phone_dial_code='+971', phone_number=phone, phone_key=f'+971{phone}',
        student_name=f'Child {phone}', student_name_key=f'child {phone}', school_name='School', grade='Class 8',
        syllabus='CBSE', owner_bde=owner, owner_assigned_at=timezone.now() if owner else None,
    )
    stamp = timezone.now()
    return model.objects.create(
        lead=lead, slot=slot, seat=1, status=status, referral_status=ReferralStatus.NO_REF,
        assigned_tutor=teacher, tutor_assigned_at=stamp if teacher else None, tutor_meet_link=link,
        completed_at=stamp if status == COMPLETED else None,
        cancelled_at=stamp if status == CANCELLED else None,
        cancel_reason_code=CancelReason.OTHER if status == CANCELLED else '',
    )


def link_of(booking):
    return type(booking).objects.values_list('tutor_meet_link', flat=True).get(pk=booking.pk)


class MeetLinkTestCase(TestCase):
    def setUp(self):
        schedule()
        self.admin = account('admin_one', role='ADMIN')
        self.tutor_a = tutor('tutor_anu', LINK)
        self.tutor_b = tutor('tutor_bala', OTHER_LINK)
        self.tutor_c = tutor('tutor_chitra')  # no link configured
        # A Demo on 28 Oct 2026, 19:30-20:30 IST; NOW is the day before.
        self.booking, _ = book(student='Riya')

    def assign(self, who, booking=None):
        return assign_tutor(booking or self.booking, who, actor=self.admin, now=NOW)


class AssignmentTests(MeetLinkTestCase):
    def test_a_booking_starts_without_a_link(self):
        self.assertIsNone(link_of(self.booking))

    def test_assigning_copies_the_tutors_link(self):
        self.assign(self.tutor_a)
        self.assertEqual(link_of(self.booking), LINK)

    def test_a_tutor_without_a_link_gives_the_booking_none(self):
        self.assign(self.tutor_c)
        self.assertIsNone(link_of(self.booking))

    def test_reassigning_takes_the_new_tutors_link(self):
        self.assign(self.tutor_a)
        self.assign(self.tutor_b)
        self.assertEqual(link_of(self.booking), OTHER_LINK)
        self.assign(self.tutor_c)
        self.assertIsNone(link_of(self.booking))

    def test_unassigning_drops_it(self):
        self.assign(self.tutor_a)
        unassign_tutor(self.booking, actor=self.admin, now=NOW)
        self.assertIsNone(link_of(self.booking))

    def test_a_cancelled_booking_keeps_the_link_it_had(self):
        self.assign(self.tutor_a)
        cancel_booking(self.booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        set_tutor_meet_link(self.tutor_a, NEW_LINK, actor=self.admin, now=NOW)
        self.assertEqual(link_of(self.booking), LINK)

    def test_a_reschedule_gives_the_new_booking_the_tutors_link_and_the_old_keeps_its_own(self):
        self.assign(self.tutor_a)
        result = reschedule_booking(
            self.booking, DAY + timedelta(days=1), EVENING, reason_code=RescheduleReason.PARENT_REQUEST,
            actor=self.admin, now=NOW,
        )
        self.assertTrue(result.tutor_carried_over)
        self.assertEqual((link_of(result.booking), link_of(result.previous)), (LINK, LINK))
        set_tutor_meet_link(self.tutor_a, NEW_LINK, actor=self.admin, now=NOW)
        self.assertEqual((link_of(result.booking), link_of(result.previous)), (NEW_LINK, LINK))

    def test_a_reschedule_without_the_tutor_has_no_link(self):
        self.assign(self.tutor_a)
        type(self.tutor_a).objects.filter(pk=self.tutor_a.pk).update(is_active=False, deactivated_at=NOW)
        result = reschedule_booking(
            self.booking, DAY + timedelta(days=1), EVENING, reason_code=RescheduleReason.PARENT_REQUEST,
            actor=self.admin, now=NOW,
        )
        self.assertFalse(result.tutor_carried_over)
        self.assertIsNone(link_of(result.booking))
        self.assertEqual(link_of(result.previous), LINK)


class LinkChangeTests(MeetLinkTestCase):
    def setUp(self):
        super().setUp()
        self.assign(self.tutor_a)
        yesterday, today = DAY - timedelta(days=2), DAY - timedelta(days=1)
        # Started half an hour before NOW (12:00 IST) and not ended yet: still live.
        self.in_progress = booking_at(self.tutor_a, today, time(11, 30), link=LINK)
        self.ended = booking_at(self.tutor_a, yesterday, EVENING, link=LINK)  # booked, report due
        self.completed = booking_at(self.tutor_a, yesterday, time(10, 0), status=COMPLETED, link=LINK)
        self.cancelled = booking_at(self.tutor_a, DAY + timedelta(days=2), EVENING, status=CANCELLED, link=LINK)
        self.diagnostic = booking_at(self.tutor_a, DAY + timedelta(days=1), EVENING, link=LINK, model=DiagnosticBooking)
        self.others = booking_at(self.tutor_b, DAY + timedelta(days=1), EVENING, link=OTHER_LINK)

    def change(self, link, who=None):
        return set_tutor_meet_link(who or self.tutor_a, link, actor=self.admin, now=NOW)

    def events(self):
        return BookingEvent.objects.filter(kind=BookingEventKind.MEET_LINK_UPDATED)

    def test_a_changed_link_reaches_the_live_bookings_only(self):
        account_, changed, bookings = self.change(NEW_LINK)
        self.assertTrue(changed)
        self.assertEqual(account_.tutor_meet_link, NEW_LINK)
        self.assertEqual([b.pk for b in bookings], [self.in_progress.pk, self.booking.pk, self.diagnostic.pk])
        for live in (self.booking, self.in_progress, self.diagnostic):
            self.assertEqual(link_of(live), NEW_LINK)
        for kept in (self.ended, self.completed, self.cancelled):
            self.assertEqual(link_of(kept), LINK)
        self.assertEqual(link_of(self.others), OTHER_LINK)

    def test_each_booking_changed_records_it_without_the_link(self):
        self.change(NEW_LINK)
        events = list(self.events())
        self.assertEqual(len(events), 3)
        self.assertEqual({(e.data['has_meet_link'], e.actor_id) for e in events}, {(True, self.admin.pk)})
        self.assertEqual({set(e.data) == {'has_meet_link'} for e in events}, {True})
        self.change(None)
        self.assertEqual(self.events().filter(data__has_meet_link=False).count(), 3)
        written = json.dumps([e.data for e in BookingEvent.objects.all()])
        self.assertNotIn('meet.google.com', written)

    def test_removing_the_link_leaves_live_bookings_without_one(self):
        self.change(None)
        self.assertIsNone(link_of(self.booking))
        self.assertEqual(link_of(self.ended), LINK)

    def test_a_missing_link_once_set_fills_the_live_bookings(self):
        self.assign(self.tutor_c, booking=self.diagnostic)
        self.assertIsNone(link_of(self.diagnostic))
        self.change(NEW_LINK, who=self.tutor_c)
        self.assertEqual(link_of(self.diagnostic), NEW_LINK)

    def test_the_same_link_again_changes_nothing(self):
        _account, changed, bookings = self.change(LINK)
        self.assertEqual((changed, bookings), (False, []))
        self.assertFalse(self.events().exists())

    def test_only_a_tutor_has_a_link(self):
        for other in (self.admin, account('mentor_one', role='MENTOR')):
            with self.subTest(role=other.role), self.assertRaises(NotATutor):
                self.change(LINK, who=other)

    def test_the_activity_log_never_holds_the_link(self):
        self.change(NEW_LINK)
        self.assign(self.tutor_b)
        written = json.dumps([[e.changes, e.context] for e in ActivityLog.objects.all()])
        self.assertNotIn('meet.google.com', written)


class DatabaseTests(MeetLinkTestCase):
    def test_a_booking_has_no_link_without_a_tutor(self):
        for model in (DemoBooking, DiagnosticBooking):
            row = booking_at(None, DAY + timedelta(days=3), EVENING, model=model)
            with self.subTest(model=model.__name__), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.filter(pk=row.pk).update(tutor_meet_link=LINK)

    def test_a_booking_holds_only_a_google_meet_link(self):
        self.assign(self.tutor_a)
        for value in ('https://zoom.us/j/1', 'meet.google.com/abc-defg-hij', ''):
            with self.subTest(value=value), self.assertRaises(IntegrityError), transaction.atomic():
                DemoBooking.objects.filter(pk=self.booking.pk).update(tutor_meet_link=value)


def days_ahead(days):
    return timezone.now().astimezone(BOOKING_TIMEZONE).date() + timedelta(days=days)


class ReadTests(TestCase):
    """What each caller is shown, by the clock: these bookings are two days ahead of now."""

    def setUp(self):
        self.admin = account('admin_one', role='ADMIN')
        self.bde = account('bde_one', role='BDE')
        self.tutor = tutor('tutor_anu', LINK)
        self.no_link_tutor = tutor('tutor_bala')
        self.with_link = booking_at(None, days_ahead(2), EVENING, owner=self.bde)
        assign_tutor(self.with_link, self.tutor, actor=self.admin)
        self.lead = self.with_link.lead
        self.client = APIClient()

    def get(self, user, path):
        self.client.force_authenticate(user)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_the_admin_sees_the_bookings_link(self):
        detail = self.get(self.admin, f'/api/bookings/demo/{self.with_link.pk}/')
        self.assertEqual(detail['tutor_meet_link'], LINK)

    def test_the_tutor_sees_the_link_of_each_booking_they_teach(self):
        rows = self.get(self.tutor, '/api/tutor/bookings/')['results']
        self.assertEqual([row['tutor_meet_link'] for row in rows], [LINK])
        detail = self.get(self.tutor, f'/api/tutor/bookings/demo/{self.with_link.pk}/')
        self.assertEqual(detail['tutor_meet_link'], LINK)

    def test_the_owner_bde_sees_who_teaches_it_and_where(self):
        # Two more bookings of the same child: one with no tutor yet, one whose tutor has no link.
        unassigned = booking_at(None, days_ahead(3), EVENING)
        DemoBooking.objects.filter(pk=unassigned.pk).update(lead=self.lead)
        no_link = booking_at(None, days_ahead(4), EVENING)
        DemoBooking.objects.filter(pk=no_link.pk).update(lead=self.lead)
        assign_tutor(no_link, self.no_link_tutor, actor=self.admin)

        rows = {row['id']: row for row in self.get(self.bde, f'/api/bde/enquiries/{self.lead.pk}/')['bookings']}
        self.assertEqual(
            (rows[str(self.with_link.pk)]['tutor'], rows[str(self.with_link.pk)]['tutor_meet_link']),
            ({'full_name': 'Tutor Anu'}, LINK),
        )
        self.assertEqual((rows[str(unassigned.pk)]['tutor'], rows[str(unassigned.pk)]['tutor_meet_link']), (None, None))
        self.assertEqual(
            (rows[str(no_link.pk)]['tutor'], rows[str(no_link.pk)]['tutor_meet_link']), ({'full_name': 'Tutor Bala'}, None),
        )

    def test_a_cancelled_booking_shows_the_bde_no_tutor_or_link(self):
        cancel_booking(self.with_link, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin)
        row = self.get(self.bde, f'/api/bde/enquiries/{self.lead.pk}/')['bookings'][0]
        self.assertEqual((row['status'], row['tutor'], row['tutor_meet_link']), ('CANCELLED', None, None))

    def test_the_bde_is_shown_the_tutors_name_and_nothing_else_of_them(self):
        body = json.dumps(self.get(self.bde, f'/api/bde/enquiries/{self.lead.pk}/'))
        self.assertNotIn(str(self.tutor.pk), body)
        self.assertNotIn(self.tutor.email, body)


class ConcurrencyTests(TransactionTestCase):
    """Real threads, each with its own database connection, starting together."""

    def setUp(self):
        schedule()
        self.admin = account('admin_one', role='ADMIN')
        self.tutor_a = tutor('tutor_anu', LINK)
        self.tutor_b = tutor('tutor_bala', OTHER_LINK)
        self.booking, _ = book(student='Riya')

    def race(self, *calls):
        barrier = threading.Barrier(len(calls))
        outcomes = [None] * len(calls)

        def run(index, call):
            try:
                barrier.wait(timeout=10)
                call()
                outcomes[index] = 'done'
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

    def slowing(self, name):
        """booking_service.<name> made slow for the test, so the assignment holds its locks while the other racer arrives."""
        original = getattr(booking_service, name)

        def slow(*args, **kwargs):
            found = original(*args, **kwargs)
            clock.sleep(0.4)
            return found
        setattr(booking_service, name, slow)
        self.addCleanup(setattr, booking_service, name, original)

    def assigner(self, who):
        return lambda: assign_tutor(self.booking, who, actor=self.admin, now=NOW)

    def link_change(self, delay=0.1):
        """The tutor's link changed a moment after the race starts, while the assignment holds its locks."""
        def call():
            clock.sleep(delay)
            set_tutor_meet_link(self.tutor_a, NEW_LINK, actor=self.admin, now=NOW)
        return call

    def test_a_link_change_waits_for_an_assignment_then_reaches_its_booking(self):
        # The assignment holds the booking and the tutor's row through its
        # (slowed) conflict check. The link change finds no live booking of the
        # tutor's yet, waits for the tutor's row, and then must update the
        # booking the assignment has just given them.
        self.slowing('find_tutor_conflict')
        outcomes = self.race(self.assigner(self.tutor_a), self.link_change())
        self.assertEqual(outcomes, ['done', 'done'])
        self.assertEqual(link_of(self.booking), NEW_LINK)

    def test_an_assignment_after_a_link_change_copies_the_new_link(self):
        outcomes = self.race(self.link_change(delay=0), lambda: (clock.sleep(0.2), self.assigner(self.tutor_a)()))
        self.assertEqual(outcomes, ['done', 'done'])
        self.assertEqual(link_of(self.booking), NEW_LINK)

    def test_a_link_change_never_deadlocks_with_an_assignment_holding_the_booking(self):
        # The booking is the tutor's. Assigning them again holds the booking's
        # lock and only then asks for the tutor's row (slowed in between); the
        # link change, arriving meanwhile, must queue on the booking first, as
        # the assignment does, never take the tutor's row first -- or each would
        # wait for the other.
        assign_tutor(self.booking, self.tutor_a, actor=self.admin, now=NOW)
        self.slowing('_check_tutor_changeable')
        outcomes = self.race(self.assigner(self.tutor_a), self.link_change())
        self.assertEqual(outcomes, ['done', 'done'])
        self.assertEqual(link_of(self.booking), NEW_LINK)

    def test_a_reassignment_racing_the_old_tutors_link_change_ends_with_the_new_tutors_link(self):
        assign_tutor(self.booking, self.tutor_a, actor=self.admin, now=NOW)
        self.slowing('find_tutor_conflict')
        outcomes = self.race(self.assigner(self.tutor_b), self.link_change())
        self.assertEqual(outcomes, ['done', 'done'])
        self.booking.refresh_from_db()
        self.assertEqual((self.booking.assigned_tutor_id, self.booking.tutor_meet_link), (self.tutor_b.pk, OTHER_LINK))
