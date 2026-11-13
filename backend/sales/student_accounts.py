"""Opening, linking, locking and correcting student financial accounts.

A child is identified by its StudentAccount, never by a parent's email or
phone. Those only produce family *suggestions*; a person confirms whether the
child joins an existing family or starts a new one, and that choice is stored.
"""
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.authz import has_app_permission
from activity.utils import log_activity
from .account_models import Guardian, GuardianRelationship, StudentAccount, StudentGuardian, StudentIdentityCorrection
from .services import SalesError

MANAGE = 'accounts.manage_initial_sales'
# The existing Admin-only financial oversight permission (see sales.payments).
OVERSIGHT = 'accounts.manage_sales_quotes'
CONTACT_FIELDS = ('full_name', 'email', 'phone')


def refusal(code, message, status=400, **extra):
    return SalesError(code, message, status, **extra)


def is_admin(actor, request=None):
    return has_app_permission(actor, MANAGE, request) and has_app_permission(actor, OVERSIGHT, request)


def next_reference():
    from .enrollment import next_number
    return f'SA-{next_number("STUDENT_ACCOUNT"):06d}'


def clean_contact(data):
    contact = {}
    if 'full_name' in data:
        contact['full_name'] = ' '.join((data.get('full_name') or '').split())[:255]
    if 'email' in data:
        contact['email'] = (data.get('email') or '').strip().lower()
        if contact['email']:
            try:
                validate_email(contact['email'])
            except ValidationError as exc:
                raise refusal('INVALID_EMAIL', 'Enter a valid parent email address.') from exc
    if 'phone' in data:
        contact['phone'] = ''.join((data.get('phone') or '').split())
        if contact['phone'] and not re.fullmatch(r'\+?[0-9]{6,19}', contact['phone']):
            raise refusal('INVALID_PHONE', 'Enter the parent phone as digits with its country code, for example +971501234567.')
    return contact


def family_candidates(lead, exclude=None):
    """Existing guardians sharing this enquiry's phone or parent email: suggestions only."""
    match = Q(pk__in=[])
    if lead.phone_key:
        match |= Q(phone=lead.phone_key)
    email = (lead.parent_email or '').strip().lower()
    if email:
        match |= Q(email__iexact=email)
    rows = []
    for guardian in Guardian.objects.filter(match).order_by('created_at'):
        children = []
        for link in guardian.student_links.filter(ended_at__isnull=True).select_related('account__student').order_by('account__reference'):
            if exclude is not None and link.account_id == exclude.pk:
                continue
            children.append({'account_id': str(link.account_id), 'reference': link.account.reference,
                             'student_name': link.account.student_name,
                             'student_code': link.account.student.student_code if link.account.student_id else None})
        if children:
            rows.append({'guardian_id': str(guardian.pk), 'full_name': guardian.full_name,
                         'matched_on': [name for name, hit in (('phone', guardian.phone == lead.phone_key and bool(lead.phone_key)),
                                                               ('email', bool(email) and guardian.email.lower() == email)) if hit],
                         'children': children})
    return rows


def open_account(actor, lead, choice, request=None):
    """Called under the enquiry lock when a sale starts. One account per enquiry."""
    existing = StudentAccount.objects.select_for_update().filter(origin_lead=lead).first()
    if existing:
        return existing
    candidates = family_candidates(lead)
    family = choice.get('family') or {}
    mode = family.get('mode') or 'NEW_FAMILY'
    if mode not in ('NEW_FAMILY', 'EXISTING_FAMILY'):
        raise refusal('INVALID_FAMILY', 'Choose a new family or one of the suggested families.')
    if candidates and not choice.get('confirm_distinct_child'):
        # Siblings share contact details; so can a duplicate enquiry for the same
        # child. A person must decide which this is. Nothing is linked automatically.
        raise refusal('FAMILY_CONFIRMATION_REQUIRED',
                      'This parent phone or email already belongs to a family. Confirm this is a different child '
                      'and choose the family before starting the sale. If it is the same child, use their existing enquiry.',
                      409, candidates=candidates)
    relationship = choice.get('relationship') or GuardianRelationship.PARENT
    if relationship not in GuardianRelationship.values:
        raise refusal('INVALID_RELATIONSHIP', 'Choose the guardian relationship.')
    if mode == 'EXISTING_FAMILY':
        allowed = {row['guardian_id'] for row in candidates}
        guardian = Guardian.objects.select_for_update().filter(pk=family.get('guardian_id')).first()
        if guardian is None or str(guardian.pk) not in allowed:
            raise refusal('INVALID_FAMILY', 'Choose one of the suggested families, or start a new family.')
    else:
        contact = clean_contact(choice.get('billing_contact') or {})
        guardian = Guardian.objects.create(
            full_name=contact.get('full_name') or ' '.join(lead.parent_name.split()),
            email=contact['email'] if 'email' in contact else (lead.parent_email or '').strip().lower(),
            phone=contact['phone'] if 'phone' in contact else lead.phone_key, created_by=actor)
        if not guardian.full_name:
            raise refusal('BILLING_CONTACT_REQUIRED', 'Enter the parent or guardian name.')
    account = StudentAccount.objects.create(reference=next_reference(), origin_lead=lead,
                                            student_name=' '.join(lead.student_name.split()), created_by=actor)
    StudentGuardian.objects.create(account=account, guardian=guardian, relationship=relationship, is_billing_contact=True,
                                   basis=mode, linked_by=actor)
    log_activity(action='student_account.open', entity_type='student_account', entity_id=account.pk,
                 entity_label=account.reference, context={'family': mode, 'enquiry': str(lead.pk), 'guardian': str(guardian.pk),
                                                          'suggested_families': len(candidates)},
                 request=request, actor=actor)
    return account


