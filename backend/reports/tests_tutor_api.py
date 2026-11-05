"""
The tutor's report APIs (reports.tutor_views, design E.1): read, submit, edit
and history on an assigned booking; who reaches them; the payload rules; every
error answer; and that nothing a tutor is sent names the parent.
"""
import json
import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.booking_service import assign_tutor, cancel_booking, create_booking
from bookings.models import BookingStatus, CancelReason, DemoBooking
from bookings.scheduling import indian_today
from bookings.tests_booking import DIAGNOSTIC, EVENING, MORNING, account, request, schedule, start

from .models import DemoReport, DiagnosticReport
from .services import ReportBusy
from .tests_services import demo_input, diagnostic_input, report_input

REPORT_KEYS = {
    'id', 'booking_id', 'booking_type', 'version', 'fields', 'student_name', 'grade', 'tutor_name', 'submitted_at',
    'updated_at',
}
# What a tutor is never sent: the parent, the lead, the submission, the BDE.
PRIVATE_KEYS = {
    'parent_name', 'phone', 'phone_number', 'phone_dial_code', 'phone_key', 'lead', 'lead_id', 'details',
    'owner_bde', 'attributed_bde', 'referral_status', 'referral_link', 'bde',
}
PRIVATE_VALUES = ('Asha', '501234567', '+971')


def path_type(booking):
    return 'diagnostic' if booking.booking_type == DIAGNOSTIC else 'demo'


def report_url(booking, suffix=''):
    return f'/api/tutor/bookings/{path_type(booking)}/{booking.id}/report/{suffix}'


def detail_url(booking):
    return f'/api/tutor/bookings/{path_type(booking)}/{booking.id}/'


