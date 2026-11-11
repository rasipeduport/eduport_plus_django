"""Reviewed deltas layered over the immutable 3d56003 authorization baseline.

Only the named field/grant/format changes and new transport scenarios below
may differ. No observed response, current permission catalogue or serializer
is used to calculate expectations. Unrelated status, records and fields remain
part of the original equality comparison.
"""
from copy import deepcopy

ADMIN_CALLERS = ('admin', 'superuser', 'su_mentor', 'su_tutor')
CALLERS = ('anon', *ADMIN_CALLERS, 'mentor_a', 'mentor_b', 'tutor_a', 'tutor_b', 'parent_a', 'unknown')
MANAGE_INITIAL = 'accounts.manage_initial_sales'
DENIED = {'status': 403, 'detail': 'You do not have permission to perform this action.',
          'records': [], 'fields': ['detail']}
ANONYMOUS = {'status': 403, 'detail': 'Authentication credentials were not provided.',
             'records': [], 'fields': ['detail']}
QUOTE_FIELDS = ('collection_intention_confirmed', 'class_mode', 'collection_amount', 'collection_discount', 'collection_mode', 'collection_subtotal')


def refusal(code, message=None, status=400):
    result = {'status': status, 'error': code, 'records': [], 'fields': ['error']}
    if message is not None:
        result['message'] = message
        result['fields'].append('message')
    return result


def empty_sale(lead):
    return {'status': 200, 'records': [lead], 'fields': sorted([
        'enquiry_id', 'quote', 'sale', 'purchase', 'payments', 'autopay', 'parent_email',
        'billing_timezone', 'autopay_configured', 'stripe_configured', 'can_collect', 'totals',
        *('totals.' + key for key in ('purchased_classes', 'paid_classes', 'unpaid_classes', 'used_classes',
            'available_quota', 'package_amount', 'paid_amount', 'remaining_amount')),
    ])}


SALE_REQUIRED = refusal('SALE_REQUIRED', 'Start the sale first.')
QUOTE_REQUIRED = refusal('QUOTE_REQUIRED', 'Choose a plan and issue a quote first.')
NEW_SALE_REQUIRED = refusal('NEW_SALE_REQUIRED', 'Initial Autopay is available only for New Sale.')
PARENT_INVALID = refusal('ACTION_LINK_INVALID', 'This private payment link is invalid or expired. Ask your adviser for a fresh link.', 404)
WEBHOOK_UNSIGNED = refusal('INVALID_SIGNATURE', 'Invalid Stripe webhook signature.')

# Valid syntax reaches the service; the unchanged baseline world has no sale,
# agreement or payment. Ownership and valid live objects get separate tests.
MANAGER_TRANSPORTS = {
    'initial_sales.read': empty_sale('lead_a'),
    'initial_sales.foreign': empty_sale('lead_b'),
    'initial_sales.start': refusal('BDE_REQUIRED', 'Assign the responsible BDE before starting a sale.'),
    'initial_sales.amount': SALE_REQUIRED,
    'initial_sales.collect': SALE_REQUIRED,
    'initial_sales.replacement': QUOTE_REQUIRED,
    'initial_sales.replacement_preview': QUOTE_REQUIRED,
    'initial_sales.proof': refusal('NOT_FOUND', status=404),
    'initial_sales.expire': refusal('NOT_FOUND', 'No such payment.', 404),
    'initial_sales.student': refusal('NOT_FOUND', status=404),
    'initial_autopay.preview': NEW_SALE_REQUIRED,
    'initial_autopay.begin': NEW_SALE_REQUIRED,
    'initial_autopay.restart': refusal('NOT_FOUND', 'No such initial agreement.', 404),
}
BDE_TRANSPORTS = {**MANAGER_TRANSPORTS,
    'initial_sales.foreign': refusal('NOT_FOUND', 'No such enquiry.', 404),
    'initial_sales.start': QUOTE_REQUIRED,
    'initial_sales.student': DENIED,
}


