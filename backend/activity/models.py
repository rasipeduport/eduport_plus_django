import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from students.models import Student

class ActivityLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    # The audit log must not be mutated by other tables: an ON DELETE SET NULL
    # would UPDATE log rows (rejected by the append-only trigger), so both FKs
    # carry no DB constraint and no delete action — the denormalized actor_*
    # snapshots keep rows self-contained forever (mirrors the original Hub
    # dropping activity_log's actor FK).
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        null=True,
        blank=True,
        related_name='activity_logs'
    )
    actor_email = models.EmailField(blank=True, null=True)
    actor_name = models.CharField(max_length=255, blank=True, null=True)
    actor_role = models.CharField(max_length=50, blank=True, null=True)
    
    action = models.CharField(max_length=255)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=255, db_index=True)
    entity_label = models.CharField(max_length=255, blank=True, null=True)
    
    student = models.ForeignKey(
        Student,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        null=True,
        blank=True,
        related_name='activity_logs'
    )
    
    changes = models.JSONField(default=dict, blank=True, null=True)
    context = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        db_table = 'activity_log'
        verbose_name = 'Activity Log'
        verbose_name_plural = 'Activity Logs'
        ordering = ['-created_at']

    def __str__(self):
        actor_str = self.actor_name or self.actor_email or 'System'
        return f"{actor_str} performed {self.action} on {self.entity_type} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"
