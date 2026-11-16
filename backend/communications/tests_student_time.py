"""
Parent messages at the student's own time (bookings.student_timezones,
communications.rendering): a booking's date and time in its parent's
messages are its start on the clock of the lead's zone, named as the Hub's
Student Time names it ("6:00 PM UAE") where the templates write "IST" -- and
everything else exactly as before. A student in India, a lead with no zone or
one the runtime does not know, and every message written before zones were
kept read word for word what they always did. The booking itself, its
tasks' and messages' times, and every staff-facing time stay Indian.

The PRD clock: NOW is 27 Oct 12:00 IST, and the bookings start on 28 Oct at
19:30 IST (14:00 UTC) or 10:00 IST (04:30 UTC).
"""
from datetime import datetime, timedelta

from django.test import SimpleTestCase

from bookings import student_timezones
from bookings.booking_service import create_booking, record_parent_confirmation, reschedule_booking
from bookings.models import Lead, ParentConfirmation, RescheduleReason
from bookings.scheduling import BOOKING_TIMEZONE, BOOKING_TIMEZONE_NAME
from bookings.tests_booking import DAY, DEMO, DIAGNOSTIC, EVENING, MORNING, NOW, request

from . import planner
from .formatting import whatsapp_message
from .models import Message, MessageStatus, Step
from .overview import booking_communication
from .prd_templates import TEMPLATES
from .providers.base import SendResult
from .rendering import message_values, render, zoned
from .sending import send_message
from .services import preview, request_confirmation
from .tests_planning import CommunicationTestCase
from .tests_providers import FakeProvider
from .tests_sending import SENT, SenderTestCase
from .tests_templates import prd_text

PRD_BODIES = {key: body for key, _type, _step, _name, body in TEMPLATES}
# 28 Oct 19:30 IST, the bookings' usual start.
EVENING_START = datetime(2026, 10, 28, 19, 30, tzinfo=BOOKING_TIMEZONE)


def lead_in(zone):
    """An unsaved lead whose zone is ``zone``, as the formatter reads it."""
    return Lead(student_timezone=zone)


