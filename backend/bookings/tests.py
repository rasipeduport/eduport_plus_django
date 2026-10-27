"""
BDE booking links: one permanent Demo and one Diagnostic link per active BDE,
served only to that BDE by GET /api/bde/booking-links/.
"""
import importlib
import json
import re
import threading
import time
from types import SimpleNamespace
from unittest import mock, skipUnless

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from activity.models import ActivityLog

from . import services
from .models import BookingLink, BookingType, new_link_token

User = get_user_model()

URL = '/api/bde/booking-links/'
TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{22}$')
LINK_RE = re.compile(r'^https://plus\.eduport\.app/(demo|exam)\?ref=([A-Za-z0-9_-]{22})$')


def make_account(username, role='BDE', **extra):
    # No usable password: these accounts are only ever force-authenticated.
    return User.objects.create_user(
        email=f'{username}@links.test', username=username, password=None,
        full_name=username.replace('_', ' ').title(), role=role, **extra,
    )


def token_of(link):
    return LINK_RE.match(link['url']).group(2)


class BookingLinkModelTests(TestCase):
    def setUp(self):
        self.bde = make_account('bde_one')

    def link(self, booking_type=BookingType.DEMO, bde=None, **fields):
        return BookingLink.objects.create(bde=bde or self.bde, booking_type=booking_type, **fields)

    def test_tokens_are_random_and_url_safe(self):
        tokens = {new_link_token() for _ in range(50)}
        self.assertEqual(len(tokens), 50)
        for token in tokens:
            self.assertRegex(token, TOKEN_RE)

    def test_a_token_says_nothing_about_its_owner(self):
        token = self.link().token
        self.assertRegex(token, TOKEN_RE)
        for value in (str(self.bde.pk), self.bde.pk.hex, self.bde.username, self.bde.email):
            self.assertNotIn(value, token)

    def test_one_active_link_per_bde_and_type(self):
        self.link(BookingType.DEMO)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link(BookingType.DEMO)
        # The other type, and another BDE's link of the same type, are fine.
        self.link(BookingType.DIAGNOSTIC)
        self.link(BookingType.DEMO, bde=make_account('bde_two'))

    def test_revoked_links_stay_as_history_beside_the_active_one(self):
        old = self.link(BookingType.DEMO)
        BookingLink.objects.filter(pk=old.pk).update(revoked_at=timezone.now(), revoked_by=self.bde)
        new = self.link(BookingType.DEMO)
        self.assertEqual(BookingLink.objects.filter(bde=self.bde, booking_type=BookingType.DEMO).count(), 2)
        self.assertEqual(list(BookingLink.objects.filter(bde=self.bde, revoked_at__isnull=True)), [new])

    def test_tokens_are_unique(self):
        taken = self.link().token
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link(BookingType.DEMO, bde=make_account('bde_two'), token=taken)

    def test_the_type_and_the_revocation_must_be_legal(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link('REFERRAL')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.link(BookingType.DEMO, revoked_by=self.bde)  # a revoker without a revocation time

    def test_a_bde_who_owns_links_cannot_be_deleted(self):
        self.link()
        with self.assertRaises(ProtectedError):
            self.bde.delete()

    def test_str_never_shows_the_token(self):
        link = self.link()
        self.assertNotIn(link.token, str(link))


@override_settings(MARKETING_SITE_URL='https://plus.eduport.app')
class BookingLinksApiTests(APITestCase):
    def setUp(self):
        self.bde = make_account('bde_one')
        self.other_bde = make_account('bde_two')

    def get(self, user, **params):
        self.client.force_authenticate(user=user)
        return self.client.get(URL, params)

    def links(self, user, **params):
        response = self.get(user, **params)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()['links']

    def assertRefused(self, user, error=None):
        response = self.get(user)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertNotIn('links', response.json())
        if error:
            self.assertEqual(response.json()['error'], error)

    def test_the_route(self):
        self.assertEqual(reverse('bookings:bde-booking-links'), URL)

    def test_a_bde_gets_one_demo_and_one_diagnostic_link(self):
        links = self.links(self.bde)
        self.assertEqual([link['booking_type'] for link in links], ['DEMO', 'DIAGNOSTIC'])
        for link, page in zip(links, ('demo', 'exam')):
            with self.subTest(booking_type=link['booking_type']):
                # The token travels only inside the URL: no raw token, row id or owner.
                self.assertEqual(set(link), {'booking_type', 'url', 'created_at'})
                match = LINK_RE.match(link['url'])
                self.assertIsNotNone(match, link['url'])
                self.assertEqual(match.group(1), page)
        tokens = [token_of(link) for link in links]
        self.assertNotEqual(tokens[0], tokens[1])
        self.assertEqual(set(BookingLink.objects.filter(bde=self.bde).values_list('token', flat=True)), set(tokens))

    def test_links_are_the_same_on_every_request(self):
        first = self.links(self.bde)
        for _ in range(3):
            self.assertEqual(self.links(self.bde), first)
        self.assertEqual(BookingLink.objects.filter(bde=self.bde).count(), 2)

    def test_issuing_is_logged_once_per_link_and_never_the_token(self):
        self.links(self.bde)
        self.links(self.bde)
        rows = ActivityLog.objects.filter(action='booking_link.issue')
        self.assertEqual(rows.count(), 2)
        links = {str(link.id): link for link in BookingLink.objects.filter(bde=self.bde)}
        tokens = [link.token for link in links.values()]
        for row in rows:
            with self.subTest(entity_label=row.entity_label):
                link = links[row.entity_id]
                self.assertEqual((row.entity_type, row.actor_id, row.actor_role), ('booking_link', self.bde.pk, 'BDE'))
                self.assertEqual(row.entity_label, link.get_booking_type_display())
                self.assertEqual((row.context['booking_type'], row.context['bde_id']), (link.booking_type, str(self.bde.pk)))
                recorded = json.dumps([row.entity_id, row.entity_label, row.changes, row.context])
                for token in tokens:
                    self.assertNotIn(token, recorded)

    def test_two_bdes_get_different_links_and_see_only_their_own(self):
        mine = self.links(self.bde)
        theirs = self.links(self.other_bde)
        self.assertFalse({link['url'] for link in mine} & {link['url'] for link in theirs})
        for account, links in ((self.bde, mine), (self.other_bde, theirs)):
            with self.subTest(account=account.username):
                owned = set(BookingLink.objects.filter(bde=account).values_list('token', flat=True))
                self.assertEqual({token_of(link) for link in links}, owned)

    def test_a_forged_bde_id_changes_nothing(self):
        theirs = self.links(self.other_bde)
        mine = self.links(self.bde)
        other_id = str(self.other_bde.pk)
        for forged in ({'bde_id': other_id}, {'bde': other_id}, {'user_id': other_id}, {'owner': other_id}):
            with self.subTest(forged=forged):
                self.assertEqual(self.links(self.bde, **forged), mine)
        # Naming a BDE who has no links yet issues none for them either.
        newcomer = make_account('bde_three')
        self.assertEqual(self.links(self.bde, bde_id=str(newcomer.pk)), mine)
        self.assertFalse(BookingLink.objects.filter(bde=newcomer).exists())
        self.assertEqual(self.links(self.other_bde), theirs)

    def test_other_roles_are_refused(self):
        for role in ('ADMIN', 'MENTOR', 'TUTOR', 'STUDENT', 'SALES_TL', 'UNASSIGNED'):
            with self.subTest(role=role):
                self.assertRefused(make_account(f'refused_{role.lower()}', role))
        self.assertFalse(BookingLink.objects.exists())

    def test_anonymous_callers_are_refused(self):
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(BookingLink.objects.exists())

    def test_superusers_get_links_only_as_bdes(self):
        # Decision D1: a superuser holds the permission whatever the role, but
        # links belong to BDE accounts only.
        root = User.objects.create_superuser(username='root', email='root@links.test', full_name='Root', password=None)
        self.assertRefused(root, 'NOT_A_BDE')
        self.assertFalse(BookingLink.objects.exists())
        super_bde = make_account('super_bde', is_superuser=True)
        self.assertEqual(len(self.links(super_bde)), 2)

    def test_inactive_and_deactivated_bdes_are_refused(self):
        self.links(self.bde)
        User.objects.filter(pk=self.bde.pk).update(is_active=False, deactivated_at=timezone.now())
        self.assertRefused(User.objects.get(pk=self.bde.pk))
        # A deactivation stamp alone is enough, should is_active ever disagree with it.
        User.objects.filter(pk=self.other_bde.pk).update(deactivated_at=timezone.now())
        self.assertRefused(User.objects.get(pk=self.other_bde.pk), 'NOT_A_BDE')
        self.assertFalse(BookingLink.objects.filter(bde=self.other_bde).exists())

    def test_an_account_whose_role_is_no_longer_bde_is_refused(self):
        before = self.links(self.bde)
        account = User.objects.get(pk=self.bde.pk)
        account.role = 'MENTOR'
        account.save()
        self.assertRefused(User.objects.get(pk=self.bde.pk))
        # Links are permanent: made a BDE again, the account gets the same ones back.
        account = User.objects.get(pk=self.bde.pk)
        account.role = 'BDE'
        account.save()
        self.assertEqual(self.links(User.objects.get(pk=self.bde.pk)), before)

    def test_a_revoked_link_is_replaced_and_the_other_one_kept(self):
        demo, diagnostic = self.links(self.bde)
        BookingLink.objects.filter(bde=self.bde, booking_type=BookingType.DEMO).update(revoked_at=timezone.now())
        new_demo, same_diagnostic = self.links(self.bde)
        self.assertNotEqual(new_demo['url'], demo['url'])
        self.assertEqual(same_diagnostic, diagnostic)

    @override_settings(MARKETING_SITE_URL='https://booking.example.test/')
    def test_links_point_at_the_configured_site(self):
        demo, diagnostic = self.links(self.bde)
        self.assertRegex(demo['url'], r'^https://booking\.example\.test/demo\?ref=[A-Za-z0-9_-]{22}$')
        self.assertRegex(diagnostic['url'], r'^https://booking\.example\.test/exam\?ref=[A-Za-z0-9_-]{22}$')


class TokenCollisionTests(TestCase):
    def setUp(self):
        self.bde = make_account('bde_one')
        self.taken = BookingLink.objects.create(bde=make_account('bde_two'), booking_type=BookingType.DEMO).token

    def test_a_colliding_token_is_drawn_again(self):
        fresh_demo, fresh_diagnostic = 'D' * 22, 'G' * 22
        with mock.patch.object(services, 'new_link_token', side_effect=[self.taken, fresh_demo, fresh_diagnostic]):
            demo, diagnostic = services.links_for(self.bde)
        self.assertEqual((demo.booking_type, demo.token), (BookingType.DEMO, fresh_demo))
        self.assertEqual((diagnostic.booking_type, diagnostic.token), (BookingType.DIAGNOSTIC, fresh_diagnostic))
        self.assertEqual(BookingLink.objects.filter(bde=self.bde).count(), 2)

    def test_issuing_gives_up_when_every_token_collides(self):
        with mock.patch.object(services, 'new_link_token', return_value=self.taken) as draw:
            with self.assertRaises(services.LinkIssueError):
                services.links_for(self.bde)
        self.assertEqual(draw.call_count, services.MAX_TOKEN_ATTEMPTS)
        self.assertFalse(BookingLink.objects.filter(bde=self.bde).exists())
        self.assertFalse(ActivityLog.objects.filter(action='booking_link.issue').exists())


@skipUnless(connection.vendor == 'postgresql', 'the race relies on PostgreSQL unique-index locking')
class ConcurrentIssueTests(TransactionTestCase):
    """
    A BDE's first requests racing each other still leave exactly one active
    link per type, and every request answers with those two.
    ``active_links_by_type`` is slowed down so that every request reads "no
    links yet" before any of them inserts.
    """

    def setUp(self):
        # A TransactionTestCase empties the database between tests, the role
        # groups the accounts migrations seed included. Seed them again (a
        # no-op where present) so the BDE holds its permission.
        for migration, seed in (
            ('0008_role_groups', 'seed_role_groups'),
            ('0009_hub_roles_bde_sales_tl', 'seed_role_groups'),
            ('0010_bde_booking_links_permission', 'grant_bde_permissions'),
        ):
            getattr(importlib.import_module(f'accounts.migrations.{migration}'), seed)(
                django_apps, SimpleNamespace(connection=connection)
            )
        self.bde = make_account('race_bde')

    def test_racing_first_requests_issue_each_link_once(self):
        real_read = services.active_links_by_type
        draws = []

        def slow_read(bde):
            found = real_read(bde)
            time.sleep(0.5)
            return found

        def counted_token():
            draws.append(1)
            return new_link_token()

        callers = 4
        barrier = threading.Barrier(callers)
        answers, errors = [], []

        def fetch():
            try:
                client = APIClient()
                client.force_authenticate(user=self.bde)
                barrier.wait(timeout=10)
                response = client.get(URL)
                answers.append((response.status_code, response.json()))
            except Exception as exc:  # reported below rather than lost in the thread
                errors.append(exc)
            finally:
                connection.close()

        with mock.patch.object(services, 'active_links_by_type', slow_read), \
                mock.patch.object(services, 'new_link_token', counted_token):
            threads = [threading.Thread(target=fetch) for _ in range(callers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        self.assertEqual(errors, [])
        # Every request tried to issue both links -- the race really happened --
        # and all but one insert per type was refused and read the winner back.
        self.assertEqual(len(draws), callers * len(BookingType.values))
        self.assertEqual([code for code, _body in answers], [status.HTTP_200_OK] * callers)
        self.assertEqual(len({json.dumps(body, sort_keys=True) for _code, body in answers}), 1, answers)
        self.assertEqual(
            sorted(BookingLink.objects.filter(bde=self.bde).values_list('booking_type', 'revoked_at')),
            [(BookingType.DEMO, None), (BookingType.DIAGNOSTIC, None)],
        )
        self.assertEqual(ActivityLog.objects.filter(action='booking_link.issue').count(), 2)