def keys_of(value):
    """Every key anywhere in a JSON value."""
    if isinstance(value, dict):
        return set(value) | set().union(*(keys_of(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(keys_of(item) for item in value)) if value else set()
    return set()


class TutorReportApiTestCase(APITestCase):
    def setUp(self):
        schedule()
        self.tutor = account('tutor_anu', role='TUTOR')
        self.other_tutor = account('tutor_binu', role='TUTOR')
        # Booked three days ago for yesterday, and taught: both started by their tutor, both slots over.
        then = timezone.now() - timedelta(days=3)
        yesterday = indian_today() - timedelta(days=1)
        self.demo = self.assigned(create_booking(request(day=yesterday, at=EVENING), now=then)[0], then)
        self.diagnostic = self.assigned(
            create_booking(request(booking_type=DIAGNOSTIC, day=yesterday, at=MORNING), now=then)[0], then,
        )
        self.client.force_authenticate(self.tutor)

    def assigned(self, booking, now, tutor=None):
        """``booking`` given to ``tutor``; one whose slot is already past was taught, so its tutor started it."""
        booking = assign_tutor(booking, tutor or self.tutor, now=now)[0]
        return start(booking) if booking.slot.starts_at <= timezone.now() else booking

    def upcoming(self, student='Ali', at=EVENING):
        """A Demo, assigned to the tutor, whose slot is two days away."""
        made = create_booking(
            request(student=student, day=indian_today() + timedelta(days=2), at=at), now=timezone.now(),
        )[0]
        return self.assigned(made, timezone.now())

    def submit(self, booking, **changes):
        return self.client.post(report_url(booking), report_input(booking, **changes), format='json')

    def edit(self, booking, version, **changes):
        return self.client.put(report_url(booking), {'version': version, **report_input(booking, **changes)}, format='json')


class TutorReportFlowTests(TutorReportApiTestCase):
    def test_submit_read_edit_and_history_for_each_type(self):
        for booking in (self.diagnostic, self.demo):
            with self.subTest(booking_type=booking.booking_type):
                missing = self.client.get(report_url(booking))
                self.assertEqual((missing.status_code, missing.json()['error']), (404, 'NO_REPORT'))

                submitted = self.submit(booking)
                self.assertEqual(submitted.status_code, 201, submitted.content)
                report, completed = submitted.json()['report'], submitted.json()['booking']
                self.assertEqual(set(report), REPORT_KEYS)
                self.assertEqual((report['version'], report['fields']), (1, report_input(booking)))
                self.assertEqual(
                    (report['student_name'], report['grade'], report['tutor_name'], report['booking_type']),
                    ('Riya', '8', 'Tutor Anu', booking.booking_type),
                )
                self.assertEqual(completed, {
                    'id': str(booking.id), 'booking_type': booking.booking_type, 'status': 'COMPLETED',
                    'completed_at': report['submitted_at'],
                })
                self.assertEqual(self.client.get(report_url(booking)).json(), report)

                first_field = next(iter(report['fields']))
                changes = {first_field: 20} if first_field == 'score' else {first_field: 'Revised after the session.'}
                edited = self.edit(booking, 1, **changes)
                self.assertEqual(edited.status_code, 200, edited.content)
                self.assertEqual((edited.json()['changed'], edited.json()['report']['version']), (True, 2))
                self.assertEqual(edited.json()['booking']['status'], 'COMPLETED')

                unchanged = self.edit(booking, 2, **changes)
                self.assertEqual((unchanged.status_code, unchanged.json()['changed']), (200, False))
                self.assertEqual(unchanged.json()['report']['version'], 2)

                history = self.client.get(report_url(booking, 'revisions/')).json()
                self.assertEqual((history['count'], history['version']), (2, 2))
                first, second = history['results']
                self.assertEqual((first['version'], first['fields']), (1, report_input(booking)))
                self.assertEqual(first['changed_fields'], list(report['fields']))
                self.assertEqual((second['version'], second['changed_fields']), (2, [first_field]))
                self.assertEqual(second['edited_by']['name'], 'Tutor Anu')

    def test_the_list_and_the_detail_say_whether_a_report_is_due_or_done(self):
        upcoming = self.upcoming()

        def rows():
            listed = self.client.get('/api/tutor/bookings/', {'when': 'all'}).json()['results']
            return {row['id']: (row['has_report'], row['report_version'], row['report_due']) for row in listed}

        self.assertEqual(rows(), {
            str(self.demo.id): (False, None, True), str(self.diagnostic.id): (False, None, True),
            str(upcoming.id): (False, None, False),
        })
        self.submit(self.demo)
        self.assertEqual(rows()[str(self.demo.id)], (True, 1, False))
        detail = self.client.get(detail_url(self.demo)).json()
        self.assertEqual((detail['status'], detail['has_report'], detail['report_version'], detail['report_due']),
                         ('COMPLETED', True, 1, False))


class TutorReportAccessTests(TutorReportApiTestCase):
    def requests(self, booking):
        return {
            'read': lambda: self.client.get(report_url(booking)),
            'submit': lambda: self.submit(booking),
            'edit': lambda: self.edit(booking, 1),
            'revisions': lambda: self.client.get(report_url(booking, 'revisions/')),
        }

    def test_only_the_assigned_tutor_reaches_the_booking(self):
        self.submit(self.diagnostic)
        self.client.force_authenticate(self.other_tutor)
        for booking in (self.demo, self.diagnostic):
            for name, send in self.requests(booking).items():
                with self.subTest(booking_type=booking.booking_type, request=name):
                    response = send()
                    self.assertEqual((response.status_code, response.json()['error']), (404, 'NOT_FOUND'))
        self.assertEqual(DiagnosticReport.objects.get().version, 1)
        self.assertFalse(DemoReport.objects.exists())

        self.client.force_authenticate(self.tutor)
        unassigned = create_booking(request(student='Sara', day=indian_today() + timedelta(days=2)), now=timezone.now())[0]
        wrong_type = f'/api/tutor/bookings/demo/{self.diagnostic.id}/report/'
        for url in (report_url(unassigned), wrong_type, f'/api/tutor/bookings/demo/{uuid.uuid4()}/report/'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(f'/api/tutor/bookings/webinar/{self.demo.id}/report/').status_code, 404)

    def test_other_roles_are_refused_and_a_superuser_teaches_nothing(self):
        for role in ('ADMIN', 'MENTOR', 'BDE', 'SALES_TL'):
            self.client.force_authenticate(account(f'{role.lower()}_one', role=role))
            for name, send in self.requests(self.demo).items():
                with self.subTest(role=role, request=name):
                    self.assertEqual(send().status_code, 403)
        self.client.force_authenticate(None)
        for name, send in self.requests(self.demo).items():
            with self.subTest(role='anonymous', request=name):
                self.assertEqual(send().status_code, 403)
        self.client.force_authenticate(account('root', role='ADMIN', is_superuser=True, is_staff=True))
        for name, send in self.requests(self.demo).items():
            with self.subTest(role='superuser', request=name):
                self.assertEqual(send().json()['error'], 'NOT_FOUND')
        self.assertEqual(DemoBooking.objects.get(pk=self.demo.pk).status, BookingStatus.BOOKED)


class TutorReportPayloadTests(TutorReportApiTestCase):
    def assertInvalid(self, response, field):
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body['error'], 'VALIDATION_ERROR')
        self.assertIn(field, body['fields'])

    def test_a_submit_carries_exactly_the_tutors_fields(self):
        system_fields = (
            'status', 'version', 'id', 'booking', 'booking_id', 'student_name_snapshot', 'grade_snapshot',
            'tutor_name_snapshot', 'submitted_by', 'completed_at',
        )
        for field in system_fields:
            with self.subTest(field=field):
                response = self.client.post(report_url(self.demo), {**demo_input(), field: 'x'}, format='json')
                self.assertInvalid(response, field)
                self.assertEqual(response.json()['fields'][field], ['This field cannot be set.'])
        missing = {key: value for key, value in diagnostic_input().items() if key != 'teacher_remarks'}
        self.assertInvalid(self.client.post(report_url(self.diagnostic), missing, format='json'), 'teacher_remarks')
        for changes, field in (({'score': 30}, 'score'), ({'strength_areas': []}, 'strength_areas'),
                               ({'performance_level': 'GREAT'}, 'performance_level')):
            with self.subTest(field=field):
                self.assertInvalid(self.submit(self.diagnostic, **changes), field)
        self.assertInvalid(self.client.post(report_url(self.demo), ['not', 'a', 'report'], format='json'), 'non_field_errors')
        self.assertEqual(self.client.post(report_url(self.demo), demo_input()).status_code, 415)  # a form, not JSON
        self.assertEqual(
            self.client.post(report_url(self.demo), '{not json', content_type='application/json').status_code, 400,
        )
        for booking in (self.demo, self.diagnostic):
            booking.refresh_from_db()
            self.assertEqual(booking.status, BookingStatus.BOOKED)

    def test_an_edit_names_its_version_and_nothing_else_of_the_systems(self):
        self.submit(self.demo)
        no_version = self.client.put(report_url(self.demo), demo_input(), format='json')
        self.assertInvalid(no_version, 'version')
        self.assertInvalid(self.edit(self.demo, '1'), 'version')
        self.assertInvalid(self.edit(self.demo, 1, tutor_name_snapshot='Someone'), 'tutor_name_snapshot')
        self.assertInvalid(self.client.put(report_url(self.demo), [1], format='json'), 'non_field_errors')
        self.assertEqual(DemoReport.objects.get().version, 1)


class TutorReportErrorTests(TutorReportApiTestCase):
    def assertRefused(self, response, http_status, code, **extra):
        body = response.json()
        self.assertEqual((response.status_code, body['error']), (http_status, code), body)
        self.assertTrue(body['message'])
        for key, value in extra.items():
            self.assertEqual(body[key], value)

    def test_every_refusal_answers_its_code(self):
        self.submit(self.demo)
        self.assertRefused(self.submit(self.demo), 409, 'REPORT_EXISTS', version=1)
        self.edit(self.demo, 1, suggested_strategy='A new plan.')
        self.assertRefused(self.edit(self.demo, 1, suggested_strategy='Another plan.'), 409, 'REPORT_VERSION_CONFLICT', version=2)
        self.assertRefused(self.submit(self.upcoming()), 409, 'NOT_STARTED')
        cancelled = self.upcoming(student='Sara', at=MORNING)
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST)
        self.assertRefused(self.submit(cancelled), 409, 'BOOKING_CANCELLED')
        self.assertRefused(self.edit(self.diagnostic, 1), 404, 'NO_REPORT')
        self.assertRefused(self.client.get(report_url(self.diagnostic, 'revisions/')), 404, 'NO_REPORT')
        with mock.patch('reports.tutor_views.submit_report', side_effect=ReportBusy()):
            self.assertRefused(self.submit(self.diagnostic), 503, 'REPORT_BUSY')