class StudentTimeTests(SimpleTestCase):
    """bookings.student_timezones.student_time: an instant on the student's clock, and its label."""

    def at(self, zone, instant=EVENING_START):
        local, label = student_timezones.student_time(instant, lead_in(zone))
        return f'{local:%Y-%m-%d %H:%M}', label

    def test_a_uae_student_reads_their_own_clock(self):
        self.assertEqual(self.at('Asia/Dubai'), ('2026-10-28 18:00', 'UAE'))

    def test_an_indian_student_reads_indian_time_as_ist_under_either_name(self):
        for zone in ('Asia/Kolkata', 'Asia/Calcutta'):
            with self.subTest(zone=zone):
                self.assertEqual(self.at(zone), ('2026-10-28 19:30', 'IST'))

    def test_no_zone_or_one_the_runtime_does_not_know_reads_indian_time(self):
        for zone in ('', 'Mars/Olympus_Mons', 'not a zone'):
            with self.subTest(zone=zone):
                self.assertEqual(self.at(zone), ('2026-10-28 19:30', 'IST'))

    def test_the_date_is_the_students_own_on_either_side_of_india(self):
        # 10:00 IST is 04:30 UTC: the evening before in Los Angeles.
        morning = datetime(2026, 10, 28, 10, 0, tzinfo=BOOKING_TIMEZONE)
        self.assertEqual(self.at('America/Los_Angeles', morning), ('2026-10-27 21:30', 'Los Angeles'))
        # 19:30 IST is 14:00 UTC: the small hours of the next day in Sydney.
        self.assertEqual(self.at('Australia/Sydney'), ('2026-10-29 01:00', 'Sydney'))

    def test_daylight_saving_as_the_zone_has_it_on_the_day(self):
        # New York leaves daylight saving on 1 Nov 2026: the same Indian time is an hour earlier there after it.
        self.assertEqual(self.at('America/New_York'), ('2026-10-28 10:00', 'New York'))
        self.assertEqual(self.at('America/New_York', EVENING_START + timedelta(days=7)), ('2026-11-04 09:00', 'New York'))

    def test_a_zone_off_the_hour(self):
        self.assertEqual(self.at('Asia/Kathmandu'), ('2026-10-28 19:45', 'Nepal'))

    def test_the_hubs_student_time_names(self):
        expected = {
            'Asia/Kolkata': 'IST', 'Asia/Dubai': 'UAE', 'Asia/Qatar': 'Qatar', 'Asia/Riyadh': 'KSA',
            'Asia/Kuwait': 'Kuwait', 'Asia/Bahrain': 'Bahrain', 'Asia/Muscat': 'Oman', 'Asia/Singapore': 'Singapore',
            'Europe/London': 'UK', 'America/New_York': 'New York', 'America/Chicago': 'Chicago',
            'America/Denver': 'Denver', 'America/Los_Angeles': 'Los Angeles', 'Australia/Sydney': 'Sydney',
            'Australia/Perth': 'Perth', 'Asia/Colombo': 'Sri Lanka', 'Asia/Kathmandu': 'Nepal',
            'Asia/Dhaka': 'Bangladesh',
            # Their older names, as browsers give them.
            'Asia/Calcutta': 'IST', 'US/Eastern': 'New York', 'US/Pacific': 'Los Angeles', 'GB': 'UK',
            'Singapore': 'Singapore', 'Australia/NSW': 'Sydney', 'Asia/Katmandu': 'Nepal', 'Asia/Dacca': 'Bangladesh',
        }
        for zone, label in expected.items():
            with self.subTest(zone=zone):
                self.assertEqual(student_timezones.zone_label(zone, EVENING_START), label)
        # Every listed zone and alias is one the runtime knows.
        for zone in (*student_timezones.ZONE_LABELS, *student_timezones.ZONE_ALIASES):
            with self.subTest(known=zone):
                self.assertEqual(student_timezones.clean(zone), zone)

    def test_any_other_zone_is_named_by_its_city_or_its_offset(self):
        for zone, label in (('Europe/Berlin', 'Berlin'), ('America/Argentina/Buenos_Aires', 'Buenos Aires'),
                            ('Etc/GMT+5', 'GMT-5'), ('Etc/GMT-4', 'GMT+4'), ('UTC', 'GMT'), ('Japan', 'GMT+9')):
            with self.subTest(zone=zone):
                self.assertEqual(student_timezones.zone_label(zone, EVENING_START), label)
        self.assertEqual(student_timezones._gmt_offset(timedelta(hours=5, minutes=30)), 'GMT+5:30')
        self.assertEqual(student_timezones._gmt_offset(-timedelta(hours=3, minutes=30)), 'GMT-3:30')


def values(prefix, date='Wed, 28 Oct 2026', time='7:30 PM', zone=None):
    """A booking's values for every PRD template of its type; ``zone`` its student's, outside India."""
    result = {
        f'{prefix}_date': date, f'{prefix}_time': time, 'parent_name': 'Asha Nair', 'student_name': 'Riya',
        'tutor_name': 'Tutor Anu', 'meeting_link': 'https://meet.google.com/abc-defg-hij', 'bde_name': 'Bde Anil',
        'bde_phone': '+91 98470 12345',
    }
    if zone:
        result[f'{prefix}_timezone'] = zone
    return result


