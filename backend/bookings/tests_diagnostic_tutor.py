"""
A Demo booked for a child whose Diagnostic is completed starts with that
Diagnostic's tutor (booking_service.diagnostic_for_demo / _diagnostic_tutor):
through a Demo invitation -- the invitation's own Diagnostic -- or on the Demo
page for the same enquiry -- the Diagnostic taught last. Only a completed
Diagnostic of the same lead hands its tutor on, and only to a tutor still
active and free for the whole slot; otherwise the Demo is booked unassigned,
as before, never refused. Nothing else changes: a Diagnostic still starts
unassigned, staff reassign and unassign as before, and the Admin's, the BDE's
and the tutor's views all read the one assignment.
"""
import threading
import time as clock
from datetime import date, datetime, timedelta
from unittest import mock, skipUnless

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import RoleChoices, User
from activity.models import ActivityLog
from reports.services import submit_report
from reports.tests_services import diagnostic_input

from . import booking_service
from .booking_service import (
    TutorUnavailable,
    assign_tutor,
    cancel_booking,
    create_booking,
    create_invited_demo_booking,
    reschedule_booking,
    unassign_tutor,
)
from .demo_invites import issue_invite
from .models import BookingEventKind, BookingStatus, CancelReason, DemoBooking, DiagnosticBooking, Lead, RescheduleReason
from .scheduling import BOOKING_TIMEZONE, indian_today
from .tests_assignment import scheduled_class
from .tests_booking import DEMO, DIAGNOSTIC, EVENING, MORNING, NOW, account, request, schedule, start
from .tests_demo_invites import AFTER, DEMO_DAY, SITE, DemoInviteTestCase, diagnostic_with_report

MEET_LINK = 'https://meet.google.com/abc-defg-hij'
# The day after DEMO_DAY: a second Diagnostic of the same child is taught on 29 Oct, and the Demo booked after it.
NEXT_DAY = date(2026, 10, 29)
LATER = datetime(2026, 10, 29, 12, 0, tzinfo=BOOKING_TIMEZONE)


class DiagnosticTutorTestCase(DemoInviteTestCase):
    def setUp(self):
        super().setUp()
        self.tutor = self.diagnostic.assigned_tutor
        self.other_tutor = account('tutor_other', role='TUTOR')

    def demo_page(self, student='Riya', phone='0501234567', day=DEMO_DAY, at=EVENING, now=AFTER):
        """A Demo booked on the Demo page: the same enquiry as the Diagnostic for the same phone and student."""
        return create_booking(request(student=student, phone=phone, booking_type=DEMO, day=day, at=at), now=now)[0]

    def invited(self, now=AFTER, **kwargs):
        """A Demo booked with an invitation sent from the Diagnostic (or ``diagnostic``)."""
        diagnostic = kwargs.pop('diagnostic', None)
        return self.book(self.invite(now=now, diagnostic=diagnostic)[0], now=now, **kwargs)[0]

    def later_diagnostic(self, tutor):
        """A second completed Diagnostic of the same child, taught on 29 Oct by ``tutor``."""
        return diagnostic_with_report(tutor=tutor, day=NEXT_DAY)

    def assertTaughtBy(self, booking, tutor):
        booking = DemoBooking.objects.get(pk=booking.pk)
        self.assertEqual((booking.assigned_tutor, booking.tutor_assigned_by), (tutor, None))
        self.assertIsNotNone(booking.tutor_assigned_at)

    def assertUnassigned(self, booking):
        booking = type(booking).objects.get(pk=booking.pk)
        self.assertEqual(
            (booking.status, booking.assigned_tutor, booking.tutor_assigned_at, booking.tutor_assigned_by,
             booking.tutor_meet_link),
            (BookingStatus.BOOKED, None, None, None, None),
        )
        self.assertFalse(booking.events.filter(kind=BookingEventKind.TUTOR_ASSIGNED).exists())

    def created_log(self, booking):
        return ActivityLog.objects.get(action='booking.create', entity_id=str(booking.pk))


