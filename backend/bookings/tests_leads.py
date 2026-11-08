"""
Lead management: the lead forms' public API (bookings.lead_intake), the
administrators' Leads API (bookings.lead_admin), giving a lead to a BDE
(bookings.ownership) and the status every lead shows (bookings.lead_status).
"""
import uuid
from datetime import datetime, time, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from activity.models import ActivityLog
from communications.models import MessageStatus, OwnerRole, Step, TaskStatus
from communications.rendering import Requirement, requirements
from communications.tests_planning import CommunicationTestCase

from . import lead_intake
from .lead_status import LeadStatus, with_status
from .models import BookingLink, BookingSlot, BookingStatus, BookingType, Lead, LeadSource, ReferralStatus, booking_model
from .ownership import ANY_OWNER, NotAnActiveBde, assign_owner
from .scheduling import BOOKING_TIMEZONE
from .tests_booking import NOW
from .tests_enquiries import account, booking, lead
from .throttles import LeadCreateThrottle

DEMO, DIAGNOSTIC = BookingType.DEMO, BookingType.DIAGNOSTIC
KEY = 'k' * 40
PUBLIC_LEADS = '/api/public/leads/'
LEADS = '/api/leads/'
BDE_ENQUIRIES = '/api/bde/enquiries/'

# What the marketing server sends for a submission of the main website's
# demo form (eduport-plus lib/lead-backend/format.ts leadPayload): the form's
# "8th" and "CBSE" as the lead model reads them, its utm_source alone.
WEBSITE_FORM = {
    'source': 'WEBSITE',
    'parent_name': 'Asha Nair',
    'student_name': 'Riya',
    'school': 'Delhi Private School',
    'phone': {'dial_code': '+971', 'number': '0501234567'},
    'grade': 'Class 8',
    'syllabus': 'CBSE',
    'country': 'United Arab Emirates',
    'utm': {'utm_source': 'instagram'},
}
LANDING_UTM = {
    'utm_source': 'google', 'utm_medium': 'cpc', 'utm_campaign': 'maths-uae', 'utm_content': 'hero', 'utm_term': 'tuition',
}


def form(**overrides):
    return {**WEBSITE_FORM, **overrides}


def status_of(of, now=None):
    return with_status(Lead.objects.filter(pk=of.pk), now or timezone.now()).get().lead_status


# ------------------------------------------------------------------ the lead forms' API

@override_settings(BOOKING_SERVICE_API_KEYS=[KEY])
class LeadFormTestCase(TestCase):
    def setUp(self):
        cache.clear()  # the rate limits count here
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {KEY}', HTTP_X_BOOKING_CLIENT_IP='203.0.113.7')

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def submit(self, body=None, **overrides):
        return self.client.post(PUBLIC_LEADS, body if body is not None else form(**overrides), format='json')