def billing_guardian(account):
    link = account.billing_link()
    return link.guardian if link else None


def capture_checkout_email(sale, raw_email, payment=None):
    """A missing parent email, taken from a VERIFIED successful Checkout only.

    Called inside the signed-webhook transaction after the payment validated.
    Fills the enquiry's existing parent email and the billing guardian's email
    when they are empty; never overwrites one Django already has. Stripe itself
    saves the email onto the student's Customer when that Customer had none.
    """
    email = (raw_email or '').strip().lower()
    if not email:
        return []
    try:
        validate_email(email)
    except ValidationError:
        return []
    account = sale.account
    filled = []
    link = account.billing_link()
    guardian = Guardian.objects.select_for_update().get(pk=link.guardian_id) if link else None
    if guardian is not None and not guardian.email:
        guardian.email = email
        guardian.save(update_fields=['email', 'updated_at'])
        filled.append('guardian')
    if account.origin_lead_id:
        from bookings.models import Lead
        if Lead.objects.filter(pk=account.origin_lead_id, parent_email='').update(parent_email=email, updated_at=timezone.now()):
            filled.append('enquiry')
    if filled:
        if guardian is not None:
            children = list(StudentAccount.objects.filter(guardian_links__guardian=guardian, guardian_links__ended_at__isnull=True,
                                                          guardian_links__is_billing_contact=True))
            mark_customers_stale(children)
        # Which records were filled, never the address itself.
        log_activity(action='student_account.email_from_checkout', entity_type='student_account', entity_id=account.pk,
                     entity_label=account.reference, context={'filled': filled, 'payment': str(payment.pk) if payment else None},
                     actor=None)
    return filled


def lock_identity(account):
    """First payment record or payment link: the child's identity becomes correction-only."""
    if not account.identity_locked_at:
        account.identity_locked_at = timezone.now()
        account.save(update_fields=['identity_locked_at'])


def locked_account_for_lead(lead_id):
    return StudentAccount.objects.filter(origin_lead_id=lead_id, identity_locked_at__isnull=False).first()


def mirror_unlocked_name(lead):
    """Before money is attached, an enquiry correction still names the child."""
    StudentAccount.objects.filter(origin_lead=lead, identity_locked_at__isnull=True).update(
        student_name=' '.join(lead.student_name.split()))


def mark_customers_stale(accounts):
    """Student-labelled Stripe Customers whose labels must be pushed again (legacy ones are never renamed)."""
    from .payment_models import StripeCustomer
    ids = list(StripeCustomer.objects.filter(account__in=accounts, label_format='STUDENT', customer_id__isnull=False)
               .values_list('pk', flat=True))
    if ids:
        StripeCustomer.objects.filter(pk__in=ids).update(student_metadata_synced=False)
        from .customers import sync_labels
        transaction.on_commit(lambda: [sync_labels(pk) for pk in ids])


@transaction.atomic
def update_billing_contact(actor, enquiry_id, data, request=None):
    from .payments import accessible_lead
    lead = accessible_lead(actor, enquiry_id, request, lock=True)
    account = StudentAccount.objects.select_for_update().filter(origin_lead=lead).first()
    if account is None:
        raise refusal('SALE_REQUIRED', 'Start the sale first.')
    link = account.billing_link()
    guardian = Guardian.objects.select_for_update().get(pk=link.guardian_id)
    contact = clean_contact(data)
    if 'full_name' in contact and not contact['full_name']:
        raise refusal('BILLING_CONTACT_REQUIRED', 'Enter the parent or guardian name.')
    changed = sorted(field for field in CONTACT_FIELDS if field in contact and getattr(guardian, field) != contact[field])
    for field in changed:
        setattr(guardian, field, contact[field])
    if changed:
        guardian.save(update_fields=[*changed, 'updated_at'])
    relationship = data.get('relationship')
    if relationship and relationship != link.relationship:
        if relationship not in GuardianRelationship.values:
            raise refusal('INVALID_RELATIONSHIP', 'Choose the guardian relationship.')
        StudentGuardian.objects.filter(pk=link.pk).update(relationship=relationship)
        changed.append('relationship')
    if changed:
        children = list(StudentAccount.objects.filter(guardian_links__guardian=guardian, guardian_links__ended_at__isnull=True,
                                                      guardian_links__is_billing_contact=True))
        mark_customers_stale(children)
        # Field names only: contact values stay out of the activity log.
        log_activity(action='student_account.billing_contact', entity_type='student_account', entity_id=account.pk,
                     entity_label=account.reference, context={'fields': changed, 'guardian': str(guardian.pk),
                                                              'children_affected': len(children)},
                     request=request, actor=actor)
    return account


