"""
Demo invitations (bookings.demo_invites): the Diagnostic -> Demo step. Only a
Diagnostic whose report is in, a CBSE child of a class the Demo page offers
and no Demo to come, under way or completed; an administrator for any lead, a
BDE for their own. One active link per Diagnostic for seven days -- the same
one every time it is sent, and opening it changes nothing -- that books one
Demo for the Diagnostic's own lead, never changing the lead, its owner, the
Diagnostic or its report, under every rule and lock a public booking meets.
"""
import threading
from datetime import date, datetime, timedelta
from unittest import skipUnless

from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.forms.models import model_to_dict
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from accounts.models import RoleGroup
from activity.models import ActivityLog
from communications.models import CommunicationTask
from reports.models import DiagnosticReport, DiagnosticReportRevision
from reports.services import submit_report
from reports.tests_services import diagnostic_input

from .booking_service import (
    BookingNotOwned,
    DateOutOfWindow,
    DemoAlreadyHeld,
    DemoNotOffered,
    DiagnosticReportMissing,
    InviteExpired,
    InviteNotFound,
    InviteRevoked,
    InviteUsed,
    LeadTimeConflict,
    SlotFull,
    SlotUnavailable,
    TooManyBookings,
    assign_tutor,
    cancel_booking,
    close_slot,
    create_booking,
    create_invited_demo_booking,
    reschedule_booking,
)
from .demo_invites import INVITE_VALIDITY, issue_invite, public_state, revoke_invite
from .models import (
    BookingChannel,
    BookingEventKind,
    BookingStatus,
    CancelReason,
    DemoBooking,
    DemoInvite,
    DemoInviteStatus,
    DiagnosticBooking,
    Lead,
    RescheduleReason,
)
from .ownership import assign_owner
from .scheduling import BOOKING_TIMEZONE, booking_window
from .tests_booking import DEMO, DIAGNOSTIC, EVENING, MORNING, NOW, BookingTestCase, account, request, schedule, start

# The day after the Diagnostic (10:00 IST on 28 Oct): its report is in, and the
# Demo window runs 29 Oct - 4 Nov.
AFTER = datetime(2026, 10, 28, 12, 0, tzinfo=BOOKING_TIMEZONE)
DEMO_DAY = date(2026, 10, 30)
SITE = 'https://plus.eduport.app'
KEY = 'k' * 40


def diagnostic_with_report(student='Riya', phone='0501234567', tutor=None, **overrides):
    """A Diagnostic booked on 28 Oct at 10:00, started by its tutor and reported on: its booking, read again."""
    booking = create_booking(request(student=student, phone=phone, booking_type=DIAGNOSTIC, at=MORNING, **overrides),
                             now=NOW)[0]
    tutor = tutor or account(f'tutor_{student.lower().replace(" ", "_")}', role='TUTOR')
    booking = assign_tutor(booking, tutor, now=NOW)[0]
    booking = start(booking)
    submit_report(booking, tutor, diagnostic_input(), now=booking.slot.starts_at + timedelta(minutes=50))
    return DiagnosticBooking.objects.select_related('report', 'lead', 'slot').get(pk=booking.pk)


def lead_row(lead_id):
    """Every column of the lead, to compare before and after."""
    return Lead.objects.filter(pk=lead_id).values().get()


@override_settings(MARKETING_SITE_URL=SITE)
class DemoInviteTestCase(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.admin = account('admin_ops', role='ADMIN')
        self.bde = account('bde_anil', role='BDE')
        self.other_bde = account('bde_bina', role='BDE')
        self.diagnostic = diagnostic_with_report()
        self.lead = self.diagnostic.lead
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=self.bde, owner_assigned_at=NOW)

    def invite(self, actor=None, now=AFTER, diagnostic=None, **kwargs):
        return issue_invite(diagnostic or self.diagnostic, actor or self.admin, now=now, **kwargs)

    def book(self, invite_or_token, day=DEMO_DAY, at=EVENING, now=AFTER, display_time='07:30 pm - 08:30 pm'):
        token = getattr(invite_or_token, 'token', invite_or_token)
        return create_invited_demo_booking(token, day, at, display_time=display_time, now=now)

    def fresh(self, invite):
        return DemoInvite.objects.get(pk=invite.pk)


