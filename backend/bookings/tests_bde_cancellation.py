"""
A BDE cancelling a booking (Phase 5.2, P3; Q22): only the bookings of their
own leads, enforced in the backend -- the view looks the booking up among
the caller's leads only and the service checks it again under the lock --
with the Admin's reasons (Q9), rules (D12) and append-only history. Another
BDE's booking, an unowned lead's, one of the other type and one that does not
exist are answered alike; tutors and every other role are refused.
"""
import json
import uuid
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import RoleGroup
from activity.models import ActivityLog

from .booking_service import BookingNotOwned, cancel_booking, create_booking, reschedule_booking
from .models import BookingEvent, BookingEventKind, BookingStatus, CancelReason, Lead, RescheduleReason
from .scheduling import indian_today
from .tests_booking import EVENING, MORNING, account, request, schedule

DEMO, DIAGNOSTIC = 'DEMO', 'DIAGNOSTIC'
NOT_FOUND = {'error': 'NOT_FOUND', 'message': 'No such booking.'}


def cancel_url(booking_or_id, booking_type=None):
    booking_type = booking_type or booking_or_id.booking_type
    return f'/api/bde/bookings/{booking_type.lower()}/{getattr(booking_or_id, "id", booking_or_id)}/cancel/'


class BdeCancellationTestCase(APITestCase):
    def setUp(self):
        schedule()
        self.bde_a = account('bde_anil', role='BDE')
        self.bde_b = account('bde_bina', role='BDE')
        self.admin = account('admin_ops', role='ADMIN')
        self.day = indian_today() + timedelta(days=2)
        self.phones = iter(f'05088800{n:02d}' for n in range(60))
        self.client = APIClient()
        self.client.force_authenticate(self.bde_a)

    def book(self, owner, student, booking_type=DEMO, day=None, at=EVENING, now=None):
        """A public booking whose lead ``owner`` owns (None: nobody)."""
        booking, _ = create_booking(request(student=student, phone=next(self.phones), booking_type=booking_type,
                                            day=day or self.day, at=at), now=now)
        if owner is not None:
            Lead.objects.filter(pk=booking.lead_id).update(owner_bde=owner, owner_assigned_at=timezone.now())
        return booking

    def cancel(self, booking_or_id, reason='PARENT_REQUEST', client=None, booking_type=None):
        return (client or self.client).post(cancel_url(booking_or_id, booking_type), {'reason': reason}, format='json')

    def untouched(self, booking):
        booking.refresh_from_db()
        self.assertEqual(booking.status, BookingStatus.BOOKED)
        self.assertFalse(booking.events.filter(kind=BookingEventKind.CANCELLED).exists())
        self.assertFalse(ActivityLog.objects.filter(action='booking.cancel', entity_id=str(booking.id)).exists())


class OwnLeadTests(BdeCancellationTestCase):
    def test_a_bde_cancels_their_own_leads_bookings_of_either_type(self):
        for booking_type in (DEMO, DIAGNOSTIC):
            with self.subTest(booking_type=booking_type):
                booking = self.book(self.bde_a, f'Mine {booking_type}', booking_type=booking_type)
                res = self.cancel(booking)
                self.assertEqual(res.status_code, 200, res.data)
                self.assertTrue(res.data['changed'])
                row = next(b for b in res.data['bookings'] if b['id'] == str(booking.id))
                self.assertEqual((row['status'], row['actions']), ('CANCELLED', {'cancel': False, 'no_show': False, 'demo_invite': False}))
                booking.refresh_from_db()
                self.assertEqual((booking.status, booking.cancel_reason_code, booking.cancelled_by),
                                 (BookingStatus.CANCELLED, 'PARENT_REQUEST', self.bde_a))
                event = booking.events.get(kind=BookingEventKind.CANCELLED)
                self.assertEqual((event.actor, event.data),
                                 (self.bde_a, {'from_status': 'BOOKED', 'to_status': 'CANCELLED', 'reason_code': 'PARENT_REQUEST'}))
                entry = ActivityLog.objects.get(action='booking.cancel', entity_id=str(booking.id))
                self.assertEqual((entry.actor, entry.context['reason_code']), (self.bde_a, 'PARENT_REQUEST'))

    def test_the_admins_reasons_and_rules(self):
        booking = self.book(self.bde_a, 'Riya')
        for body in ({}, {'reason': 'Parent asked to cancel'}, {'reason': 'TUTOR_UNAVAILABLE'}):
            with self.subTest(body=body):
                res = self.client.post(cancel_url(booking), body, format='json')
                self.assertEqual((res.status_code, res.data['error']), (400, 'VALIDATION_ERROR'))
        res = self.cancel(booking, reason='NO_SHOW')
        self.assertEqual((res.status_code, res.data['error']), (409, 'NO_SHOW_BEFORE_START'))
        self.untouched(booking)

        then = timezone.now() - timedelta(days=7)
        started = self.book(self.bde_a, 'Old Kid', day=indian_today(then) + timedelta(days=1), now=then)
        self.assertEqual(self.cancel(started, reason='NO_SHOW').status_code, 200)

        moved = self.book(self.bde_a, 'Moved Kid', at=MORNING)
        reschedule_booking(moved, self.day + timedelta(days=1), MORNING, reason_code=RescheduleReason.OTHER, actor=self.admin)
        self.assertEqual(self.cancel(moved).data['error'], 'BOOKING_RESCHEDULED')

        self.assertEqual(self.cancel(booking).status_code, 200)
        again = self.cancel(booking, reason='DUPLICATE')
        self.assertEqual((again.status_code, again.data['changed']), (200, False))
        booking.refresh_from_db()
        self.assertEqual(booking.cancel_reason_code, 'PARENT_REQUEST')

    def test_the_enquiry_offers_cancel_only_for_live_bookings(self):
        # Booked a week ago for the next day: its slot has ended, so the child
        # may book another Demo (one live booking per type, Q26).
        then = timezone.now() - timedelta(days=7)
        started = self.book(self.bde_a, 'Riya', day=indian_today(then) + timedelta(days=1), at=MORNING, now=then)
        upcoming = create_booking(request(student='Riya', phone=started.lead.phone_number, day=self.day, at=EVENING))[0]
        cancelled = create_booking(request(student='Riya', phone=started.lead.phone_number, booking_type=DIAGNOSTIC,
                                           day=self.day, at=MORNING))[0]
        cancel_booking(cancelled, reason_code=CancelReason.OTHER, actor=self.admin)
        rows = {row['id']: row['actions'] for row in self.client.get(f'/api/bde/enquiries/{upcoming.lead_id}/').data['bookings']}
        self.assertEqual(rows, {
            str(upcoming.id): {'cancel': True, 'no_show': False, 'demo_invite': False},
            str(started.id): {'cancel': True, 'no_show': True, 'demo_invite': False},
            str(cancelled.id): {'cancel': False, 'no_show': False, 'demo_invite': False},
        })