@transaction.atomic
def correct_identity(actor, account_id, data, request=None):
    """Authorized, reasoned correction of a locked child identity, applied everywhere at once."""
    if not is_admin(actor, request):
        raise refusal('FORBIDDEN', 'Only an administrator can correct a student’s identity.', 403)
    from bookings.models import Lead
    found = StudentAccount.objects.filter(pk=account_id).values('origin_lead_id').first()
    if found is None:
        raise refusal('NOT_FOUND', 'No such student account.', 404)
    # Same lock order as collection and enrollment: the enquiry first, then the account.
    lead = Lead.objects.select_for_update().filter(pk=found['origin_lead_id']).first() if found['origin_lead_id'] else None
    account = StudentAccount.objects.select_for_update().get(pk=account_id)
    reason = ' '.join((data.get('reason') or '').split())
    if len(reason) < 10:
        raise refusal('REASON_REQUIRED', 'Explain the correction (at least 10 characters).')
    name = ' '.join((data.get('student_name') or '').split())
    if not name:
        raise refusal('INVALID_NAME', 'Enter the student’s name.')
    if name == account.student_name:
        raise refusal('NO_CHANGE', 'The name is unchanged.')
    from bookings.leads import InvalidLeadDetails, student_name_key
    try:
        key = student_name_key(name)
    except InvalidLeadDetails as exc:
        raise refusal('INVALID_NAME', exc.message if hasattr(exc, 'message') else str(exc)) from exc
    if lead and Lead.objects.filter(phone_key=lead.phone_key, student_name_key=key).exclude(pk=lead.pk).exists():
        raise refusal('LEAD_EXISTS', 'Another enquiry already uses this name with the same phone number. Correct that record instead.', 409)
    changes = {'student_name': {'old': account.student_name, 'new': name}}
    account.student_name = name
    account.save(update_fields=['student_name'])
    if lead:
        lead.student_name, lead.student_name_key = name, key
        lead.save(update_fields=['student_name', 'student_name_key', 'updated_at'])
        from communications import planner
        planner.lead_details_changed(lead, timezone.now())
    if account.student_id:
        from students.models import Student
        student = Student.objects.select_for_update().get(pk=account.student_id)
        student.full_name = name
        student.save(update_fields=['full_name', 'updated_at'])
    StudentIdentityCorrection.objects.create(account=account, changes=changes, reason=reason, corrected_by=actor)
    log_activity(action='student_account.identity_correction', entity_type='student_account', entity_id=account.pk,
                 entity_label=account.reference, context={'fields': sorted(changes)},
                 student=account.student if account.student_id else None, request=request, actor=actor)
    mark_customers_stale([account])
    return account


def account_data(account, actor=None, request=None):
    if account is None:
        return None
    admin = bool(actor) and is_admin(actor, request)
    link = account.billing_link()
    guardians = [{'guardian_id': str(row.guardian_id), 'full_name': row.guardian.full_name, 'relationship': row.relationship,
                  'is_billing_contact': row.is_billing_contact, 'basis': row.basis}
                 for row in account.guardian_links.select_related('guardian').filter(ended_at__isnull=True)]
    from .payment_models import StripeCustomer
    return {
        'id': str(account.pk), 'reference': account.reference, 'student_name': account.student_name,
        'identity_locked': bool(account.identity_locked_at),
        'student': {'id': str(account.student_id), 'student_code': account.student.student_code} if account.student_id else None,
        'billing_contact': {'guardian_id': str(link.guardian_id), 'full_name': link.guardian.full_name, 'email': link.guardian.email,
                            'phone': link.guardian.phone, 'relationship': link.relationship} if link else None,
        'guardians': guardians,
        'stripe_customers': [{'customer_id': row.customer_id, 'livemode': row.livemode, 'label_format': row.label_format}
                             for row in StripeCustomer.objects.filter(account=account).exclude(customer_id=None)],
        'corrections': [{'created_at': row.created_at.isoformat(), 'changes': row.changes, 'reason': row.reason,
                         'corrected_by': row.corrected_by.full_name or row.corrected_by.username}
                        for row in account.identity_corrections.select_related('corrected_by')] if admin else None,
        'can_correct_identity': admin,
    }
