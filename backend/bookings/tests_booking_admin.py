"""
Booking management for the Admin / Coordinator (/api/bookings/, bookings.coordination
and bookings.management_views): the paged and filtered list, one booking in
full, every active tutor with whether they are free for a slot, and assigning,
reassigning and unassigning a booking's tutor through booking_service -- for
holders of accounts.view_all_bookings / accounts.assign_booking_tutor only.
"""
import json
import uuid
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from activity.models import ActivityLog
from sessions.models import Session, SessionStatusChoices
from students.models import Student

from .booking_service import assign_tutor, cancel_booking, create_booking
from .models import Booking, BookingStatus, BookingType
from .scheduling import BOOKING_TIMEZONE, indian_today
from .tests_booking import EVENING, MORNING, account, link, request, schedule

User = get_user_model()

DEMO, DIAGNOSTIC = BookingType.DEMO, BookingType.DIAGNOSTIC
LIST_URL = '/api/bookings/'
# Names, phone and school the requests fill in (tests_booking.request); none may reach a log.
PRIVATE = ('Asha Nair', 'Delhi Private School', '501234567')


def detail_url(booking):
    return f'{LIST_URL}{booking.id}/'


def tutors_url(booking):
    return f'{LIST_URL}{booking.id}/tutors/'


def slot_tutors_url(slot_id):
    return f'{LIST_URL}slots/{slot_id}/tutors/'


def tutor_url(booking):
    return f'{LIST_URL}{booking.id}/tutor/'


class BookingAdminTestCase(APITestCase):
    def setUp(self):
        schedule()
        self.admin = account('admin_one', role='ADMIN')
        self.tutor_a = account('tutor_anu', role='TUTOR')
        self.tutor_b = account('tutor_binu', role='TUTOR')
        self.tutor_off = account('tutor_off', role='TUTOR', is_active=False, deactivated_at=timezone.now())
        self.mentor = account('mentor_one', role='MENTOR')
        self.bde = account('bde_one', role='BDE')
        # Inside the booking window (tomorrow through six days on), and still ahead.
        self.day = indian_today() + timedelta(days=2)
        self.phones = iter(f'05077700{n:02d}' for n in range(80))
        self.client.force_authenticate(user=self.admin)

    def book(self, student, booking_type=DEMO, at=EVENING, day=None, now=None, **kwargs):
        booking, _ = create_booking(
            request(student=student, phone=next(self.phones), booking_type=booking_type, day=day or self.day, at=at, **kwargs),
            now=now,
        )
        return booking

    def ist(self, at, days=0):
        return datetime.combine(self.day + timedelta(days=days), at, tzinfo=BOOKING_TIMEZONE)

    def class_for(self, tutor, starts_at, code, minutes=60):
        student = Student.objects.create(
            profile=account(f'kid_{code.lower()}', role='STUDENT'), student_code=code, full_name=f'Kid {code}', tutor=tutor,
        )
        return Session.objects.create(
            student=student, tutor=tutor, title='Maths', status=SessionStatusChoices.SCHEDULED,
            start_time=starts_at, end_time=starts_at + timedelta(minutes=minutes),
        )

    def ids(self, response):
        return [row['id'] for row in response.data['results']]