class TutorReportPrivacyTests(TutorReportApiTestCase):
    def test_nothing_a_tutor_is_sent_names_the_parent(self):
        responses = [
            self.client.get('/api/tutor/bookings/', {'when': 'all'}),
            self.client.get(report_url(self.demo)),
            self.submit(self.demo),
            self.submit(self.demo),
            self.edit(self.demo, 1, assessment_review='Revised.'),
            self.edit(self.demo, 1, assessment_review='Stale.'),
            self.client.get(report_url(self.demo)),
            self.client.get(report_url(self.demo, 'revisions/')),
            self.client.get(detail_url(self.demo)),
            self.submit(self.diagnostic, score=99),
        ]
        bodies = [response.json() for response in responses]
        self.assertFalse(keys_of(bodies) & PRIVATE_KEYS, keys_of(bodies) & PRIVATE_KEYS)
        sent = json.dumps(bodies)
        for private in (*PRIVATE_VALUES, str(self.demo.lead_id)):
            self.assertNotIn(private, sent)
        # The child is named, as the report prints them.
        self.assertIn('Riya', sent)


class LegacyCompletedApiTests(TutorReportApiTestCase):
    """
    A booking completed before Start existed -- started_at NULL, as
    bookings.0009 leaves it -- on every report route: read, edited, printed
    and previewed as any completed booking, never started again.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.assertEqual(self.submit(self.demo).status_code, 201)
        DemoBooking.objects.filter(pk=self.demo.pk).update(started_at=None, started_by=None)

    def test_the_tutor_reads_edits_previews_and_prints_it(self):
        shown = self.client.get(detail_url(self.demo)).json()
        self.assertEqual(
            (shown['status'], shown['activity_state'], shown['started_at'], shown['actions'], shown['start_refusal']['code'],
             shown['has_report'], shown['report_due']),
            ('COMPLETED', 'COMPLETED', None, {'start': False}, 'BOOKING_COMPLETED', True, False),
        )
        self.assertEqual(self.client.get(report_url(self.demo)).json()['version'], 1)
        edited = self.edit(self.demo, 1, suggested_strategy='Revised later.')
        self.assertEqual((edited.status_code, edited.json()['report']['version']), (200, 2))
        self.assertEqual(self.client.get(report_url(self.demo, 'revisions/')).json()['count'], 2)
        for suffix in ('pdf/', 'revisions/1/pdf/'):
            pdf = self.client.get(report_url(self.demo, suffix))
            self.assertEqual((pdf.status_code, pdf['Content-Type']), (200, 'application/pdf'), suffix)
        preview = self.client.post(report_url(self.demo, 'preview/'), {'version': 2, **report_input(self.demo)}, format='json')
        self.assertEqual((preview.status_code, preview['Content-Type']), (200, 'application/pdf'))
        # Already complete: a second submit says so, and nothing can start it.
        again = self.submit(self.demo)
        self.assertEqual((again.status_code, again.json()['error']), (409, 'REPORT_EXISTS'))
        started = self.client.post(f'/api/tutor/bookings/demo/{self.demo.id}/start/')
        self.assertEqual((started.status_code, started.json()['error']), (409, 'BOOKING_COMPLETED'))
        self.assertIsNone(DemoBooking.objects.get(pk=self.demo.pk).started_at)

    def test_the_admin_reads_it_with_no_start_recorded(self):
        self.client.force_authenticate(account('admin_legacy', role='ADMIN'))
        detail = self.client.get(f'/api/bookings/demo/{self.demo.id}/').json()
        self.assertEqual(
            (detail['status'], detail['activity_state'], detail['started_at'], detail['started_by'], detail['report']['version'],
             detail['report_due'], detail['tutor_change_refusal']['code'], detail['actions']),
            ('COMPLETED', 'COMPLETED', None, None, 1, False, 'BOOKING_COMPLETED',
             {'cancel': False, 'no_show': False, 'reschedule': False}),
        )
        self.assertEqual(self.client.get(f'/api/bookings/demo/{self.demo.id}/report/').json()['version'], 1)
        pdf = self.client.get(f'/api/bookings/demo/{self.demo.id}/report/pdf/')
        self.assertEqual((pdf.status_code, pdf['Content-Type']), (200, 'application/pdf'))
        submitted = self.client.get('/api/bookings/demo/', {'report': 'submitted'}).json()['results']
        self.assertEqual([row['id'] for row in submitted], [str(self.demo.id)])
        self.assertEqual(self.client.get('/api/bookings/demo/', {'report': 'due'}).json()['results'], [])