class RenderingTests(SimpleTestCase):
    """communications.rendering: the templates' "IST" made the student's zone, and nothing else touched."""

    def test_every_prd_template_reads_the_students_zone_where_it_says_ist(self):
        for key, booking_type, _step, _name, body in TEMPLATES:
            prefix = booking_type.lower()
            with self.subTest(template=key):
                filled = render(body, values(prefix, time='6:00 PM', zone='UAE'))
                expected = render(body.replace(f'{{{{{prefix}_time}}}} IST', f'{{{{{prefix}_time}}}} UAE'),
                                  values(prefix, time='6:00 PM'))
                self.assertEqual(filled, expected)
                self.assertNotIn('IST', filled)

    def test_without_a_zone_every_template_reads_word_for_word_as_before(self):
        # A student in India, a lead with no zone, a message kept before zones were.
        for key, booking_type, _step, _name, body in TEMPLATES:
            prefix = booking_type.lower()
            with self.subTest(template=key):
                plain = values(prefix)
                expected = body
                for name, value in plain.items():
                    expected = expected.replace(f'{{{{{name}}}}}', value)
                self.assertEqual(render(body, plain), expected)

    def test_whatsapp_text_carries_the_zone_inside_the_templates_bold(self):
        text = whatsapp_message(PRD_BODIES['DEMO_ACKNOWLEDGEMENT'], values('demo', time='6:00 PM', zone='UAE'))
        self.assertIn('Demo class on *Wed, 28 Oct 2026 at 6:00 PM UAE*. We will share', text)
        confirmed = whatsapp_message(PRD_BODIES['DIAGNOSTIC_CONFIRMED'], values('diagnostic', time='6:00 PM', zone='UAE'))
        self.assertIn('📅 Date: Wed, 28 Oct 2026\n\n⏰ Time: 6:00 PM UAE\n\n💻 Access the test:', confirmed)

    def test_only_the_ist_right_after_a_time_placeholder_is_the_zone(self):
        zones = {'demo_timezone': 'UAE'}
        for body in ('IST {{demo_time}}', '{{demo_date}} IST', '{{demo_time}} ISTANBUL', '{{demo_time}}  IST',
                     '{{diagnostic_time}} IST', '{{demo_time}} ist'):
            with self.subTest(body=body):
                self.assertEqual(zoned(body, zones), body)
        self.assertEqual(zoned('at {{ demo_time }} IST.', zones), 'at {{ demo_time }} {{demo_timezone}}.')
        self.assertEqual(zoned('{{demo_time}} IST', {}), '{{demo_time}} IST')

    def test_a_message_keeps_its_zone_only_where_its_template_shows_a_time(self):
        uae = values('demo', time='6:00 PM', zone='UAE')
        self.assertEqual(message_values(PRD_BODIES['DEMO_ACKNOWLEDGEMENT'], uae),
                         {'demo_date': 'Wed, 28 Oct 2026', 'demo_time': '6:00 PM', 'demo_timezone': 'UAE',
                          'bde_name': 'Bde Anil'})
        self.assertEqual(message_values(PRD_BODIES['DEMO_AFTER_ACTIVITY'], uae), {'bde_name': 'Bde Anil'})
        self.assertNotIn('demo_timezone', message_values(PRD_BODIES['DEMO_ACKNOWLEDGEMENT'], values('demo')))


class ZonedBookings:
    """Public bookings whose page gave the student's zone."""

    def book_in(self, zone, booking_type=DEMO, day=DAY, at=EVENING, owned=True):
        child = next(self.children)
        booking, _ = create_booking(request(
            student=f'Child {child}', phone=f'05077{child:05d}', booking_type=booking_type, day=day, at=at,
            ref=self.links[booking_type].token if owned else None, student_timezone=zone,
        ), now=NOW)
        return booking

    @staticmethod
    def message(booking, step):
        return booking.communication_messages.select_related('template_version').get(template__step=step)

    @staticmethod
    def expected(key, time, date='Wed, 28 Oct 2026'):
        """The PRD text of ``key`` with the booking's values, its time and zone as ``time`` ("6:00 PM UAE")."""
        prefix = 'demo' if key.startswith('DEMO_') else 'diagnostic'
        return (prd_text(key).replace(f'{{{{{prefix}_date}}}}', date)
                .replace(f'{{{{{prefix}_time}}}} IST', time).replace('{{bde_name}}', 'Bde Anil'))

    @staticmethod
    def fresh(booking):
        return type(booking).objects.select_related('slot', 'lead__owner_bde', 'assigned_tutor').get(pk=booking.pk)