class EligibilityTests(DemoInviteTestCase):
    def test_no_invitation_before_the_report_is_submitted(self):
        tutor = account('tutor_kiran', role='TUTOR')
        pending = assign_tutor(create_booking(request(student='Kiran', phone='0507000001', booking_type=DIAGNOSTIC,
                                                      at=MORNING), now=NOW)[0], tutor, now=NOW)[0]
        pending = start(pending)
        with self.assertRaises(DiagnosticReportMissing):
            self.invite(diagnostic=pending)
        # Completed without a report (a status alone): still no invitation -- the report decides.
        DiagnosticBooking.objects.filter(pk=pending.pk).update(
            status=BookingStatus.COMPLETED, completed_at=AFTER, completed_by=tutor,
        )
        with self.assertRaises(DiagnosticReportMissing):
            self.invite(diagnostic=DiagnosticBooking.objects.get(pk=pending.pk))
        self.assertFalse(DemoInvite.objects.exists())

    def test_cbse_and_a_demo_class_only(self):
        for field, value in (('syllabus', 'IB'), ('grade', 'Class 4')):
            with self.subTest(**{field: value}):
                Lead.objects.filter(pk=self.lead.pk).update(**{field: value})
                with self.assertRaises(DemoNotOffered):
                    self.invite()
                Lead.objects.filter(pk=self.lead.pk).update(syllabus='CBSE', grade='Class 8')
        self.assertFalse(DemoInvite.objects.exists())
        # A non-CBSE Diagnostic (the Diagnostic page offers five syllabi) is never invited either.
        ib = diagnostic_with_report(student='Ishan', phone='0507000002', syllabus='IB')
        with self.assertRaises(DemoNotOffered):
            self.invite(diagnostic=ib)

    def test_no_invitation_while_a_demo_is_booked_under_way_or_completed(self):
        tutor = account('tutor_demo', role='TUTOR')
        demo = create_booking(request(student='Riya', day=date(2026, 10, 29), at=EVENING), now=AFTER)[0]
        with self.assertRaises(DemoAlreadyHeld):
            self.invite()
        demo = start(assign_tutor(demo, tutor, now=AFTER)[0])
        later = demo.slot.ends_at + timedelta(hours=1)
        with self.assertRaises(DemoAlreadyHeld):  # started, its slot over: the class happened
            self.invite(now=later)
        submit_report(demo, tutor, {
            'assessment_review': 'Good.', 'class_observation_review': 'Attentive.', 'suggested_strategy': 'Algebra.',
        }, now=demo.slot.starts_at + timedelta(minutes=50))
        with self.assertRaises(DemoAlreadyHeld):
            self.invite(now=later)

    def test_a_cancelled_or_never_started_demo_holds_nothing(self):
        demo = create_booking(request(student='Riya', day=date(2026, 10, 29), at=EVENING), now=AFTER)[0]
        cancel_booking(demo, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=AFTER)
        invite, created = self.invite()
        self.assertTrue(created)
        other = diagnostic_with_report(student='Nila', phone='0507000003')
        missed = create_booking(request(student='Nila', phone='0507000003', day=date(2026, 10, 29), at=EVENING),
                                now=AFTER)[0]
        # Its slot ended with no start: that class never happened.
        self.assertTrue(self.invite(diagnostic=other, now=missed.slot.ends_at + timedelta(minutes=1))[1])

    def test_a_demo_an_invitation_booked_holds_until_staff_cancel_it(self):
        invite, _ = self.invite()
        booked = create_invited_demo_booking(invite.token, date(2026, 10, 29), EVENING, now=AFTER)[0]
        # Moved, then its new slot ends with nobody starting it or recording a No-show: still no new link.
        moved = reschedule_booking(booked, date(2026, 10, 30), MORNING, reason_code=RescheduleReason.OTHER,
                                   actor=self.admin, now=AFTER).booking
        later = moved.slot.ends_at + timedelta(minutes=1)
        with self.assertRaises(DemoAlreadyHeld):
            self.invite(now=later)
        self.assertEqual(public_state(invite.token, now=later)['status'], 'USED')
        cancel_booking(moved, reason_code=CancelReason.NO_SHOW, actor=self.admin, now=later)
        self.assertTrue(self.invite(now=later)[1])