class LeadFormTests(LeadFormTestCase):
    def test_a_website_lead_is_stored_unassigned_with_its_source(self):
        res = self.submit()
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()['created'], True)
        made = Lead.objects.get(pk=res.json()['lead_id'])
        self.assertEqual(
            (made.source, made.parent_name, made.student_name, made.school_name, made.phone_dial_code, made.phone_number,
             made.phone_key, made.grade, made.syllabus, made.country, made.parent_email),
            ('WEBSITE', 'Asha Nair', 'Riya', 'Delhi Private School', '+971', '501234567', '+971501234567', 'Class 8',
             'CBSE', 'United Arab Emirates', ''),
        )
        self.assertEqual(made.source_details, {'utm_source': 'instagram'})
        self.assertEqual((made.owner_bde, made.owner_link, made.owner_assigned_at, made.created_by), (None, None, None, None))
        entry = ActivityLog.objects.get(action='lead.create')
        self.assertEqual((entry.actor, entry.entity_id, entry.context),
                         (None, str(made.id), {'source': 'WEBSITE', 'grade': 'Class 8', 'via': 'lead_form'}))
        # Ids and choices only: no names, phone numbers or campaign values in the log.
        for value in ('Asha', 'Riya', '501234567', 'instagram'):
            self.assertNotIn(value, f'{entry.entity_label} {entry.context}')

    def test_a_landing_page_lead_keeps_every_campaign_parameter(self):
        res = self.submit(source='LANDING_PAGE', grade='Class 3', utm=LANDING_UTM)
        self.assertEqual(res.status_code, 201, res.content)
        made = Lead.objects.get(pk=res.json()['lead_id'])
        self.assertEqual((made.source, made.grade, made.source_details), ('LANDING_PAGE', 'Class 3', LANDING_UTM))

    def test_a_repeated_submission_makes_no_second_lead_and_changes_nothing(self):
        first = self.submit()
        # A retry, then the same child again from the landing page under another parent name and school.
        retry = self.submit()
        again = self.submit(source='LANDING_PAGE', parent_name='Someone Else', school='Other School',
                            phone={'dial_code': '+971', 'number': '501234567'}, student_name=' riya ', utm=LANDING_UTM)
        self.assertEqual([res.status_code for res in (first, retry, again)], [201, 200, 200])
        self.assertEqual({res.json()['lead_id'] for res in (first, retry, again)}, {first.json()['lead_id']})
        self.assertEqual([retry.json()['created'], again.json()['created']], [False, False])
        kept = Lead.objects.get()
        self.assertEqual((kept.source, kept.parent_name, kept.school_name, kept.source_details),
                         ('WEBSITE', 'Asha Nair', 'Delhi Private School', {'utm_source': 'instagram'}))
        self.assertEqual(ActivityLog.objects.filter(action='lead.create').count(), 1)

    def test_a_child_who_already_has_a_lead_keeps_it_as_it_is(self):
        bde = account('bde_keeper')
        known = lead(bde, 'Riya', source=LeadSource.PHONE_CALL)
        res = self.submit()
        self.assertEqual((res.status_code, res.json()), (200, {'lead_id': str(known.id), 'created': False}))
        known.refresh_from_db()
        self.assertEqual((known.source, known.owner_bde, known.source_details), ('PHONE_CALL', bde, {}))

    def test_a_submission_racing_another_for_the_same_child_answers_the_lead_that_won(self):
        winner = lead(None, 'Riya', source=LeadSource.LANDING_PAGE)
        real = lead_intake.existing_lead
        # Both lookups before the insert miss the winner, as when it commits in between.
        with mock.patch('bookings.lead_intake.existing_lead', side_effect=[None, None, real('+971501234567', 'riya')]):
            res = self.submit()
        self.assertEqual((res.status_code, res.json()), (200, {'lead_id': str(winner.id), 'created': False}))
        self.assertEqual(Lead.objects.count(), 1)

    def test_nothing_in_a_submission_names_an_owner(self):
        bde = account('bde_named')
        token = BookingLink.objects.create(bde=bde, booking_type=DEMO).token
        res = self.submit(owner_bde=str(bde.id), owner_bde_id=str(bde.id), ref=token, created_by=str(bde.id))
        self.assertEqual(res.status_code, 201, res.content)
        made = Lead.objects.get(pk=res.json()['lead_id'])
        self.assertEqual((made.owner_bde, made.owner_link, made.created_by), (None, None, None))

    def test_invalid_submissions_are_refused_and_store_nothing(self):
        cases = {
            'no parent name': form(parent_name='   '),
            'no student name': form(student_name=''),
            'no school': {key: value for key, value in WEBSITE_FORM.items() if key != 'school'},
            'a short phone number': form(phone={'dial_code': '+971', 'number': '12'}),
            'a made-up dial code': form(phone={'dial_code': '971', 'number': '0501234567'}),
            "the form's own grade label": form(grade='8th'),
            'a class not offered': form(grade='Class 11'),
            'a syllabus not offered': form(syllabus='Cambridge'),
            "a booking page's source": form(source='BOOKING_PAGE'),
            'a hand-picked source': form(source='PHONE_CALL'),
            'no source': {key: value for key, value in WEBSITE_FORM.items() if key != 'source'},
            'a control character': form(parent_name='Asha\x00Nair'),
            'a line break in a name': form(student_name='Riya\nDROP'),
            'a campaign tag too long': form(utm={'utm_campaign': 'x' * 201}),
            'a name too long': form(parent_name='A' * 256),
            'not an object': [],
        }
        for case, body in cases.items():
            with self.subTest(case=case):
                cache.clear()  # every refused submission counts towards the rate limit too
                res = self.submit(body)
                self.assertEqual(res.status_code, 400, res.content)
                self.assertEqual(res.json()['error'], 'VALIDATION_ERROR')
        self.assertEqual(Lead.objects.count(), 0)

    @override_settings(LEAD_PHONE_DAILY_LIMIT=1)
    def test_one_phone_number_makes_a_limited_number_of_leads_a_day(self):
        self.assertEqual(self.submit().status_code, 201)
        sibling = self.submit(student_name='Arjun')
        self.assertEqual((sibling.status_code, sibling.json()['error']), (429, 'TOO_MANY_LEADS'))
        # A retry of the first is still answered with its lead.
        self.assertEqual(self.submit().status_code, 200)
        self.assertEqual(Lead.objects.count(), 1)

    def test_submissions_are_rate_limited_per_parent_address(self):
        with mock.patch.object(LeadCreateThrottle, 'rate', '2/min', create=True):
            allowed = [self.submit(student_name=name).status_code for name in ('A', 'B')]
            limited = self.submit(student_name='C')
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {KEY}', HTTP_X_BOOKING_CLIENT_IP='198.51.100.9')
            elsewhere = self.submit(student_name='C')
        self.assertEqual((allowed, limited.status_code, elsewhere.status_code), ([201, 201], 429, 201))

    def test_only_a_post_is_answered(self):
        self.assertEqual(self.client.get(PUBLIC_LEADS).status_code, 405)