class ListTests(BookingAdminTestCase):
    def test_every_booking_soonest_first_and_paged(self):
        evening = self.book('Riya')
        morning = self.book('Ali', booking_type=DIAGNOSTIC, at=MORNING)
        next_day = self.book('Sara', day=self.day + timedelta(days=1))
        res = self.client.get(LIST_URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual((res.data['count'], res.data['page'], res.data['page_size'], res.data['timezone']), (3, 1, 25, 'Asia/Kolkata'))
        self.assertEqual(self.ids(res), [str(morning.id), str(evening.id), str(next_day.id)])
        row = res.data['results'][1]
        self.assertEqual((row['student_name'], row['parent_name'], row['grade'], row['status'], row['tutor']),
                         ('Riya', 'Asha Nair', 'Class 8', 'BOOKED', None))
        self.assertEqual((row['slot']['date'], row['slot']['time'], row['slot']['started']), (self.day.isoformat(), '19:30', False))

        page_two = self.client.get(LIST_URL, {'page': 2, 'page_size': 2})
        self.assertEqual((page_two.data['count'], self.ids(page_two)), (3, [str(next_day.id)]))
        # Unusable paging falls back to the defaults and the 200-row cap, as everywhere in the API.
        self.assertEqual(self.client.get(LIST_URL, {'page': 'x', 'page_size': '0'}).data['page_size'], 1)
        self.assertEqual(self.client.get(LIST_URL, {'page': 'x'}).data['page'], 1)
        self.assertEqual(self.client.get(LIST_URL, {'page_size': 5000}).data['page_size'], 200)
        self.assertEqual(self.client.get(LIST_URL, {'page': 9}).data['results'], [])

    def test_the_bde_a_booking_is_credited_to(self):
        credited = self.book('Riya', ref=link(self.bde).token)
        row = self.client.get(LIST_URL).data['results'][0]
        self.assertEqual((row['id'], row['bde']), (str(credited.id), {'id': str(self.bde.id), 'full_name': 'Bde One'}))

    def test_filters(self):
        evening = self.book('Riya')
        diagnostic = self.book('Ali', booking_type=DIAGNOSTIC, at=MORNING)
        cancelled = self.book('Sara', day=self.day + timedelta(days=1))
        cancel_booking(cancelled, actor=self.admin)
        assign_tutor(evening, self.tutor_a, actor=self.admin)
        last_week = timezone.now() - timedelta(days=7)
        past = self.book('Old Kid', day=indian_today(last_week) + timedelta(days=1), now=last_week)

        def listed(**params):
            res = self.client.get(LIST_URL, params)
            self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
            return sorted(self.ids(res))

        def ids(*bookings):
            return sorted(str(booking.id) for booking in bookings)

        self.assertEqual(listed(type='diagnostic'), ids(diagnostic))
        self.assertEqual(listed(status='CANCELLED'), ids(cancelled))
        self.assertEqual(listed(assigned='true'), ids(evening))
        self.assertEqual(listed(assigned='false'), ids(diagnostic, cancelled, past))
        self.assertEqual(listed(tutor=str(self.tutor_a.id)), ids(evening))
        self.assertEqual(listed(slot=str(evening.slot_id)), ids(evening))
        self.assertEqual(listed(**{'from': self.day.isoformat(), 'to': self.day.isoformat()}), ids(evening, diagnostic))
        self.assertEqual(listed(when='past'), ids(past))
        self.assertEqual(listed(when='upcoming'), ids(evening, diagnostic, cancelled))
        self.assertEqual(listed(q='riya'), ids(evening))
        self.assertEqual(listed(q='Asha'), ids(evening, diagnostic, cancelled, past))
        # Phone digits, the domestic leading 0 included or not.
        self.assertEqual(listed(q=evening.lead.phone_number), ids(evening))
        self.assertEqual(listed(q='0' + evening.lead.phone_number), ids(evening))
        self.assertEqual(listed(type='DEMO', status='BOOKED', when='upcoming'), ids(evening))

    def test_unknown_filter_values_are_refused_never_guessed(self):
        self.book('Riya')
        res = self.client.get(LIST_URL, {
            'type': 'TRIAL', 'status': 'done', 'assigned': 'maybe', 'tutor': 'not-an-id', 'slot': '42',
            'from': '2026-13-01', 'to': '31-10-2026', 'when': 'tomorrow', 'q': 'x' * 101,
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['error'], 'INVALID_INPUT')
        self.assertEqual(sorted(res.data['fields']), sorted(['type', 'status', 'assigned', 'tutor', 'slot', 'from', 'to', 'when', 'q']))
        self.assertNotIn('results', res.data)
        res = self.client.get(LIST_URL, {'from': '2026-11-02', 'to': '2026-11-01'})
        self.assertEqual((res.status_code, res.data['fields']), (status.HTTP_400_BAD_REQUEST, ['to']))
        # A well-formed id that matches nothing is simply an empty list.
        self.assertEqual(self.client.get(LIST_URL, {'tutor': str(uuid.uuid4())}).data['count'], 0)


class DetailTests(BookingAdminTestCase):
    def test_one_booking_in_full(self):
        booking = self.book('Riya', ref=link(self.bde).token)
        assign_tutor(booking, self.tutor_a, actor=self.admin)
        res = self.client.get(detail_url(booking))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual((data['id'], data['seat'], data['referral_status'], data['timezone']),
                         (str(booking.id), 1, 'ATTRIBUTED', 'Asia/Kolkata'))
        self.assertEqual(data['lead']['phone_dial_code'], '+971')
        self.assertEqual((data['lead']['school_name'], data['lead']['syllabus'], data['lead']['owner_bde']['id']),
                         ('Delhi Private School', 'CBSE', str(self.bde.id)))
        self.assertEqual((data['tutor']['id'], data['tutor_assigned_by']['id']), (str(self.tutor_a.id), str(self.admin.id)))
        self.assertIsNotNone(data['tutor_assigned_at'])
        self.assertEqual((data['tutor_changeable'], data['tutor_change_refusal']), (True, None))

        cancel_booking(booking, actor=self.admin, reason='Parent asked')
        data = self.client.get(detail_url(booking)).data
        self.assertEqual((data['status'], data['cancel_reason'], data['cancelled_by']['id']), ('CANCELLED', 'Parent asked', str(self.admin.id)))
        # Cancelled, it keeps its tutor as history, and the tutor can no longer change.
        self.assertEqual(data['tutor']['id'], str(self.tutor_a.id))
        self.assertEqual((data['tutor_changeable'], data['tutor_change_refusal']['code']), (False, 'BOOKING_CANCELLED'))

    def test_unknown_and_malformed_ids(self):
        res = self.client.get(f'{LIST_URL}{uuid.uuid4()}/')
        self.assertEqual((res.status_code, res.data['error']), (status.HTTP_404_NOT_FOUND, 'NOT_FOUND'))
        for path in (f'{LIST_URL}not-a-booking/', f'{LIST_URL}123/tutors/', f'{LIST_URL}slots/xyz/tutors/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, status.HTTP_404_NOT_FOUND)


class AvailabilityTests(BookingAdminTestCase):
    def setUp(self):
        super().setUp()
        self.tutor_c = account('tutor_chitra', role='TUTOR')
        self.booking = self.book('Riya')  # 19:30-20:30 IST
        # Anu teaches a class 19:00-20:00 IST; Binu another booking in the same slot.
        self.anus_class = self.class_for(self.tutor_a, self.ist(time(19, 0)), 'EDP71')
        self.other = self.book('Ali')
        assign_tutor(self.other, self.tutor_b, actor=self.admin)

    def statuses(self, data):
        return {row['full_name']: (row['status'], row['reason'] and row['reason']['code'], row['current']) for row in data['tutors']}

    def test_every_active_tutor_with_its_status_and_reason(self):
        res = self.client.get(tutors_url(self.booking))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Every active tutor, nobody else: not the deactivated one, the mentor or the admin.
        self.assertEqual(self.statuses(res.data), {
            'Tutor Anu': ('UNAVAILABLE', 'CLASS_CONFLICT', False),
            'Tutor Binu': ('UNAVAILABLE', 'BOOKING_CONFLICT', False),
            'Tutor Chitra': ('AVAILABLE', None, False),
        })
        reasons = {row['full_name']: row['reason'] for row in res.data['tutors']}
        self.assertEqual(reasons['Tutor Anu']['session_id'], str(self.anus_class.id))
        self.assertEqual(reasons['Tutor Binu']['booking_id'], str(self.other.id))
        self.assertIn('Teaching a class from 7:00 PM to 8:00 PM IST on', reasons['Tutor Anu']['message'])
        self.assertEqual(datetime.fromisoformat(reasons['Tutor Anu']['starts_at']), self.anus_class.start_time)
        # Neither the class's student nor the other booking's child is named.
        for private in ('Kid EDP71', 'Ali', 'Riya', 'Asha'):
            self.assertNotIn(private, json.dumps(res.data['tutors']))
        self.assertEqual((res.data['tutor_changeable'], res.data['slot']['id']), (True, str(self.booking.slot_id)))

    def test_the_current_tutor_is_marked_and_not_blocked_by_its_own_booking(self):
        assign_tutor(self.booking, self.tutor_c, actor=self.admin)
        statuses = self.statuses(self.client.get(tutors_url(self.booking)).data)
        self.assertEqual(statuses['Tutor Chitra'], ('AVAILABLE', None, True))
        # For the other booking in the slot, Chitra is taken.
        statuses = self.statuses(self.client.get(tutors_url(self.other)).data)
        self.assertEqual(statuses['Tutor Chitra'], ('UNAVAILABLE', 'BOOKING_CONFLICT', False))
        self.assertEqual(statuses['Tutor Binu'], ('AVAILABLE', None, True))

    def test_a_slot_on_its_own(self):
        res = self.client.get(slot_tutors_url(self.booking.slot_id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(self.statuses(res.data), {
            'Tutor Anu': ('UNAVAILABLE', 'CLASS_CONFLICT', False),
            'Tutor Binu': ('UNAVAILABLE', 'BOOKING_CONFLICT', False),
            'Tutor Chitra': ('AVAILABLE', None, False),
        })
        res = self.client.get(slot_tutors_url(uuid.uuid4()))
        self.assertEqual((res.status_code, res.data['error']), (status.HTTP_404_NOT_FOUND, 'NOT_FOUND'))

    def test_the_picker_agrees_with_the_assignment(self):
        rows = self.client.get(tutors_url(self.booking)).data['tutors']
        for row in rows:
            with self.subTest(tutor=row['full_name']):
                res = self.client.put(tutor_url(self.booking), {'tutor_id': row['id']}, format='json')
                self.assertEqual(res.status_code, status.HTTP_200_OK if row['status'] == 'AVAILABLE' else status.HTTP_409_CONFLICT)
                self.client.delete(tutor_url(self.booking))

    def test_a_booking_whose_tutor_cannot_change(self):
        cancel_booking(self.booking, actor=self.admin)
        res = self.client.get(tutors_url(self.booking))
        self.assertEqual((res.data['tutor_changeable'], res.data['tutor_change_refusal']['code']), (False, 'BOOKING_CANCELLED'))
        last_week = timezone.now() - timedelta(days=7)
        past = self.book('Old Kid', day=indian_today(last_week) + timedelta(days=1), now=last_week)
        res = self.client.get(tutors_url(past))
        self.assertEqual((res.data['slot']['ended'], res.data['tutor_change_refusal']['code']), (True, 'SLOT_STARTED'))


class AssignmentTests(BookingAdminTestCase):
    def setUp(self):
        super().setUp()
        self.booking = self.book('Riya')

    def put(self, tutor_id, booking=None):
        return self.client.put(tutor_url(booking or self.booking), {'tutor_id': str(tutor_id)}, format='json')

    def test_assign_reassign_and_unassign(self):
        res = self.put(self.tutor_a.id)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual((res.data['changed'], res.data['tutor']['id'], res.data['tutor_assigned_by']['id']),
                         (True, str(self.tutor_a.id), str(self.admin.id)))
        self.assertFalse(self.put(self.tutor_a.id).data['changed'])
        res = self.put(self.tutor_b.id)
        self.assertEqual((res.data['changed'], res.data['tutor']['id']), (True, str(self.tutor_b.id)))
        res = self.client.delete(tutor_url(self.booking))
        self.assertEqual((res.status_code, res.data['changed'], res.data['tutor']), (status.HTTP_200_OK, True, None))
        self.assertFalse(self.client.delete(tutor_url(self.booking)).data['changed'])
        self.booking.refresh_from_db()
        self.assertEqual((self.booking.assigned_tutor, self.booking.tutor_assigned_at), (None, None))

    def test_a_busy_tutor_is_refused_with_the_reason(self):
        self.class_for(self.tutor_a, self.ist(time(20, 0)), 'EDP81')
        res = self.put(self.tutor_a.id)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual((res.data['error'], res.data['conflict']['code']), ('TUTOR_UNAVAILABLE', 'CLASS_CONFLICT'))
        other = self.book('Ali')
        self.assertEqual(self.put(self.tutor_b.id, booking=other).status_code, status.HTTP_200_OK)
        res = self.put(self.tutor_b.id)
        self.assertEqual((res.data['error'], res.data['conflict']['code'], res.data['conflict']['booking_id']),
                         ('TUTOR_UNAVAILABLE', 'BOOKING_CONFLICT', str(other.id)))
        self.booking.refresh_from_db()
        self.assertIsNone(self.booking.assigned_tutor)

    def test_bad_tutor_ids_and_accounts(self):
        for body in ({}, {'tutor_id': 'not-an-id'}, {'tutor_id': None}):
            with self.subTest(body=body):
                res = self.client.put(tutor_url(self.booking), body, format='json')
                self.assertEqual((res.status_code, res.data['error']), (status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR'))
                self.assertIn('tutor_id', res.data['fields'])
        for who in (uuid.uuid4(), self.mentor.id, self.tutor_off.id, self.admin.id):
            with self.subTest(who=str(who)):
                res = self.put(who)
                self.assertEqual((res.status_code, res.data['error']), (status.HTTP_400_BAD_REQUEST, 'INVALID_TUTOR'))
        self.booking.refresh_from_db()
        self.assertIsNone(self.booking.assigned_tutor)

    def test_a_booking_whose_tutor_cannot_change(self):
        res = self.client.put(f'{LIST_URL}{uuid.uuid4()}/tutor/', {'tutor_id': str(self.tutor_a.id)}, format='json')
        self.assertEqual((res.status_code, res.data['error']), (status.HTTP_404_NOT_FOUND, 'NOT_FOUND'))
        cancel_booking(self.booking, actor=self.admin)
        res = self.put(self.tutor_a.id)
        self.assertEqual((res.status_code, res.data['error']), (status.HTTP_409_CONFLICT, 'BOOKING_CANCELLED'))
        res = self.client.delete(tutor_url(self.booking))
        self.assertEqual((res.status_code, res.data['error']), (status.HTTP_409_CONFLICT, 'BOOKING_CANCELLED'))
        last_week = timezone.now() - timedelta(days=7)
        past = self.book('Old Kid', day=indian_today(last_week) + timedelta(days=1), now=last_week)
        res = self.put(self.tutor_a.id, booking=past)
        self.assertEqual((res.status_code, res.data['error']), (status.HTTP_409_CONFLICT, 'SLOT_STARTED'))

    def test_the_activity_log_holds_ids_only(self):
        self.put(self.tutor_a.id)
        self.put(self.tutor_b.id)
        self.client.delete(tutor_url(self.booking))
        entries = ActivityLog.objects.filter(action__in=('booking.assign_tutor', 'booking.unassign_tutor'), entity_id=str(self.booking.id))
        self.assertEqual(entries.count(), 3)
        for entry in entries:
            self.assertEqual(entry.actor, self.admin)
            self.assertEqual(set(entry.context), {'booking_type', 'slot_starts_at', 'lead_id', 'old_tutor_id', 'new_tutor_id'})
            recorded = json.dumps([entry.entity_label, entry.changes, entry.context])
            for private in (*PRIVATE, 'Riya', self.booking.lead.phone_number, self.tutor_a.full_name, self.tutor_a.email,
                            self.tutor_b.full_name, self.tutor_b.email):
                self.assertNotIn(private, recorded)


class PermissionTests(BookingAdminTestCase):
    """Only holders of the booking-management permissions reach any of it; nobody else learns a thing."""

    def setUp(self):
        super().setUp()
        self.booking = self.book('Riya')
        self.callers = {
            'mentor': self.mentor, 'tutor': self.tutor_a, 'bde': self.bde,
            'sales_tl': account('sales_one', role='SALES_TL'), 'student': account('parent_one', role='STUDENT'),
            'unknown': account('nobody_one', role='UNASSIGNED'),
        }

    def calls(self):
        body = {'tutor_id': str(self.tutor_a.id)}
        return [
            ('get', LIST_URL, None), ('get', detail_url(self.booking), None), ('get', tutors_url(self.booking), None),
            ('get', slot_tutors_url(self.booking.slot_id), None),
            ('put', tutor_url(self.booking), body), ('delete', tutor_url(self.booking), None),
        ]

    def test_every_other_role_and_anonymous_are_refused(self):
        clients = {name: APIClient() for name in self.callers}
        for name, user in self.callers.items():
            clients[name].force_authenticate(user=user)
        clients['anonymous'] = APIClient()
        for name, client in clients.items():
            for method, url, body in self.calls():
                with self.subTest(caller=name, call=f'{method.upper()} {url}'):
                    res = getattr(client, method)(url, body, format='json')
                    self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
                    for private in ('Riya', 'Asha', str(self.booking.id)):
                        self.assertNotIn(private, json.dumps(res.data))
        self.booking.refresh_from_db()
        self.assertIsNone(self.booking.assigned_tutor)
        self.assertFalse(ActivityLog.objects.filter(action='booking.assign_tutor').exists())

    def test_reading_and_assigning_need_their_own_permissions(self):
        # A mentor given one permission directly is still refused: only the ADMIN role may hold either.
        for codename in ('view_all_bookings', 'assign_booking_tutor'):
            self.mentor.user_permissions.add(Permission.objects.get(codename=codename))
        client = APIClient()
        client.force_authenticate(user=User.objects.get(pk=self.mentor.pk))
        self.assertEqual(client.get(LIST_URL).status_code, status.HTTP_403_FORBIDDEN)
        # GET is not a way to change the tutor, even for an administrator.
        self.assertEqual(self.client.get(tutor_url(self.booking)).status_code, status.HTTP_403_FORBIDDEN)

    def test_superusers_whatever_their_role(self):
        for role in ('MENTOR', 'TUTOR', 'ADMIN'):
            superuser = account(f'su_{role.lower()}', role=role, is_superuser=True)
            client = APIClient()
            client.force_authenticate(user=superuser)
            for method, url, body in self.calls():
                with self.subTest(role=role, call=f'{method.upper()} {url}'):
                    self.assertEqual(getattr(client, method)(url, body, format='json').status_code, status.HTTP_200_OK)

    def test_the_bde_workspace_is_unchanged(self):
        credited = self.book('Ali', ref=link(self.bde).token)
        assign_tutor(credited, self.tutor_b, actor=self.admin)
        client = APIClient()
        client.force_authenticate(user=self.bde)
        enquiry = client.get(f'/api/bde/enquiries/{credited.lead_id}/')
        self.assertEqual(enquiry.status_code, status.HTTP_200_OK)
        # The BDE sees its enquiry's booking, not who teaches it.
        self.assertNotIn('tutor', json.dumps(enquiry.data))
        self.assertEqual(client.get('/api/bde/dashboard/').status_code, status.HTTP_200_OK)
