"""One Stripe Customer per student account, per Stripe account and mode.

The Customer is the student's financial account: its name is the student's and
its email/phone are the billing guardian's. Django finds it through its own
mapping only, never by email or phone, and never merges or replaces Customers.
Legacy enquiry Customers (LEGACY_PARENT, created before student accounts) keep
their original parent name: they are reused, never renamed.
"""
import hashlib
import json
import logging
import uuid
from datetime import timedelta

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .account_models import StudentAccount
from .payment_models import StripeCustomer

logger = logging.getLogger(__name__)
# Reusable catalogue products; student and sale references live in metadata.
PRODUCTS = {'TUITION': ('eduport_plus_tuition', 'Eduport Plus tuition'),
            'TOKEN': ('eduport_plus_token', 'Eduport Plus admission token')}
_STRIPE_ACCOUNTS = {}


def data(value):
    return value if isinstance(value, dict) else value.to_dict()


def same_metadata(remote, expected):
    # Stripe stores no empty metadata value, so an empty expected value means absent.
    remote = remote or {}
    return all(remote.get(key, '') == value for key, value in expected.items())


def current_stripe_account(gateway):
    """The Stripe account the configured secret key belongs to, cached per key."""
    digest = hashlib.sha256(settings.STRIPE_SECRET_KEY.encode()).hexdigest()
    if digest not in _STRIPE_ACCOUNTS:
        account_id = data(gateway.v1.accounts.retrieve_current()).get('id')
        if not isinstance(account_id, str) or not account_id.startswith('acct_'):
            raise ValueError('The Stripe account of the configured key could not be verified.')
        _STRIPE_ACCOUNTS[digest] = account_id
    return _STRIPE_ACCOUNTS[digest]


def labels(account, guardian):
    """The Customer fields Django owns: student name, guardian contact, references."""
    reference = account.reference + (f' · {account.student.student_code}' if account.student_id else '')
    fields = [{'name': 'Student ref', 'value': reference[:140]}]
    description = reference
    if guardian and guardian.full_name:
        fields.append({'name': 'Parent/guardian', 'value': guardian.full_name[:140]})
        description += f' · Parent/guardian: {guardian.full_name}'
    meta = {'eduport_account_id': str(account.pk), 'eduport_account_ref': account.reference}
    if account.origin_lead_id:
        meta['enquiry_id'] = str(account.origin_lead_id)
    if guardian:
        meta['eduport_guardian_id'] = str(guardian.pk)
    if account.student_id:
        meta.update(student_id=str(account.student_id), edp_student_id=account.student.student_code)
    body = {'name': account.student_name[:256], 'description': description[:350],
            'invoice_settings': {'custom_fields': fields}, 'metadata': meta}
    if guardian and guardian.email:
        body['email'] = guardian.email
    if guardian and guardian.phone:
        body['phone'] = guardian.phone
    return body


def _new_row(account, livemode, stripe_account_id=''):
    from .student_accounts import billing_guardian
    row_id = uuid.uuid4()
    request = labels(account, billing_guardian(account))
    request['metadata']['eduport_customer_request'] = str(row_id)
    return StripeCustomer.objects.create(id=row_id, account=account, livemode=livemode, stripe_account_id=stripe_account_id,
                                         label_format='STUDENT', creation_request=request, student_metadata_synced=True)


def prepared_mapping(account):
    """Inside the collection transaction: ensure this mode has a Customer row. No provider IO."""
    account = StudentAccount.objects.select_for_update().get(pk=account.pk)
    row = StripeCustomer.objects.select_for_update().filter(account=account, livemode=settings.STRIPE_LIVE_MODE).first()
    return row or _new_row(account, settings.STRIPE_LIVE_MODE)


def _idempotency_key(row):
    if row.label_format == 'LEGACY_PARENT' and row.legacy_enquiry_id:
        return f'eduport-customer-{row.legacy_enquiry_id}-{row.livemode}'  # the key its request was first sent with
    return f'eduport-customer-{row.pk}'


def _choose_row(account_id, livemode, stripe_account_id):
    """(row to use, legacy row needing verification). Caller holds no lock."""
    with transaction.atomic():
        account = StudentAccount.objects.select_for_update().get(pk=account_id)
        rows = StripeCustomer.objects.select_for_update().filter(account=account, livemode=livemode)
        row = rows.filter(stripe_account_id=stripe_account_id).first()
        if row:
            return row, None
        unverified = rows.filter(stripe_account_id='').first()
        if unverified and not unverified.customer_id:
            unverified.stripe_account_id = stripe_account_id
            unverified.save(update_fields=['stripe_account_id'])
            return unverified, None
        if unverified:
            return None, unverified
        return _new_row(account, livemode, stripe_account_id), None


def _verify_unbound_account(row, gateway, stripe_account_id):
    """A Customer bound before Stripe account IDs were recorded: confirm it lives in this account."""
    try:
        remote = data(gateway.v1.customers.retrieve(row.customer_id))
    except stripe.InvalidRequestError as exc:
        if exc.code != 'resource_missing':
            raise
        remote = None  # Not in this Stripe account: it belongs to another account or sandbox.
    if remote and (remote.get('deleted') or bool(remote.get('livemode')) != row.livemode):
        raise ValueError('The student’s existing Stripe Customer was deleted or is in another mode. Review it; no replacement was created.')
    with transaction.atomic():
        account = StudentAccount.objects.select_for_update().get(pk=row.account_id)
        fresh = StripeCustomer.objects.select_for_update().get(pk=row.pk)
        if remote:
            if not fresh.stripe_account_id:
                fresh.stripe_account_id = stripe_account_id
                fresh.save(update_fields=['stripe_account_id'])
            return fresh if fresh.stripe_account_id == stripe_account_id else None
        existing = StripeCustomer.objects.filter(account=account, livemode=fresh.livemode, stripe_account_id=stripe_account_id).first()
        return existing or _new_row(account, fresh.livemode, stripe_account_id)