class LeadFormSecurityTests(LeadFormTestCase):
    def test_no_key_or_a_wrong_one_is_refused(self):
        for header in (None, 'Bearer wrong', f'Token {KEY}'):
            with self.subTest(header=header and header[:12]):
                self.client.credentials(**({'HTTP_AUTHORIZATION': header} if header else {}))
                res = self.submit()
                self.assertEqual(res.status_code, 401)
                self.assertIn('Bearer', res['WWW-Authenticate'])
        with override_settings(BOOKING_SERVICE_API_KEYS=[]):
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {KEY}')
            self.assertEqual(self.submit().status_code, 401)
        self.assertEqual(Lead.objects.count(), 0)

    def test_signed_in_staff_are_refused(self):
        self.client.credentials()
        for role in ('ADMIN', 'BDE'):
            with self.subTest(role=role):
                self.client.force_authenticate(account(f'signed_{role.lower()}', role=role, is_superuser=role == 'ADMIN'))
                self.assertEqual(self.submit().status_code, 403)
        self.assertEqual(Lead.objects.count(), 0)

    def test_the_service_key_opens_no_staff_endpoint(self):
        for path in (LEADS, f'{LEADS}bdes/', BDE_ENQUIRIES, '/api/bookings/demo/'):
            with self.subTest(path=path):
                self.assertIn(self.client.get(path).status_code, (401, 403))


# ------------------------------------------------------------------ the administrators' Leads API

