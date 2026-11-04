"""
The WhatsApp providers and what guards them (Phase 2B, step 1): choosing a
provider -- ``none`` by default, ``console`` for local development, a fake for
tests only, any other name refused -- WhatsApp's formatting of all eight
templates, with filled-in values as plain text that can never change it,
WhatsApp as the only channel, international numbers with their own country codes (never India
assumed), and the safety gate, closed by default: sending off, nothing to a
number off the allow-list. Nothing is sent anywhere.
"""
from datetime import date, time
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from bookings.leads import normalize_phone

from .checks import check_whatsapp_settings
from .formatting import InvalidWhatsAppNumber, whatsapp_message, whatsapp_number, whatsapp_text, whatsapp_value
from .models import Channel, MessageStatus, MessageTemplate, MessageTemplateVersion
from .providers import PROVIDERS, get_provider
from .providers.base import OutgoingMessage, ProviderNotConfigured, SendResult, WhatsAppProvider
from .providers.console import ConsoleProvider
from .providers.none import NoneProvider
from .rendering import VARIABLES, MissingValues, format_date, format_time, render
from .safety import SendBlock, recipient_allowed, sending_block
from .tests_templates import PRD, prd_text

UAE = '+971501234567'
MARKS = '*_~`'
# A value doing its worst: every WhatsApp mark, the template's own bold marker,
# and line breaks that would start a quote or a list.
HOSTILE = 'Anil ** Kumar* _x_ ~y~ `z`\n> quote\n- item\t\t end'


class FakeProvider(WhatsAppProvider):
    """
    Test-only: answers each send from ``outcomes`` -- a SendResult, an
    exception to raise, or a function of the message returning either, which
    runs during the call -- Queued by default, and keeps every message it was
    given in ``outbox``. Never registered outside tests: use_fake_provider().
    """
    name = 'fake'
    statuses = frozenset({MessageStatus.QUEUED, MessageStatus.SENT, MessageStatus.DELIVERED,
                          MessageStatus.READ, MessageStatus.FAILED})
    outbox = []
    outcomes = []

    @classmethod
    def reset(cls, *outcomes):
        cls.outbox, cls.outcomes = [], list(outcomes)

    def send(self, message, timeout):
        self.outbox.append((message, timeout))
        outcome = self.outcomes.pop(0) if self.outcomes else SendResult(
            accepted=True, status=MessageStatus.QUEUED, provider_message_id=f'fake-{len(self.outbox)}',
        )
        if callable(outcome):
            outcome = outcome(message)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def use_fake_provider():
    """The fake as a provider name, for the duration (with COMMUNICATIONS_WHATSAPP_PROVIDER='fake')."""
    return mock.patch.dict(PROVIDERS, {FakeProvider.name: FakeProvider})


def outgoing(**fields):
    values = dict(message_id='m-1', to='971501234567', text='Hello *there*', template_key='DEMO_ACKNOWLEDGEMENT')
    values.update(fields)
    return OutgoingMessage(**values)


# The settings as shipped (config/settings.py defaults).
CLOSED = dict(
    COMMUNICATIONS_SENDING_ENABLED=False,
    COMMUNICATIONS_WHATSAPP_PROVIDER='none',
    COMMUNICATIONS_RECIPIENT_ALLOWLIST=[],
    COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=False,
    COMMUNICATIONS_PROVIDER_TIMEOUT=10,
)


