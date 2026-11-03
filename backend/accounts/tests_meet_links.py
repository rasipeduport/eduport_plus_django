"""
A tutor's permanent Google Meet link (accounts.meet_links) and the Team
endpoint that sets it (PUT /api/team/<id>/meet-link/,
accounts.team.TeamMemberMeetLinkView): only a Google Meet meeting link, only
on a tutor, only by a team manager -- the activity log saying that it
changed, never what it is -- and gone with the tutor role.
"""
import json
from datetime import time, timedelta

from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from activity.models import ActivityLog
from bookings.booking_service import assign_tutor
from bookings.models import BookingSlot, BookingStatus, DemoBooking, Lead, ReferralStatus
from bookings.scheduling import BOOKING_TIMEZONE, slot_instants

from .meet_links import InvalidMeetLink, canonical_meet_link
from .models import User
from .tests_auth import PLAIN_STORAGES, STRONG, admin_change_form_data

LINK = 'https://meet.google.com/abc-defg-hij'
NEW_LINK = 'https://meet.google.com/kln-opqr-stu'
EVENING = time(19, 30)


def account(username, role, **extra):
    return User.objects.create_user(
        email=f'{username}@meet.test', username=username, password=None,
        full_name=username.replace('_', ' ').title(), role=role, **extra,
    )


def url(account):
    return f'/api/team/{account.pk}/meet-link/'


class CanonicalMeetLinkTests(SimpleTestCase):
    def test_a_link_in_its_stored_form_is_kept(self):
        self.assertEqual(canonical_meet_link(LINK), LINK)

    def test_a_pasted_link_is_stored_in_its_stored_form(self):
        for pasted in (
            'meet.google.com/abc-defg-hij', '  https://MEET.Google.com/ABC-DEFG-HIJ \n', f'{LINK}/',
            f'{LINK}?authuser=0', f'{LINK}?pli=1#chat', f'{LINK}#x',
        ):
            with self.subTest(pasted=pasted):
                self.assertEqual(canonical_meet_link(pasted), LINK)

    def test_an_empty_value_is_no_link(self):
        for empty in (None, '', '   '):
            with self.subTest(empty=empty):
                self.assertIsNone(canonical_meet_link(empty))

    def test_anything_but_a_google_meet_meeting_link_is_refused(self):
        for value in (
            'http://meet.google.com/abc-defg-hij',  # not https
            'ftp://meet.google.com/abc-defg-hij',
            'https://meet.google.com/new',  # would start a new meeting
            'https://meet.google.com/lookup/abcdefgh',
            'https://meet.google.com/abc-defg-hi',
            'https://meet.google.com/abcdefghij',
            'https://meet.google.com/abc-defg-hij/extra',
            'https://meet.google.com/abc-defg-hij extra',
            'https://www.meet.google.com/abc-defg-hij',
            'https://meet.google.com.example.test/abc-defg-hij',
            'https://example.test/meet.google.com/abc-defg-hij',
            'https://user@meet.google.com/abc-defg-hij',
            'https://zoom.us/j/123456789',
            'javascript:alert(1)',
            'https://meet.google.com/abc-defg-hıj',  # a dotless i
            'https://meet.google.com/abc-defg-hiK',  # the Kelvin sign, a K under IGNORECASE
            f'{LINK}?{"x" * 400}',
        ):
            with self.subTest(value=value), self.assertRaises(InvalidMeetLink):
                canonical_meet_link(value)

    def test_a_value_that_is_not_text_is_refused(self):
        for value in (12, True, ['https://meet.google.com/abc-defg-hij'], {'url': LINK}):
            with self.subTest(value=value), self.assertRaises(InvalidMeetLink):
                canonical_meet_link(value)


class TeamMeetLinkTestCase(TestCase):
    def setUp(self):
        self.admin = account('admin_one', 'ADMIN')
        self.tutor = account('tutor_one', 'TUTOR')
        self.mentor = account('mentor_one', 'MENTOR')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def put(self, target, value, as_user=None, **extra):
        if as_user is not None:
            self.client.force_authenticate(as_user)
        return self.client.put(url(target), {'tutor_meet_link': value, **extra}, format='json')

    def stored(self, target=None):
        return User.objects.get(pk=(target or self.tutor).pk).tutor_meet_link

    def logs(self):
        return ActivityLog.objects.filter(action='user.meet_link_update', entity_id=str(self.tutor.pk)).order_by('created_at')


