"""
The public booking API (DEVT-5935): service-key authentication, the calendar
and booking contracts, the error codes and the rate limits.
"""
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from .booking_service import BookingBusy
from .models import Booking, BookingType, Lead, ReferralStatus
from .scheduling import booking_window
from .tests_booking import account, link, schedule
from .throttles import BookingCreateThrottle

KEY = 'k' * 40
OTHER_KEY = 'o' * 40
CALENDAR = '/api/public/booking-calendar/{}/'
BOOK = '/api/public/bookings/{}/'


@override_settings(BOOKING_SERVICE_API_KEYS=[KEY])
class PublicApiTestCase(APITestCase):
    def setUp(self):
        cache.clear()  # the rate limits count here
        schedule()
        self.window = booking_window(BookingType.DEMO)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {KEY}', HTTP_X_BOOKING_CLIENT_IP='203.0.113.7')

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def body(self, **overrides):
        values = {
            'date': self.window[0].isoformat(), 'time': '19:30', 'parent_name': 'Asha Nair', 'student_name': 'Riya',
            'phone': {'dial_code': '+971', 'number': '0501234567'}, 'school': 'Delhi Private School',
            'student_class': 'Class 8', 'syllabus': 'CBSE', 'country': 'United Arab Emirates',
            'display_time': '06:00 pm - 07:00 pm',
        }
        values.update(overrides)
        return values

    def post(self, booking_type='demo', **overrides):
        return self.client.post(BOOK.format(booking_type), self.body(**overrides), format='json')