class IssuingTests(DemoInviteTestCase):
    def test_an_active_link_for_seven_days_the_same_every_time(self):
        invite, created = self.invite()
        self.assertTrue(created)
        self.assertEqual(len(invite.token), 43)
        self.assertEqual((invite.lead_id, invite.diagnostic_booking_id, invite.created_by),
                         (self.lead.pk, self.diagnostic.pk, self.admin))
        self.assertEqual(invite.expires_at - invite.created_at, timedelta(days=7))
        self.assertEqual(invite.status(AFTER), DemoInviteStatus.ACTIVE)
        for moment in (AFTER + timedelta(hours=1), AFTER + INVITE_VALIDITY - timedelta(seconds=1)):
            with self.subTest(moment=moment):
                again, created = self.invite(actor=self.bde, owner_bde=self.bde, now=moment)
                self.assertEqual((again.pk, again.token, created), (invite.pk, invite.token, False))
        self.assertEqual(DemoInvite.objects.count(), 1)
        entry = ActivityLog.objects.get(action='demo_invite.issue')
        self.assertEqual((entry.entity_id, entry.actor, entry.context['diagnostic_booking_id']),
                         (str(invite.pk), self.admin, str(self.diagnostic.pk)))
        self.assertNotIn(invite.token, str(entry.context) + entry.entity_label)

    def test_an_expired_link_is_replaced_and_stays_expired(self):
        old, _ = self.invite()
        expired = AFTER + INVITE_VALIDITY
        self.assertEqual(old.status(expired), DemoInviteStatus.EXPIRED)
        new, created = self.invite(now=expired)
        self.assertTrue(created)
        self.assertNotEqual(new.token, old.token)
        old = self.fresh(old)
        self.assertEqual((old.replaced_at, old.status(expired)), (expired, DemoInviteStatus.EXPIRED))
        with self.assertRaises(InviteExpired):
            self.book(old, now=expired)
        self.assertEqual(self.book(new, day=date(2026, 11, 6), now=expired)[0].lead_id, self.lead.pk)

    def test_a_bde_sends_for_their_own_lead_only_checked_under_the_lock(self):
        with self.assertRaises(BookingNotOwned):
            self.invite(actor=self.other_bde, owner_bde=self.other_bde)
        assign_owner(self.lead.pk, self.other_bde.pk, actor=self.admin, via='test')
        with self.assertRaises(BookingNotOwned):
            self.invite(actor=self.bde, owner_bde=self.bde)
        self.assertTrue(self.invite(actor=self.other_bde, owner_bde=self.other_bde)[1])

    def test_one_open_invitation_per_diagnostic_in_the_database(self):
        invite, _ = self.invite()
        with self.assertRaises(IntegrityError), transaction.atomic():
            DemoInvite.objects.create(lead=self.lead, diagnostic_booking=self.diagnostic, created_by=self.admin,
                                      created_at=AFTER, expires_at=AFTER + INVITE_VALIDITY)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DemoInvite.objects.filter(pk=invite.pk).update(used_at=AFTER)  # used, but no booking named