@override_settings(**CLOSED)
class ProviderSelectionTests(SimpleTestCase):
    def test_none_is_the_default_and_console_the_other_built_in(self):
        self.assertIsInstance(get_provider(), NoneProvider)
        self.assertEqual(set(PROVIDERS), {'none', 'console'})
        with override_settings(COMMUNICATIONS_WHATSAPP_PROVIDER=' Console '):
            self.assertIsInstance(get_provider(), ConsoleProvider)
        self.assertIsInstance(get_provider('console'), ConsoleProvider)

    def test_an_unknown_provider_is_refused_never_guessed(self):
        for name in ('meta', 'twilio', 'sms', '', 'fake'):
            with self.subTest(name=name), override_settings(COMMUNICATIONS_WHATSAPP_PROVIDER=name):
                with self.assertRaisesMessage(ImproperlyConfigured, 'Choose one of: console, none.'):
                    get_provider()

    def test_the_fake_exists_for_tests_only(self):
        with use_fake_provider(), override_settings(COMMUNICATIONS_WHATSAPP_PROVIDER='fake'):
            self.assertIsInstance(get_provider(), FakeProvider)
        self.assertNotIn('fake', PROVIDERS)

    def test_the_system_check_reports_a_misconfiguration(self):
        self.assertEqual(check_whatsapp_settings(), [])
        cases = (
            ({'COMMUNICATIONS_WHATSAPP_PROVIDER': 'meta'}, 'communications.E001'),
            ({'COMMUNICATIONS_RECIPIENT_ALLOWLIST': ['0501234567']}, 'communications.E002'),
            ({'COMMUNICATIONS_PROVIDER_TIMEOUT': 0}, 'communications.E003'),
            ({'COMMUNICATIONS_PROVIDER_TIMEOUT': 120}, 'communications.E003'),
        )
        for changes, error_id in cases:
            with self.subTest(error=error_id, changes=changes), override_settings(**changes):
                self.assertEqual([error.id for error in check_whatsapp_settings()], [error_id])