def customer_for(account_id, gateway, livemode):
    """Provider phase: the verified Customer ID of this student account. Raises ValueError for review."""
    stripe_account_id = current_stripe_account(gateway)
    row, unverified = _choose_row(account_id, livemode, stripe_account_id)
    if unverified is not None:
        row = _verify_unbound_account(unverified, gateway, stripe_account_id)
        if row is None:
            raise ValueError('The student’s Customer mapping belongs to another Stripe account. Review it.')
    if row.customer_id:
        return row.customer_id
    return _create_or_recover(row, gateway)


def _create_or_recover(row, gateway):
    with transaction.atomic():
        StudentAccount.objects.select_for_update().get(pk=row.account_id)
        row = StripeCustomer.objects.select_for_update().get(pk=row.pk)
        if row.customer_id:
            return row.customer_id
        if not row.creation_request:
            raise ValueError('The Customer has no durable creation request. Manual reconciliation is required.')
        started = row.creation_started_at
        if not started:
            row.creation_started_at = timezone.now()
            row.save(update_fields=['creation_started_at'])
    request = row.creation_request
    marker = request['metadata']['eduport_customer_request']
    matches = []
    if started:
        # Recover by the frozen request marker. The email filter only narrows the
        # scan; it never decides identity, and absence never authorizes a new key.
        params = {'limit': 100, **({'email': request['email']} if request.get('email') else {})}
        matches = [data(item) for item in gateway.v1.customers.list(params).auto_paging_iter()
                   if data(item).get('metadata', {}).get('eduport_customer_request') == marker]
    if len(matches) > 1:
        raise ValueError('Multiple Customers match this creation request. No automatic merge or creation is permitted.')
    if matches:
        remote = matches[0]
    elif started and started < timezone.now() - timedelta(hours=23):
        raise ValueError('Customer creation is unconfirmed beyond the safe idempotency window. Manual reconciliation is required.')
    else:
        remote = data(gateway.v1.customers.create(request, options={'idempotency_key': _idempotency_key(row)}))
    if (not remote.get('id') or remote.get('deleted') or bool(remote.get('livemode')) != row.livemode
            or not same_metadata(remote.get('metadata'), request['metadata'])):
        raise ValueError('The Stripe Customer does not match the frozen student account request.')
    with transaction.atomic():
        account = StudentAccount.objects.select_for_update().get(pk=row.account_id)
        row = StripeCustomer.objects.select_for_update().get(pk=row.pk)
        if row.customer_id and row.customer_id != remote['id']:
            raise ValueError('Another Customer is already bound. Historical references were not changed.')
        row.customer_id = remote['id']
        # Labels frozen before enrollment lack the EDP ID: push them once enrolled.
        row.student_metadata_synced = (row.label_format == 'STUDENT'
                                       and ('edp_student_id' in request['metadata']) == bool(account.student_id))
        row.save(update_fields=['customer_id', 'student_metadata_synced'])
    return remote['id']


def ensure_product(gateway, purpose):
    """The reusable catalogue product for this purpose, created once if missing."""
    product_id, name = PRODUCTS[purpose]
    try:
        product = data(gateway.v1.products.retrieve(product_id))
    except stripe.InvalidRequestError as exc:
        if exc.code != 'resource_missing':
            raise
        product = data(gateway.v1.products.create({'id': product_id, 'name': name, 'metadata': {'eduport_product': purpose}},
                                                  options={'idempotency_key': f'eduport-product-{product_id}'}))
    if (product.get('metadata') or {}).get('eduport_product') != purpose or product.get('active') is False:
        raise ValueError(f'Stripe product {product_id} is archived or not an Eduport product. Review it in the Dashboard.')
    return product_id


def _label_body(row):
    account = row.account
    if row.label_format == 'LEGACY_PARENT':
        # Legacy Customers keep their parent name; only the historical student metadata is added.
        if not account.student_id:
            return None
        return {'metadata': {'enquiry_id': str(row.legacy_enquiry_id or account.origin_lead_id or ''),
                             'student_id': str(account.student_id), 'edp_student_id': account.student.student_code}}
    from .student_accounts import billing_guardian
    return labels(account, billing_guardian(account))


def sync_labels(row_id):
    """Push Django-owned labels to the student's Customer. Best effort; beat retries."""
    row = StripeCustomer.objects.select_related('account__student').filter(pk=row_id, customer_id__isnull=False,
                                                                           student_metadata_synced=False).first()
    if row is None or row.livemode != settings.STRIPE_LIVE_MODE:
        return
    body = _label_body(row)
    if body is None:
        return
    pushed = json.dumps(body, sort_keys=True)
    try:
        from .stripe_gateway import client
        client().v1.customers.update(row.customer_id, body)
    except Exception:
        logger.exception('Stripe Customer labels will be retried for mapping %s', row_id)
        return
    current = StripeCustomer.objects.select_related('account__student').get(pk=row.pk)
    # A change made while this update was in flight stays pending for the next run.
    if json.dumps(_label_body(current), sort_keys=True) == pushed:
        StripeCustomer.objects.filter(pk=row.pk).update(student_metadata_synced=True)


def sync_pending():
    for row_id in list(StripeCustomer.objects.filter(customer_id__isnull=False, student_metadata_synced=False)
                       .values_list('pk', flat=True)):
        sync_labels(row_id)