class BookingTests(DemoInviteTestCase):
    def test_the_demo_is_the_diagnostics_lead_and_nothing_about_the_lead_changes(self):
        before = lead_row(self.lead.pk)
        leads = Lead.objects.count()
        invite, _ = self.invite()
        booking, created = self.book(invite)
        self.assertTrue(created)
        self.assertEqual(lead_row(self.lead.pk), before)
        self.assertEqual(Lead.objects.count(), leads)
        self.assertEqual(
            (booking.lead_id, booking.status, booking.channel, booking.created_by, booking.referral_status,
             booking.referral_link, booking.attributed_bde, booking.slot.local_date, booking.slot.local_time),
            (self.lead.pk, BookingStatus.BOOKED, BookingChannel.BDE_HANDOFF, self.admin, None, None, None,
             DEMO_DAY, EVENING),
        )
        # The details a public booking keeps, in its keys, from the lead (export_bookings reads them).
        self.assertEqual(booking.details, {
            'parent_name': 'Asha Nair', 'phone': '+971 501234567', 'student_name': 'Riya',
            'school': 'Delhi Private School', 'student_class': 'Class 8', 'syllabus': 'CBSE',
            'country': 'United Arab Emirates', 'display_time': '07:30 pm - 08:30 pm',
        })
        invite = self.fresh(invite)
        self.assertEqual((invite.used_at, invite.demo_booking_id, invite.status(AFTER)),
                         (AFTER, booking.pk, DemoInviteStatus.USED))
        event = booking.events.get()
        self.assertEqual((event.kind, event.actor, event.data),
                         (BookingEventKind.CREATED, None,
                          {'slot_id': str(booking.slot_id), 'seat': 1, 'via': 'demo_invite', 'invite_id': str(invite.pk)}))
        # Its parent communication is planned as for any Demo, with the lead's own BDE.
        tasks = CommunicationTask.objects.filter(demo_booking=booking)
        self.assertEqual((tasks.count(), {task.owner_id for task in tasks}), (5, {self.bde.pk}))
        entry = ActivityLog.objects.get(action='booking.create', entity_id=str(booking.pk))
        self.assertEqual(
            {key: entry.context[key] for key in ('via', 'invite_id', 'diagnostic_booking_id', 'lead_owner_id')},
            {'via': 'demo_invite', 'invite_id': str(invite.pk), 'diagnostic_booking_id': str(self.diagnostic.pk),
             'lead_owner_id': str(self.bde.pk)},
        )
        self.assertNotIn(invite.token, str(entry.context))

    def test_the_diagnostic_its_report_and_their_history_are_untouched(self):
        report = DiagnosticReport.objects.get(booking=self.diagnostic)
        snapshot = (
            model_to_dict(DiagnosticBooking.objects.get(pk=self.diagnostic.pk)),
            DiagnosticBooking.objects.get(pk=self.diagnostic.pk).updated_at,
            model_to_dict(report), report.updated_at,
            list(DiagnosticReportRevision.objects.filter(report=report).values()),
            list(self.diagnostic.events.values()),
        )
        invite, _ = self.invite()
        booking, _ = self.book(invite)
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=AFTER)
        report = DiagnosticReport.objects.get(booking=self.diagnostic)
        self.assertEqual((
            model_to_dict(DiagnosticBooking.objects.get(pk=self.diagnostic.pk)),
            DiagnosticBooking.objects.get(pk=self.diagnostic.pk).updated_at,
            model_to_dict(report), report.updated_at,
            list(DiagnosticReportRevision.objects.filter(report=report).values()),
            list(self.diagnostic.events.values()),
        ), snapshot)

    def test_the_owner_stays_whoever_owns_the_lead_when_it_is_booked(self):
        invite, _ = self.invite(actor=self.bde, owner_bde=self.bde)
        assign_owner(self.lead.pk, self.other_bde.pk, actor=self.admin, via='test')
        booking, _ = self.book(invite)
        lead = Lead.objects.get(pk=self.lead.pk)
        self.assertEqual((lead.owner_bde, booking.created_by), (self.other_bde, self.bde))
        self.assertEqual({task.owner_id for task in CommunicationTask.objects.filter(demo_booking=booking)},
                         {self.other_bde.pk})

    def test_a_lead_nobody_owns_stays_unowned(self):
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=None, owner_assigned_at=None)
        booking, _ = self.book(self.invite()[0])
        self.assertIsNone(Lead.objects.get(pk=self.lead.pk).owner_bde)
        self.assertEqual(booking.created_by, self.admin)

    def test_one_booking_per_invitation(self):
        invite, _ = self.invite()
        booking, _ = self.book(invite)
        # The same submission again gets the booking it made; any other slot is refused.
        self.assertEqual(self.book(invite), (booking, False))
        with self.assertRaises(InviteUsed):
            self.book(invite, day=date(2026, 10, 31))
        # The Demo moved: the invitation is still used, and moving it again is the Admin's.
        moved = reschedule_booking(booking, date(2026, 10, 31), MORNING, reason_code=RescheduleReason.OTHER,
                                   actor=self.admin, now=AFTER).booking
        self.assertEqual(moved.channel, BookingChannel.BDE_HANDOFF)
        with self.assertRaises(InviteUsed):
            self.book(invite)
        self.assertEqual(DemoBooking.objects.filter(lead=self.lead, status=BookingStatus.BOOKED).count(), 1)
        with self.assertRaises(DemoAlreadyHeld):
            self.invite()

    def test_after_the_invited_demo_is_cancelled_a_new_invitation(self):
        first, _ = self.invite()
        booking, _ = self.book(first)
        cancel_booking(booking, reason_code=CancelReason.PARENT_REQUEST, actor=self.admin, now=AFTER)
        with self.assertRaises(InviteUsed):
            self.book(first, day=date(2026, 10, 31))
        second, created = self.invite(actor=self.bde, owner_bde=self.bde)
        self.assertTrue(created)
        self.assertNotEqual(second.token, first.token)
        self.assertEqual(self.fresh(first).status(AFTER), DemoInviteStatus.USED)
        again, _ = self.book(second, day=date(2026, 10, 31))
        self.assertEqual((again.lead_id, again.created_by), (self.lead.pk, self.bde))

    def test_a_revoked_invitation_books_nothing(self):
        invite, _ = self.invite()
        self.assertEqual(revoke_invite(invite, self.admin, now=AFTER)[1], True)
        self.assertEqual(revoke_invite(invite, self.admin, now=AFTER)[1], False)
        self.assertEqual(self.fresh(invite).status(AFTER), DemoInviteStatus.REVOKED)
        with self.assertRaises(InviteRevoked):
            self.book(invite)
        self.assertTrue(ActivityLog.objects.filter(action='demo_invite.revoke', entity_id=str(invite.pk)).exists())
        # The next send issues a new link.
        self.assertTrue(self.invite()[1])

    def test_unknown_and_malformed_tokens(self):
        for token in ('n' * 43, '', None, 42, 'x' * 65, 'not a token!', '../demo'):
            with self.subTest(token=token):
                with self.assertRaises(InviteNotFound):
                    self.book(token)
                self.assertIsNone(public_state(token, now=AFTER))
        self.assertFalse(DemoBooking.objects.exists())

    def test_every_rule_a_public_booking_meets(self):
        invite, _ = self.invite()
        with self.assertRaises(DateOutOfWindow):
            self.book(invite, day=AFTER.date())
        with self.assertRaises(SlotUnavailable):
            self.book(invite, at=datetime(2026, 1, 1, 15, 0).time())
        close_slot(DEMO, DEMO_DAY, EVENING, actor=self.admin)
        with self.assertRaises(SlotFull):
            self.book(invite)
        # The child's other booking at the same time (Q26).
        create_booking(request(student='Riya', booking_type=DIAGNOSTIC, day=DEMO_DAY, at=MORNING), now=AFTER)
        with self.assertRaises(LeadTimeConflict):
            self.book(invite, at=MORNING)
        with override_settings(BOOKING_PHONE_DAILY_LIMIT=1), self.assertRaises(TooManyBookings):
            self.book(invite, day=date(2026, 10, 31))
        self.assertIsNone(self.fresh(invite).used_at)
        self.assertFalse(DemoBooking.objects.exists())

    def test_a_demo_booked_on_the_demo_page_meanwhile(self):
        invite, _ = self.invite()
        create_booking(request(student='Riya', day=date(2026, 10, 29), at=EVENING), now=AFTER)
        self.assertEqual(public_state(invite.token, now=AFTER)['status'], 'UNAVAILABLE')
        with self.assertRaises(DemoAlreadyHeld):
            self.book(invite)
        self.assertIsNone(self.fresh(invite).used_at)


