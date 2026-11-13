"""Student financial identity: one account per child, opened at the child's first sale.

The StudentAccount is the central financial reference. It exists before payment
(reference SA-000123), keeps that reference for life and gains the Student (and
its EDP ID) at enrollment. Guardians are billing contacts. Their phone and email
are attributes only: a child is never found or merged by them, and siblings are
linked only by StudentGuardian rows a person confirmed.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Guardian(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=255)
    email = models.EmailField(max_length=254, blank=True)
    # "+<dial code><number>", as Lead.phone_key. Deliberately not unique.
    phone = models.CharField(max_length=20, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='created_guardians')
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)


class StudentAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=20, unique=True, editable=False)
    origin_lead = models.OneToOneField('bookings.Lead', on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='student_account')
    # Set once, at enrollment; the account and its reference stay the same afterwards.
    student = models.OneToOneField('students.Student', on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='account')
    # The child's name as Django owns it. Once money or a payment link is
    # attached it changes only through StudentIdentityCorrection.
    student_name = models.CharField(max_length=255)
    identity_locked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='created_student_accounts')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['reference']
        constraints = [models.CheckConstraint(condition=Q(reference__regex=r'^SA-[0-9]{6,}$'), name='sales_account_reference_format')]

    def billing_link(self):
        return self.guardian_links.select_related('guardian').filter(is_billing_contact=True, ended_at__isnull=True).first()


class GuardianRelationship(models.TextChoices):
    PARENT = 'PARENT', 'Parent'
    MOTHER = 'MOTHER', 'Mother'
    FATHER = 'FATHER', 'Father'
    GUARDIAN = 'GUARDIAN', 'Guardian'
    OTHER = 'OTHER', 'Other'


class StudentGuardian(models.Model):
    """An explicit, attributable child-guardian link. Ended, never deleted."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(StudentAccount, on_delete=models.PROTECT, related_name='guardian_links')
    guardian = models.ForeignKey(Guardian, on_delete=models.PROTECT, related_name='student_links')
    relationship = models.CharField(max_length=10, choices=GuardianRelationship.choices, default=GuardianRelationship.PARENT)
    is_billing_contact = models.BooleanField(default=False)
    # NEW_FAMILY: new guardian for this child. EXISTING_FAMILY: a person confirmed
    # this child belongs to an existing guardian. BACKFILL: created by migration.
    basis = models.CharField(max_length=20, choices=[('NEW_FAMILY', 'New family'), ('EXISTING_FAMILY', 'Confirmed existing family'),
                                                     ('BACKFILL', 'Migrated from the enquiry'), ('CORRECTION', 'Correction')])
    linked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    linked_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['account', 'guardian'], condition=Q(ended_at__isnull=True), name='sales_guardian_link_once'),
            models.UniqueConstraint(fields=['account'], condition=Q(is_billing_contact=True, ended_at__isnull=True), name='sales_one_billing_contact'),
        ]


class StudentIdentityCorrection(models.Model):
    """Append-only audit of an authorized correction to a locked child identity."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(StudentAccount, on_delete=models.PROTECT, related_name='identity_corrections')
    changes = models.JSONField()
    reason = models.TextField()
    corrected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['created_at']
        constraints = [models.CheckConstraint(condition=~Q(reason=''), name='sales_identity_correction_reason')]
