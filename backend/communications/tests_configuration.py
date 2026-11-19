"""
Invalid WhatsApp settings never stop the backend (F2): `check --deploy
--fail-level ERROR` (the entrypoint) and `migrate` print them as warnings and
go on, while an unrelated error still stops both; the settings load and the
WSGI application imports even with a timeout that is not a number; and every
business operation -- booking, the parent's answer, cancelling, moving,
assigning a tutor, Start, the report -- runs as it does with valid settings,
the communication plan following it through the outbox, while not one
message is handed to any provider: the dispatcher holds them all back as
MISCONFIGURED. Nothing reaches WhatsApp.
"""
import json
import os
import subprocess
import sys
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core import checks
from django.core.checks.registry import registry
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import SimpleTestCase, TestCase, override_settings

from bookings.booking_service import cancel_booking, record_parent_confirmation, reschedule_booking
from bookings.models import BookingStatus, CancelReason, ParentConfirmation, RescheduleReason
from bookings.tests_booking import DAY, DEMO, DIAGNOSTIC, MORNING, NOW

from . import sending, tasks, tests_outbox
from .models import CommunicationEvent, EventStatus, Message, MessageAttempt, MessageStatus, Step
from .safety import SendBlock

# Sending switched on, and every WhatsApp setting wrong at once.
INVALID = dict(
    COMMUNICATIONS_SENDING_ENABLED=True,
    COMMUNICATIONS_WHATSAPP_PROVIDER='meta',
    COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=False,
    COMMUNICATIONS_RECIPIENT_ALLOWLIST=['0501234567'],
    COMMUNICATIONS_PROVIDER_TIMEOUT='abc',
)
WARNINGS = ('communications.W001', 'communications.W002', 'communications.W003')


def unrelated_error(app_configs=None, **kwargs):
    return [checks.Error('An unrelated deployment error.', id='f2tests.E001')]


@override_settings(**INVALID)
class StartupCommandTests(TestCase):
    def run_command(self, *args, **options):
        out, err = StringIO(), StringIO()
        call_command(*args, stdout=out, stderr=err, **options)
        return out.getvalue() + err.getvalue()

    def migrate(self, **options):
        """``manage.py migrate`` as the entrypoint runs it: call_command alone would skip its system checks."""
        return self.run_command('migrate', interactive=False, skip_checks=False, **options)

    def test_the_entrypoint_check_reports_and_passes(self):
        output = self.run_command('check', deploy=True, fail_level='ERROR')
        for check_id in WARNINGS:
            self.assertIn(check_id, output)
        self.assertIn("Unknown WhatsApp provider 'meta'", output)

    def test_migrate_reports_and_runs(self):
        """`migrate` runs every system check first; on the disposable test database it then finds nothing to apply."""
        output = self.migrate(verbosity=1)
        for check_id in WARNINGS:
            self.assertIn(check_id, output)
        self.assertIn('No migrations to apply.', output)

    def test_an_unrelated_error_still_stops_check_and_migrate(self):
        checks.register(unrelated_error)
        self.addCleanup(registry.registered_checks.discard, unrelated_error)
        with self.assertRaisesMessage(SystemCheckError, 'f2tests.E001'):
            self.run_command('check', deploy=True, fail_level='ERROR')
        with self.assertRaisesMessage(SystemCheckError, 'f2tests.E001'):
            self.migrate(verbosity=0)


class SettingsLoadTests(SimpleTestCase):
    """In a fresh process, as gunicorn, the worker and beat load them: config.settings, then the WSGI application."""
    LOAD = (
        'import json, django; django.setup(); import config.wsgi; '
        'from django.conf import settings; from django.core.checks import run_checks; '
        'print(json.dumps([settings.COMMUNICATIONS_PROVIDER_TIMEOUT, '
        'sorted(m.id for m in run_checks() if m.id.startswith("communications."))]))'
    )

    def load(self, timeout):
        env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'COMMUNICATIONS_WHATSAPP_PROVIDER': 'none',
               'COMMUNICATIONS_RECIPIENT_ALLOWLIST': ''}
        env.pop('COMMUNICATIONS_PROVIDER_TIMEOUT', None)
        if timeout is not None:
            env['COMMUNICATIONS_PROVIDER_TIMEOUT'] = timeout
        done = subprocess.run([sys.executable, '-c', self.LOAD], cwd=settings.BASE_DIR, env=env,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_a_timeout_that_is_not_a_number_loads_and_is_reported(self):
        for given in ('abc', '', '10s', '7.5'):
            with self.subTest(given=given):
                self.assertEqual(self.load(given), [given, ['communications.W003']])

    def test_a_valid_timeout_loads_as_before(self):
        self.assertEqual(self.load(None), [10, []])
        self.assertEqual(self.load('15'), [15, []])
        self.assertEqual(self.load('0'), [0, ['communications.W003']])


@override_settings(**INVALID)
class BusinessRunsWithInvalidSettingsTests(tests_outbox.SessionNeverWaitsForCommunicationTests):
    """
    Every Start-and-report scenario of the outbox suite again, with invalid
    WhatsApp settings and sending on (inherited), and the rest of the
    business beside it.
    """

    def assert_nothing_handed_over(self):
        self.assertFalse(MessageAttempt.objects.exists())
        self.assertFalse(Message.objects.filter(claimed_at__isnull=False).exists())
        self.assertFalse(Message.objects.exclude(
            status__in=(MessageStatus.WAITING, MessageStatus.PENDING, MessageStatus.CANCELLED)).exists())

    def dispatch(self):
        with mock.patch.object(sending, 'send_message', side_effect=AssertionError('picked up')), \
                self.assertLogs('communications.tasks', 'WARNING'):
            summary = tasks.run_dispatch(now=NOW)
        self.assertEqual((summary['held_back'], summary['outcomes'], summary['errors']), (SendBlock.MISCONFIGURED, {}, 0))

    def test_the_business_runs_and_its_plan_follows_with_nothing_sent(self):
        demo, diagnostic = self.planned(DEMO), self.planned(DIAGNOSTIC, at=MORNING)
        cancelled, moved = self.planned(), self.planned()
        record_parent_confirmation(demo, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        demo, diagnostic = self.ready(demo), self.ready(diagnostic)
        cancel_booking(cancelled, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=NOW)
        new = reschedule_booking(moved, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
                                 actor=self.admin, now=NOW).booking
        self.drain()

        # The business stands, and the outbox applied every change to the plan.
        statuses = {booking.pk: type(booking).objects.get(pk=booking.pk).status
                    for booking in (demo, diagnostic, cancelled, moved, new)}
        self.assertEqual(statuses, {demo.pk: BookingStatus.BOOKED, diagnostic.pk: BookingStatus.BOOKED,
                                    cancelled.pk: BookingStatus.CANCELLED, moved.pk: BookingStatus.RESCHEDULED,
                                    new.pk: BookingStatus.BOOKED})
        self.assertEqual(set(CommunicationEvent.objects.values_list('status', flat=True)), {EventStatus.DONE})
        self.assertTrue(new.communication_messages.filter(status=MessageStatus.PENDING).exists())
        self.assertFalse(cancelled.communication_messages.exclude(status=MessageStatus.CANCELLED).exists())
        self.dispatch()
        self.assert_nothing_handed_over()

        # Start and the report, through the tutor API; the after-activity message is planned and held back too.
        for booking in (demo, diagnostic):
            completed = self.conduct(type(booking).objects.get(pk=booking.pk))
            self.drain()
            self.assertTrue(completed.communication_messages.filter(template__step=Step.AFTER_ACTIVITY).exists())
        self.dispatch()
        self.assert_nothing_handed_over()