class AdminLeadsTestCase(TestCase):
    def setUp(self):
        self.admin = account('admin_ops', role='ADMIN')
        self.bde = account('bde_anil')
        self.other_bde = account('bde_bina')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def ids(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return [row['id'] for row in response.json()['results']]

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client


def new_lead(**overrides):
    return {
        'parent_name': 'Meera Menon', 'phone_dial_code': '+91', 'phone_number': '09876543210', 'student_name': 'Kavya',
        'grade': 'Class 7', 'source': 'PHONE_CALL', 'school_name': 'Kendriya Vidyalaya', 'syllabus': 'CBSE',
        'country': 'India', 'parent_email': 'meera@example.com', **overrides,
    }


class AdminLeadAccessTests(AdminLeadsTestCase):
    def test_only_administrators_reach_the_leads_api(self):
        some = lead(self.bde, 'Riya')
        requests = [
            ('get', LEADS, None), ('get', f'{LEADS}bdes/', None), ('get', f'{LEADS}{some.id}/', None),
            ('post', LEADS, new_lead()),
            ('put', f'{LEADS}{some.id}/owner/', {'bde_id': str(self.other_bde.id), 'current_owner_id': str(self.bde.id)}),
        ]
        for role in ('BDE', 'TUTOR', 'MENTOR', 'SALES_TL'):
            client = self.as_user(self.bde if role == 'BDE' else account(f'user_{role.lower()}', role=role))
            for method, path, body in requests:
                with self.subTest(role=role, method=method, path=path):
                    self.assertEqual(getattr(client, method)(path, body, format='json').status_code, 403)
        for method, path, body in requests:
            with self.subTest(caller='anonymous', method=method, path=path):
                self.assertIn(getattr(APIClient(), method)(path, body, format='json').status_code, (401, 403))
        some.refresh_from_db()
        self.assertEqual((some.owner_bde, Lead.objects.count()), (self.bde, 1))


class AdminLeadListTests(AdminLeadsTestCase):
    def setUp(self):
        super().setUp()
        link = BookingLink.objects.create(bde=self.bde, booking_type=DEMO)
        self.from_link = lead(self.bde, 'Linked', phone='501000001', link=link)
        self.unlinked = lead(None, 'Booked', phone='501000002')
        self.website = lead(None, 'Web', phone='501000003', source=LeadSource.WEBSITE)
        self.landing = lead(None, 'Land', phone='501000004', source=LeadSource.LANDING_PAGE)
        self.by_hand = lead(self.other_bde, 'Called', phone='501000005', source=LeadSource.PHONE_CALL)
        booking(self.website, 2, DIAGNOSTIC)

    def test_every_lead_is_listed_with_its_owner_and_when_it_came_in(self):
        rows = {row['id']: row for row in self.client.get(LEADS).json()['results']}
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[str(self.from_link.id)]['owner'], {'id': str(self.bde.id), 'full_name': 'Bde Anil'})
        self.assertEqual(rows[str(self.by_hand.id)]['owner']['full_name'], 'Bde Bina')
        self.assertIsNone(rows[str(self.website.id)]['owner'])
        self.assertEqual(rows[str(self.website.id)]['created_at'], self.website.created_at.isoformat())
        self.assertEqual(
            {row['source_label'] for row in rows.values()},
            {'Demo link', 'Booking page', 'Website', 'Landing page', 'Phone call'},
        )
        self.assertEqual((rows[str(self.website.id)]['status'], rows[str(self.website.id)]['status_label']),
                         ('DIAGNOSTIC_BOOKED', 'Diagnostic booked'))
        # The latest received first.
        self.assertEqual(self.ids(self.client.get(LEADS))[0], str(self.by_hand.id))

    def test_filters(self):
        cases = [
            ({'source': 'WEBSITE'}, [self.website]),
            ({'source': 'landing_page'}, [self.landing]),
            ({'source': 'DEMO_LINK'}, [self.from_link]),
            # As listed: a booking page's lead no link brought.
            ({'source': 'BOOKING_PAGE'}, [self.unlinked]),
            ({'source': 'PHONE_CALL'}, [self.by_hand]),
            ({'owner': str(self.bde.id)}, [self.from_link]),
            ({'owner': 'unassigned'}, [self.unlinked, self.website, self.landing]),
            ({'status': 'DIAGNOSTIC_BOOKED'}, [self.website]),
            ({'status': 'NEW', 'owner': 'unassigned'}, [self.unlinked, self.landing]),
            # A stage of either type.
            ({'status': 'booked'}, [self.website]),
            ({'q': 'land'}, [self.landing]),
            ({'q': '0501 000 005'}, [self.by_hand]),
        ]
        for params, expected in cases:
            with self.subTest(params=params):
                self.assertEqual(set(self.ids(self.client.get(LEADS, params))), {str(each.id) for each in expected})
        Lead.objects.filter(pk=self.landing.pk).update(parent_email='parent@land.example')
        self.assertEqual(self.ids(self.client.get(LEADS, {'q': 'land.example'})), [str(self.landing.id)])

    def test_the_dates_a_lead_came_in_on_are_indian_dates(self):
        today = timezone.now().astimezone(BOOKING_TIMEZONE).date()
        midnight = datetime.combine(today, time.min, tzinfo=BOOKING_TIMEZONE)
        # Just before midnight in India came in yesterday; just after, today -- whatever the server's zone.
        Lead.objects.filter(pk=self.website.pk).update(created_at=midnight - timedelta(minutes=5))
        Lead.objects.filter(pk=self.landing.pk).update(created_at=midnight + timedelta(minutes=5))
        Lead.objects.exclude(pk__in=[self.website.pk, self.landing.pk]).update(created_at=midnight - timedelta(days=9))
        yesterday, iso = (today - timedelta(days=1)).isoformat(), today.isoformat()
        cases = [
            ({'from': iso, 'to': iso}, [self.landing]),
            ({'from': yesterday, 'to': yesterday}, [self.website]),
            ({'from': yesterday}, [self.website, self.landing]),
            ({'to': yesterday, 'source': 'WEBSITE'}, [self.website]),
            ({'to': (today - timedelta(days=9)).isoformat()}, [self.from_link, self.unlinked, self.by_hand]),
        ]
        for params, expected in cases:
            with self.subTest(params=params):
                self.assertEqual(set(self.ids(self.client.get(LEADS, params))), {str(each.id) for each in expected})

    def test_unknown_filters_are_refused(self):
        for params in ({'status': 'DONE'}, {'source': 'SALESFORCE'}, {'owner': 'someone'}, {'from': '08-11-2026'},
                       {'to': '2026-02-30'}, {'from': '2026-11-08', 'to': '2026-11-01'}):
            with self.subTest(params=params):
                res = self.client.get(LEADS, params)
                self.assertEqual((res.status_code, res.json()['error']), (400, 'INVALID_INPUT'))

    def test_one_lead_in_full(self):
        Lead.objects.filter(pk=self.website.pk).update(source_details={'utm_source': 'instagram'})
        res = self.client.get(f'{LEADS}{self.website.id}/')
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual((data['source'], data['owner'], data['added_by'], data['source_details']),
                         ('WEBSITE', None, None, {'utm_source': 'instagram'}))
        self.assertEqual([(b['booking_type'], b['status']) for b in data['bookings']], [('DIAGNOSTIC', 'BOOKED')])
        self.assertEqual(self.client.get(f'{LEADS}{uuid.uuid4()}/').status_code, 404)

    def test_the_bde_choices(self):
        gone = account('bde_gone')
        lead(gone, 'Orphan', phone='501000009')
        gone.deactivated_at, gone.is_active = timezone.now(), False
        gone.save(update_fields=['deactivated_at', 'is_active'])
        account('bde_idle', deactivated_at=timezone.now(), is_active=False)
        account('tutor_only', role='TUTOR')
        res = self.client.get(f'{LEADS}bdes/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            [(row['full_name'], row['assignable']) for row in res.json()['results']],
            [('Bde Anil', True), ('Bde Bina', True), ('Bde Gone', False), ('Bde Idle', False)],
        )