def apply_reviewed_changes(recorded):
    """91 reviewed existing differences, plus explicit new transport contracts."""
    expected = deepcopy(recorded)

    def add_fields(scenario, callers, fields):
        for caller in callers:
            row = expected[f'{scenario} @ {caller}']
            row['fields'] = sorted({*row['fields'], *fields})

    # Four /me results: one new capability, restricted to Admin (and the
    # pre-existing superuser override). No Mentor/Tutor grant is changed.
    for caller in ADMIN_CALLERS:
        row = expected[f'auth.me @ {caller}']
        row['capture']['permissions'] = sorted({*row['capture']['permissions'], MANAGE_INITIAL})
    # Twelve CRM responses expose the preserved original enquiry source.
    for scenario in ('leads.create', 'leads.detail', 'leads.student_timezone'):
        add_fields(scenario, ADMIN_CALLERS, ['original_source'])
    # Sixteen immutable quote responses expose Chapter Plan mode and the
    # authoritative whole-AED collection breakdown. No record scope changes.
    for scenario in ('sales.quote', 'sales.quote_cancel', 'sales.quote_create', 'sales.quotes'):
        prefix = 'results[].' if scenario == 'sales.quotes' else ''
        add_fields(scenario, ADMIN_CALLERS, [prefix + field for field in QUOTE_FIELDS])
    # Twenty-one academic responses identify PAYMENTS versus SHEET quota;
    # they do not expose receipts, amounts, attempts or Autopay to teaching staff.
    add_fields('students.list', (*ADMIN_CALLERS, 'mentor_a', 'mentor_b'), ['[].quota_source'])
    for scenario, mentor in (('students.profile.a', 'mentor_a'), ('students.profile.b', 'mentor_b'),
                              ('students.profile.c_expired', 'mentor_a')):
        add_fields(scenario, (*ADMIN_CALLERS, mentor), ['student.quota_source'])
    # Five messages: Decimal quota supports half classes; the value remains 40.
    for caller in (*ADMIN_CALLERS, 'mentor_a'):
        expected[f'students.sync_quota.a @ {caller}']['message'] = 'Quota updated from the enrolment sheet: 40.0 hrs.'
    # Thirty-three previously unrecorded note scenarios. Pin every role's
    # outcome explicitly; never infer access from a new endpoint's response.
    notes = {'status': 200, 'records': [], 'fields': ['count', 'results', 'timezone']}
    booking_missing = refusal('NOT_FOUND', 'No such booking.', 404)
    for caller in CALLERS:
        blocked = ANONYMOUS if caller == 'anon' else DENIED
        expected[f'leads.notes @ {caller}'] = deepcopy(notes if caller in ADMIN_CALLERS else blocked)
        expected[f'bde.enquiries.notes @ {caller}'] = deepcopy(
            refusal('NOT_A_BDE', 'Enquiries belong to BDE accounts, and this account is not one.', 403)
            if caller in ('superuser', 'su_mentor', 'su_tutor') else blocked)
        expected[f'tutor_bookings.notes @ {caller}'] = deepcopy(
            booking_missing if caller in ('superuser', 'su_mentor', 'su_tutor', 'tutor_a', 'tutor_b') else blocked)
    # Twelve new routes, fourteen method/scoping scenarios. Only Admin's
    # initial-sales group can use staff transports in the baseline world.
    for scenario, allowed in MANAGER_TRANSPORTS.items():
        for caller in CALLERS:
            expected[f'{scenario} @ {caller}'] = deepcopy(
                allowed if caller in ADMIN_CALLERS else ANONYMOUS if caller == 'anon' else DENIED)
    # These external transports accept neither a staff session nor a frontend
    # success callback as proof: every caller still needs a valid signature/token.
    for caller in CALLERS:
        expected[f'initial_autopay.parent_invalid @ {caller}'] = deepcopy(PARENT_INVALID)
        expected[f'initial_sales.webhook_unsigned @ {caller}'] = deepcopy(WEBHOOK_UNSIGNED)
    return expected
