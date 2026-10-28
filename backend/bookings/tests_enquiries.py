"""
The BDE workspace's dashboard and enquiries (bookings.enquiries): a BDE reads
and adds only their own leads, statuses follow the bookings, and every other
caller -- superusers included -- is refused.
"""
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from activity.models import ActivityLog

from .booking_service import BookingRequest, create_booking
from .models import Booking, BookingLink, BookingSlot, BookingStatus, BookingType, Lead, LeadSource, ReferralStatus, SlotTime
from .scheduling import BOOKING_TIMEZONE, booking_window, slot_instants

User = get_user_model()

DEMO, DIAGNOSTIC = BookingType.DEMO, BookingType.DIAGNOSTIC
EVENING = time(19, 30)
ENQUIRIES = '/api/bde/enquiries/'
DASHBOARD = '/api/bde/dashboard/'


def account(username, role='BDE', **extra):
    return User.objects.create_user(
        email=f'{username}@enquiries.test', username=username, password=None,
        full_name=username.replace('_', ' ').title(), role=role, **extra,
    )


def lead(owner, student, phone='501234567', link=None, source=LeadSource.BOOKING_PAGE, parent='Asha Nair'):
    return Lead.objects.create(
        parent_name=parent, phone_dial_code='+971', phone_number=phone, phone_key=f'+971{phone}',
        student_name=student, student_name_key=student.casefold(), school_name='Delhi Private School',
        grade='Class 8', syllabus='CBSE', source=source, owner_bde=owner, owner_link=link,
        owner_assigned_at=timezone.now() if owner else None,
    )


def booking(of, days, booking_type=DEMO, status=BookingStatus.BOOKED):
    """A booking of ``of`` at 19:30 IST, ``days`` from today (negative: in the past)."""
    local_date = timezone.now().astimezone(BOOKING_TIMEZONE).date() + timedelta(days=days)
    starts_at, ends_at = slot_instants(local_date, EVENING)
    slot, _ = BookingSlot.objects.get_or_create(
        booking_type=booking_type, local_date=local_date, local_time=EVENING,
        defaults={'starts_at': starts_at, 'ends_at': ends_at},
    )
    seat = slot.bookings.filter(status=BookingStatus.BOOKED).count() + 1
    cancelled = status == BookingStatus.CANCELLED
    return Booking.objects.create(
        booking_type=booking_type, lead=of, slot=slot, seat=seat, status=status,
        referral_status=ReferralStatus.NO_REF, cancelled_at=timezone.now() if cancelled else None,
    )


def new_enquiry(**overrides):
    body = {
        'parent_name': 'Meera Menon', 'phone_dial_code': '+91', 'phone_number': '09876543210',
        'student_name': 'Kavya', 'grade': 'Class 7', 'source': 'PHONE_CALL',
        'school_name': 'Kendriya Vidyalaya', 'syllabus': 'CBSE', 'country': 'India',
    }
    body.update(overrides)
    return body