class SettingTests(TeamMeetLinkTestCase):
    def test_an_administrator_sets_a_tutors_link(self):
        response = self.put(self.tutor, LINK)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['tutor_meet_link'], LINK)
        self.assertEqual(self.stored(), LINK)
        self.assertEqual(self.client.get(f'/api/team/{self.tutor.pk}/').json()['tutor_meet_link'], LINK)

    def test_a_pasted_link_is_saved_in_its_stored_form(self):
        self.assertEqual(self.put(self.tutor, ' meet.google.com/ABC-defg-hij?authuser=0 ').status_code, 200)
        self.assertEqual(self.stored(), LINK)

    def test_it_can_be_changed_and_removed(self):
        self.put(self.tutor, LINK)
        self.assertEqual(self.put(self.tutor, NEW_LINK).json()['tutor_meet_link'], NEW_LINK)
        for empty in (None, ''):
            with self.subTest(empty=empty):
                self.put(self.tutor, LINK)
                response = self.put(self.tutor, empty)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json()['tutor_meet_link'])
                self.assertIsNone(self.stored())

    def test_an_unrelated_link_is_refused_and_nothing_changes(self):
        self.put(self.tutor, LINK)
        for value in ('https://zoom.us/j/1', 'https://meet.google.com/new', 42):
            with self.subTest(value=value):
                response = self.put(self.tutor, value)
                self.assertEqual(response.status_code, 400)
                self.assertEqual((response.json()['error'], response.json()['fields']), ('INVALID_MEET_LINK', ['tutor_meet_link']))
                self.assertEqual(self.stored(), LINK)

    def test_only_a_tutor_has_a_link(self):
        for role in ('MENTOR', 'BDE', 'SALES_TL'):
            with self.subTest(role=role):
                other = account(f'someone_{role.lower()}', role)
                response = self.put(other, LINK)
                self.assertEqual((response.status_code, response.json()['error']), (400, 'NOT_A_TUTOR'))
                self.assertIsNone(self.stored(other))

    def test_a_deactivated_tutor_keeps_a_link_that_can_be_set(self):
        User.objects.filter(pk=self.tutor.pk).update(is_active=False, deactivated_at=timezone.now())
        self.assertEqual(self.put(self.tutor, LINK).status_code, 200)
        self.assertEqual(self.stored(), LINK)

    def test_the_link_is_the_only_field_and_it_is_required(self):
        missing = self.client.put(url(self.tutor), {}, format='json')
        self.assertEqual((missing.status_code, missing.json()['error']), (400, 'INVALID_INPUT'))
        extra = self.put(self.tutor, LINK, role='ADMIN')
        self.assertEqual((extra.status_code, extra.json()['error']), (400, 'UNKNOWN_FIELDS'))
        self.assertIsNone(self.stored())

    def test_the_details_patch_never_sets_it(self):
        response = self.client.patch(f'/api/team/{self.tutor.pk}/', {'tutor_meet_link': LINK}, format='json')
        self.assertEqual((response.status_code, response.json()['error']), (400, 'UNKNOWN_FIELDS'))
        self.assertIsNone(self.stored())

    def test_an_unknown_account_is_not_found(self):
        student = account('parent_one', 'STUDENT')
        response = self.put(student, LINK)
        self.assertEqual((response.status_code, response.json()['error']), (404, 'NOT_FOUND'))


class PermissionTests(TeamMeetLinkTestCase):
    def test_only_team_managers_may_set_it(self):
        reader = account('mentor_reader', 'MENTOR')
        reader.user_permissions.add(Permission.objects.get(content_type__app_label='accounts', codename='view_team'))
        for caller in (self.tutor, account('tutor_two', 'TUTOR'), self.mentor, reader, account('bde_one', 'BDE'),
                       account('sales_one', 'SALES_TL')):
            with self.subTest(caller=caller.username):
                self.assertEqual(self.put(self.tutor, LINK, as_user=caller).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.put(self.tutor, LINK).status_code, 403)
        self.assertIsNone(self.stored())

    def test_a_superuser_sets_it_but_never_on_their_own_account(self):
        root = User.objects.create_superuser(username='root', email='root@meet.test', full_name='Root', password=STRONG)
        self.assertEqual(self.put(self.tutor, LINK, as_user=root).status_code, 200)
        teaching_root = account('su_tutor', 'TUTOR', is_superuser=True)
        response = self.put(teaching_root, LINK, as_user=teaching_root)
        self.assertEqual((response.status_code, response.json()['error']), (403, 'SELF_CHANGE_FORBIDDEN'))

    def test_directory_readers_never_see_it(self):
        self.put(self.tutor, LINK)
        reader = account('mentor_reader', 'MENTOR')
        reader.user_permissions.add(Permission.objects.get(content_type__app_label='accounts', codename='view_team'))
        self.client.force_authenticate(reader)
        detail = self.client.get(f'/api/team/{self.tutor.pk}/')
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn('tutor_meet_link', detail.json())
        self.assertNotIn('meet.google.com', self.client.get('/api/team/').content.decode())


class LogTests(TeamMeetLinkTestCase):
    def test_the_log_says_how_it_changed_never_the_link(self):
        self.put(self.tutor, LINK)
        self.put(self.tutor, LINK)  # the same again: nothing changed, nothing logged
        self.put(self.tutor, NEW_LINK)
        self.put(self.tutor, None)
        entries = list(self.logs())
        self.assertEqual([entry.context['change'] for entry in entries], ['added', 'changed', 'removed'])
        self.assertEqual({entry.context['live_bookings_updated'] for entry in entries}, {0})
        self.assertEqual({entry.actor_id for entry in entries}, {self.admin.pk})
        written = json.dumps([[e.changes, e.context, e.entity_label] for e in ActivityLog.objects.all()])
        self.assertNotIn('meet.google.com', written)
        self.assertNotIn('abc-defg-hij', written)


