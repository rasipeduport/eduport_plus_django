"""
My Bookings for tutors (/api/tutor/bookings/, bookings.tutor_bookings and
bookings.tutor_views): the Demo and Diagnostic bookings assigned to the caller
now -- booked or cancelled, with the child and the slot only -- for holders of
accounts.view_assigned_bookings (the TUTOR role) only, and never a booking
assigned to anyone else.
"""
import json
import uuid
from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .booking_service import assign_tutor, cancel_booking, create_booking, unassign_tutor
from .models import BookingType
from .scheduling import indian_today
from .tests_booking import EVENING, MORNING, account, link, request, schedule

DEMO, DIAGNOSTIC = BookingType.DEMO, BookingType.DIAGNOSTIC
LIST_URL = '/api/tutor/bookings/'
# Everything a tutor is shown of a booking, and of its slot.
ROW_FIELDS = {'id', 'booking_type', 'status', 'slot', 'student_name', 'grade', 'syllabus', 'school_name', 'country'}
SLOT_FIELDS = {'date', 'time', 'starts_at', 'ends_at', 'started', 'ended'}
NOT_FOUND = {'error': 'NOT_FOUND', 'message': 'No such booking.'}


def detail_url(booking):
    return f'{LIST_URL}{getattr(booking, "id", booking)}/'