class ManualLeadTests(AdminLeadsTestCase):
    def test_an_administrator_adds_a_lead_owned_by_nobody(self):
        res = self.client.post(LEADS, new_lead(), format='json')
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()
        self.assertEqual((data['source'], data['source_label'], data['status'], data['owner']),
                         ('PHONE_CALL', 'Phone call', 'NEW', None))
        self.assertEqual((data['added_by']['full_name'], data['parent_email'], data['phone']),
                         ('Admin Ops', 'meera@example.com', '+91 9876543210'))
        made = Lead.objects.get(pk=data['id'])
        self.assertEqual((made.created_by, made.owner_bde), (self.admin, None))
        entry = ActivityLog.objects.get(action='lead.create')
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual({key: entry.context[key] for key in ('source', 'grade', 'via')},
                         {'source': 'PHONE_CALL', 'grade': 'Class 7', 'via': 'admin_leads'})
        # In the same list as every other lead.
        self.assertIn(data['id'], self.ids(self.client.get(LEADS, {'source': 'PHONE_CALL'})))

    def test_email_is_optional(self):
        res = self.client.post(LEADS, {key: value for key, value in new_lead().items() if key != 'parent_email'}, format='json')
        self.assertEqual((res.status_code, res.json()['parent_email']), (201, ''))

    def test_a_child_who_already_has_a_lead_is_named_not_duplicated(self):
        known = lead(self.bde, 'Kavya', phone='9876543210')
        Lead.objects.filter(pk=known.pk).update(phone_dial_code='+91', phone_key='+919876543210')
        res = self.client.post(LEADS, new_lead(student_name='KAVYA'), format='json')
        self.assertEqual((res.status_code, res.json()['error'], res.json()['lead_id']), (409, 'LEAD_EXISTS', str(known.id)))
        self.assertEqual(Lead.objects.count(), 1)

    def test_invalid_leads_are_refused(self):
        cases = {
            'a public source': new_lead(source='WEBSITE'),
            "a booking page's source": new_lead(source='BOOKING_PAGE'),
            'a bad email': new_lead(parent_email='not-an-email'),
            'a short phone number': new_lead(phone_number='12'),
            'no class': new_lead(grade=''),
        }
        for case, body in cases.items():
            with self.subTest(case=case):
                res = self.client.post(LEADS, body, format='json')
                self.assertEqual((res.status_code, res.json()['error']), (400, 'VALIDATION_ERROR'))
        self.assertEqual(Lead.objects.count(), 0)

    def test_a_bde_still_adds_their_own_enquiries_and_is_recorded_as_adding_them(self):
        res = self.as_user(self.bde).post(BDE_ENQUIRIES, {**new_lead(), 'source': 'WALK_IN'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        made = Lead.objects.get(pk=res.json()['id'])
        self.assertEqual((made.owner_bde, made.created_by, made.source), (self.bde, self.bde, 'WALK_IN'))


# ------------------------------------------------------------------ giving a lead to a BDE

class AssignOwnerTests(AdminLeadsTestCase):
    def assign(self, of, bde, current):
        return self.client.put(f'{LEADS}{of.id}/owner/', {
            'bde_id': str(bde.id) if bde else None, 'current_owner_id': str(current.id) if current else None,
        }, format='json')

    def test_an_unassigned_lead_given_to_a_bde_is_in_their_my_leads(self):
        website = lead(None, 'Web', source=LeadSource.WEBSITE)
        res = self.assign(website, self.bde, None)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()['changed'], res.json()['owner']['id']), (True, str(self.bde.id)))
        website.refresh_from_db()
        self.assertEqual(website.owner_bde, self.bde)
        self.assertIsNotNone(website.owner_assigned_at)
        mine = self.as_user(self.bde)
        rows = mine.get(BDE_ENQUIRIES).json()['results']
        self.assertEqual([(row['id'], row['source_label']) for row in rows], [(str(website.id), 'Website')])
        self.assertEqual(mine.get(BDE_ENQUIRIES, {'source': 'WEBSITE'}).json()['count'], 1)
        entry = ActivityLog.objects.get(action='lead.assign_owner')
        self.assertEqual((entry.actor, entry.entity_id), (self.admin, str(website.id)))
        self.assertEqual({key: entry.context[key] for key in ('previous_owner_id', 'owner_id', 'via')},
                         {'previous_owner_id': None, 'owner_id': str(self.bde.id), 'via': 'admin_leads'})

    def test_a_reassigned_lead_leaves_the_previous_bde_and_joins_the_new_one(self):
        link = BookingLink.objects.create(bde=self.bde, booking_type=DEMO)
        theirs = lead(self.bde, 'Riya', link=link)
        upcoming = booking(theirs, 2)
        before = theirs.owner_assigned_at
        res = self.assign(theirs, self.other_bde, self.bde)
        self.assertEqual(res.status_code, 200, res.content)
        theirs.refresh_from_db()
        self.assertEqual((theirs.owner_bde, theirs.owner_link), (self.other_bde, None))
        self.assertGreater(theirs.owner_assigned_at, before)

        previous, new = self.as_user(self.bde), self.as_user(self.other_bde)
        self.assertEqual(previous.get(BDE_ENQUIRIES).json()['count'], 0)
        self.assertEqual(previous.get(f'{BDE_ENQUIRIES}{theirs.id}/').status_code, 404)
        # Enforced in the API, not by the Hub: the previous BDE can no longer act on its bookings.
        cancel = previous.post(f'/api/bde/bookings/demo/{upcoming.id}/cancel/', {'reason': 'PARENT_REQUEST'}, format='json')
        self.assertEqual(cancel.status_code, 404)
        self.assertEqual(previous.get(f'/api/communications/bookings/demo/{upcoming.id}/').status_code, 404)
        self.assertEqual([row['id'] for row in new.get(BDE_ENQUIRIES).json()['results']], [str(theirs.id)])
        self.assertEqual(new.get(f'{BDE_ENQUIRIES}{theirs.id}/').status_code, 200)
        self.assertEqual(new.get(f'/api/communications/bookings/demo/{upcoming.id}/').status_code, 200)
        # Its link was the previous owner's, so it no longer reads as one.
        self.assertEqual(new.get(BDE_ENQUIRIES).json()['results'][0]['source_label'], 'Booking page')

    def test_an_owner_changed_meanwhile_is_not_overwritten(self):
        theirs = lead(self.bde, 'Riya')
        for current in (None, self.other_bde):
            with self.subTest(current=current and current.username):
                res = self.assign(theirs, self.other_bde, current)
                self.assertEqual((res.status_code, res.json()['error']), (409, 'OWNER_CHANGED'))
        theirs.refresh_from_db()
        self.assertEqual(theirs.owner_bde, self.bde)
        self.assertFalse(ActivityLog.objects.filter(action='lead.assign_owner').exists())

    def test_only_an_active_bde_takes_a_lead(self):
        website = lead(None, 'Web', source=LeadSource.WEBSITE)
        candidates = {
            'a tutor': account('tutor_t', role='TUTOR'),
            'an administrator': self.admin,
            'a deactivated BDE': account('bde_gone', deactivated_at=timezone.now(), is_active=False),
            'an inactive BDE': account('bde_off', is_active=False),
        }
        for case, candidate in candidates.items():
            with self.subTest(case=case):
                res = self.assign(website, candidate, None)
                self.assertEqual((res.status_code, res.json()['error']), (400, 'NOT_AN_ACTIVE_BDE'))
        res = self.client.put(f'{LEADS}{website.id}/owner/', {'bde_id': str(uuid.uuid4()), 'current_owner_id': None},
                              format='json')
        self.assertEqual((res.status_code, res.json()['error']), (400, 'NOT_AN_ACTIVE_BDE'))
        website.refresh_from_db()
        self.assertIsNone(website.owner_bde)

    def test_the_same_owner_again_changes_nothing(self):
        theirs = lead(self.bde, 'Riya')
        res = self.assign(theirs, self.bde, self.bde)
        self.assertEqual((res.status_code, res.json()['changed']), (200, False))
        self.assertFalse(ActivityLog.objects.filter(action='lead.assign_owner').exists())

    def test_requests_it_cannot_read(self):
        theirs = lead(self.bde, 'Riya')
        for body in ({}, {'bde_id': 'someone', 'current_owner_id': None}, {'bde_id': str(self.other_bde.id)}):
            with self.subTest(body=body):
                res = self.client.put(f'{LEADS}{theirs.id}/owner/', body, format='json')
                self.assertEqual((res.status_code, res.json()['error']), (400, 'VALIDATION_ERROR'))
        missing = self.client.put(f'{LEADS}{uuid.uuid4()}/owner/', {'bde_id': str(self.bde.id), 'current_owner_id': None},
                                  format='json')
        self.assertEqual((missing.status_code, missing.json()['error']), (404, 'NOT_FOUND'))

    def test_any_other_source_of_assignments_calls_the_same_hook(self):
        # A later sync (a CRM's own assignment rules) names its BDE and need not check the owner it replaces.
        website = lead(None, 'Web', source=LeadSource.WEBSITE)
        assigned, changed = assign_owner(website.pk, self.bde.pk, via='crm_sync', expected_owner_id=ANY_OWNER)
        self.assertEqual((assigned.owner_bde, changed), (self.bde, True))
        self.assertEqual(ActivityLog.objects.get(action='lead.assign_owner').context['via'], 'crm_sync')
        with self.assertRaises(NotAnActiveBde):
            assign_owner(website.pk, self.admin.pk, via='crm_sync')


