"""
Student Local Time (bookings.student_timezones): the IANA zone a booking page
showed its slots in is kept on the student's lead -- given by the first
booking that brings a valid one, never replaced by a later booking -- and in
each booking's details as it was used; the staff APIs give it as
``student_timezone`` beside each booking's real instant (its slot's
starts_at); a BDE (their own enquiries) or an administrator corrects it, with
the old and new zones in the activity log. Every booking stays in its Indian
slot.
"""
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import RoleGroup
from activity.models import ActivityLog

from . import student_timezones
from .booking_service import LeadAlreadyBooked, assign_tutor, create_booking, create_invited_demo_booking
from .demo_invites import issue_invite
from .leads import name_key
from .models import DemoBooking, Lead, LeadSource
from .scheduling import BOOKING_TIMEZONE, booking_window, indian_today, slot_instants
from .tests_booking import DAY, DEMO, DIAGNOSTIC, EVENING, MORNING, NOW, BookingTestCase, account, book, request, schedule
from .tests_demo_invites import AFTER, DEMO_DAY, DemoInviteTestCase, InviteApiTestCase, lead_row
from .tests_enquiries import booking_on
from .tests_public_api import PublicApiTestCase

DUBAI, NEW_YORK, LONDON, QATAR = 'Asia/Dubai', 'America/New_York', 'Europe/London', 'Asia/Qatar'
CHANGE = 'change_student_timezone'


def lead_of(booking):
    return Lead.objects.get(pk=booking.lead_id)


def wall(instant, zone):
    """``instant`` (ISO, as the APIs give it) on the clock of ``zone``, as 'YYYY-MM-DD HH:MM'."""
    return datetime.fromisoformat(instant).astimezone(ZoneInfo(zone)).strftime('%Y-%m-%d %H:%M')


def enquiry(student='Riya', national='501234567', **fields):
    """A lead added by hand, as a BDE or an administrator adds one: no zone unless given."""
    return Lead.objects.create(
        parent_name='Asha Nair', phone_dial_code='+971', phone_number=national, phone_key=f'+971{national}',
        student_name=student, student_name_key=name_key(student), school_name='', grade='Class 8', syllabus='',
        source=LeadSource.PHONE_CALL, **fields,
    )


def without(role, codename=CHANGE):
    """Take ``codename`` off ``role``'s group: its holders no longer have it."""
    RoleGroup.objects.get(role=role).group.permissions.remove(Permission.objects.get(codename=codename))


# ------------------------------------------------------------------ bookings keep the zone