class PublicStateTests(DemoInviteTestCase):
    def test_opening_the_link_changes_nothing(self):
        invite, _ = self.invite()
        row = model_to_dict(invite)
        expires_at = self.fresh(invite).expires_at.isoformat()
        for moment in (AFTER, AFTER + timedelta(days=3), AFTER + INVITE_VALIDITY - timedelta(minutes=1)):
            self.assertEqual(public_state(invite.token, now=moment), {'status': 'ACTIVE', 'expires_at': expires_at})
        self.assertEqual(model_to_dict(self.fresh(invite)), row)
        self.assertFalse(DemoBooking.objects.exists())
        # Six days on, the same link still books.
        self.assertTrue(self.book(invite, day=date(2026, 11, 5), now=AFTER + timedelta(days=6))[1])

    def test_each_state(self):
        invite, _ = self.invite()
        self.assertEqual(public_state(invite.token, now=AFTER + INVITE_VALIDITY),
                         {'status': 'EXPIRED', 'expires_at': None})
        self.book(invite)
        self.assertEqual(public_state(invite.token, now=AFTER), {'status': 'USED', 'expires_at': None})
        other = diagnostic_with_report(student='Nila', phone='0507000003')
        revoked, _ = self.invite(diagnostic=other)
        revoke_invite(revoked, self.admin, now=AFTER)
        self.assertEqual(public_state(revoked.token, now=AFTER), {'status': 'REVOKED', 'expires_at': None})


# ------------------------------------------------------------------ the APIs

def invite_url(booking_type, booking_id, bde=False):
    return f"/api/{'bde/' if bde else ''}bookings/{booking_type}/{booking_id}/demo-invite/"