class OwnerChangeCommunicationTests(CommunicationTestCase):
    """A lead's bookings' open tasks and unsent messages follow its owner (communications.planner.lead_owner_changed)."""

    def test_an_assigned_lead_signs_its_messages_with_its_new_bde(self):
        booking = self.book(owned=False)
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        self.assertEqual(ack.status, MessageStatus.WAITING)
        checks = requirements(booking, Step.ACKNOWLEDGEMENT, ack.template.current_version().body, NOW)
        self.assertIn(Requirement.CENTRAL_CONTACT, [check for check, met in checks if not met])

        assign_owner(booking.lead_id, self.bde.pk, actor=self.admin, via='admin_leads', expected_owner_id=None, now=NOW)
        ack.refresh_from_db()
        self.assertEqual(ack.status, MessageStatus.PENDING)
        self.assertIn('**Bde Anil**', ack.body)
        tasks = self.tasks(booking)
        self.assertEqual({(task.owner_role, task.owner_id) for task in tasks.values()}, {(OwnerRole.BDE, self.bde.pk)})

    def test_a_reassigned_lead_moves_its_open_tasks_and_rewrites_its_unsent_messages(self):
        booking = self.book()
        done = self.tasks(booking)[Step.ACKNOWLEDGEMENT]
        type(done).objects.filter(pk=done.pk).update(status=TaskStatus.DONE, resolution='MARKED_SENT', resolved_at=NOW)

        assign_owner(booking.lead_id, self.other_bde.pk, actor=self.admin, via='admin_leads',
                     expected_owner_id=self.bde.pk, now=NOW)
        tasks = self.tasks(booking)
        self.assertEqual(tasks[Step.ACKNOWLEDGEMENT].owner, self.bde, 'a closed task keeps who it was for')
        self.assertEqual({tasks[step].owner for step in tasks if step != Step.ACKNOWLEDGEMENT}, {self.other_bde})
        ack = booking.communication_messages.get(template__step=Step.ACKNOWLEDGEMENT)
        self.assertIn('**Bde Bina**', ack.body)
        self.assertNotIn('Bde Anil', ack.body)


