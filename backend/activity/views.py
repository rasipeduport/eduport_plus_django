import uuid

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from django.db.models import Q

from accounts.authz import has_app_permission
from core.permissions import HasAnyAppPermission
from core.querysets import ACTIVITY_VIEW_PERMISSIONS, scope_activity
from .models import ActivityLog
from .serializers import ActivityLogSerializer

User = get_user_model()

# Authentication/provisioning entries. Recorded for audit, but excluded from
# the unfiltered feed so it reads as a log of changes, like the Hub's.
AUTH_ACTIONS = ('user.sign_in', 'user.sign_out', 'user.onboarded')


def _actor_options(may_filter_by_actor):
    """
    Choices for the actor filter dropdown. Whoever holds
    accounts.view_activity_actors (admins) picks from every account. Anyone
    else is pinned to their own entries, so they get no choices (the SPA hides
    the control) and the staff roster is not handed out.
    """
    if not may_filter_by_actor:
        return []
    return [
        {"id": str(u.id), "name": u.full_name or u.email}
        for u in User.objects.all().order_by('full_name')
    ]


class ActivityLogListView(APIView):
    """
    GET /api/activity/
    Returns list of activity logs matching query parameters.
    Supports pagination, filters, and full-text keyword search.

    Every staff role may read, but not the same rows. view_all_activity
    (admins) gets the whole log -- their oversight tool, as in the original
    Hub. view_own_activity (mentors, tutors) gets only the entries they wrote
    themselves -- see core.querysets.scope_activity. The scope is applied
    before any query parameter, so ?actor=, ?student_id= and the rest can only
    narrow it, never widen it.
    """
    permission_classes = [IsAuthenticated, HasAnyAppPermission(*ACTIVITY_VIEW_PERMISSIONS)]

    def get(self, request, *args, **kwargs):
        params = request.query_params

        # Everything this caller may ever see; the request filters below only
        # narrow it further.
        queryset = scope_activity(ActivityLog.objects.all(), request.user, request).order_by('-created_at')

        # Filters
        student_id = params.get('student_id')
        if student_id:
            queryset = queryset.filter(student_id=student_id)

        action = params.get('action')
        if action:
            queryset = queryset.filter(action=action)
        else:
            # Hub parity: this feed is a change log -- "who changed what". The
            # sign-in and onboarding entries are still written and kept for the
            # audit trail, they just don't drown the default view; picking one
            # by name in the action filter brings them back.
            queryset = queryset.exclude(action__in=AUTH_ACTIONS)

        entity_type = params.get('entity') or params.get('entity_type')
        if entity_type:
            queryset = queryset.filter(entity_type=entity_type)

        actor_id = params.get('actor') or params.get('actor_id')
        if actor_id:
            queryset = queryset.filter(actor_id=actor_id)

        # One account's history (the Hub's Team details page): what they did,
        # and what was done to their profile -- role changes, password resets,
        # deactivation. Like every filter it only narrows the scope above.
        subject = params.get('subject')
        if subject:
            try:
                subject_id = uuid.UUID(str(subject))
            except ValueError:
                return Response(
                    {"error": "INVALID_INPUT", "message": "subject must be a valid account id."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(
                Q(actor_id=subject_id) | Q(entity_type='profile', entity_id=str(subject_id))
            )

        from_date = params.get('from')
        if from_date:
            queryset = queryset.filter(created_at__gte=from_date)

        to_date = params.get('to')
        if to_date:
            queryset = queryset.filter(created_at__lte=to_date)

        # Keyword search
        q = params.get('q', '').strip()
        if q:
            # Clean special characters that might be passed in OR search
            safe_q = q.replace(',', ' ').replace('*', ' ').strip()
            if safe_q:
                # Support search by actor name, actor email, or entity label
                queryset = queryset.filter(
                    Q(actor_name__icontains=safe_q) |
                    Q(actor_email__icontains=safe_q) |
                    Q(entity_label__icontains=safe_q)
                )

        # Pagination
        try:
            page = max(1, int(params.get('page', 1)))
        except ValueError:
            page = 1

        try:
            page_size = max(1, int(params.get('page_size') or params.get('pageSize') or 25))
        except ValueError:
            page_size = 25

        total_count = queryset.count()
        offset = (page - 1) * page_size
        paginated_queryset = queryset[offset:offset + page_size]

        serializer = ActivityLogSerializer(paginated_queryset, many=True)

        response_data = {
            "results": serializer.data,
            "count": total_count,
            "page": page,
            "page_size": page_size,
            "actor_options": _actor_options(
                has_app_permission(request.user, 'accounts.view_activity_actors', request)
            ),
        }

        return Response(response_data, status=status.HTTP_200_OK)