class TutorBookingsTestCase(APITestCase):
    def setUp(self):
        schedule()
        self.admin = account('admin_one', role='ADMIN')
        self.tutor_a = account('tutor_anu', role='TUTOR')
        self.tutor_b = account('tutor_binu', role='TUTOR')
        self.bde = account('bde_one', role='BDE')
        # Inside the booking window (tomorrow through six days on), and still ahead.
        self.day = indian_today() + timedelta(days=2)
        self.phones = iter(f'05077700{n:02d}' for n in range(80))

    def book(self, student, booking_type=DEMO, at=EVENING, day=None, now=None, tutor=None, **kwargs):
        booking, _ = create_booking(
            request(student=student, phone=next(self.phones), booking_type=booking_type, day=day or self.day, at=at, **kwargs),
            now=now,
        )
        if tutor is not None:
            booking, _ = assign_tutor(booking, tutor, actor=self.admin, now=now)
        return booking

    def get(self, user, url, params=None):
        self.client.force_authenticate(user=user)
        return self.client.get(url, params or {})

    def ids(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return [row['id'] for row in response.data['results']]


class ListTests(TutorBookingsTestCase):
    def test_a_tutor_lists_the_bookings_assigned_to_them_soonest_first(self):
        evening = self.book('Riya', tutor=self.tutor_a)
        morning = self.book('Ali', booking_type=DIAGNOSTIC, at=MORNING, tutor=self.tutor_a)
        next_day = self.book('Sara', day=self.day + timedelta(days=1), tutor=self.tutor_a)
        theirs = self.book('Zoya', at=MORNING, tutor=self.tutor_b)
        self.book('Noor', day=self.day + timedelta(days=1), at=MORNING)  # nobody's yet

        res = self.get(self.tutor_a, LIST_URL)
        self.assertEqual(self.ids(res), [str(morning.id), str(evening.id), str(next_day.id)])
        self.assertEqual((res.data['count'], res.data['page'], res.data['page_size'], res.data['timezone']),
                         (3, 1, 25, 'Asia/Kolkata'))
        self.assertEqual(res.data['results'][1], {
            'id': str(evening.id),
            'booking_type': DEMO,
            'status': 'BOOKED',
            'slot': {
                'date': self.day.isoformat(),
                'time': '19:30',
                'starts_at': evening.slot.starts_at.isoformat(),
                'ends_at': evening.slot.ends_at.isoformat(),
                'started': False,
                'ended': False,
            },
            'student_name': 'Riya',
            'grade': 'Class 8',
            'syllabus': 'CBSE',
            'school_name': 'Delhi Private School',
            'country': 'United Arab Emirates',
        })
        self.assertEqual(self.ids(self.get(self.tutor_b, LIST_URL)), [str(theirs.id)])

    def test_paged(self):
        bookings = [self.book(name, day=self.day + timedelta(days=days), tutor=self.tutor_a)
                    for days, name in enumerate(('Riya', 'Ali', 'Sara'))]
        page_two = self.get(self.tutor_a, LIST_URL, {'page': 2, 'page_size': 2})
        self.assertEqual((page_two.data['count'], page_two.data['page_size'], self.ids(page_two)),
                         (3, 2, [str(bookings[2].id)]))
        # Unusable paging falls back to the defaults and the 200-row cap, as everywhere in the API.
        self.assertEqual(self.get(self.tutor_a, LIST_URL, {'page': 'x'}).data['page'], 1)
        self.assertEqual(self.get(self.tutor_a, LIST_URL, {'page_size': 5000}).data['page_size'], 200)
        self.assertEqual(self.get(self.tutor_a, LIST_URL, {'page': 9}).data['results'], [])

    def test_upcoming_by_default_or_past_or_all_and_by_type(self):
        demo = self.book('Riya', tutor=self.tutor_a)
        diagnostic = self.book('Ali', booking_type=DIAGNOSTIC, at=MORNING, tutor=self.tutor_a)
        last_week = timezone.now() - timedelta(days=7)
        old_day = indian_today(last_week) + timedelta(days=1)
        past_evening = self.book('Old Kid', day=old_day, now=last_week, tutor=self.tutor_a)
        past_morning = self.book('Older Kid', day=old_day, at=MORNING, now=last_week, tutor=self.tutor_a)

        def listed(**params):
            return self.ids(self.get(self.tutor_a, LIST_URL, params))

        upcoming = [str(diagnostic.id), str(demo.id)]
        self.assertEqual(listed(), upcoming)
        self.assertEqual(listed(when='upcoming'), upcoming)
        # Past: most recent first.
        self.assertEqual(listed(when='past'), [str(past_evening.id), str(past_morning.id)])
        everything = [str(past_morning.id), str(past_evening.id), str(diagnostic.id), str(demo.id)]
        self.assertEqual(listed(when='all'), everything)
        self.assertEqual(listed(when=' ALL '), everything)
        self.assertEqual(listed(type='diagnostic'), [str(diagnostic.id)])
        self.assertEqual(listed(type='DEMO', when='all'), [str(past_morning.id), str(past_evening.id), str(demo.id)])
        # Blank values are unset ones.
        self.assertEqual(listed(type='', when=''), upcoming)

        ended = self.get(self.tutor_a, LIST_URL, {'when': 'past'}).data['results'][0]['slot']
        self.assertEqual((ended['date'], ended['time'], ended['started'], ended['ended']),
                         (old_day.isoformat(), '19:30', True, True))

    def test_unknown_filter_values_are_refused_not_guessed(self):
        self.book('Riya', tutor=self.tutor_a)
        res = self.get(self.tutor_a, LIST_URL, {'type': 'tuition', 'when': 'tomorrow'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': 'INVALID_INPUT', 'message': 'Check the booking filters.',
                                    'fields': ['type', 'when']})

    def test_the_list_reads_the_same_queries_however_many_bookings(self):
        self.book('Riya', tutor=self.tutor_a)

        def queries():
            with CaptureQueriesContext(connection) as captured:
                self.assertEqual(self.get(self.tutor_a, LIST_URL).status_code, status.HTTP_200_OK)
            return len(captured)

        one = queries()
        self.book('Ali', booking_type=DIAGNOSTIC, at=MORNING, tutor=self.tutor_a)
        self.book('Sara', day=self.day + timedelta(days=1), tutor=self.tutor_a)
        self.assertEqual(queries(), one)


class DetailTests(TutorBookingsTestCase):
    def test_one_booking_of_their_own_and_no_other(self):
        mine = self.book('Riya', tutor=self.tutor_a)
        theirs = self.book('Ali', at=MORNING, tutor=self.tutor_b)
        nobodys = self.book('Sara', day=self.day + timedelta(days=1))

        res = self.get(self.tutor_a, detail_url(mine))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual((res.data['id'], res.data['student_name'], res.data['timezone']),
                         (str(mine.id), 'Riya', 'Asia/Kolkata'))
        # Another tutor's booking, an unassigned one and one that does not
        # exist are answered alike: nothing tells them apart.
        for other in (theirs, nobodys, uuid.uuid4()):
            with self.subTest(booking=str(getattr(other, 'id', other))):
                res = self.get(self.tutor_a, detail_url(other))
                self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
                self.assertEqual(res.data, NOT_FOUND)

    def test_the_row_and_the_detail_show_the_same_booking(self):
        booking = self.book('Riya', booking_type=DIAGNOSTIC, syllabus='IGCSE', tutor=self.tutor_a)
        row = self.get(self.tutor_a, LIST_URL).data['results'][0]
        detail = self.get(self.tutor_a, detail_url(booking)).data
        self.assertEqual(detail, {**row, 'timezone': 'Asia/Kolkata'})
        self.assertEqual((row['booking_type'], row['syllabus']), (DIAGNOSTIC, 'IGCSE'))


class OwnershipTests(TutorBookingsTestCase):
    def test_a_booking_reassigned_away_or_unassigned_is_no_longer_theirs(self):
        booking = self.book('Riya', tutor=self.tutor_a)
        self.assertEqual(self.get(self.tutor_a, detail_url(booking)).status_code, status.HTTP_200_OK)

        assign_tutor(booking, self.tutor_b, actor=self.admin)
        self.assertEqual(self.ids(self.get(self.tutor_a, LIST_URL, {'when': 'all'})), [])
        self.assertEqual(self.get(self.tutor_a, detail_url(booking)).data, NOT_FOUND)
        self.assertEqual(self.ids(self.get(self.tutor_b, LIST_URL)), [str(booking.id)])
        self.assertEqual(self.get(self.tutor_b, detail_url(booking)).status_code, status.HTTP_200_OK)

        unassign_tutor(booking, actor=self.admin)
        self.assertEqual(self.ids(self.get(self.tutor_b, LIST_URL, {'when': 'all'})), [])
        self.assertEqual(self.get(self.tutor_b, detail_url(booking)).data, NOT_FOUND)

    def test_a_cancelled_booking_keeps_its_tutor_and_shows_as_cancelled(self):
        booking = self.book('Riya', tutor=self.tutor_a)
        cancel_booking(booking, actor=self.admin, reason='Parent asked to move it')

        listed = self.get(self.tutor_a, LIST_URL)
        self.assertEqual(self.ids(listed), [str(booking.id)])
        self.assertEqual(listed.data['results'][0]['status'], 'CANCELLED')
        shown = self.get(self.tutor_a, detail_url(booking))
        self.assertEqual((shown.data['status'], set(shown.data)), ('CANCELLED', ROW_FIELDS | {'timezone'}))
        # Neither why it was cancelled nor by whom.
        body = json.dumps(listed.json()) + json.dumps(shown.json())
        for private in ('Parent asked', str(self.admin.id), self.admin.full_name):
            with self.subTest(private=private):
                self.assertNotIn(private, body)

    def test_nothing_in_the_request_chooses_the_tutor(self):
        mine = self.book('Riya', tutor=self.tutor_b)
        theirs = self.book('Ali', at=MORNING, tutor=self.tutor_a)
        someone = str(self.tutor_a.id)
        res = self.get(self.tutor_b, LIST_URL, {
            'tutor': someone, 'tutor_id': someone, 'assigned_tutor': someone, 'assigned': 'false', 'q': 'Ali',
        })
        self.assertEqual(self.ids(res), [str(mine.id)])
        self.assertEqual(self.get(self.tutor_b, detail_url(theirs), {'tutor': someone}).data, NOT_FOUND)

    def test_a_superuser_lists_only_the_bookings_they_teach(self):
        booking = self.book('Riya', tutor=self.tutor_a)
        root = account('root_admin', role='ADMIN', is_superuser=True, is_staff=True)
        res = self.get(root, LIST_URL, {'when': 'all'})
        self.assertEqual((self.ids(res), res.data['count']), ([], 0))
        self.assertEqual(self.get(root, detail_url(booking)).data, NOT_FOUND)

        # A superuser with the TUTOR role may be given one to teach, and sees that one only.
        su_tutor = account('root_tutor', role='TUTOR', is_superuser=True)
        theirs = self.book('Ali', at=MORNING, tutor=su_tutor)
        self.assertEqual(self.ids(self.get(su_tutor, LIST_URL)), [str(theirs.id)])
        self.assertEqual(self.get(su_tutor, detail_url(booking)).data, NOT_FOUND)


class PrivacyTests(TutorBookingsTestCase):
    def test_nothing_but_the_child_and_the_slot_reaches_the_tutor(self):
        booking = self.book('Riya', ref=link(self.bde).token, tutor=self.tutor_a)
        booking.refresh_from_db()
        lead = booking.lead
        self.assertEqual((booking.attributed_bde, booking.tutor_assigned_by), (self.bde, self.admin))

        listed = self.get(self.tutor_a, LIST_URL)
        shown = self.get(self.tutor_a, detail_url(booking))
        row = listed.data['results'][0]
        self.assertEqual(set(row), ROW_FIELDS)
        self.assertEqual(set(row['slot']), SLOT_FIELDS)
        self.assertEqual(set(shown.data), ROW_FIELDS | {'timezone'})
        self.assertEqual(set(shown.data['slot']), SLOT_FIELDS)

        # Not the parent, the submission, the lead, the slot's id, the BDE or
        # the referral, nor who assigned the tutor -- by value, and by key
        # (keys only: "bde" could be part of an id).
        body = json.dumps(listed.json()) + json.dumps(shown.json())
        for private in (
            lead.parent_name, lead.phone_number, lead.phone_key, booking.details['phone'],
            booking.details['display_time'], str(lead.id), str(booking.slot_id),
            str(self.bde.id), self.bde.full_name, booking.referral_status,
            str(self.admin.id), self.admin.full_name, booking.tutor_assigned_at.isoformat(),
        ):
            with self.subTest(private=private):
                self.assertNotIn(private, body)
        keys = ' '.join(sorted(set(row) | set(row['slot']) | set(shown.data)))
        for word in ('parent', 'phone', 'details', 'bde', 'referral', 'seat', 'assigned', 'cancel', 'lead', 'source'):
            with self.subTest(key=word):
                self.assertNotIn(word, keys)


class AccessTests(TutorBookingsTestCase):
    def test_only_the_tutor_role_holds_it(self):
        booking = self.book('Riya', tutor=self.tutor_a)
        refused = {
            'admin': self.admin,
            'mentor': account('mentor_one', role='MENTOR'),
            'bde': self.bde,
            'sales_tl': account('sales_tl_one', role='SALES_TL'),
            'student': account('student_one', role='STUDENT'),
            'unknown role': account('nobody_one', role='UNASSIGNED'),
            'deactivated tutor': account('tutor_off', role='TUTOR', is_active=False, deactivated_at=timezone.now()),
        }
        for label, user in refused.items():
            for url in (LIST_URL, detail_url(booking)):
                with self.subTest(caller=label, url=url):
                    self.assertEqual(self.get(user, url).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=None)
        for url in (LIST_URL, detail_url(booking)):
            with self.subTest(caller='anonymous', url=url):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_read_only(self):
        booking = self.book('Riya', tutor=self.tutor_a)
        self.client.force_authenticate(user=self.tutor_a)
        for method, url in (('post', LIST_URL), ('put', detail_url(booking)), ('patch', detail_url(booking)),
                            ('delete', detail_url(booking))):
            with self.subTest(method=method, url=url):
                res = getattr(self.client, method)(url, {'tutor_id': str(self.tutor_b.id)}, format='json')
                self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        booking.refresh_from_db()
        self.assertEqual(booking.assigned_tutor, self.tutor_a)