class BookingZoneTests(BookingTestCase):
    def test_a_booking_gives_a_new_lead_its_page_zone_and_keeps_it_in_its_details(self):
        demo, _ = book(student_timezone=DUBAI)
        diagnostic, _ = book(student='Ali', phone='0509990001', booking_type=DIAGNOSTIC, student_timezone=NEW_YORK)
        for booking, zone in ((demo, DUBAI), (diagnostic, NEW_YORK)):
            with self.subTest(booking_type=booking.booking_type):
                self.assertEqual((lead_of(booking).student_timezone, booking.details['student_timezone']), (zone, zone))
                # Display only: the booking is the Indian slot it asked for.
                self.assertEqual((booking.slot.local_date, booking.slot.local_time), (DAY, EVENING))
                self.assertEqual(booking.slot.starts_at, slot_instants(DAY, EVENING)[0])

    def test_a_zone_the_runtime_does_not_know_is_dropped_and_the_booking_is_made(self):
        values = (None, '', '   ', 'Not/AZone', 'Etc/Unknown', 42, ['Asia/Dubai'], {'zone': DUBAI}, DUBAI + 'x' * 64)
        for n, value in enumerate(values):
            with self.subTest(value=value):
                # One booking a slot (three seats each): a day of the window for each two.
                booking, created = book(student=f'Kid {n}', phone=f'05099900{n:02d}', student_timezone=value,
                                        day=DAY + timedelta(days=n // 2), at=(MORNING, EVENING)[n % 2])
                self.assertTrue(created)
                self.assertEqual((lead_of(booking).student_timezone, booking.details['student_timezone']), ('', ''))
        # Spaces around a zone it knows are not part of it.
        booking, _ = book(student='Meera', phone='0509990100', student_timezone=f'  {LONDON} ')
        self.assertEqual(lead_of(booking).student_timezone, LONDON)

    def test_a_later_booking_never_replaces_the_leads_zone_but_keeps_its_own(self):
        first, _ = book(student_timezone=DUBAI)
        second, _ = book(booking_type=DIAGNOSTIC, at=MORNING, student_timezone=LONDON)
        self.assertEqual(first.lead_id, second.lead_id)
        self.assertEqual(lead_of(second).student_timezone, DUBAI)
        self.assertEqual((first.details['student_timezone'], second.details['student_timezone']), (DUBAI, LONDON))

    def test_a_lead_without_a_zone_takes_the_first_a_booking_brings(self):
        # A BDE's enquiry, added with no zone, and a first booking that brought none.
        added = enquiry()
        first, _ = book(student_timezone=None)
        self.assertEqual((first.lead_id, lead_of(first).student_timezone), (added.pk, ''))
        second, _ = book(booking_type=DIAGNOSTIC, at=MORNING, student_timezone=QATAR)
        self.assertEqual(lead_of(second).student_timezone, QATAR)

    def test_a_refused_booking_gives_the_lead_no_zone(self):
        booking, _ = book()
        with self.assertRaises(LeadAlreadyBooked):
            create_booking(request(day=DAY + timedelta(days=1), student_timezone=DUBAI), now=NOW)
        self.assertEqual(lead_of(booking).student_timezone, '')


class CountryTests(BookingTestCase):
    def test_a_country_on_file_is_never_replaced_by_the_pages(self):
        lead = enquiry(country='Qatar')
        book(country='United Arab Emirates', student_timezone=DUBAI)
        book(booking_type=DIAGNOSTIC, at=MORNING, country='Undetected')
        lead.refresh_from_db()
        # The zone fills in on its own; the country stays the one on file.
        self.assertEqual((lead.country, lead.student_timezone), ('Qatar', DUBAI))

    def test_undetected_is_no_country_and_a_real_one_fills_it_in(self):
        for n, on_file in enumerate(('', 'Undetected')):
            with self.subTest(on_file=on_file):
                student, national = f'Kid {n}', f'5099930{n:02d}'
                lead = enquiry(student, national, country=on_file)
                book(student=student, phone=f'0{national}', country='Undetected', student_timezone=DUBAI)
                lead.refresh_from_db()
                self.assertEqual(lead.country, on_file)
                book(student=student, phone=f'0{national}', booking_type=DIAGNOSTIC, at=MORNING, country='Oman')
                lead.refresh_from_db()
                self.assertEqual(lead.country, 'Oman')

    def test_a_new_lead_takes_the_pages_country_as_sent(self):
        booking, _ = book(country='Undetected', student_timezone=DUBAI)
        # The zone never becomes a country: a guess stays a guess.
        self.assertEqual((lead_of(booking).country, lead_of(booking).student_timezone), ('Undetected', DUBAI))


# ------------------------------------------------------------------ Demo invitations

class InvitationZoneTests(DemoInviteTestCase):
    def test_an_invitation_booking_gives_a_lead_without_a_zone_its_pages_zone(self):
        invite, _ = self.invite()
        before = lead_row(self.lead.pk)
        booking, created = create_invited_demo_booking(
            invite.token, DEMO_DAY, EVENING, display_time='08:00 pm - 09:00 pm', now=AFTER, student_timezone=DUBAI,
        )
        self.assertTrue(created)
        after = lead_row(self.lead.pk)
        self.assertEqual((before['student_timezone'], after['student_timezone']), ('', DUBAI))
        # Nothing else about the lead changes.
        unchanged = {key for key in before if key not in ('student_timezone', 'updated_at')}
        self.assertEqual({key: after[key] for key in unchanged}, {key: before[key] for key in unchanged})
        self.assertEqual(booking.details['student_timezone'], DUBAI)
        self.assertEqual((booking.slot.local_date, booking.slot.local_time), (DEMO_DAY, EVENING))

    def test_an_invitation_booking_never_replaces_a_zone(self):
        Lead.objects.filter(pk=self.lead.pk).update(student_timezone=QATAR)
        invite, _ = self.invite()
        booking, _ = create_invited_demo_booking(invite.token, DEMO_DAY, EVENING, now=AFTER, student_timezone=LONDON)
        self.assertEqual((lead_of(booking).student_timezone, booking.details['student_timezone']), (QATAR, LONDON))

    def test_an_invitation_booking_without_a_usable_zone_changes_nothing(self):
        invite, _ = self.invite()
        before = lead_row(self.lead.pk)
        booking, _ = create_invited_demo_booking(invite.token, DEMO_DAY, EVENING, now=AFTER, student_timezone='Not/AZone')
        self.assertEqual(lead_row(self.lead.pk), before)
        self.assertEqual(booking.details['student_timezone'], '')


class InvitationApiZoneTests(InviteApiTestCase):
    def book(self, zone):
        invite, _ = issue_invite(self.diagnostic, self.admin)
        body = {'token': invite.token, 'date': booking_window(DEMO)[1].isoformat(), 'time': '19:30',
                'display_time': '07:30 pm - 08:30 pm', 'student_timezone': zone}
        return self.service().post('/api/public/demo-invites/book/', body, format='json')

    def test_the_invitation_page_sends_its_zone(self):
        res = self.book(NEW_YORK)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(Lead.objects.get(pk=self.lead.pk).student_timezone, NEW_YORK)
        self.assertEqual(DemoBooking.objects.get(pk=res.json()['booking_id']).details['student_timezone'], NEW_YORK)

    def test_a_zone_nobody_knows_never_refuses_the_booking(self):
        res = self.book('Not/AZone')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(Lead.objects.get(pk=self.lead.pk).student_timezone, '')


# ------------------------------------------------------------------ the public API

class PublicApiZoneTests(PublicApiTestCase):
    def test_both_pages_send_their_zone_and_it_reaches_the_lead(self):
        for path, student, zone in (('demo', 'Riya', DUBAI), ('diagnostic', 'Ali', NEW_YORK)):
            with self.subTest(path=path):
                res = self.post(path, student_name=student, student_timezone=zone,
                                **({'syllabus': 'IGCSE'} if path == 'diagnostic' else {}))
                self.assertEqual(res.status_code, 201, res.content)
                self.assertEqual(Lead.objects.get(student_name=student).student_timezone, zone)

    def test_a_missing_or_unusable_zone_never_refuses_a_booking(self):
        for n, value in enumerate((None, 'Not/AZone', 12, {'zone': DUBAI}, ['Asia/Dubai'], 'x' * 500)):
            with self.subTest(value=value):
                # One booking a slot (three seats each): a day of the window for each two.
                res = self.post(student_name=f'Kid {n}', phone={'dial_code': '+971', 'number': f'05099911{n:02d}'},
                                date=self.window[n // 2].isoformat(), time=('10:00', '19:30')[n % 2],
                                student_timezone=value)
                self.assertEqual(res.status_code, 201, res.content)
                self.assertEqual(Lead.objects.get(student_name=f'Kid {n}').student_timezone, '')
        res = self.post(student_name='No Zone', phone={'dial_code': '+971', 'number': '0509991200'},
                        date=self.window[3].isoformat(), time='19:30')
        self.assertEqual((res.status_code, Lead.objects.get(student_name='No Zone').student_timezone), (201, ''))


# ------------------------------------------------------------------ what staff are shown

class StaffApiTestCase(TestCase):
    """Bookings ahead of now (the window starts tomorrow), of leads with and without a zone."""

    def setUp(self):
        self.admin = account('admin_tz', role='ADMIN')
        self.bde = account('bde_tz', role='BDE')
        self.other_bde = account('bde_other', role='BDE')
        self.tutor = account('tutor_tz', role='TUTOR')
        schedule()
        self.day = indian_today() + timedelta(days=2)
        self.dubai = self.make('Riya', '0501230001', DUBAI)
        self.unknown = self.make('Ali', '0501230002', None, booking_type=DIAGNOSTIC, at=MORNING)
        for booking in (self.dubai, self.unknown):
            Lead.objects.filter(pk=booking.lead_id).update(owner_bde=self.bde, owner_assigned_at=NOW)

    def make(self, student, phone, zone, booking_type=DEMO, at=EVENING, day=None):
        booking, _ = create_booking(
            request(student=student, phone=phone, booking_type=booking_type, day=day or self.day, at=at,
                    student_timezone=zone),
        )
        return booking

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def get(self, user, path, **params):
        res = self.client_for(user).get(path, params)
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()


class StaffApiTests(StaffApiTestCase):
    def test_the_tutor_sees_the_zone_beside_each_slot(self):
        for booking in (self.dubai, self.unknown):
            assign_tutor(booking, self.tutor, actor=self.admin)
        rows = {row['id']: row for row in self.get(self.tutor, '/api/tutor/bookings/')['results']}
        self.assertEqual(
            {(rows[str(b.id)]['student_timezone'], rows[str(b.id)]['slot']['starts_at']) for b in (self.dubai, self.unknown)},
            {(DUBAI, self.dubai.slot.starts_at.isoformat()), (None, self.unknown.slot.starts_at.isoformat())},
        )
        detail = self.get(self.tutor, f'/api/tutor/bookings/demo/{self.dubai.id}/')
        self.assertEqual((detail['student_timezone'], detail['timezone']), (DUBAI, 'Asia/Kolkata'))

    def test_the_bde_sees_the_zone_on_enquiries_bookings_the_dashboard_and_the_history(self):
        lead_id = str(self.dubai.lead_id)
        listed = {row['id']: row for row in self.get(self.bde, '/api/bde/enquiries/')['results']}
        self.assertEqual(
            (listed[lead_id]['student_timezone'], listed[str(self.unknown.lead_id)]['student_timezone']), (DUBAI, None),
        )
        detail = self.get(self.bde, f'/api/bde/enquiries/{lead_id}/')
        self.assertEqual((detail['student_timezone'], detail['timezone']), (DUBAI, 'Asia/Kolkata'))
        self.assertEqual([(b['student_timezone'], b['starts_at']) for b in detail['bookings']],
                         [(DUBAI, self.dubai.slot.starts_at.isoformat())])
        rows = self.get(self.bde, '/api/bde/bookings/demo/')['results']
        self.assertEqual([(row['id'], row['student_timezone']) for row in rows], [(str(self.dubai.id), DUBAI)])
        dashboard = self.get(self.bde, '/api/bde/dashboard/')
        self.assertEqual({row['student_timezone'] for row in dashboard['upcoming']['rows']}, {DUBAI, None})
        history = self.get(self.bde, '/api/bde/activity/', enquiry=lead_id)['results']
        self.assertTrue(history)
        self.assertEqual({row['booking']['student_timezone'] for row in history}, {DUBAI})

    def test_the_bde_agenda_names_the_zone_of_todays_bookings(self):
        today = booking_on(Lead.objects.get(pk=self.dubai.lead_id), indian_today(), at=MORNING)
        agenda = self.get(self.bde, '/api/bde/dashboard/')['agenda']['rows']
        self.assertEqual([(row['id'], row['student_timezone']) for row in agenda], [(str(today.id), DUBAI)])

    def test_the_admin_sees_the_zone_on_leads_and_bookings(self):
        lead_id = str(self.dubai.lead_id)
        listed = {row['id']: row for row in self.get(self.admin, '/api/leads/')['results']}
        self.assertEqual(listed[lead_id]['student_timezone'], DUBAI)
        detail = self.get(self.admin, f'/api/leads/{lead_id}/')
        self.assertEqual((detail['student_timezone'], [b['student_timezone'] for b in detail['bookings']]), (DUBAI, [DUBAI]))
        rows = {row['id']: row for row in self.get(self.admin, '/api/bookings/demo/')['results']}
        self.assertEqual(rows[str(self.dubai.id)]['student_timezone'], DUBAI)
        diagnostic = self.get(self.admin, '/api/bookings/diagnostic/')['results']
        self.assertEqual([row['student_timezone'] for row in diagnostic], [None])
        booking = self.get(self.admin, f'/api/bookings/demo/{self.dubai.id}/')
        self.assertEqual((booking['student_timezone'], booking['lead']['student_timezone'], booking['timezone']),
                         (DUBAI, DUBAI, 'Asia/Kolkata'))

    def test_a_stored_zone_the_runtime_no_longer_knows_reads_as_unknown(self):
        Lead.objects.filter(pk=self.dubai.lead_id).update(student_timezone='Mars/Olympus_Mons')
        booking = self.get(self.admin, f'/api/bookings/demo/{self.dubai.id}/')
        self.assertEqual((booking['student_timezone'], booking['lead']['student_timezone']), (None, None))
        self.assertIsNone(self.get(self.bde, f'/api/bde/enquiries/{self.dubai.lead_id}/')['student_timezone'])

    def test_nothing_the_parent_typed_rides_along(self):
        # The booking's details (the submission, display_time included) never reach a staff screen.
        assign_tutor(self.dubai, self.tutor, actor=self.admin)
        for user, path in ((self.tutor, f'/api/tutor/bookings/demo/{self.dubai.id}/'),
                           (self.bde, f'/api/bde/enquiries/{self.dubai.lead_id}/'),
                           (self.admin, f'/api/bookings/demo/{self.dubai.id}/')):
            with self.subTest(path=path):
                body = json.dumps(self.get(user, path))
                self.assertNotIn('06:00 pm - 07:00 pm', body)
                self.assertNotIn('display_time', body)


class RescheduleZoneTests(StaffApiTestCase):
    def test_a_moved_booking_is_read_at_its_new_slot_and_the_old_one_at_its_own(self):
        # 10:00 IST is 23:30 the evening before in New York (EST); 19:30 IST is 09:00 the same day.
        booking = self.make('Sara', '0501230003', NEW_YORK, at=MORNING)
        new_day = self.day + timedelta(days=1)
        res = self.client_for(self.admin).post(
            f'/api/bookings/demo/{booking.id}/reschedule/',
            {'date': new_day.isoformat(), 'time': '19:30', 'reason': 'PARENT_REQUEST'}, format='json',
        )
        self.assertEqual(res.status_code, 201, res.content)
        moved = res.json()['booking']
        new_starts_at = slot_instants(new_day, EVENING)[0]
        self.assertEqual((moved['slot']['starts_at'], moved['student_timezone']), (new_starts_at.isoformat(), NEW_YORK))
        old = self.get(self.admin, f'/api/bookings/demo/{booking.id}/')
        self.assertEqual((old['status'], old['slot']['starts_at']), ('RESCHEDULED', booking.slot.starts_at.isoformat()))
        self.assertNotEqual(wall(old['slot']['starts_at'], NEW_YORK), wall(moved['slot']['starts_at'], NEW_YORK))
        # The enquiry lists both, each at its own slot, in the lead's one zone.
        detail = self.get(self.admin, f'/api/leads/{booking.lead_id}/')
        self.assertEqual(
            sorted((entry['status'], entry['starts_at'], entry['student_timezone']) for entry in detail['bookings']),
            sorted([('BOOKED', new_starts_at.isoformat(), NEW_YORK),
                    ('RESCHEDULED', booking.slot.starts_at.isoformat(), NEW_YORK)]),
        )
        # The submission it carries over keeps the zone its page used; its display_time is never shown.
        replacement = DemoBooking.objects.get(pk=moved['id'])
        self.assertEqual(replacement.details['student_timezone'], NEW_YORK)

    def test_a_correction_shows_every_booking_of_the_lead_in_the_new_zone(self):
        res = self.client_for(self.admin).put(f'/api/leads/{self.dubai.lead_id}/student-timezone/',
                                              {'student_timezone': LONDON}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        rows = {row['id']: row for row in self.get(self.admin, '/api/bookings/demo/')['results']}
        self.assertEqual(rows[str(self.dubai.id)]['student_timezone'], LONDON)
        # The booking's own record of what its page used stays as it was.
        self.assertEqual(DemoBooking.objects.get(pk=self.dubai.pk).details['student_timezone'], DUBAI)


# ------------------------------------------------------------------ correcting it

class CorrectionTests(StaffApiTestCase):
    def bde_url(self, booking):
        return f'/api/bde/enquiries/{booking.lead_id}/student-timezone/'

    def admin_url(self, booking):
        return f'/api/leads/{booking.lead_id}/student-timezone/'

    def put(self, user, path, value):
        return self.client_for(user).put(path, {'student_timezone': value}, format='json')

    def logs(self):
        return list(ActivityLog.objects.filter(action='lead.update_student_timezone').order_by('created_at'))

    def test_a_bde_corrects_their_own_enquiry_and_the_log_keeps_both_zones(self):
        res = self.put(self.bde, self.bde_url(self.dubai), LONDON)
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual((body['changed'], body['student_timezone'], body['id']), (True, LONDON, str(self.dubai.lead_id)))
        self.assertEqual({b['student_timezone'] for b in body['bookings']}, {LONDON})
        [log] = self.logs()
        self.assertEqual((log.entity_type, log.entity_id, log.actor_id), ('lead', str(self.dubai.lead_id), self.bde.pk))
        self.assertEqual(log.changes, {'student_timezone': {'old': DUBAI, 'new': LONDON}})
        self.assertEqual(log.context['via'], 'bde_workspace')
        for private in ('Riya', 'Asha Nair', '501230001'):
            self.assertNotIn(private, str(log.entity_label) + json.dumps(log.context) + json.dumps(log.changes))

    def test_the_same_zone_changes_nothing_and_null_clears_it(self):
        res = self.put(self.bde, self.bde_url(self.dubai), DUBAI)
        self.assertEqual((res.status_code, res.json()['changed'], self.logs()), (200, False, []))
        res = self.put(self.bde, self.bde_url(self.dubai), None)
        self.assertEqual((res.status_code, res.json()['changed'], res.json()['student_timezone']), (200, True, None))
        self.assertEqual(lead_of(self.dubai).student_timezone, '')
        self.assertEqual(self.logs()[-1].changes, {'student_timezone': {'old': DUBAI, 'new': None}})
        # A lead with no zone yet gets one from a correction.
        res = self.put(self.bde, self.bde_url(self.unknown), QATAR)
        self.assertEqual((res.status_code, lead_of(self.unknown).student_timezone), (200, QATAR))
        self.assertEqual(self.logs()[-1].changes, {'student_timezone': {'old': None, 'new': QATAR}})

    def test_a_zone_the_runtime_does_not_know_is_refused(self):
        for value in ('Not/AZone', 'asia/nowhere', 'Etc/Unknown', 42, ['Asia/Dubai'], 'x' * 65):
            with self.subTest(value=value):
                for user, path in ((self.bde, self.bde_url(self.dubai)), (self.admin, self.admin_url(self.dubai))):
                    res = self.put(user, path, value)
                    self.assertEqual((res.status_code, res.json()['error']), (400, 'INVALID_TIMEZONE'))
        res = self.client_for(self.bde).put(self.bde_url(self.dubai), {}, format='json')
        self.assertEqual((res.status_code, res.json()['error']), (400, 'INVALID_TIMEZONE'))
        self.assertEqual((lead_of(self.dubai).student_timezone, self.logs()), (DUBAI, []))

    def test_a_bde_reaches_only_their_own_enquiries(self):
        nobodys = self.make('Zoya', '0501230009', DUBAI)
        Lead.objects.filter(pk=nobodys.lead_id).update(owner_bde=None, owner_assigned_at=None, owner_link=None)
        theirs = self.make('Noor', '0501230010', DUBAI)
        Lead.objects.filter(pk=theirs.lead_id).update(owner_bde=self.other_bde, owner_assigned_at=NOW)
        for booking in (nobodys, theirs):
            with self.subTest(student=booking.lead.student_name):
                res = self.put(self.bde, self.bde_url(booking), LONDON)
                self.assertEqual((res.status_code, res.json()['error']), (404, 'NOT_FOUND'))
                self.assertEqual(lead_of(booking).student_timezone, DUBAI)
        res = self.client_for(self.bde).put('/api/bde/enquiries/00000000-0000-0000-0000-000000000000/student-timezone/',
                                            {'student_timezone': LONDON}, format='json')
        self.assertEqual(res.status_code, 404)
        # Nor any lead through the administrators' route: it needs view_all_leads.
        self.assertEqual(self.put(self.bde, self.admin_url(theirs), LONDON).status_code, 403)
        self.assertEqual(self.logs(), [])

    def test_an_administrator_corrects_any_lead(self):
        nobodys = self.make('Zoya', '0501230009', None)
        Lead.objects.filter(pk=nobodys.lead_id).update(owner_bde=None, owner_assigned_at=None, owner_link=None)
        for booking in (self.dubai, nobodys):
            with self.subTest(student=booking.lead.student_name):
                res = self.put(self.admin, self.admin_url(booking), NEW_YORK)
                self.assertEqual(res.status_code, 200, res.content)
                body = res.json()
                self.assertEqual((body['changed'], body['student_timezone']), (True, NEW_YORK))
                self.assertIn('owner', body)  # the lead in full, as GET /api/leads/<id>/ answers
        self.assertEqual([log.context['via'] for log in self.logs()], ['admin_leads', 'admin_leads'])
        res = self.put(self.admin, '/api/leads/00000000-0000-0000-0000-000000000000/student-timezone/', LONDON)
        self.assertEqual((res.status_code, res.json()['error']), (404, 'NOT_FOUND'))

    def test_the_permission_is_needed_and_tutors_and_mentors_only_read(self):
        mentor = account('mentor_tz', role='MENTOR')
        for user in (self.tutor, mentor):
            for path in (self.bde_url(self.dubai), self.admin_url(self.dubai)):
                with self.subTest(role=user.role, path=path):
                    self.assertEqual(self.put(user, path, LONDON).status_code, 403)
        without('BDE')
        without('ADMIN')
        self.assertEqual(self.put(self.bde, self.bde_url(self.dubai), LONDON).status_code, 403)
        self.assertEqual(self.put(self.admin, self.admin_url(self.dubai), LONDON).status_code, 403)
        self.assertEqual((lead_of(self.dubai).student_timezone, self.logs()), (DUBAI, []))

    def test_a_superuser_is_no_bde(self):
        root = account('root_tz', role='ADMIN', is_superuser=True)
        res = self.put(root, self.bde_url(self.dubai), LONDON)
        self.assertEqual((res.status_code, res.json()['error']), (403, 'NOT_A_BDE'))
        self.assertEqual(self.put(root, self.admin_url(self.dubai), LONDON).status_code, 200)


# ------------------------------------------------------------------ adding an enquiry or a lead with one

class ManualZoneTests(TestCase):
    def setUp(self):
        self.bde = account('bde_add', role='BDE')
        self.admin = account('admin_add', role='ADMIN')

    def post(self, user, path, **overrides):
        client = APIClient()
        client.force_authenticate(user)
        body = {'parent_name': 'Meera Menon', 'phone_dial_code': '+91', 'phone_number': '09876543210',
                'student_name': 'Kavya', 'grade': 'Class 7', 'source': 'PHONE_CALL', **overrides}
        return client.post(path, body, format='json')

    def test_an_enquiry_or_a_lead_is_added_with_a_zone_or_without_one(self):
        for user, path in ((self.bde, '/api/bde/enquiries/'), (self.admin, '/api/leads/')):
            with self.subTest(path=path):
                Lead.objects.all().delete()
                res = self.post(user, path, student_timezone=DUBAI)
                self.assertEqual(res.status_code, 201, res.content)
                self.assertEqual((res.json()['student_timezone'], Lead.objects.get().student_timezone), (DUBAI, DUBAI))
                Lead.objects.all().delete()
                for blank in ('', None):
                    res = self.post(user, path, student_timezone=blank)
                    self.assertEqual((res.status_code, Lead.objects.get().student_timezone), (201, ''))
                    Lead.objects.all().delete()
                res = self.post(user, path)
                self.assertEqual((res.status_code, res.json()['student_timezone']), (201, None))
                Lead.objects.all().delete()

    def test_a_zone_the_runtime_does_not_know_is_refused(self):
        for user, path in ((self.bde, '/api/bde/enquiries/'), (self.admin, '/api/leads/')):
            with self.subTest(path=path):
                res = self.post(user, path, student_timezone='Not/AZone')
                self.assertEqual(res.status_code, 400, res.content)
                self.assertIn('student_timezone', res.json()['fields'])
                self.assertFalse(Lead.objects.exists())


# ------------------------------------------------------------------ the helpers

class HelperTests(TestCase):
    def test_clean_keeps_only_zones_the_runtime_knows(self):
        for value, kept in ((DUBAI, DUBAI), ('Asia/Calcutta', 'Asia/Calcutta'), (' Europe/London ', LONDON),
                            ('UTC', 'UTC'), ('Etc/GMT+5', 'Etc/GMT+5'), ('', ''), (None, ''), ('Not/AZone', ''),
                            (5, ''), ('a' * 65, '')):
            with self.subTest(value=value):
                self.assertEqual(student_timezones.clean(value), kept)

    def test_the_indian_slot_and_the_students_clock_are_the_same_instant(self):
        # 8 Nov 2026, 07:30 IST (the example the feature names) is 06:00 in Dubai.
        starts_at, _ = slot_instants(date(2026, 11, 8), time(7, 30))
        self.assertEqual(starts_at.astimezone(BOOKING_TIMEZONE).strftime('%d %b %H:%M'), '08 Nov 07:30')
        self.assertEqual(starts_at.astimezone(ZoneInfo(DUBAI)).strftime('%d %b %H:%M'), '08 Nov 06:00')
        self.assertEqual(starts_at.astimezone(ZoneInfo(NEW_YORK)).strftime('%d %b %H:%M'), '07 Nov 21:00')