class EnquiryTestCase(TestCase):
    def setUp(self):
        self.bde = account('bde_a')
        self.other_bde = account('bde_b')
        self.client = APIClient()
        self.client.force_authenticate(self.bde)

    def ids(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return {row['id'] for row in response.json()['results']}


class ScopeTests(EnquiryTestCase):
    def test_a_bde_lists_only_their_own_enquiries(self):
        demo_link = BookingLink.objects.create(bde=self.bde, booking_type=DEMO)
        from_link = lead(self.bde, 'Riya', link=demo_link)
        by_hand = lead(self.bde, 'Arjun', phone='501111111', source=LeadSource.WALK_IN)
        lead(self.other_bde, 'Sara', phone='502222222')
        lead(None, 'Nobody', phone='503333333')

        response = self.client.get(ENQUIRIES)
        self.assertEqual(self.ids(response), {str(from_link.id), str(by_hand.id)})
        self.assertEqual(response.json()['count'], 2)

    def test_another_bdes_or_an_unowned_enquiry_is_not_found(self):
        theirs = lead(self.other_bde, 'Sara')
        unowned = lead(None, 'Nobody', phone='503333333')
        for other in (theirs, unowned):
            with self.subTest(owner=other.owner_bde_id):
                response = self.client.get(f'{ENQUIRIES}{other.id}/')
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {'error': 'NOT_FOUND', 'message': 'No such enquiry.'})

    def test_the_detail_carries_the_bookings_but_not_who_cancelled_or_why(self):
        mine = lead(self.bde, 'Riya')
        booking(mine, 2)
        cancelled = booking(mine, 3, DIAGNOSTIC, status=BookingStatus.CANCELLED)
        Booking.objects.filter(pk=cancelled.pk).update(cancel_reason='Parent asked', cancelled_by=self.other_bde)

        response = self.client.get(f'{ENQUIRIES}{mine.id}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['student_name'], 'Riya')
        self.assertEqual(data['phone'], '+971 501234567')
        self.assertEqual([b['status'] for b in data['bookings']], ['CANCELLED', 'BOOKED'])
        for row in data['bookings']:
            self.assertEqual(set(row), {'id', 'booking_type', 'date', 'time', 'starts_at', 'status', 'ended',
                                        'booked_at', 'cancelled_at'})
        self.assertNotIn('Parent asked', response.content.decode())
        self.assertNotIn('owner_bde', data)


class StatusAndFilterTests(EnquiryTestCase):
    def setUp(self):
        super().setUp()
        self.new = lead(self.bde, 'Fresh', phone='501000001')
        self.booked = lead(self.bde, 'Coming', phone='501000002')
        booking(self.booked, 4, DIAGNOSTIC)
        booking(self.booked, 2, DEMO)
        booking(self.booked, -3, DEMO)
        self.done = lead(self.bde, 'Visited', phone='501000003')
        booking(self.done, -2)
        booking(self.done, 5, status=BookingStatus.CANCELLED)
        self.cancelled = lead(self.bde, 'Dropped', phone='501000004')
        booking(self.cancelled, 2, status=BookingStatus.CANCELLED)

    def test_the_status_follows_the_bookings(self):
        rows = {row['id']: row for row in self.client.get(ENQUIRIES).json()['results']}
        self.assertEqual(rows[str(self.new.id)]['status'], 'NEW')
        self.assertEqual(rows[str(self.new.id)]['next_booking'], None)
        booked = rows[str(self.booked.id)]
        # The earliest booking still to come names the status.
        self.assertEqual((booked['status'], booked['status_label']), ('BOOKED', 'Demo booked'))
        self.assertEqual(booked['next_booking']['booking_type'], DEMO)
        self.assertEqual(booked['next_booking']['time'], '19:30')
        self.assertEqual((rows[str(self.done.id)]['status'], rows[str(self.done.id)]['status_label']), ('DONE', 'Booking done'))
        self.assertEqual(rows[str(self.cancelled.id)]['status'], 'CANCELLED')

    def test_status_filter(self):
        expected = {'NEW': self.new, 'BOOKED': self.booked, 'DONE': self.done, 'CANCELLED': self.cancelled}
        for state, row in expected.items():
            with self.subTest(status=state):
                self.assertEqual(self.ids(self.client.get(ENQUIRIES, {'status': state.lower()})), {str(row.id)})

    def test_source_and_its_filter(self):
        link = BookingLink.objects.create(bde=self.bde, booking_type=DIAGNOSTIC)
        Lead.objects.filter(pk=self.booked.pk).update(owner_link=link)
        Lead.objects.filter(pk=self.done.pk).update(source=LeadSource.REFERRAL)
        rows = {row['id']: row for row in self.client.get(ENQUIRIES).json()['results']}
        self.assertEqual((rows[str(self.booked.id)]['source'], rows[str(self.booked.id)]['source_label']),
                         ('DIAGNOSTIC_LINK', 'Diagnostic link'))
        self.assertEqual((rows[str(self.done.id)]['source'], rows[str(self.done.id)]['source_label']), ('REFERRAL', 'Referral'))
        self.assertEqual(self.ids(self.client.get(ENQUIRIES, {'source': 'DIAGNOSTIC_LINK'})), {str(self.booked.id)})
        self.assertEqual(self.ids(self.client.get(ENQUIRIES, {'source': 'REFERRAL'})), {str(self.done.id)})
        self.assertEqual(self.ids(self.client.get(ENQUIRIES, {'source': 'DEMO_LINK'})), set())

    def test_search_by_name_or_phone(self):
        Lead.objects.filter(pk=self.new.pk).update(parent_name='Lakshmi Pillai')
        self.assertEqual(self.ids(self.client.get(ENQUIRIES, {'q': 'lakshmi'})), {str(self.new.id)})
        self.assertEqual(self.ids(self.client.get(ENQUIRIES, {'q': 'visit'})), {str(self.done.id)})
        # The domestic leading 0 is dropped, as stored numbers drop it.
        self.assertEqual(self.ids(self.client.get(ENQUIRIES, {'q': '0501 000 004'})), {str(self.cancelled.id)})
        # Too few digits to search numbers by; nobody's name holds "12".
        self.assertEqual(self.ids(self.client.get(ENQUIRIES, {'q': '12'})), set())

    def test_unknown_filters_are_refused(self):
        for params in ({'status': 'LOST'}, {'source': 'BOOKING_PAGE'}):
            with self.subTest(params=params):
                response = self.client.get(ENQUIRIES, params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error'], 'INVALID_INPUT')

    def test_paging(self):
        response = self.client.get(ENQUIRIES, {'page': 2, 'page_size': 3})
        data = response.json()
        self.assertEqual((data['count'], data['page'], data['page_size'], len(data['results'])), (4, 2, 3, 1))


class AddEnquiryTests(EnquiryTestCase):
    def test_adding_an_enquiry(self):
        response = self.client.post(ENQUIRIES, new_enquiry(), format='json')
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data['source'], data['source_label'], data['status']), ('PHONE_CALL', 'Phone call', 'NEW'))
        self.assertEqual(data['phone'], '+91 9876543210')
        created = Lead.objects.get(pk=data['id'])
        self.assertEqual(created.owner_bde, self.bde)
        self.assertIsNone(created.owner_link)
        self.assertEqual((created.phone_key, created.student_name_key), ('+919876543210', 'kavya'))

        log = ActivityLog.objects.get(action='enquiry.create')
        self.assertEqual((log.actor, log.entity_type, log.entity_id), (self.bde, 'lead', str(created.id)))
        self.assertEqual(log.context['source'], 'PHONE_CALL')
        for private in ('Meera', 'Kavya', '9876543210'):
            self.assertNotIn(private, str(log.entity_label) + str(log.context))

    def test_a_duplicate_of_their_own_points_to_it(self):
        mine = lead(self.bde, 'Kavya', phone='9876543210')
        Lead.objects.filter(pk=mine.pk).update(phone_dial_code='+91', phone_key='+919876543210')
        response = self.client.post(ENQUIRIES, new_enquiry(student_name='KAVYA'), format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['enquiry_id'], str(mine.id))

    def test_a_duplicate_of_someone_elses_names_nothing_and_changes_nothing(self):
        for owner in (self.other_bde, None):
            with self.subTest(owner=owner):
                Lead.objects.all().delete()
                theirs = lead(owner, 'Kavya', phone='9876543210')
                Lead.objects.filter(pk=theirs.pk).update(phone_dial_code='+91', phone_key='+919876543210')
                response = self.client.post(ENQUIRIES, new_enquiry(), format='json')
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()['error'], 'ENQUIRY_EXISTS')
                self.assertNotIn('enquiry_id', response.json())
                theirs.refresh_from_db()
                self.assertEqual(theirs.owner_bde, owner)
                self.assertEqual(theirs.parent_name, 'Asha Nair')

    def test_invalid_details_are_refused(self):
        cases = {
            'source': new_enquiry(source='BOOKING_PAGE'),
            'phone': new_enquiry(phone_number='123'),
            'grade': new_enquiry(grade='Class 12'),
            'parent_name': new_enquiry(parent_name='  '),
        }
        for field, body in cases.items():
            with self.subTest(field=field):
                response = self.client.post(ENQUIRIES, body, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()['fields'])
        self.assertFalse(Lead.objects.exists())

    def test_an_owner_in_the_body_is_ignored(self):
        response = self.client.post(ENQUIRIES, new_enquiry(owner_bde=str(self.other_bde.id)), format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Lead.objects.get().owner_bde, self.bde)

    def test_a_later_booking_keeps_the_enquiry_with_the_bde_who_added_it(self):
        SlotTime.objects.create(booking_type=DEMO, start_time=EVENING)
        added = self.client.post(ENQUIRIES, new_enquiry(), format='json').json()
        other_link = BookingLink.objects.create(bde=self.other_bde, booking_type=DEMO)
        made, _created = create_booking(BookingRequest(
            booking_type=DEMO, date=booking_window(DEMO)[0], time=EVENING, parent_name='Meera Menon',
            phone_dial_code='+91', phone_number='9876543210', student_name='Kavya', school='KV',
            student_class='Class 7', syllabus='CBSE', ref=other_link.token,
        ))
        self.assertEqual(str(made.lead_id), added['id'])
        self.assertEqual(made.attributed_bde, self.other_bde)
        self.assertEqual(Lead.objects.get(pk=added['id']).owner_bde, self.bde)

        mine = self.client.get(DASHBOARD).json()
        self.assertEqual(mine['bookings'][DEMO], {'total': 1, 'upcoming': 1})
        self.assertEqual(mine['upcoming']['rows'][0]['enquiry']['id'], added['id'])
        # The other BDE's link took the booking, but the enquiry is not theirs to see.
        self.client.force_authenticate(self.other_bde)
        theirs = self.client.get(DASHBOARD).json()
        self.assertEqual((theirs['enquiries']['total'], theirs['upcoming']['total']), (0, 0))
        self.assertEqual(self.client.get(f'{ENQUIRIES}{added["id"]}/').status_code, 404)