def live_booking(tutor, days=2, link=None, status=BookingStatus.BOOKED, phone='501230000'):
    """A Demo booking at 19:30 IST ``days`` from today (negative: past), assigned to ``tutor`` with ``link``."""
    local_date = timezone.now().astimezone(BOOKING_TIMEZONE).date() + timedelta(days=days)
    starts_at, ends_at = slot_instants(local_date, EVENING)
    slot = BookingSlot.objects.create(
        booking_type='DEMO', local_date=local_date, local_time=EVENING, starts_at=starts_at, ends_at=ends_at,
    )
    lead = Lead.objects.create(
        parent_name='Asha Nair', phone_dial_code='+971', phone_number=phone, phone_key=f'+971{phone}',
        student_name=f'Child {phone}', student_name_key=f'child {phone}', school_name='School', grade='Class 8',
        syllabus='CBSE',
    )
    return DemoBooking.objects.create(
        lead=lead, slot=slot, seat=1, status=status, referral_status=ReferralStatus.NO_REF,
        assigned_tutor=tutor, tutor_assigned_at=timezone.now() if tutor else None, tutor_meet_link=link,
    )


class BookingTests(TeamMeetLinkTestCase):
    def test_live_bookings_take_the_new_link_and_past_ones_keep_theirs(self):
        self.put(self.tutor, LINK)
        upcoming = live_booking(None, phone='501230001')
        assign_tutor(upcoming, self.tutor, actor=self.admin)
        past = live_booking(self.tutor, days=-2, link=LINK, phone='501230002')
        upcoming.refresh_from_db()
        self.assertEqual(upcoming.tutor_meet_link, LINK)

        self.put(self.tutor, NEW_LINK)
        upcoming.refresh_from_db()
        past.refresh_from_db()
        self.assertEqual((upcoming.tutor_meet_link, past.tutor_meet_link), (NEW_LINK, LINK))
        context = self.logs().last().context
        self.assertEqual((context['change'], context['live_bookings_updated']), ('changed', 1))


class RoleChangeTests(TeamMeetLinkTestCase):
    def test_a_tutor_who_changes_role_loses_the_link_and_past_bookings_keep_theirs(self):
        self.put(self.tutor, LINK)
        past = live_booking(self.tutor, days=-3, link=LINK)
        response = self.client.patch(f'/api/team/{self.tutor.pk}/', {'role': 'MENTOR'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()['tutor_meet_link'])
        self.assertIsNone(self.stored())
        past.refresh_from_db()
        self.assertEqual(past.tutor_meet_link, LINK)
        entry = ActivityLog.objects.get(action='user.role_change', entity_id=str(self.tutor.pk))
        self.assertTrue(entry.context['meet_link_removed'])
        self.assertNotIn('meet.google.com', json.dumps([entry.changes, entry.context]))

    def test_a_role_change_without_a_link_says_nothing_of_one(self):
        self.client.patch(f'/api/team/{self.tutor.pk}/', {'role': 'MENTOR'}, format='json')
        entry = ActivityLog.objects.get(action='user.role_change', entity_id=str(self.tutor.pk))
        self.assertNotIn('meet_link_removed', entry.context)


@override_settings(STORAGES=PLAIN_STORAGES)
class DjangoAdminRoleChangeTests(TestCase):
    def test_a_tutor_whose_role_changes_in_the_django_admin_loses_the_link(self):
        root = User.objects.create_superuser(username='root', email='root@meet.test', full_name='Root', password=STRONG)
        tutor = account('tutor_one', 'TUTOR', tutor_meet_link=LINK)
        browser = Client()
        browser.force_login(root)
        change = f'/admin/accounts/user/{tutor.pk}/change/'
        data = admin_change_form_data(browser.get(change))
        self.assertNotIn('tutor_meet_link', data, 'set through Team only')
        data['role'] = 'MENTOR'
        self.assertEqual(browser.post(change, data).status_code, 302)
        tutor.refresh_from_db()
        self.assertEqual((tutor.role, tutor.tutor_meet_link), ('MENTOR', None))


class DatabaseTests(TestCase):
    def test_only_a_tutor_may_hold_a_link(self):
        mentor = account('mentor_one', 'MENTOR')
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=mentor.pk).update(tutor_meet_link=LINK)

    def test_only_a_link_in_its_stored_form_is_held(self):
        tutor = account('tutor_one', 'TUTOR')
        for value in ('https://zoom.us/j/1', 'meet.google.com/abc-defg-hij', 'https://meet.google.com/ABC-DEFG-HIJ', ''):
            with self.subTest(value=value), self.assertRaises(IntegrityError), transaction.atomic():
                User.objects.filter(pk=tutor.pk).update(tutor_meet_link=value)

    def test_existing_accounts_have_no_link(self):
        self.assertIsNone(account('tutor_one', 'TUTOR').tutor_meet_link)