class InvitedDemoTests(DiagnosticTutorTestCase):
    def test_an_invited_demo_is_taught_by_its_diagnostics_tutor(self):
        User.objects.filter(pk=self.tutor.pk).update(tutor_meet_link=MEET_LINK)
        booking = self.invited()
        self.assertTaughtBy(booking, self.tutor)
        # Their Meet link as it is now, as assign_tutor copies it.
        self.assertEqual(DemoBooking.objects.get(pk=booking.pk).tutor_meet_link, MEET_LINK)
        # Its history: booked by the parent, then the tutor assigned by the system from the Diagnostic -- ids only.
        self.assertEqual(
            [(event.kind, event.actor, event.data) for event in booking.events.all()][1:],
            [(BookingEventKind.TUTOR_ASSIGNED, None, {
                'old_tutor_id': None, 'new_tutor_id': str(self.tutor.pk), 'via': 'diagnostic',
                'diagnostic_booking_id': str(self.diagnostic.pk),
            })],
        )
        self.assertEqual(self.created_log(booking).context['tutor_id'], str(self.tutor.pk))
        # One entry for the booking: no separate assignment by anyone.
        self.assertFalse(ActivityLog.objects.filter(action='booking.assign_tutor', entity_id=str(booking.pk)).exists())

    def test_the_invitations_own_diagnostic_whichever_other_the_child_has(self):
        later = self.later_diagnostic(self.other_tutor)
        self.assertEqual(later.lead_id, self.lead.pk)
        # The invitation names the first Diagnostic: its tutor, not the one who taught last.
        booking = self.invited(now=LATER)
        self.assertTaughtBy(booking, self.tutor)
        self.assertEqual(booking.events.get(kind=BookingEventKind.TUTOR_ASSIGNED).data['diagnostic_booking_id'],
                         str(self.diagnostic.pk))


class DemoPageTests(DiagnosticTutorTestCase):
    def test_a_demo_booked_on_the_demo_page_for_the_same_enquiry(self):
        booking = self.demo_page()
        self.assertEqual(booking.lead_id, self.lead.pk)
        self.assertTaughtBy(booking, self.tutor)
        event = booking.events.get(kind=BookingEventKind.TUTOR_ASSIGNED)
        self.assertEqual((event.actor, event.data['via'], event.data['diagnostic_booking_id']),
                         (None, 'diagnostic', str(self.diagnostic.pk)))
        self.assertEqual(self.created_log(booking).context['tutor_id'], str(self.tutor.pk))

    def test_the_diagnostic_taught_last_when_there_are_several(self):
        later = self.later_diagnostic(self.other_tutor)
        booking = self.demo_page(now=LATER)
        self.assertTaughtBy(booking, self.other_tutor)
        self.assertEqual(booking.events.get(kind=BookingEventKind.TUTOR_ASSIGNED).data['diagnostic_booking_id'],
                         str(later.pk))

    def test_a_later_diagnostic_not_completed_hands_nothing_on(self):
        # After the completed one: a Diagnostic cancelled, then another booked and not yet taught, each with a tutor.
        cancelled = create_booking(request(student='Riya', booking_type=DIAGNOSTIC, day=NEXT_DAY, at=MORNING), now=NOW)[0]
        assign_tutor(cancelled, self.other_tutor, actor=self.admin, now=NOW)
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        pending = create_booking(request(student='Riya', booking_type=DIAGNOSTIC, day=date(2026, 10, 31), at=MORNING),
                                 now=NOW)[0]
        assign_tutor(pending, self.other_tutor, actor=self.admin, now=NOW)
        self.assertEqual({cancelled.lead_id, pending.lead_id}, {self.lead.pk})
        # The completed Diagnostic's tutor still teaches the Demo.
        booking = self.demo_page()
        self.assertTaughtBy(booking, self.tutor)
        self.assertEqual(booking.events.get(kind=BookingEventKind.TUTOR_ASSIGNED).data['diagnostic_booking_id'],
                         str(self.diagnostic.pk))

    def test_only_the_same_enquirys_diagnostic(self):
        # The same parent's other child is another enquiry, with no Diagnostic of their own.
        sibling = self.demo_page(student='Arjun')
        self.assertNotEqual(sibling.lead_id, self.lead.pk)
        self.assertUnassigned(sibling)
        # Another family altogether.
        self.assertUnassigned(self.demo_page(student='Sara', phone='0507000009'))

    def test_only_a_completed_diagnostic(self):
        # Booked and assigned, not yet taught: its tutor is not handed on.
        pending = create_booking(request(student='Kiran', phone='0507000001', booking_type=DIAGNOSTIC, day=NEXT_DAY,
                                         at=MORNING), now=NOW)[0]
        assign_tutor(pending, self.other_tutor, actor=self.admin, now=NOW)
        self.assertUnassigned(self.demo_page(student='Kiran', phone='0507000001'))
        # Cancelled: the Diagnostic keeps its tutor as history, and hands it to no Demo.
        cancelled = create_booking(request(student='Meera', phone='0507000002', booking_type=DIAGNOSTIC, day=NEXT_DAY,
                                           at=MORNING), now=NOW)[0]
        third = account('tutor_third', role='TUTOR')
        assign_tutor(cancelled, third, actor=self.admin, now=NOW)
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        self.assertEqual(DiagnosticBooking.objects.get(pk=cancelled.pk).assigned_tutor, third)
        self.assertUnassigned(self.demo_page(student='Meera', phone='0507000002'))