class DashboardTests(EnquiryTestCase):
    def test_counts_and_upcoming_bookings_are_the_bdes_own(self):
        first = lead(self.bde, 'Riya', phone='501000001')
        second = lead(self.bde, 'Arjun', phone='501000002')
        Lead.objects.filter(pk=second.pk).update(owner_assigned_at=timezone.now() - timedelta(days=10))
        later = booking(first, 3, DEMO)
        sooner = booking(second, 1, DIAGNOSTIC)
        booking(first, -2, DEMO)
        booking(second, 2, DEMO, status=BookingStatus.CANCELLED)
        booking(lead(self.other_bde, 'Sara', phone='502000000'), 1, DEMO)

        data = self.client.get(DASHBOARD).json()
        self.assertEqual(data['enquiries'], {'total': 2, 'last_7_days': 1})
        self.assertEqual(data['bookings'], {DEMO: {'total': 2, 'upcoming': 1}, DIAGNOSTIC: {'total': 1, 'upcoming': 1}})
        self.assertEqual(data['upcoming']['total'], 2)
        self.assertEqual([row['id'] for row in data['upcoming']['rows']], [str(sooner.id), str(later.id)])
        self.assertEqual(data['upcoming']['rows'][0]['enquiry'],
                         {'id': str(second.id), 'parent_name': 'Asha Nair', 'student_name': 'Arjun', 'grade': 'Class 8'})
        self.assertEqual([row['id'] for row in data['recent_enquiries']], [str(first.id), str(second.id)])

    def test_an_empty_dashboard(self):
        data = self.client.get(DASHBOARD).json()
        self.assertEqual(data['enquiries'], {'total': 0, 'last_7_days': 0})
        self.assertEqual(data['upcoming'], {'total': 0, 'rows': []})
        self.assertEqual(data['recent_enquiries'], [])


