"""
The authorization matrix (core.authz_matrix) against its recorded baseline.

The baseline (authz_matrix_data/baseline.json) was recorded from the Phase 1
code, commit 3d56003, before authorization moved to permissions. Every result
must still match it, except the changes listed -- with the decision that
approved each -- in authz_matrix_data/approved_changes.json.

    AUTHZ_MATRIX_RECORD=1 manage.py test core.tests_authz_matrix
        writes a new baseline.json from the code under test (only ever from
        the commit named in AUTHZ_MATRIX_SOURCE).
    AUTHZ_MATRIX_REPORT=<path> manage.py test core.tests_authz_matrix
        also writes every difference to <path> as JSON, for review.
"""
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from core.authz_matrix import NEW_ROLES, add_new_role_accounts, api_routes, build_world, exercised_routes, run_matrix

DATA_DIR = Path(__file__).resolve().parent / 'authz_matrix_data'
BASELINE = DATA_DIR / 'baseline.json'
APPROVED = DATA_DIR / 'approved_changes.json'

# Where BDE is not answered as the unknown role: it holds its workspace's
# permissions, so /me lists them, the booking-links endpoint serves the BDE its
# own two links (tokens recorded by shape), the dashboard and enquiry
# endpoints its own enquiry (lead_a, given to it by add_new_role_accounts), the
# catalogue on sale (accounts.0021) answers it as it answers an administrator,
# and it quotes (accounts.0022) and sees its own quotes -- never another's.
BDE_PERMISSIONS = [
    'accounts.add_enquiry',
    'accounts.cancel_booking',
    'accounts.change_student_timezone',
    'accounts.create_demo_booking',
    'accounts.create_sales_quotes',
    'accounts.manage_own_conversion',
    'accounts.record_parent_confirmation',
    'accounts.send_lead_communications',
    'accounts.share_booking_report',
    'accounts.view_own_booking_links',
    'accounts.view_own_enquiries',
    'accounts.view_own_lead_communications',
    'accounts.view_own_lead_reports',
    'accounts.view_sales_catalogue',
]
# Sales TL holds the Conversion Tracker's two permissions (0015); like BDE's
# workflow ones, they open nothing yet, so only /me differs from the unknown role.
SALES_TL_PERMISSIONS = ['accounts.manage_team_conversion', 'accounts.view_conversion_tracker']
BDE_OWN_LINKS = {
    'status': 200,
    'records': [],
    'fields': ['links', 'links[].booking_type', 'links[].created_at', 'links[].url'],
    'capture': [
        {'booking_type': 'DEMO', 'url': 'https://plus.eduport.app/demo?ref=<token>'},
        {'booking_type': 'DIAGNOSTIC', 'url': 'https://plus.eduport.app/exam?ref=<token>'},
    ],
}
ENQUIRY_ROW_FIELDS = [
    'added_at', 'grade', 'id', 'next_booking', 'parent_name', 'phone', 'source', 'source_label', 'status',
    'status_label', 'student_name',
    # The zone the student books from (Student Local Time).
    'student_timezone',
]
ENQUIRY_FIELDS = sorted(ENQUIRY_ROW_FIELDS + [
    'bookings', 'country', 'created_at', 'parent_email', 'phone_dial_code', 'phone_number', 'school_name', 'syllabus',
    'timezone',
])
# A reminder as the BDE's follow-ups list it (communications.followups.row): a new enquiry's has no booking.
FOLLOW_UP_ROW_FIELDS = [
    'actions', 'actions.record_answer', 'actions.record_outcome', 'actions.request_confirmation', 'booking', 'due_at',
    'enquiry', 'enquiry.grade', 'enquiry.id', 'enquiry.parent_name', 'enquiry.phone', 'enquiry.phone_dial_code',
    # parent_messages: a Re-Demo confirmation's messages to send by hand (communications.redemo_messages), else null.
    'enquiry.phone_number', 'enquiry.student_name', 'id', 'opens_at', 'parent_messages', 'request', 'state',
    'state_label', 'type', 'type_label',
]
BDE_WORKSPACE = {
    'bde.booking_links': BDE_OWN_LINKS,
    'bde.dashboard': {
        'status': 200,
        'records': ['lead_a'],
        'fields': sorted([
            'bookings', 'bookings.DEMO', 'bookings.DEMO.total', 'bookings.DEMO.upcoming', 'bookings.DIAGNOSTIC',
            'bookings.DIAGNOSTIC.total', 'bookings.DIAGNOSTIC.upcoming', 'enquiries', 'enquiries.last_7_days',
            'enquiries.total', 'recent_enquiries', 'timezone', 'upcoming', 'upcoming.rows', 'upcoming.total',
            # Today's agenda (BDE Hub redesign, Phase 3): lead_a has no booking today, so no row fields appear.
            'agenda', 'agenda.date', 'agenda.rows', 'agenda.total',
            *(f'recent_enquiries[].{field}' for field in ENQUIRY_ROW_FIELDS),
        ]),
        'capture': {'enquiries': {'total': 1, 'last_7_days': 1}, 'upcoming': 0},
    },
    # Their Demo Bookings: lead_a has no booking, and booking_a's lead is nobody's.
    'bde.bookings.list': {
        'status': 200,
        'records': [],
        'fields': ['count', 'page', 'page_size', 'results', 'timezone'],
    },
    # Their follow-ups: lead_a, given to them just now and still New, is their reminder to call it; it has no
    # booking, so its activity has nothing yet.
    'bde.follow_ups.list': {
        'status': 200,
        'records': ['lead_a'],
        'fields': ['count', 'page', 'page_size', 'results', *(f'results[].{field}' for field in FOLLOW_UP_ROW_FIELDS),
                   'summary', 'summary.today', 'summary.total', 'summary.upcoming', 'timezone'],
    },
    'bde.activity.list': {
        'status': 200,
        'records': [],
        'fields': ['count', 'page', 'page_size', 'results', 'timezone'],
    },
    # The notes on their own enquiry, lead_a: none yet.
    'bde.enquiries.notes': {
        'status': 200,
        'records': [],
        'fields': ['count', 'results', 'timezone'],
    },
    'bde.enquiries.list': {
        'status': 200,
        'records': ['lead_a'],
        'fields': sorted(['count', 'page', 'page_size', 'results', *(f'results[].{field}' for field in ENQUIRY_ROW_FIELDS)]),
    },
    'bde.enquiries.detail': {'status': 200, 'records': ['lead_a'], 'fields': ENQUIRY_FIELDS},
    # Correcting their own enquiry's student time zone (Student Local Time): the enquiry in full, and whether it changed.
    'bde.enquiries.student_timezone': {
        'status': 200, 'records': ['lead_a'], 'fields': sorted(ENQUIRY_FIELDS + ['changed']),
    },
    # Rolled back with the scenario, like every write the matrix makes.
    'bde.enquiries.create': {'status': 201, 'records': ['new'], 'fields': ENQUIRY_FIELDS},
    # booking_a's lead is not the BDE's own: answered as a booking that does not exist (Q22).
    'bde.bookings.cancel': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.', 'records': [],
                            'fields': ['error', 'message']},
    # Its own enquiry has no report yet (P9).
    'bde.enquiries.reports': {'status': 200, 'records': [], 'fields': ['count', 'results', 'timezone']},
    # booking_a's lead is not the BDE's own: its report is answered as a booking that does not exist (P9).
    'bde.bookings.report_pdf': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.', 'records': [],
                                'fields': ['error', 'message']},
    'bde.bookings.report_share': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.', 'records': [],
                                  'fields': ['error', 'message']},
    # ... and sends a Demo invitation only from their own leads' Diagnostics: booking_a is a Demo of a lead nobody owns.
    'bde.bookings.demo_invite': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.', 'records': [],
                                 'fields': ['error', 'message']},
    # ... and asks for a Re-Demo only for their own leads' Demos: booking_a's lead is nobody's.
    'bde.bookings.redemo_request': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.', 'records': [],
                                    'fields': ['error', 'message']},
    # ... and closes and reopens only their own leads' requests (2026-11-08): booking_a's lead is nobody's.
    'bde.bookings.redemo_close': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.', 'records': [],
                                  'fields': ['error', 'message']},
    'bde.bookings.redemo_reopen': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.', 'records': [],
                                   'fields': ['error', 'message']},
    # Its own enquiry's History (bookings.timeline): lead_a has no booking, so nothing has happened yet.
    'bde.enquiries.history': {
        'status': 200, 'records': [],
        'fields': ['booking_id', 'bookings', 'chain_ids', 'entries', 'student_timezone', 'timezone'],
    },
    # ... and its communication too (Phase 3.1), which the BDE may neither preview, ask about nor answer for (3.2).
    'communications.booking': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.', 'records': [],
                               'fields': ['error', 'message']},
    'communications.preview': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.', 'records': [],
                               'fields': ['error', 'message']},
    'communications.request_confirmation': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.',
                                            'records': [], 'fields': ['error', 'message']},
    'communications.parent_confirmation': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.',
                                           'records': [], 'fields': ['error', 'message']},
    'communications.call_outcome': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such booking.', 'records': [],
                                    'fields': ['error', 'message']},
    # The catalogue on sale, as an administrator sees it: syllabus_a (published) only -- syllabus_b, a draft, is
    # not found -- each without its drafts, status, history or audit, and the pricing's rates; choosing days of a
    # chapter-wise syllabus is refused.
    'sales.catalogue': {
        'status': 200, 'records': ['syllabus_a'],
        'fields': ['count', 'page', 'page_size', 'results', 'results[].board', 'results[].chapter_count', 'results[].grade',
                   'results[].id', 'results[].plan_types', 'results[].revision', 'results[].structure',
                   'results[].syllabus_version', 'results[].title', 'results[].totals', 'results[].totals.bridge',
                   'results[].totals.regular', 'results[].totals.revision'],
    },
    'sales.catalogue_syllabus': {
        'status': 200, 'records': ['new', 'syllabus_a'],
        'fields': ['board', 'chapters', 'chapters[].bridge_classes', 'chapters[].id', 'chapters[].name',
                   'chapters[].position', 'chapters[].regular_classes', 'chapters[].revision_classes', 'grade', 'id',
                   'inclusions', 'package_title', 'packages', 'packages[].classes', 'packages[].fee_per_class',
                   'packages[].plan_type', 'packages[].single_payment', 'packages[].single_payment.price',
                   'packages[].single_payment.saving', 'packages[].title', 'packages[].total', 'plan_types', 'pricing',
                   'pricing.currency', 'pricing.offer_fee', 'pricing.single_payment_percent',
                   'pricing.single_payment_plan_types', 'pricing.standard_fee', 'pricing.version', 'revision', 'structure',
                   'subtitle', 'syllabus_version', 'title', 'totals', 'totals.bridge', 'totals.regular', 'totals.revision'],
    },
    'sales.catalogue_draft': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such syllabus on sale.', 'records': [],
                              'fields': ['error', 'message']},
    'sales.catalogue_pdf': {'status': 200, 'content_type': 'application/pdf'},
    'sales.catalogue_selection': {'status': 409, 'error': 'NOT_A_BRIDGE_COURSE', 'records': [], 'fields': ['error', 'message'],
                                  'message': 'Only a Bridge Course is sold by the day.'},
    'sales.catalogue_selection_pdf': {'status': 409, 'error': 'NOT_A_BRIDGE_COURSE', 'records': [],
                                      'fields': ['error', 'message'], 'message': 'Only a Bridge Course is sold by the day.'},
    # Quotes: its own -- it has none, quote_a is admin2's, so that one is not found -- and a new one of its own.
    # Cancelling is the administrators' (refused, as for the unknown role).
    'sales.quotes': {'status': 200, 'records': [], 'fields': ['count', 'page', 'page_size', 'results']},
    'sales.enquiry_plan': {
        'status': 200, 'records': ['lead_a'],
        'fields': ['current', 'history', 'latest_quote', 'lead', 'lead.id', 'lead.parent_name', 'lead.student_name', 'locked'],
    },
    'sales.quote': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such quote.', 'records': [], 'fields': ['error', 'message']},
    'sales.quote_pdf': {'status': 404, 'error': 'NOT_FOUND', 'message': 'No such quote.', 'records': [],
                        'fields': ['error', 'message']},
    'sales.quote_create': {
        'status': 201, 'records': ['<caller>', 'new', 'syllabus_a'],
        'fields': ['cancel_reason', 'cancelled_at', 'cancelled_by', 'chapters', 'chapters[].classes', 'chapters[].id',
                   'chapters[].name', 'chapters[].position', 'classes', 'created_at', 'created_by', 'created_by.id',
                   'created_by.name', 'currency', 'full_course', 'id', 'lead', 'lines', 'lines[].classes',
                   'lines[].fee_per_class', 'lines[].plan_type', 'lines[].single_payment', 'lines[].single_payment.price',
                   'lines[].single_payment.saving', 'lines[].title', 'lines[].total', 'offer_fee', 'payable_amount',
                   'plan_type', 'pricing_version', 'reference', 'revision', 'single_payment_percent',
                   'single_payment_saving', 'standard_fee', 'status', 'syllabus', 'syllabus.board', 'syllabus.grade',
                   'syllabus.id', 'syllabus.structure', 'syllabus.syllabus_version', 'syllabus.title', 'total_fee'],
    },
}

