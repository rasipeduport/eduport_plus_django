import logging
from django.utils import timezone
from rest_framework.throttling import BaseThrottle
from .models import ActivityLog

logger = logging.getLogger(__name__)

def log_activity(
    action,
    entity_type,
    entity_id,
    entity_label=None,
    student=None,
    changes=None,
    context=None,
    request=None,
    actor=None
):
    """
    Best-effort log creation helper to write activity log entries.
    It resolves request context (IP, User Agent) and actor credentials automatically.
    """
    try:
        if request and not actor:
            actor = request.user if request.user.is_authenticated else None

        actor_email = actor.email if actor else None
        actor_name = actor.full_name if actor else None
        actor_role = actor.role if actor else None

        # Build context metadata
        ctx = {}
        if context:
            ctx.update(context)
        
        if request:
            # The same client-address rule as the login throttle (DRF's
            # NUM_PROXIES): only X-Forwarded-For entries appended by the
            # configured number of trusted proxies are believed. The leftmost
            # entry is whatever the client chose to send.
            ip = BaseThrottle().get_ident(request)
            ctx.update({
                "ip": ip or None,
                "user_agent": request.META.get('HTTP_USER_AGENT') or None
            })

        # Save activity log entry
        log_entry = ActivityLog.objects.create(
            actor=actor,
            actor_email=actor_email,
            actor_name=actor_name,
            actor_role=actor_role,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            entity_label=entity_label,
            student=student,
            changes=changes or {},
            context=ctx
        )
        return log_entry
    except Exception as e:
        # Prevent logging errors from causing functional failures in user transactions
        logger.exception(f"Failed to create ActivityLog for action '{action}': {e}")
        return None