class UnavailableTutorTests(DiagnosticTutorTestCase):
    def assertBookedUnassigned(self, booking):
        self.assertUnassigned(booking)
        self.assertIsNone(self.created_log(booking).context['tutor_id'])

    def test_a_class_of_theirs_at_that_time(self):
        scheduled_class(self.tutor, datetime.combine(DEMO_DAY, EVENING, tzinfo=BOOKING_TIMEZONE) - timedelta(minutes=30))
        self.assertBookedUnassigned(self.invited())

    def test_another_booking_of_theirs_in_that_slot(self):
        other = self.demo_page(student='Sara', phone='0507000009')
        assign_tutor(other, self.tutor, actor=self.admin, now=AFTER)
        booking = self.invited()
        self.assertBookedUnassigned(booking)
        # One student at a time: the tutor still teaches the one booking in that slot.
        self.assertEqual(DemoBooking.objects.filter(assigned_tutor=self.tutor, slot=booking.slot).count(), 1)

    def test_a_tutor_no_longer_active_or_no_longer_a_tutor(self):
        changes = (
            {'is_active': False, 'deactivated_at': AFTER},
            {'role': RoleChoices.MENTOR},
        )
        for change in changes:
            with self.subTest(**change):
                User.objects.filter(pk=self.tutor.pk).update(**change)
                booking = self.invited()
                self.assertBookedUnassigned(booking)
                cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=AFTER)
                User.objects.filter(pk=self.tutor.pk).update(is_active=True, deactivated_at=None, role=RoleChoices.TUTOR)


class UnchangedTests(DiagnosticTutorTestCase):
    def test_a_diagnostic_still_starts_unassigned(self):
        again = create_booking(request(student='Riya', booking_type=DIAGNOSTIC, day=NEXT_DAY, at=MORNING), now=NOW)[0]
        self.assertEqual(again.lead_id, self.lead.pk)
        self.assertUnassigned(again)

    def test_staff_still_reassign_and_unassign(self):
        booking = self.invited()
        # The same tutor again changes nothing.
        self.assertFalse(assign_tutor(booking, self.tutor, actor=self.admin, now=AFTER)[1])
        booking, changed = assign_tutor(booking, self.other_tutor, actor=self.admin, now=AFTER)
        self.assertTrue(changed)
        booking.refresh_from_db()
        self.assertEqual((booking.assigned_tutor, booking.tutor_assigned_by), (self.other_tutor, self.admin))
        event = booking.events.filter(kind=BookingEventKind.TUTOR_ASSIGNED).last()
        self.assertEqual((event.actor, event.data['old_tutor_id'], event.data['new_tutor_id']),
                         (self.admin, str(self.tutor.pk), str(self.other_tutor.pk)))
        self.assertTrue(unassign_tutor(booking, actor=self.admin, now=AFTER)[1])
        booking.refresh_from_db()
        self.assertIsNone(booking.assigned_tutor)

    def test_a_reschedule_carries_the_tutor_as_before(self):
        booking = self.invited()
        moved = reschedule_booking(booking, date(2026, 10, 31), MORNING, reason_code=RescheduleReason.OTHER,
                                   actor=self.admin, now=AFTER)
        self.assertTrue(moved.tutor_carried_over)
        self.assertEqual(moved.booking.assigned_tutor, self.tutor)
        self.assertEqual(moved.booking.events.get(kind=BookingEventKind.TUTOR_ASSIGNED).data['via'], 'reschedule')


