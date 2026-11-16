"""Admin card corrections: partial updates, identity rules and communication safety."""
from unittest import mock

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import RoleGroup
from activity.models import ActivityLog
from communications.models import MessageStatus
from communications.tests_planning import CommunicationTestCase

from . import lead_admin
from .booking_service import BookingBusy
from .models import BookingLink, BookingType, LeadSource
from .tests_booking import NOW
from .tests_enquiries import account, lead


class AdminLeadDetailsTests(TestCase):
    def setUp(self):
        self.admin = account('details_admin', role='ADMIN')
        self.bde = account('details_bde')
        self.lead = lead(self.bde, 'Riya')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = f'/api/leads/{self.lead.pk}/'

    def patch(self, **fields):
        return self.client.patch(self.url, fields, format='json')

    def test_partial_parent_correction_preserves_student_owner_and_workflow(self):
        before = dict(self.lead.__dict__)
        res = self.patch(parent_name='Corrected Parent', parent_email='parent@example.com', country='India')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['parent_email'], 'parent@example.com')
        self.lead.refresh_from_db()
        changed = {'parent_name', 'parent_email', 'country', 'updated_at', '_state'}
        for field, value in before.items():
            if field not in changed:
                self.assertEqual(getattr(self.lead, field), value, field)
        entry = ActivityLog.objects.get(action='lead.update_details')
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.context['fields'], ['country', 'parent_email', 'parent_name'])
        self.assertNotIn('parent@example.com', str(entry.context))

    def test_identity_corrections_use_the_existing_normalization(self):
        res = self.patch(phone_number='050 999 0001', student_name=' RéNu! ', grade='Class 9',
                         school_name='New School', syllabus='ICSE')
        self.assertEqual(res.status_code, 200, res.content)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.phone_dial_code, self.lead.phone_number, self.lead.phone_key),
                         ('+971', '509990001', '+971509990001'))
        self.assertEqual((self.lead.student_name, self.lead.student_name_key), ('RéNu!', 'rénu'))
        self.assertEqual((self.lead.grade, self.lead.school_name, self.lead.syllabus), ('Class 9', 'New School', 'ICSE'))

    def test_duplicate_identity_is_rejected_without_merging_or_partial_changes(self):
        duplicate = lead(None, 'Riya', phone='509990001')
        res = self.patch(phone_number='0509990001', parent_name='Must not be saved')
        self.assertEqual((res.status_code, res.json()['error']), (409, 'LEAD_EXISTS'))
        self.assertEqual(res.json()['lead_id'], str(duplicate.pk))
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.phone_number, self.lead.parent_name), ('501234567', 'Asha Nair'))
        sibling = lead(None, 'Sibling')
        res = self.patch(student_name='SIBLING!')
        self.assertEqual((res.status_code, res.json()['lead_id']), (409, str(sibling.pk)))
        self.assertFalse(ActivityLog.objects.filter(action='lead.update_details').exists())

    def test_invalid_or_workflow_fields_reject_the_whole_update(self):
        cases = [
            {'parent_email': 'invalid'}, {'phone_number': '12'}, {'parent_name': ''},
            {'student_name': '---'}, {'grade': 'Class 99'}, {'syllabus': 'Unknown'},
            {'source': 'DEMO_LINK'}, {'parent_name': 'x' * 256}, {'country': None},
            {'owner_bde': str(self.admin.pk)}, {'status': 'COMPLETED'},
            {'student_timezone': 'Asia/Dubai'}, {'source_details': {'utm_source': 'changed'}},
            {'phone_key': '+19999999999'}, {'plan_changes_locked_at': None},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                res = self.patch(school_name='Must not be saved', **fields)
                self.assertEqual((res.status_code, res.json()['error']), (400, 'VALIDATION_ERROR'))
                self.lead.refresh_from_db()
                self.assertEqual(self.lead.school_name, 'Delhi Private School')

    def test_source_correction_preserves_link_attribution_owner_and_campaign(self):
        link = BookingLink.objects.create(bde=self.bde, booking_type=BookingType.DEMO)
        self.lead.owner_link = link
        self.lead.source_details = {'utm_source': 'original'}
        self.lead.save(update_fields=['owner_link', 'source_details'])
        before = self.client.get(self.url).json()
        self.assertEqual((before['source'], before['original_source']), ('DEMO_LINK', 'BOOKING_PAGE'))
        res = self.patch(source=LeadSource.WEBSITE)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()['source'], res.json()['original_source']), ('WEBSITE', 'WEBSITE'))
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.owner_link_id, self.lead.owner_bde_id, self.lead.source_details),
                         (link.pk, self.bde.pk, {'utm_source': 'original'}))

    def test_bde_tutor_and_other_roles_cannot_edit_even_as_superusers(self):
        for role in ('BDE', 'TUTOR', 'MENTOR', 'SALES_TL', 'STUDENT'):
            for superuser in (False, True):
                with self.subTest(role=role, superuser=superuser):
                    user = account(f'details_{role}_{superuser}', role=role, is_superuser=superuser)
                    self.client.force_authenticate(user)
                    self.assertEqual(self.patch(parent_name='Denied').status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.patch(parent_name='Denied').status_code, (401, 403))
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.parent_name, 'Asha Nair')

    def test_admin_still_needs_the_existing_add_lead_permission(self):
        RoleGroup.objects.get(role='ADMIN').group.permissions.remove(
            Permission.objects.get(content_type__app_label='accounts', codename='add_lead'),
        )
        self.assertEqual(self.patch(parent_name='Denied').status_code, 403)

    def test_noop_does_not_touch_updated_at_or_log_an_edit(self):
        before = self.lead.updated_at
        for fields in ({}, {'parent_name': self.lead.parent_name}):
            self.assertEqual(self.patch(**fields).status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.updated_at, before)
        self.assertFalse(ActivityLog.objects.filter(action='lead.update_details').exists())

    def test_busy_message_refresh_rolls_back_the_contact_correction(self):
        with mock.patch('communications.planner.lead_details_changed', side_effect=BookingBusy):
            res = self.patch(parent_name='Must not be saved')
        self.assertEqual((res.status_code, res.json()['error']), (503, 'LEAD_BUSY'))
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.parent_name, 'Asha Nair')


class LeadDetailsCommunicationTests(CommunicationTestCase):
    def test_only_unsent_messages_follow_contact_changes_and_booking_snapshots_stay(self):
        booked = self.book()
        details = dict(booked.details)
        messages = self.messages(booked)
        sent = messages['DEMO_ACKNOWLEDGEMENT']
        type(sent).objects.filter(pk=sent.pk).update(status=MessageStatus.SENT, sent_at=NOW)
        original = (sent.recipient_phone, sent.body, sent.variables)
        with mock.patch('bookings.lead_admin.timezone.now', return_value=NOW):
            lead_admin.update_lead_details(self.admin, booked.lead_id, {
                'phone_number': '0509990001', 'parent_name': 'Corrected Parent', 'student_name': 'Corrected Child',
            })
        sent.refresh_from_db()
        self.assertEqual((sent.status, sent.recipient_phone, sent.body, sent.variables),
                         (MessageStatus.SENT, *original))
        waiting = messages['DEMO_CONFIRMED']
        waiting.refresh_from_db()
        self.assertEqual(waiting.recipient_phone, '+971509990001')
        booked.refresh_from_db()
        self.assertEqual(booked.details, details)