class ParentMessageTests(ZonedBookings, CommunicationTestCase):
    def test_a_uae_parents_acknowledgement_shows_the_uae_time(self):
        for booking_type in (DEMO, DIAGNOSTIC):
            with self.subTest(booking_type=booking_type):
                booking = self.book_in('Asia/Dubai', booking_type)
                ack = self.message(booking, Step.ACKNOWLEDGEMENT)
                prefix = booking_type.lower()
                self.assertEqual((ack.status, ack.body),
                                 (MessageStatus.PENDING, self.expected(f'{booking_type}_ACKNOWLEDGEMENT', '6:00 PM UAE')))
                self.assertEqual(ack.variables, {f'{prefix}_date': 'Wed, 28 Oct 2026', f'{prefix}_time': '6:00 PM',
                                                 f'{prefix}_timezone': 'UAE', 'bde_name': 'Bde Anil'})

    def test_an_indian_parent_reads_exactly_what_they_did(self):
        for zone in (None, 'Asia/Kolkata', 'Asia/Calcutta'):
            with self.subTest(zone=zone):
                booking = self.book_in(zone)
                self.assertEqual(booking.lead.student_timezone, zone or '')
                ack = self.message(booking, Step.ACKNOWLEDGEMENT)
                self.assertEqual(ack.body, self.expected('DEMO_ACKNOWLEDGEMENT', '7:30 PM IST'))
                self.assertEqual(ack.variables, {'demo_date': 'Wed, 28 Oct 2026', 'demo_time': '7:30 PM',
                                                 'bde_name': 'Bde Anil'})

    def test_a_zone_the_runtime_does_not_know_reads_indian_time(self):
        booking = self.book_in(None)
        # Saved past bookings.student_timezones.clean, as an old row might be.
        Lead.objects.filter(pk=booking.lead_id).update(student_timezone='Mars/Olympus_Mons')
        booking = self.fresh(booking)
        shown = preview(booking, Step.CONFIRMATION_REQUEST, now=NOW)
        self.assertIn('scheduled for *Wed, 28 Oct 2026 at 7:30 PM IST*,', shown.text)
        planner.lead_timezone_changed(booking.lead, NOW)
        ack = self.message(booking, Step.ACKNOWLEDGEMENT)
        self.assertEqual((ack.status, ack.body), (MessageStatus.PENDING, self.expected('DEMO_ACKNOWLEDGEMENT', '7:30 PM IST')))

    def test_the_date_is_the_parents_own_when_the_time_crosses_midnight(self):
        before = self.message(self.book_in('America/Los_Angeles', at=MORNING), Step.ACKNOWLEDGEMENT)
        self.assertEqual(before.body, self.expected('DEMO_ACKNOWLEDGEMENT', '9:30 PM Los Angeles', date='Tue, 27 Oct 2026'))
        after = self.message(self.book_in('Australia/Sydney', DIAGNOSTIC), Step.ACKNOWLEDGEMENT)
        self.assertEqual(after.body,
                         self.expected('DIAGNOSTIC_ACKNOWLEDGEMENT', '1:00 AM Sydney', date='Thu, 29 Oct 2026'))
        self.assertEqual(after.variables['diagnostic_date'], 'Thu, 29 Oct 2026')

    def test_the_confirmation_request_and_its_preview(self):
        for booking_type in (DEMO, DIAGNOSTIC):
            with self.subTest(booking_type=booking_type):
                booking = self.book_in('Asia/Dubai', booking_type)
                shown = preview(booking, Step.CONFIRMATION_REQUEST, now=NOW)
                self.assertIn('scheduled for *Wed, 28 Oct 2026 at 6:00 PM UAE*, and we are awaiting', shown.text)
                self.assertIn('scheduled for **Wed, 28 Oct 2026 at 6:00 PM UAE**, and we are awaiting', shown.body)
                message, _ = request_confirmation(booking, actor=self.bde, owner_bde=self.bde, now=NOW)
                self.assertEqual(message.body, self.expected(f'{booking_type}_CONFIRMATION_REQUEST', '6:00 PM UAE'))
                self.assertEqual(whatsapp_message(message.template_version.body, message.variables), shown.text)

    def test_the_confirmed_message(self):
        # On two days: the tutor teaches one class at a time.
        for booking_type, day, date in ((DEMO, DAY, 'Wed, 28 Oct 2026'),
                                        (DIAGNOSTIC, DAY + timedelta(days=1), 'Thu, 29 Oct 2026')):
            with self.subTest(booking_type=booking_type):
                booking = self.ready(self.book_in('Asia/Dubai', booking_type, day=day))
                record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
                confirmed = self.message(booking, Step.PARENT_CONFIRMATION)
                self.assertEqual(confirmed.status, MessageStatus.PENDING)
                self.assertIn(f'📅 Date: {date}\n\n⏰ Time: 6:00 PM UAE\n\n', confirmed.body)
                self.assertNotIn('IST', confirmed.body)
                self.assertEqual(confirmed.variables[f'{booking_type.lower()}_timezone'], 'UAE')

    def test_a_rescheduled_booking_shows_its_new_time_on_the_parents_clock(self):
        old = self.book_in('Asia/Dubai')
        new = reschedule_booking(old, DAY + timedelta(days=1), MORNING, reason_code=RescheduleReason.PARENT_REQUEST,
                                 actor=self.admin, now=NOW).booking
        old_ack = self.message(old, Step.ACKNOWLEDGEMENT)
        # The old booking's stays as it was written: cancelled, its time the old one.
        self.assertEqual((old_ack.status, old_ack.variables['demo_time']), (MessageStatus.CANCELLED, '6:00 PM'))
        new_ack = self.message(new, Step.ACKNOWLEDGEMENT)
        # 10:00 IST on 29 Oct is 8:30 in Dubai.
        self.assertEqual((new_ack.status, new_ack.body),
                         (MessageStatus.PENDING, self.expected('DEMO_ACKNOWLEDGEMENT', '8:30 AM UAE',
                                                               date='Thu, 29 Oct 2026')))

    def test_the_booking_and_its_workflow_times_stay_indian(self):
        india, uae = self.book(), self.book_in('Asia/Dubai')
        self.assertEqual(uae.slot_id, india.slot_id)
        self.assertEqual((uae.slot.local_date, uae.slot.local_time, uae.slot.starts_at),
                         (DAY, EVENING, EVENING_START))
        self.assertEqual(uae.details['display_time'], india.details['display_time'])

        def timings(booking):
            tasks = sorted((t.step, t.status, t.active_from, t.due_at, t.expires_at, t.owner_id)
                           for t in booking.communication_tasks.all())
            messages = sorted((m.template_id, m.status, m.scheduled_for, m.send_before)
                              for m in booking.communication_messages.all())
            return tasks, messages

        self.assertEqual(timings(uae), timings(india))
        shown = booking_communication(self.fresh(uae), NOW, user=self.admin)
        self.assertEqual((shown['timezone'], shown['booking']['slot']),
                         (BOOKING_TIMEZONE_NAME, booking_communication(self.fresh(india), NOW)['booking']['slot']))