class CrossBdeTests(BdeCancellationTestCase):
    def test_never_another_bdes_or_an_unowned_leads_booking(self):
        theirs = self.book(self.bde_b, 'Theirs')
        nobodys = self.book(None, 'Nobodys')
        mine = self.book(self.bde_a, 'Mine')
        attempts = {
            "another BDE's booking": cancel_url(theirs),
            "an unowned lead's booking": cancel_url(nobodys),
            'a booking that does not exist': cancel_url(uuid.uuid4(), DEMO),
            'their own booking under the other type': cancel_url(mine.id, DIAGNOSTIC),
            'an unknown type': f'/api/bde/bookings/webinar/{mine.id}/cancel/',
        }
        for what, url in attempts.items():
            with self.subTest(what=what):
                res = self.client.post(url, {'reason': 'OTHER'}, format='json')
                self.assertEqual((res.status_code, res.data), (404, NOT_FOUND))
                # Nothing in the answer tells them apart -- not even a bad body.
                self.assertEqual(self.client.post(url, {}, format='json').data, NOT_FOUND)
        for booking in (theirs, nobodys, mine):
            self.untouched(booking)
        # The owner can.
        other = APIClient()
        other.force_authenticate(self.bde_b)
        self.assertEqual(self.cancel(theirs, client=other).status_code, 200)

    def test_the_service_checks_ownership_again_under_the_lock(self):
        theirs = self.book(self.bde_b, 'Theirs')
        with self.assertRaises(BookingNotOwned):
            cancel_booking(theirs, reason_code=CancelReason.OTHER, actor=self.bde_a, owner_bde=self.bde_a)
        self.untouched(theirs)
        # Without an owner to check, it is the Admin's cancel.
        self.assertTrue(cancel_booking(theirs, reason_code=CancelReason.OTHER, actor=self.admin)[1])

    def test_the_admin_routes_stay_closed_to_a_bde(self):
        mine = self.book(self.bde_a, 'Mine')
        res = self.client.post(f'/api/bookings/demo/{mine.id}/cancel/', {'reason': 'OTHER'}, format='json')
        self.assertEqual(res.status_code, 403)
        self.untouched(mine)


class WhoMayNotTests(BdeCancellationTestCase):
    def test_tutors_and_every_other_role_are_refused(self):
        mine = self.book(self.bde_a, 'Mine')
        callers = {
            'tutor': account('tutor_ops', role='TUTOR'), 'mentor': account('mentor_ops', role='MENTOR'),
            'admin': self.admin, 'sales_tl': account('sales_ops', role='SALES_TL'),
            'student': account('parent_ops', role='STUDENT'), 'unknown': account('nobody_ops', role='UNASSIGNED'),
        }
        for name, user in [*callers.items(), ('anonymous', None)]:
            client = APIClient()
            if user is not None:
                client.force_authenticate(user)
            with self.subTest(caller=name):
                res = self.cancel(mine, client=client)
                self.assertEqual(res.status_code, 403)
                self.assertNotIn('Mine', json.dumps(res.data))
        # A superuser holds every permission (D1) but is no BDE, and owns no lead.
        root = APIClient()
        root.force_authenticate(account('root_ops', role='ADMIN', is_superuser=True))
        res = self.cancel(mine, client=root)
        self.assertEqual((res.status_code, res.data['error']), (403, 'NOT_A_BDE'))
        self.untouched(mine)

    def test_a_bde_without_the_permission(self):
        mine = self.book(self.bde_a, 'Mine')
        RoleGroup.objects.get(role='BDE').group.permissions.remove(Permission.objects.get(codename='cancel_booking'))
        client = APIClient()
        client.force_authenticate(type(self.bde_a).objects.get(pk=self.bde_a.pk))
        self.assertEqual(self.cancel(mine, client=client).status_code, 403)
        rows = client.get(f'/api/bde/enquiries/{mine.lead_id}/').data['bookings']
        self.assertEqual(rows[0]['actions'], {'cancel': False, 'no_show': False, 'demo_invite': False})
        self.untouched(mine)
        self.assertEqual(BookingEvent.objects.filter(kind=BookingEventKind.CANCELLED).count(), 0)