@override_settings(MARKETING_SITE_URL=SITE, BOOKING_SERVICE_API_KEYS=[KEY])
class InviteApiTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        schedule()
        self.admin = account('admin_ops', role='ADMIN')
        self.bde = account('bde_anil', role='BDE')
        self.other_bde = account('bde_bina', role='BDE')
        self.diagnostic = diagnostic_with_report()
        self.lead = self.diagnostic.lead
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=self.bde, owner_assigned_at=NOW)

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def as_user(self, user):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=type(user).objects.get(pk=user.pk) if user.pk else user)
        return client

    def service(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {KEY}', HTTP_X_BOOKING_CLIENT_IP='203.0.113.9')
        return client


class StaffApiTests(InviteApiTestCase):
    def test_the_admin_sends_one_link_for_any_lead(self):
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=None, owner_assigned_at=None)
        res = self.as_user(self.admin).post(invite_url('diagnostic', self.diagnostic.pk))
        self.assertEqual(res.status_code, 201, res.data)
        invite = DemoInvite.objects.get()
        self.assertEqual(set(res.data), {'invite', 'created'})
        self.assertEqual(res.data['invite']['url'], f'{SITE}/demo-invite#{invite.token}')
        self.assertEqual((res.data['invite']['status'], res.data['invite']['created_by']['id']),
                         ('ACTIVE', str(self.admin.pk)))
        again = self.as_user(self.admin).post(invite_url('diagnostic', self.diagnostic.pk))
        self.assertEqual((again.status_code, again.data['created'], again.data['invite']['url']),
                         (200, False, res.data['invite']['url']))

    def test_only_a_diagnostic_and_only_with_its_report(self):
        demo = create_booking(request(student='Other', phone='0507000009', day=booking_window(DEMO)[0]))[0]
        for path in (invite_url('demo', demo.pk), invite_url('demo', self.diagnostic.pk),
                     invite_url('diagnostic', demo.pk), invite_url('exam', self.diagnostic.pk)):
            with self.subTest(path=path):
                res = self.as_user(self.admin).post(path)
                self.assertEqual((res.status_code, res.json()['error']), (404, 'NOT_FOUND'))
        Lead.objects.filter(pk=self.lead.pk).update(syllabus='ICSE')
        res = self.as_user(self.admin).post(invite_url('diagnostic', self.diagnostic.pk))
        self.assertEqual((res.status_code, res.data['error']), (409, 'DEMO_NOT_OFFERED'))
        self.assertFalse(DemoInvite.objects.exists())

    def test_who_may_send(self):
        tutor, mentor = account('tutor_x', role='TUTOR'), account('mentor_x', role='MENTOR')
        for user in (None, tutor, mentor, self.bde):
            with self.subTest(user=getattr(user, 'username', 'anonymous')):
                res = self.as_user(user).post(invite_url('diagnostic', self.diagnostic.pk))
                self.assertIn(res.status_code, (401, 403))
        for user in (None, tutor, mentor, self.admin):
            with self.subTest(bde_route=getattr(user, 'username', 'anonymous')):
                res = self.as_user(user).post(invite_url('diagnostic', self.diagnostic.pk, bde=True))
                self.assertIn(res.status_code, (401, 403))
        self.assertFalse(DemoInvite.objects.exists())

    def test_the_admin_needs_send_lead_communications(self):
        group = RoleGroup.objects.select_related('group').get(role='ADMIN').group
        group.permissions.remove(Permission.objects.get(codename='send_lead_communications'))
        client = self.as_user(self.admin)
        self.assertEqual(client.post(invite_url('diagnostic', self.diagnostic.pk)).status_code, 403)
        detail = client.get(f'/api/bookings/diagnostic/{self.diagnostic.pk}/').data
        self.assertFalse(detail['actions']['demo_invite'])

    def test_the_bde_sends_for_their_own_leads_only(self):
        res = self.as_user(self.bde).post(invite_url('diagnostic', self.diagnostic.pk, bde=True))
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['invite']['created_by']['id'], str(self.bde.pk))
        other = self.as_user(self.other_bde).post(invite_url('diagnostic', self.diagnostic.pk, bde=True))
        self.assertEqual((other.status_code, other.data), (404, {'error': 'NOT_FOUND', 'message': 'No such booking.'}))
        Lead.objects.filter(pk=self.lead.pk).update(owner_bde=None, owner_assigned_at=None)
        unowned = self.as_user(self.bde).post(invite_url('diagnostic', self.diagnostic.pk, bde=True))
        self.assertEqual(unowned.status_code, 404)
        self.assertEqual(DemoInvite.objects.count(), 1)

    def test_the_button_shows_on_the_diagnostic_whose_report_is_in(self):
        detail = self.as_user(self.admin).get(f'/api/bookings/diagnostic/{self.diagnostic.pk}/').data
        self.assertEqual(detail['actions'], {'cancel': False, 'no_show': False, 'reschedule': False, 'demo_invite': True,
                                             'request_redemo': False})
        rows = {row['id']: row['actions'] for row in
                self.as_user(self.bde).get(f'/api/bde/enquiries/{self.lead.pk}/').data['bookings']}
        self.assertEqual(rows, {str(self.diagnostic.pk): {'cancel': False, 'no_show': False, 'demo_invite': True,
                                                   'request_redemo': False}})

        invite, _ = issue_invite(self.diagnostic, self.admin)
        day = booking_window(DEMO)[1]
        demo, _ = create_invited_demo_booking(invite.token, day, EVENING)
        detail = self.as_user(self.admin).get(f'/api/bookings/diagnostic/{self.diagnostic.pk}/').data
        self.assertFalse(detail['actions']['demo_invite'])
        rows = {row['id']: row['actions'] for row in
                self.as_user(self.bde).get(f'/api/bde/enquiries/{self.lead.pk}/').data['bookings']}
        self.assertEqual(rows[str(self.diagnostic.pk)]['demo_invite'], False)
        self.assertEqual(rows[str(demo.pk)], {'cancel': True, 'no_show': False, 'demo_invite': False,
                                              'request_redemo': False})
        self.assertEqual(self.as_user(self.bde).get(f'/api/bde/enquiries/{self.lead.pk}/').data['status'], 'DEMO_BOOKED')

        # The Demo, in the Admin's Demo list: made with the invitation, from this Diagnostic.
        shown = self.as_user(self.admin).get(f'/api/bookings/demo/{demo.pk}/').data
        self.assertEqual(
            (shown['channel'], shown['created_by']['id'], shown['referral_status'], shown['bde'],
             shown['invited_from']['id'], shown['lead']['owner_bde']['id']),
            ('BDE_HANDOFF', str(self.admin.pk), None, None, str(self.diagnostic.pk), str(self.bde.pk)),
        )
        listed = self.as_user(self.admin).get('/api/bookings/demo/').data['results']
        self.assertEqual([row['id'] for row in listed], [str(demo.pk)])
        moved = self.as_user(self.admin).post(f'/api/bookings/demo/{demo.pk}/reschedule/', {
            'date': booking_window(DEMO)[2].isoformat(), 'time': '19:30', 'reason': 'PARENT_REQUEST'}, format='json')
        self.assertEqual(moved.status_code, 201, moved.data)
        self.assertEqual(moved.data['booking']['invited_from']['id'], str(self.diagnostic.pk))