# ------------------------------------------------------------------ the status every lead shows

class LeadStatusTests(TestCase):
    """bookings.lead_status: one booking decides, booked > completed > not started > cancelled, then New."""

    def setUp(self):
        self.tutor = account('tutor_s', role='TUTOR')
        self.children = iter(range(1, 100))

    def lead(self):
        return lead(None, f'Child {next(self.children)}', phone=f'5010{next(self.children):05d}')

    def at(self, of, starts_at, booking_type=DEMO, status=BookingStatus.BOOKED, started=False, cancelled_at=None,
           moved=False):
        """A booking of ``of`` in an hour-long slot starting at ``starts_at``."""
        local = starts_at.astimezone(BOOKING_TIMEZONE)
        slot, _ = BookingSlot.objects.get_or_create(
            booking_type=booking_type, local_date=local.date(), local_time=local.time().replace(second=0, microsecond=0),
            defaults={'starts_at': starts_at, 'ends_at': starts_at + timedelta(hours=1)},
        )
        model = booking_model(booking_type)
        completed = status == BookingStatus.COMPLETED
        teaches = started or completed
        if moved:
            status = BookingStatus.RESCHEDULED
        cancelled = status == BookingStatus.CANCELLED
        return model.objects.create(
            lead=of, slot=slot, seat=model.objects.filter(slot=slot).count() + 1, status=status,
            referral_status=ReferralStatus.NO_REF,
            assigned_tutor=self.tutor if teaches else None, tutor_assigned_at=starts_at if teaches else None,
            started_at=starts_at if started else None,
            completed_at=starts_at + timedelta(minutes=50) if completed else None,
            cancelled_at=(cancelled_at or timezone.now()) if cancelled else None,
            cancel_reason_code='OTHER' if cancelled else '',
            rescheduled_at=timezone.now() if moved else None, reschedule_reason_code='OTHER' if moved else '',
        )

    def test_each_status(self):
        now = timezone.now()
        days = lambda n: now + timedelta(days=n)  # noqa: E731
        cases = []

        fresh = self.lead()
        cases.append(('no booking', fresh, LeadStatus.NEW))

        diagnostic = self.lead()
        self.at(diagnostic, days(2), DIAGNOSTIC)
        cases.append(('a diagnostic to come', diagnostic, LeadStatus.DIAGNOSTIC_BOOKED))

        under_way = self.lead()
        self.at(under_way, now - timedelta(minutes=10), started=True)
        cases.append(('a demo under way', under_way, LeadStatus.DEMO_BOOKED))

        reported = self.lead()
        self.at(reported, days(-3), DIAGNOSTIC, BookingStatus.COMPLETED)
        cases.append(('a diagnostic reported on', reported, LeadStatus.DIAGNOSTIC_COMPLETED))

        taught = self.lead()
        self.at(taught, days(-1), DIAGNOSTIC, started=True)
        cases.append(('a diagnostic started and over', taught, LeadStatus.DIAGNOSTIC_COMPLETED))

        then_demo = self.lead()
        self.at(then_demo, days(-3), DIAGNOSTIC, BookingStatus.COMPLETED)
        self.at(then_demo, days(2))
        cases.append(('a diagnostic done, a demo to come', then_demo, LeadStatus.DEMO_BOOKED))

        demo_sooner = self.lead()
        self.at(demo_sooner, days(4), DIAGNOSTIC)
        self.at(demo_sooner, days(2))
        cases.append(('one of each to come, the demo sooner', demo_sooner, LeadStatus.DEMO_BOOKED))

        diagnostic_sooner = self.lead()
        self.at(diagnostic_sooner, days(1), DIAGNOSTIC)
        self.at(diagnostic_sooner, days(3))
        cases.append(('one of each to come, the diagnostic sooner', diagnostic_sooner, LeadStatus.DIAGNOSTIC_BOOKED))

        both_done = self.lead()
        self.at(both_done, days(-5), DIAGNOSTIC, BookingStatus.COMPLETED)
        self.at(both_done, days(-2), DEMO, BookingStatus.COMPLETED)
        cases.append(('both done, the demo last', both_done, LeadStatus.DEMO_COMPLETED))

        done_then_cancelled = self.lead()
        self.at(done_then_cancelled, days(-3), DIAGNOSTIC, BookingStatus.COMPLETED)
        self.at(done_then_cancelled, days(2), DEMO, BookingStatus.CANCELLED)
        cases.append(('a later cancellation never hides a class that happened', done_then_cancelled,
                      LeadStatus.DIAGNOSTIC_COMPLETED))

        missed = self.lead()
        self.at(missed, days(-1))
        self.at(missed, days(3), DIAGNOSTIC, BookingStatus.CANCELLED)
        cases.append(('a slot over with no start, beside a cancellation', missed, LeadStatus.DEMO_NOT_STARTED))

        cancelled_last = self.lead()
        self.at(cancelled_last, days(5), DEMO, BookingStatus.CANCELLED, cancelled_at=days(-2))
        self.at(cancelled_last, days(1), DIAGNOSTIC, BookingStatus.CANCELLED, cancelled_at=days(-1))
        cases.append(('cancelled only: the latest cancellation', cancelled_last, LeadStatus.DIAGNOSTIC_CANCELLED))

        moved_on = self.lead()
        self.at(moved_on, days(1), DIAGNOSTIC, moved=True)
        self.at(moved_on, days(3), DIAGNOSTIC)
        cases.append(('moved, its replacement to come', moved_on, LeadStatus.DIAGNOSTIC_BOOKED))

        moved_off = self.lead()
        self.at(moved_off, days(1), moved=True)
        self.at(moved_off, days(3), DEMO, BookingStatus.CANCELLED)
        cases.append(('moved, its replacement cancelled', moved_off, LeadStatus.DEMO_CANCELLED))

        moved_only = self.lead()
        self.at(moved_only, days(1), moved=True)
        cases.append(('moved only (a reschedule never leaves this)', moved_only, LeadStatus.NEW))

        for case, of, expected in cases:
            with self.subTest(case=case):
                self.assertEqual(status_of(of, now), expected)

        # The same status filters the administrators' list.
        admin = APIClient()
        admin.force_authenticate(account('admin_s', role='ADMIN'))
        res = admin.get(LEADS, {'status': 'DIAGNOSTIC_COMPLETED', 'page_size': 50})
        self.assertEqual({row['id'] for row in res.json()['results']},
                         {str(reported.id), str(taught.id), str(done_then_cancelled.id)})
        for row in res.json()['results']:
            self.assertEqual(row['status_label'], 'Diagnostic completed')