class ProviderBehaviourTests(SimpleTestCase):
    def test_none_sends_nothing_and_reports_nothing(self):
        provider = NoneProvider()
        self.assertEqual((provider.sends, provider.statuses), (False, frozenset()))
        with self.assertRaises(ProviderNotConfigured):
            provider.send(outgoing(), timeout=10)
        self.assertFalse(provider.verify_webhook(object()))

    def test_console_writes_the_message_to_the_log_and_reports_sent_only(self):
        provider = ConsoleProvider()
        with self.assertLogs('communications.providers.console', 'INFO') as logged:
            result = provider.send(outgoing(text='✅ *Demo Confirmed!*\n\nHi'), timeout=10)
        self.assertEqual(result, SendResult(accepted=True, status=MessageStatus.SENT, provider_message_id='console-m-1'))
        line = logged.output[0]
        self.assertIn('not sent', line)
        self.assertIn('DEMO_ACKNOWLEDGEMENT, message m-1', line)
        self.assertIn('✅ *Demo Confirmed!*\n\nHi', line)
        # The recipient by its last four digits only.
        self.assertIn('+********4567', line)
        self.assertNotIn('971501234567', line)
        # It cannot know a delivery or a read, so it never reports one.
        self.assertEqual(provider.statuses, {MessageStatus.SENT})
        self.assertFalse(provider.reports(MessageStatus.DELIVERED) or provider.reports(MessageStatus.READ))
        self.assertFalse(provider.verify_webhook(object()))

    def test_a_send_result_says_what_happened(self):
        SendResult(accepted=True, status=MessageStatus.QUEUED, provider_message_id='p-1')
        SendResult(accepted=False, error_code='TIMEOUT', retryable=True)
        for bad in (dict(accepted=True), dict(accepted=True, status=MessageStatus.DELIVERED),
                    dict(accepted=False), dict(accepted=False, status=MessageStatus.SENT, error_code='X')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                SendResult(**bad)

    def test_the_fake_answers_from_its_script(self):
        FakeProvider.reset(SendResult(accepted=False, error_code='TIMEOUT', retryable=True), RuntimeError('crash'))
        provider = FakeProvider()
        self.assertEqual(provider.send(outgoing(), timeout=5).error_code, 'TIMEOUT')
        with self.assertRaises(RuntimeError):
            provider.send(outgoing(), timeout=5)
        self.assertEqual(provider.send(outgoing(), timeout=5).status, MessageStatus.QUEUED)
        self.assertEqual([timeout for _message, timeout in FakeProvider.outbox], [5, 5, 5])


class WhatsAppFormattingTests(TestCase):
    def test_all_eight_templates_take_whatsapp_bold_and_nothing_else_changes(self):
        templates = MessageTemplate.objects.all()
        self.assertEqual(templates.count(), 8)
        for template in templates:
            with self.subTest(key=template.key):
                body = template.current_version().body
                self.assertEqual(body, prd_text(template.key))
                text = whatsapp_text(body)
                self.assertNotIn('**', text)
                self.assertEqual(text, body.replace('**', '*'))
                self.assertEqual(text.count('*') % 2, 0)

    def test_a_rendered_message_as_whatsapp_shows_it(self):
        values = {
            'demo_date': format_date(date(2026, 10, 28)), 'demo_time': format_time(time(19, 30)),
            'tutor_name': 'Tutor Anu', 'meeting_link': 'https://meet.google.com/abc-defg-hij',
            'bde_name': 'Bde Anil', 'bde_phone': '+971 50 123 4567',
        }
        confirmed = whatsapp_message(prd_text('DEMO_CONFIRMED'), values)
        self.assertTrue(confirmed.startswith("✅ *Demo Confirmed!*\n\nHi Sir/Ma'am,\n\n"))
        self.assertIn('⏰ Time: 7:30 PM IST\n\n💻 Join the class: https://meet.google.com/abc-defg-hij', confirmed)
        self.assertTrue(confirmed.endswith('contact me at +971 50 123 4567.\n\n*Bde Anil*\n\n*Eduport Plus*'))
        ack = whatsapp_message(prd_text('DEMO_ACKNOWLEDGEMENT'), values)
        self.assertIn('Demo class on *Wed, 28 Oct 2026 at 7:30 PM IST*. We will share', ack)
        self.assertEqual(len(PRD), 8)

    def test_with_ordinary_values_the_template_text_is_kept_exactly(self):
        for template in MessageTemplate.objects.all():
            with self.subTest(key=template.key):
                body = template.current_version().body
                values = {name: f'Value {index}' for index, name in enumerate(VARIABLES[template.booking_type])}
                self.assertEqual(whatsapp_message(body, values), render(body, values).replace('**', '*'))

    def test_values_go_in_as_plain_text(self):
        self.assertEqual(whatsapp_value('Anil_Kumar'), 'Anil' + chr(0x02CD) + 'Kumar')
        self.assertEqual(whatsapp_value('*Star* ~gone~ `code`'),
                         f'{chr(0x2217)}Star{chr(0x2217)} {chr(0x223C)}gone{chr(0x223C)} {chr(0x02CB)}code{chr(0x02CB)}')
        self.assertEqual(whatsapp_value('  Line one\n\nLine\ttwo  '), 'Line one Line two')
        # What carries none of those marks goes in exactly as it is.
        for value in ('https://meet.google.com/abc-defg-hij', '+971 50 123 4567', 'Wed, 28 Oct 2026', '7:30 PM',
                      "Ma'am O’Brien", 'रानी', 'محمد'):
            with self.subTest(value=value):
                self.assertEqual(whatsapp_value(value), value)

    def test_no_value_can_change_any_templates_formatting(self):
        for template in MessageTemplate.objects.all():
            with self.subTest(key=template.key):
                body = template.current_version().body
                names = VARIABLES[template.booking_type]
                # The template with ordinary values: its own marks only (placeholder names gone).
                own = whatsapp_message(body, {name: 'Value' for name in names})
                message = whatsapp_message(body, {name: HOSTILE for name in names})
                # Every formatting mark in the message is the template's own, and no line was added.
                self.assertEqual([message.count(mark) for mark in MARKS], [own.count(mark) for mark in MARKS])
                self.assertEqual(message.count('\n'), own.count('\n'))
                self.assertNotIn('\n> ', message)

    def test_a_name_full_of_marks_keeps_the_signature_bold(self):
        message = whatsapp_message(prd_text('DEMO_AFTER_ACTIVITY'), {'bde_name': 'Anil ** Kumar*'})
        star = chr(0x2217)
        self.assertTrue(message.endswith(f'*Anil {star}{star} Kumar{star}*\n\n*Eduport Plus*'))

    def test_an_empty_value_still_blocks_the_message(self):
        for blank in ('', '   ', '\n\t'):
            with self.subTest(blank=repr(blank)), self.assertRaises(MissingValues) as caught:
                whatsapp_message(prd_text('DEMO_AFTER_ACTIVITY'), {'bde_name': blank})
            self.assertEqual(caught.exception.names, ['bde_name'])


class WhatsAppOnlyTests(SimpleTestCase):
    def test_whatsapp_is_the_only_channel(self):
        self.assertEqual(Channel.values, ['WHATSAPP', 'MANUAL_WHATSAPP'])
        self.assertNotIn('sms_body', {field.name for field in MessageTemplateVersion._meta.get_fields()})


class InternationalNumberTests(SimpleTestCase):
    def test_every_country_keeps_its_own_code(self):
        # (country code, number as a parent types it, WhatsApp's digits)
        cases = (
            ('+971', '050 123 4567', '971501234567'),   # UAE
            ('+966', '0501234567', '966501234567'),     # Saudi Arabia
            ('+974', '3312 3456', '97433123456'),       # Qatar
            ('+965', '5001 2345', '96550012345'),       # Kuwait
            ('+973', '3600 1234', '97336001234'),       # Bahrain
            ('+968', '9212 3456', '96892123456'),       # Oman
            ('+91', '98470 12345', '919847012345'),     # India
            ('+44', '07700 900123', '447700900123'),    # United Kingdom
            ('+1', '(415) 555-0101', '14155550101'),    # United States
        )
        for dial, typed, expected in cases:
            with self.subTest(dial=dial):
                _dial, _national, phone_key = normalize_phone(dial, typed)
                self.assertEqual(whatsapp_number(phone_key), expected)
                self.assertTrue(expected.startswith(dial[1:]))

    def test_separators_are_ignored(self):
        for typed in ('+971 50 123 4567', '+971-50-123-4567', '+971 (50) 123 4567', UAE):
            with self.subTest(typed=typed):
                self.assertEqual(whatsapp_number(typed), '971501234567')

    def test_a_number_without_its_country_code_is_refused_never_given_indias(self):
        for bad in ('9847012345', '0501234567', '971501234567', '+0501234567', '+12345', '+1234567890123456', '', None,
                    '+971 50 123 456x'):
            with self.subTest(bad=bad), self.assertRaises(InvalidWhatsAppNumber):
                whatsapp_number(bad)


class SafetyGateTests(SimpleTestCase):
    @override_settings(**CLOSED)
    def test_as_shipped_nothing_can_be_sent(self):
        self.assertEqual(sending_block(UAE), SendBlock.SENDING_DISABLED)
        self.assertFalse(recipient_allowed(UAE))

    @override_settings(**{**CLOSED, 'COMMUNICATIONS_WHATSAPP_PROVIDER': 'console'})
    def test_sending_disabled_stops_every_provider(self):
        self.assertEqual(sending_block(UAE), SendBlock.SENDING_DISABLED)
        with use_fake_provider():
            self.assertEqual(sending_block(UAE, provider=FakeProvider()), SendBlock.SENDING_DISABLED)

    @override_settings(**{**CLOSED, 'COMMUNICATIONS_SENDING_ENABLED': True})
    def test_without_a_provider_messages_stay_pending(self):
        self.assertEqual(sending_block(UAE), SendBlock.NO_PROVIDER)

    @override_settings(**{**CLOSED, 'COMMUNICATIONS_SENDING_ENABLED': True, 'COMMUNICATIONS_WHATSAPP_PROVIDER': 'console'})
    def test_the_allow_list_is_closed_by_default(self):
        # An empty list allows nobody.
        self.assertEqual(sending_block(UAE), SendBlock.RECIPIENT_NOT_ALLOWED)
        with override_settings(COMMUNICATIONS_RECIPIENT_ALLOWLIST=['+971 50 123 4567', ' ']):
            self.assertIsNone(sending_block(UAE))
            # The same digits under another country code are another number.
            self.assertEqual(sending_block('+91501234567'), SendBlock.RECIPIENT_NOT_ALLOWED)
            self.assertEqual(sending_block('+966501234567'), SendBlock.RECIPIENT_NOT_ALLOWED)
        with override_settings(COMMUNICATIONS_ALLOW_ALL_RECIPIENTS=True):
            self.assertIsNone(sending_block('+966501234567'))

    @override_settings(**{**CLOSED, 'COMMUNICATIONS_SENDING_ENABLED': True, 'COMMUNICATIONS_WHATSAPP_PROVIDER': 'console',
                          'COMMUNICATIONS_ALLOW_ALL_RECIPIENTS': True})
    def test_a_recipient_must_be_an_international_number(self):
        self.assertEqual(sending_block('0501234567'), SendBlock.INVALID_RECIPIENT)

    @override_settings(**{**CLOSED, 'COMMUNICATIONS_SENDING_ENABLED': True, 'COMMUNICATIONS_WHATSAPP_PROVIDER': 'console',
                          'COMMUNICATIONS_RECIPIENT_ALLOWLIST': ['0501234567']})
    def test_a_malformed_allow_list_entry_is_refused(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "'0501234567' is not an international number"):
            sending_block(UAE)