class PublicApiTests(InviteApiTestCase):
    def state(self, token, client=None):
        return (client or self.service()).post('/api/public/demo-invites/state/', {'token': token}, format='json')

    def book(self, token, **overrides):
        body = {'token': token, 'date': booking_window(DEMO)[1].isoformat(), 'time': '19:30',
                'display_time': '07:30 pm - 08:30 pm', **overrides}
        return self.service().post('/api/public/demo-invites/book/', body, format='json')

    def test_only_the_marketing_server(self):
        invite, _ = issue_invite(self.diagnostic, self.admin)
        for client in (APIClient(), self.as_user(self.admin)):
            self.assertIn(self.state(invite.token, client).status_code, (401, 403))
            res = client.post('/api/public/demo-invites/book/', {'token': invite.token}, format='json')
            self.assertIn(res.status_code, (401, 403))
        self.assertIsNone(DemoInvite.objects.get().used_at)

    def test_the_page_reads_the_state_and_books(self):
        invite, _ = issue_invite(self.diagnostic, self.admin)
        res = self.state(invite.token)
        self.assertEqual((res.status_code, res.json()['status'], res['Cache-Control']), (200, 'ACTIVE', 'no-store'))
        self.assertEqual(set(res.json()), {'status', 'expires_at'})
        self.assertEqual(self.state('n' * 43).json(), {'error': 'INVITE_NOT_FOUND', 'message': 'This invitation link is not valid.'})
        self.assertIsNone(DemoInvite.objects.get().used_at)

        booked = self.book(invite.token)
        self.assertEqual((booked.status_code, booked.json()['created']), (201, True))
        booking = DemoBooking.objects.get()
        self.assertEqual((booking.lead_id, booking.details['display_time']), (self.lead.pk, '07:30 pm - 08:30 pm'))
        again = self.book(invite.token)
        self.assertEqual((again.status_code, again.json()), (200, {'booking_id': str(booking.pk), 'created': False}))
        other = self.book(invite.token, date=booking_window(DEMO)[2].isoformat())
        self.assertEqual((other.status_code, other.json()['error']), (409, 'INVITE_USED'))
        self.assertEqual(self.state(invite.token).json(), {'status': 'USED', 'expires_at': None})

    def test_what_it_refuses(self):
        invite, _ = issue_invite(self.diagnostic, self.admin)
        cases = [
            ({'date': 'tomorrow'}, 400, 'VALIDATION_ERROR'),
            ({'token': 'n' * 43}, 404, 'INVITE_NOT_FOUND'),
            ({'date': booking_window(DEMO)[0] - timedelta(days=1)}, 400, 'DATE_OUT_OF_WINDOW'),
            ({'time': '03:00'}, 409, 'SLOT_UNAVAILABLE'),
        ]
        for overrides, status_code, error in cases:
            with self.subTest(error=error):
                if isinstance(overrides.get('date'), date):
                    overrides = {**overrides, 'date': overrides['date'].isoformat()}
                res = self.book(overrides.pop('token', invite.token), **overrides)
                self.assertEqual((res.status_code, res.json()['error']), (status_code, error))
        # Unknown fields -- a lead or a BDE -- are dropped.
        res = self.book(invite.token, lead_id=str(Lead.objects.create(
            parent_name='X', phone_dial_code='+91', phone_number='9800000000', phone_key='+919800000000',
            student_name='X', student_name_key='x', school_name='', grade='Class 8', syllabus='CBSE').pk),
            bde_id=str(self.other_bde.pk))
        self.assertEqual(res.status_code, 201)
        self.assertEqual(DemoBooking.objects.get().lead_id, self.lead.pk)