# New quote metadata identifies the current selection; the chapter counts are
# still read from the quote's immutable published revision.
BDE_WORKSPACE['sales.catalogue']['fields'] = sorted([*BDE_WORKSPACE['sales.catalogue']['fields'], 'results[].subtitle'])
BDE_WORKSPACE['sales.quote_create']['fields'] = sorted([
    *BDE_WORKSPACE['sales.quote_create']['fields'], 'chapters[].regular_classes',
    'is_current', 'selection_status', 'supersedes',
])


class AuthorizationMatrixTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix='eduplus-authz-matrix-')
        # Uploads go to a throwaway directory; a fast hasher keeps the many
        # fixture accounts cheap (the real hasher is covered by tests_auth).
        cls._override = override_settings(
            MEDIA_ROOT=cls._media,
            PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
            # Booking links are recorded with their URL; pin the site they point at.
            MARKETING_SITE_URL='https://plus.eduport.app',
        )
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def run_quietly(self, world, **kwargs):
        # Hundreds of deliberate refusals would otherwise flood the output.
        logging.disable(logging.CRITICAL)
        try:
            return run_matrix(world, **kwargs)
        finally:
            logging.disable(logging.NOTSET)

    def test_new_roles_reach_what_an_unknown_role_reaches(self):
        # Sales TL's catalogue permissions (0015) open no endpoint yet: in every
        # scenario open to signed-in accounts it must be answered as the
        # account whose role nothing knows -- no data and no action -- but for
        # the permissions /me lists. So must BDE, except where its own
        # workspace shows (BDE_WORKSPACE above). This is the Sales TL ceiling.
        world = build_world()
        add_new_role_accounts(world)
        results = self.run_quietly(world, like_unknown=tuple(NEW_ROLES))

        def as_anyone(result, caller):
            # The caller's own account (in /me, say) is the one thing that may differ.
            result = json.loads(json.dumps(result).replace(f'"{caller}"', '"<caller>"'))
            if isinstance(result.get('capture'), dict):
                result['capture'].pop('role', None)
            return result

        def expected(scenario, caller, unknown):
            if caller == 'bde' and scenario == 'auth.me':
                return {**unknown, 'capture': {**unknown['capture'], 'permissions': BDE_PERMISSIONS}}
            if caller == 'sales_tl' and scenario == 'auth.me':
                return {**unknown, 'capture': {**unknown['capture'], 'permissions': SALES_TL_PERMISSIONS}}
            if caller == 'bde' and scenario in BDE_WORKSPACE:
                return BDE_WORKSPACE[scenario]
            return unknown

        scenarios = sorted({key.split(' @ ')[0] for key in results})
        self.assertGreater(len(scenarios), 100)
        self.assertLessEqual(set(BDE_WORKSPACE), set(scenarios))
        for scenario in scenarios:
            unknown = as_anyone(results[f'{scenario} @ unknown'], 'unknown')
            for caller in NEW_ROLES:
                with self.subTest(scenario=scenario, caller=caller):
                    self.assertEqual(as_anyone(results[f'{scenario} @ {caller}'], caller), expected(scenario, caller, unknown))

    def test_every_api_route_is_in_the_matrix(self):
        covered = {route.rstrip('/') for route in exercised_routes(build_world())}
        missing = sorted({route for route in api_routes() if route.rstrip('/') not in covered})
        self.assertEqual(missing, [], 'API routes no matrix scenario exercises')

    def test_every_endpoint_answers_every_caller_as_recorded(self):
        results = self.run_quietly(build_world())

        if os.environ.get('AUTHZ_MATRIX_RECORD'):
            DATA_DIR.mkdir(exist_ok=True)
            payload = {'source': os.environ.get('AUTHZ_MATRIX_SOURCE', 'unspecified'), 'results': results}
            BASELINE.write_text(json.dumps(payload, indent=1, sort_keys=True) + '\n')
            self.skipTest(f'Recorded {len(results)} results to {BASELINE}.')

        baseline = json.loads(BASELINE.read_text())['results']
        approved = json.loads(APPROVED.read_text()).get('changes', {}) if APPROVED.exists() else {}
        expected = dict(baseline)
        for key, change in approved.items():
            expected[key] = change.get('result')

        differences = {
            key: {'expected': expected.get(key), 'actual': results.get(key)}
            for key in sorted(set(expected) | set(results))
            if expected.get(key) != results.get(key)
        }
        report = os.environ.get('AUTHZ_MATRIX_REPORT')
        if report:
            Path(report).write_text(json.dumps(differences, indent=1, sort_keys=True) + '\n')
        if differences:
            self.fail('\n'.join(
                [f'{len(differences)} result(s) differ from the baseline and its approved changes:'] +
                [f'{key}\n  expected: {json.dumps(d["expected"], sort_keys=True)}\n  actual:   {json.dumps(d["actual"], sort_keys=True)}'
                 for key, d in differences.items()]
            ))