class CorrectionTests(ZonedBookings, CommunicationTestCase):
    """A BDE or administrator correcting the zone (student_timezones.correct) writes the unsent messages again."""

    def correct(self, booking, zone):
        return student_timezones.correct(booking.lead_id, zone, actor=self.admin, via='test', now=NOW)[1]

    def test_the_unsent_messages_are_written_again_at_once(self):
        booking = self.book_in('Asia/Dubai')
        other = self.book_in('Asia/Dubai')
        self.assertTrue(self.correct(booking, 'Europe/London'))
        ack = self.message(booking, Step.ACKNOWLEDGEMENT)
        # 14:00 UTC is 2:00 PM in London once its summer time ended on 25 Oct.
        self.assertEqual((ack.status, ack.body), (MessageStatus.PENDING, self.expected('DEMO_ACKNOWLEDGEMENT', '2:00 PM UK')))
        self.assertEqual(ack.variables['demo_timezone'], 'UK')
        # Still waiting for what it lacks, with no text; another lead's are not touched.
        confirmed = self.message(booking, Step.PARENT_CONFIRMATION)
        self.assertEqual((confirmed.status, confirmed.body, confirmed.variables), (MessageStatus.WAITING, '', {}))
        self.assertIn('6:00 PM UAE', self.message(other, Step.ACKNOWLEDGEMENT).body)

        self.assertTrue(self.correct(booking, ''))
        ack = self.message(booking, Step.ACKNOWLEDGEMENT)
        self.assertEqual(ack.body, self.expected('DEMO_ACKNOWLEDGEMENT', '7:30 PM IST'))
        self.assertNotIn('demo_timezone', ack.variables)

    def test_the_same_zone_again_writes_nothing(self):
        booking = self.book_in('Asia/Dubai')
        written = self.message(booking, Step.ACKNOWLEDGEMENT).updated_at
        self.assertFalse(self.correct(booking, 'Asia/Dubai'))
        self.assertEqual(self.message(booking, Step.ACKNOWLEDGEMENT).updated_at, written)

    def test_a_message_already_handed_over_keeps_what_it_said(self):
        booking = self.book_in('Asia/Dubai')
        Message.objects.filter(demo_booking=booking, template__step=Step.ACKNOWLEDGEMENT).update(
            status=MessageStatus.SENT, sent_at=NOW,
        )
        sent = self.message(booking, Step.ACKNOWLEDGEMENT)
        self.correct(booking, 'Asia/Kolkata')
        again = self.message(booking, Step.ACKNOWLEDGEMENT)
        self.assertEqual((again.body, again.variables, again.updated_at), (sent.body, sent.variables, sent.updated_at))

    def test_a_message_kept_from_before_zones_shows_its_ist_text_in_the_history(self):
        booking = self.ready(self.book())
        Message.objects.filter(demo_booking=booking, template__step=Step.ACKNOWLEDGEMENT).update(
            status=MessageStatus.SENT, sent_at=NOW,
        )
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        self.correct(booking, 'Asia/Dubai')
        shown = {m['step']: m['text'] for m in booking_communication(self.fresh(booking), NOW)['messages']}
        self.assertIn('Demo class on *Wed, 28 Oct 2026 at 7:30 PM IST*.', shown[Step.ACKNOWLEDGEMENT])
        # The confirmed message, not sent yet, is written again with the zone.
        self.assertIn('⏰ Time: 6:00 PM UAE', shown[Step.PARENT_CONFIRMATION])