# ------------------------------------------------------------------ concurrency

@skipUnless(connection.vendor == 'postgresql', 'the booking locks need PostgreSQL row locking')
@override_settings(MARKETING_SITE_URL=SITE)
class ConcurrentInviteTests(TransactionTestCase):
    """Real threads, each with its own database connection, starting together."""

    def setUp(self):
        schedule()
        self.admin = account('admin_race', role='ADMIN')
        self.diagnostic = diagnostic_with_report()

    def race(self, calls):
        barrier = threading.Barrier(len(calls))
        outcomes = [None] * len(calls)

        def run(index, call):
            try:
                barrier.wait(timeout=10)
                outcomes[index] = call()
            except Exception as exc:  # reported in the assertion, not lost in the thread
                outcomes[index] = type(exc).__name__
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        return outcomes

    def test_one_link_used_twice_at_once_books_one_demo(self):
        invite, _ = issue_invite(self.diagnostic, self.admin, now=AFTER)
        outcomes = self.race([
            lambda: create_invited_demo_booking(invite.token, DEMO_DAY, EVENING, now=AFTER)[1],
            lambda: create_invited_demo_booking(invite.token, date(2026, 10, 31), MORNING, now=AFTER)[1],
        ])
        self.assertEqual(sorted(map(str, outcomes)), ['InviteUsed', 'True'], outcomes)
        self.assertEqual(DemoBooking.objects.count(), 1)
        self.assertEqual(DemoInvite.objects.get().demo_booking_id, DemoBooking.objects.get().pk)

    def test_the_same_slot_twice_at_once_is_one_booking(self):
        invite, _ = issue_invite(self.diagnostic, self.admin, now=AFTER)
        outcomes = self.race([lambda: create_invited_demo_booking(invite.token, DEMO_DAY, EVENING, now=AFTER)[1]] * 3)
        self.assertEqual(sorted(map(str, outcomes)), ['False', 'False', 'True'], outcomes)
        self.assertEqual(DemoBooking.objects.count(), 1)

    def test_the_link_and_the_demo_page_at_once_book_one_demo(self):
        invite, _ = issue_invite(self.diagnostic, self.admin, now=AFTER)
        outcomes = self.race([
            lambda: create_invited_demo_booking(invite.token, DEMO_DAY, EVENING, now=AFTER)[1],
            lambda: create_booking(request(student='Riya', day=date(2026, 10, 31), at=MORNING), now=AFTER)[1],
        ])
        self.assertEqual(DemoBooking.objects.count(), 1, outcomes)
        # Whichever commits second sees the first: the Demo page's Q26 refusal, or the invitation's.
        self.assertIn(set(map(str, outcomes)), [{'True', 'LeadAlreadyBooked'}, {'True', 'DemoAlreadyHeld'}])

    def test_two_sends_at_once_give_one_link(self):
        outcomes = self.race([lambda: issue_invite(self.diagnostic, self.admin, now=AFTER)] * 3)
        self.assertEqual(DemoInvite.objects.count(), 1, outcomes)
        self.assertEqual(sorted(created for _invite, created in outcomes), [False, False, True])
        self.assertEqual({invite.token for invite, _ in outcomes}, {DemoInvite.objects.get().token})