class OtherCallerTests(TestCase):
    """Only an active BDE reaches the workspace; a superuser holds its permissions (D1) but is told it is not a BDE."""

    def setUp(self):
        self.mine = lead(account('bde_a'), 'Riya')
        self.requests = [
            ('get', DASHBOARD, None),
            ('get', ENQUIRIES, None),
            ('post', ENQUIRIES, new_enquiry()),
            ('get', f'{ENQUIRIES}{self.mine.id}/', None),
        ]

    def answers(self, user):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return [getattr(client, method)(path, body, format='json') for method, path, body in self.requests]

    def test_superusers_are_not_bdes(self):
        for response in self.answers(account('root', 'ADMIN', is_superuser=True)):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()['error'], 'NOT_A_BDE')
        self.assertEqual(Lead.objects.count(), 1)

    def test_other_roles_and_deactivated_bdes_are_refused(self):
        callers = {
            role: account(role.lower(), role) for role in ('ADMIN', 'MENTOR', 'TUTOR', 'SALES_TL', 'STUDENT')
        }
        callers['deactivated BDE'] = account('bde_off', 'BDE', deactivated_at=timezone.now())
        callers['anonymous'] = None
        for label, user in callers.items():
            with self.subTest(caller=label):
                for response in self.answers(user):
                    self.assertIn(response.status_code, (401, 403))
                    self.assertNotIn('Riya', response.content.decode())
        self.assertEqual(Lead.objects.count(), 1)