class CalendarTests(PublicApiTestCase):
    def test_the_calendar(self):
        self.post()
        res = self.client.get(CALENDAR.format('demo'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Cache-Control'], 'no-store')
        data = res.json()
        self.assertEqual(
            {key: data[key] for key in ('booking_type', 'timezone', 'slot_minutes', 'capacity')},
            {'booking_type': 'DEMO', 'timezone': 'Asia/Kolkata', 'slot_minutes': 60, 'capacity': 3},
        )
        self.assertEqual([day['date'] for day in data['dates']], [day.isoformat() for day in self.window])
        self.assertEqual(data['dates'][0], {
            'date': self.window[0].isoformat(), 'status': 'Filling Fast',
            'slots': [{'time': '10:00', 'status': 'Available'}, {'time': '19:30', 'status': 'Filling Fast'}],
        })
        self.assertEqual(self.client.get(CALENDAR.format('diagnostic')).json()['dates'][0]['status'], 'Available')

    def test_an_unknown_booking_type_is_not_found(self):
        self.assertEqual(self.client.get(CALENDAR.format('webinar')).status_code, 404)
        self.assertEqual(self.post('webinar').status_code, 404)


class BookingTests(PublicApiTestCase):
    def test_a_booking_and_its_repeat(self):
        first = self.post()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(set(first.json()), {'booking_id', 'created'})
        again = self.post(phone={'dial_code': '+971', 'number': '501234567'})
        self.assertEqual((again.status_code, again.json()), (200, {'booking_id': first.json()['booking_id'], 'created': False}))
        self.assertEqual(Booking.objects.count(), 1)

    def test_only_the_ref_token_attributes_and_forged_fields_are_ignored(self):
        bde, other = account('bde_one'), account('bde_two')
        forged = {'bde_id': str(other.pk), 'attributed_bde': str(other.pk), 'owner_bde': str(other.pk),
                  'referral_status': 'ATTRIBUTED'}
        res = self.post(ref=link(bde).token, **forged)
        self.assertEqual(res.status_code, 201)
        self.assertEqual((Booking.objects.get().attributed_bde, Lead.objects.get().owner_bde), (bde, bde))
        res = self.post(student_name='Ali', **forged)
        booking = Booking.objects.get(pk=res.json()['booking_id'])
        self.assertEqual((booking.referral_status, booking.attributed_bde), (ReferralStatus.NO_REF, None))

    def test_a_ref_of_any_shape_never_blocks_the_booking(self):
        for offset, ref in enumerate((12345, {'token': 'x'}, ['x'], 'x' * 500, 'not a token')):
            with self.subTest(ref=str(ref)[:12]):
                res = self.post(student_name=f'Child {offset}', date=self.window[offset].isoformat(), ref=ref)
                self.assertEqual(res.status_code, 201, res.content)
                booking = Booking.objects.get(pk=res.json()['booking_id'])
                self.assertEqual(booking.referral_status, ReferralStatus.INVALID_REF)

    def test_invalid_details_are_refused_with_their_fields(self):
        cases = [
            ({'student_name': ''}, 'student_name'),
            # 255 characters, but NFKC makes each of these 18 letters long.
            ({'student_name': 'ﷺ' * 255}, 'student_name'),
            ({'student_class': 'Class 4'}, 'student_class'),
            ({'syllabus': 'IB'}, 'syllabus'),
            ({'phone': {'dial_code': '+971', 'number': '123'}}, 'phone'),
            ({'phone': {'dial_code': '971', 'number': '0501234567'}}, 'phone'),
            ({'date': '28/10/2026'}, 'date'),
            ({'time': '7:30 pm'}, 'time'),
        ]
        for overrides, field in cases:
            with self.subTest(field=field, overrides=overrides):
                res = self.post(**overrides)
                self.assertEqual((res.status_code, res.json()['error']), (400, 'VALIDATION_ERROR'))
                self.assertIn(field, res.json()['fields'])
        body = self.body()
        del body['school']
        self.assertIn('school', self.client.post(BOOK.format('demo'), body, format='json').json()['fields'])
        # The Diagnostic page offers more syllabi than the Demo page.
        self.assertEqual(self.post('diagnostic', syllabus='IB').status_code, 201)
        self.assertEqual(Booking.objects.count(), 1)

    def test_the_error_codes(self):
        today = self.post(date=(self.window[0] - timedelta(days=1)).isoformat())
        self.assertEqual((today.status_code, today.json()), (400, {
            'error': 'DATE_OUT_OF_WINDOW', 'message': 'That date is not available for booking. Please pick another.',
        }))
        not_offered = self.post(time='11:00')
        self.assertEqual((not_offered.status_code, not_offered.json()['error']), (409, 'SLOT_UNAVAILABLE'))
        for name in ('A', 'B', 'C'):
            self.post(student_name=name)
        full = self.post(student_name='D')
        self.assertEqual((full.status_code, full.json()), (409, {
            'error': 'SLOT_FULL', 'message': 'This slot is fully booked. Please choose another time.',
        }))
        with mock.patch('bookings.public_views.create_booking', side_effect=BookingBusy()):
            busy = self.post(student_name='E')
        self.assertEqual((busy.status_code, busy.json()['error']), (503, 'CAPACITY_CHECK_UNAVAILABLE'))

    @override_settings(BOOKING_PHONE_DAILY_LIMIT=1)
    def test_one_phone_number_has_a_daily_limit(self):
        self.assertEqual(self.post().status_code, 201)
        res = self.post(student_name='Ali', time='10:00')
        self.assertEqual((res.status_code, res.json()['error']), (429, 'TOO_MANY_BOOKINGS'))

    def test_bookings_are_rate_limited_per_parent_address(self):
        with mock.patch.object(BookingCreateThrottle, 'rate', '2/min', create=True):
            allowed = [self.post(student_name=name).status_code for name in ('A', 'B')]
            limited = self.post(student_name='C')
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {KEY}', HTTP_X_BOOKING_CLIENT_IP='198.51.100.9')
            elsewhere = self.post(student_name='C')
        self.assertEqual((allowed, limited.status_code, elsewhere.status_code), ([201, 201], 429, 201))


class ServiceAuthTests(PublicApiTestCase):
    def test_no_key_or_a_wrong_one_is_refused(self):
        for header in (None, 'Bearer wrong', f'Bearer {KEY} extra', f'Token {KEY}', f'bearer{KEY}'):
            with self.subTest(header=header and header[:12]):
                self.client.credentials(**({'HTTP_AUTHORIZATION': header} if header else {}))
                for res in (self.client.get(CALENDAR.format('demo')), self.post()):
                    self.assertEqual(res.status_code, 401)
                    self.assertIn('Bearer', res['WWW-Authenticate'])
        self.assertFalse(Booking.objects.exists())

    def test_signed_in_accounts_are_refused(self):
        self.client.credentials()
        for role in ('ADMIN', 'BDE'):
            with self.subTest(role=role):
                self.client.force_authenticate(account(f'signed_{role.lower()}', role=role, is_superuser=role == 'ADMIN'))
                self.assertEqual(self.client.get(CALENDAR.format('demo')).status_code, 403)
                self.assertEqual(self.post().status_code, 403)
        self.assertFalse(Booking.objects.exists())

    def test_keys_rotate_and_no_usable_key_refuses_everyone(self):
        with override_settings(BOOKING_SERVICE_API_KEYS=[OTHER_KEY, KEY]):
            for key in (OTHER_KEY, KEY):
                self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {key}')
                self.assertEqual(self.client.get(CALENDAR.format('demo')).status_code, 200)
        with override_settings(BOOKING_SERVICE_API_KEYS=[]):
            self.assertEqual(self.client.get(CALENDAR.format('demo')).status_code, 401)
        with override_settings(BOOKING_SERVICE_API_KEYS=['short']), self.assertLogs('bookings.authentication', 'WARNING'):
            self.client.credentials(HTTP_AUTHORIZATION='Bearer short')
            self.assertEqual(self.client.get(CALENDAR.format('demo')).status_code, 401)