class SentTextTests(ZonedBookings, SenderTestCase):
    """What the provider is handed: WhatsApp's text with the parent's time, and the history showing the same."""

    def test_the_whatsapp_text_sent_to_a_uae_parent(self):
        for booking_type, phrase in ((DEMO, 'Demo class on *Wed, 28 Oct 2026 at 6:00 PM UAE*. We will share'),
                                     (DIAGNOSTIC, 'scheduled on *Wed, 28 Oct 2026 at 6:00 PM UAE*.')):
            with self.subTest(booking_type=booking_type):
                FakeProvider.reset(SendResult(accepted=True, status=MessageStatus.SENT,
                                              provider_message_id=f'wamid.{booking_type}'))
                booking = self.book_in('Asia/Dubai', booking_type)
                ack = self.message(booking, Step.ACKNOWLEDGEMENT)
                send_message(ack.pk, now=NOW)
                outgoing, _timeout = FakeProvider.outbox[-1]
                self.assertIn(phrase, outgoing.text)
                self.assertNotIn('IST', outgoing.text)
                self.assertEqual(outgoing.variables[f'{booking_type.lower()}_timezone'], 'UAE')
                ack = self.message(booking, Step.ACKNOWLEDGEMENT)
                self.assertEqual(ack.status, MessageStatus.SENT)
                history = {m['step']: m['text'] for m in booking_communication(self.fresh(booking), NOW)['messages']}
                self.assertEqual(history[Step.ACKNOWLEDGEMENT], outgoing.text)

    def test_the_confirmed_message_as_sent(self):
        FakeProvider.reset(SENT)
        booking = self.ready(self.book_in('Asia/Dubai', DIAGNOSTIC))
        record_parent_confirmation(booking, ParentConfirmation.CONFIRMED, actor=self.bde, now=NOW)
        send_message(self.message(booking, Step.PARENT_CONFIRMATION).pk, now=NOW)
        outgoing, _timeout = FakeProvider.outbox[-1]
        self.assertIn('📅 Date: Wed, 28 Oct 2026\n\n⏰ Time: 6:00 PM UAE\n\n💻 Access the test:', outgoing.text)

    def test_a_zone_saved_after_the_message_was_written_is_used_when_it_goes(self):
        # A later booking can give a lead its first zone (student_timezones.fill), without the correction's
        # refresh: the sender writes the message again as it claims it.
        FakeProvider.reset(SENT)
        booking = self.book_in(None)
        self.assertIn('7:30 PM IST', self.message(booking, Step.ACKNOWLEDGEMENT).body)
        Lead.objects.filter(pk=booking.lead_id).update(student_timezone='Asia/Dubai')
        send_message(self.message(booking, Step.ACKNOWLEDGEMENT).pk, now=NOW)
        outgoing, _timeout = FakeProvider.outbox[-1]
        self.assertIn('Demo class on *Wed, 28 Oct 2026 at 6:00 PM UAE*.', outgoing.text)