@override_settings(MARKETING_SITE_URL=SITE)
class ViewTests(DiagnosticTutorTestCase):
    """
    The Admin's Demo Bookings, the BDE's enquiry and Demo Bookings and the
    tutor's My Bookings, on the real clock: a Diagnostic tomorrow morning, its
    invited Demo the day after.
    """

    def setUp(self):
        super().setUp()
        tomorrow = indian_today() + timedelta(days=1)
        self.today = datetime.combine(indian_today(), MORNING, tzinfo=BOOKING_TIMEZONE)
        diagnostic = create_booking(request(student='Noor', phone='0507000010', booking_type=DIAGNOSTIC, day=tomorrow,
                                            at=MORNING), now=self.today)[0]
        diagnostic = assign_tutor(diagnostic, self.tutor, actor=self.admin, now=self.today)[0]
        diagnostic = start(diagnostic)
        submit_report(diagnostic, self.tutor, diagnostic_input(), now=diagnostic.slot.starts_at + timedelta(minutes=50))
        self.noor = Lead.objects.get(pk=diagnostic.lead_id)
        Lead.objects.filter(pk=self.noor.pk).update(owner_bde=self.bde, owner_assigned_at=self.today)
        after = diagnostic.slot.ends_at + timedelta(hours=1)
        invite, _ = issue_invite(DiagnosticBooking.objects.get(pk=diagnostic.pk), self.admin, now=after)
        self.demo, _ = create_invited_demo_booking(invite.token, tomorrow + timedelta(days=1), EVENING, now=after)
        self.client = APIClient()

    def get(self, user, url, params=None):
        self.client.force_authenticate(user=user)
        response = self.client.get(url, params or {})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_every_view_names_the_diagnostics_tutor(self):
        tutor = {'id': str(self.tutor.pk), 'full_name': self.tutor.full_name}
        # Admin Hub -> Demo Bookings, and the booking itself.
        rows = {row['id']: row for row in self.get(self.admin, '/api/bookings/demo/')['results']}
        self.assertEqual(rows[str(self.demo.pk)]['tutor'], tutor)
        self.assertEqual(self.get(self.admin, f'/api/bookings/demo/{self.demo.pk}/')['tutor'], tutor)
        # Admin Hub -> Demo Bookings, Unassigned: not there.
        unassigned = self.get(self.admin, '/api/bookings/demo/', {'assigned': 'false'})['results']
        self.assertNotIn(str(self.demo.pk), [row['id'] for row in unassigned])
        # BDE Hub -> the enquiry's Bookings tab, and Demo Bookings.
        enquiry = self.get(self.bde, f'/api/bde/enquiries/{self.noor.pk}/')
        entry = next(entry for entry in enquiry['bookings'] if entry['id'] == str(self.demo.pk))
        self.assertEqual(entry['tutor'], {'full_name': self.tutor.full_name})
        rows = {row['id']: row for row in self.get(self.bde, '/api/bde/bookings/demo/')['results']}
        self.assertEqual(rows[str(self.demo.pk)]['tutor'], {'full_name': self.tutor.full_name})
        # The tutor's My Bookings.
        mine = self.get(self.tutor, '/api/tutor/bookings/', {'type': 'DEMO'})['results']
        self.assertEqual([row['id'] for row in mine], [str(self.demo.pk)])
        # The enquiry's History: the system assigned them, from the Diagnostic.
        history = self.get(self.bde, f'/api/bde/enquiries/{self.noor.pk}/history/')['entries']
        assigned = [entry for entry in history
                    if entry['kind'] == BookingEventKind.TUTOR_ASSIGNED and entry['booking']['id'] == str(self.demo.pk)]
        self.assertEqual([(entry['by'], entry['actor'], entry['details']['via'], entry['details']['new_tutor'])
                          for entry in assigned],
                         [('SYSTEM', None, 'diagnostic', {'full_name': self.tutor.full_name})])

    def test_the_admin_still_reassigns_and_unassigns(self):
        self.client.force_authenticate(user=self.admin)
        url = f'/api/bookings/demo/{self.demo.pk}/tutor/'
        response = self.client.put(url, {'tutor_id': str(self.other_tutor.pk)}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()['changed'], response.json()['tutor']['id']), (True, str(self.other_tutor.pk)))
        response = self.client.delete(url)
        self.assertEqual((response.status_code, response.json()['changed'], response.json()['tutor']), (200, True, None))
        # A BDE assigns no tutor, as before.
        self.client.force_authenticate(user=self.bde)
        self.assertEqual(self.client.put(url, {'tutor_id': str(self.tutor.pk)}, format='json').status_code, 403)


