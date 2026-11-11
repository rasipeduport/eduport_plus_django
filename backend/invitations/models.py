import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone

class InvitationRoleChoices(models.TextChoices):
    STUDENT = 'STUDENT', 'Student'
    MENTOR = 'MENTOR', 'Mentor'
    TUTOR = 'TUTOR', 'Tutor'
    ADMIN = 'ADMIN', 'Admin'

class InvitationStatusChoices(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    ACCEPTED = 'ACCEPTED', 'Accepted'
    EXPIRED = 'EXPIRED', 'Expired'

class Invitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Retained only as optional contact data for historical invitations.
    email = models.EmailField(db_index=True, blank=True)
    student = models.OneToOneField('students.Student', on_delete=models.PROTECT,
                                  null=True, blank=True, related_name='learn_invitation')
    account = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                  null=True, blank=True, related_name='learn_invitation')
    credential_ciphertext = models.TextField(blank=True, editable=False)
    activated_at = models.DateTimeField(null=True, blank=True)
    role = models.CharField(
        max_length=20,
        choices=InvitationRoleChoices.choices,
        db_index=True
    )
    extra_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_invitations'
    )
    status = models.CharField(
        max_length=20,
        choices=InvitationStatusChoices.choices,
        default=InvitationStatusChoices.PENDING,
        db_index=True
    )

    class Meta:
        db_table = 'whitelisted_emails'
        verbose_name = 'Invitation'
        verbose_name_plural = 'Invitations'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.email} ({self.role}) - {self.status}"