@skipUnless(connection.vendor == 'postgresql', 'the booking locks need PostgreSQL row locking')
@override_settings(MARKETING_SITE_URL=SITE)
class ConcurrentDiagnosticTutorTests(TransactionTestCase):
    """Real threads, each with its own database connection, starting together."""

    def setUp(self):
        schedule()
        self.admin = account('admin_race', role='ADMIN')
        self.diagnostic = diagnostic_with_report()
        self.tutor = self.diagnostic.assigned_tutor

    def race(self, calls):
        barrier = threading.Barrier(len(calls))
        outcomes = [None] * len(calls)

        def run(index, call):
            try:
                barrier.wait(timeout=10)
                outcomes[index] = call()
            except Exception as exc:  # reported in the assertion, not lost in the thread
                outcomes[index] = type(exc).__name__
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return outcomes

    def slowed_conflict_check(self):
        """find_tutor_conflict made slow, so that without the tutor's locks both racers would pass it before either writes."""
        check = booking_service.find_tutor_conflict

        def slow(*args, **kwargs):
            found = check(*args, **kwargs)
            clock.sleep(0.3)
            return found

        return mock.patch.object(booking_service, 'find_tutor_conflict', slow)

    def test_an_invited_demo_and_an_assignment_racing_for_the_tutor(self):
        # Another child's Diagnostic at the same time -- a slot row of its own, so only the tutor's locks keep the
        # two apart -- the admin giving it the same tutor as the invitation is used.
        other = create_booking(request(student='Sara', phone='0507000009', booking_type=DIAGNOSTIC, day=DEMO_DAY,
                                       at=EVENING), now=AFTER)[0]
        invite, _ = issue_invite(self.diagnostic, self.admin, now=AFTER)

        def book():
            booking, created = create_invited_demo_booking(invite.token, DEMO_DAY, EVENING, now=AFTER)
            return 'booked' if created else 'repeat'

        def assign():
            assign_tutor(other, self.tutor, actor=self.admin, now=AFTER)
            return 'assigned'

        with self.slowed_conflict_check():
            outcomes = self.race([book, assign])
        # The parent's booking always goes through; the tutor teaches one of the two.
        self.assertEqual(outcomes[0], 'booked', outcomes)
        self.assertIn(outcomes[1], ('assigned', TutorUnavailable.__name__), outcomes)
        teaching = sum(model.objects.filter(assigned_tutor=self.tutor, slot__local_date=DEMO_DAY).count()
                       for model in (DemoBooking, DiagnosticBooking))
        self.assertEqual(teaching, 1, outcomes)
