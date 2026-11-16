"""
The BDE workspace's follow-ups (communications.followups), beside the rest of
the workspace under /api/bde/ (bookings.urls):

    GET /api/bde/follow-ups/?due=&type=&enquiry=&page=&page_size=

The reminders that need the caller's attention now on their own leads --
the five reminder types, never the system's own messages -- soonest due
first, always paged, with how many are due today and later. ``due`` is today
or upcoming; ``type`` a reminder type; ``enquiry`` one of the caller's own
leads (any other finds nothing). The list needs accounts.view_own_enquiries
and accounts.view_own_lead_communications -- the reminders carry the
parent's phone number; only the BDE role may hold either, and an account
that is not a BDE (a superuser, D1) is answered NOT_A_BDE before anything is
read. Acting on a reminder is the API's that owns its record: the booking's
communication (communications.views) and the report's sharing (reports.bde_views);
a new enquiry's call ends with the enquiry's own status.
"""
import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bookings.scheduling import BOOKING_TIMEZONE_NAME
from bookings.views import BdeWorkspaceView
from core.pagination import page_params
from core.permissions import HasAppPermission

from . import followups

def _error(code, message, http_status, **extra):
    return Response({'error': code, 'message': message, **extra}, status=http_status)


class BdeFollowUpsView(BdeWorkspaceView):
    permission_classes = [
        IsAuthenticated,
        HasAppPermission('accounts.view_own_enquiries'),
        HasAppPermission('accounts.view_own_lead_communications'),
    ]

    def get(self, request, *args, **kwargs):
        refusal = self.non_bde_refusal(request)
        if refusal:
            return refusal
        params = request.query_params
        due = (params.get('due') or '').strip().lower()
        follow_up_type = (params.get('type') or '').strip().upper()
        enquiry = (params.get('enquiry') or '').strip()
        invalid = []
        if due and due not in followups.DUE_FILTERS:
            invalid.append('due')
        if follow_up_type and follow_up_type not in followups.FollowUpType.values:
            invalid.append('type')
        if enquiry:
            try:
                enquiry = uuid.UUID(enquiry)
            except ValueError:
                invalid.append('enquiry')
        if invalid:
            return _error('INVALID_INPUT', 'Check the follow-up filters.', status.HTTP_400_BAD_REQUEST, fields=invalid)

        now = timezone.now()
        items = followups.open_items(request.user, now, request, enquiry=enquiry or None)
        counts = followups.summary(items)
        items = followups.filtered(items, due=due or None, follow_up_type=follow_up_type or None)
        page, page_size = page_params(request)
        offset = (page - 1) * page_size
        return Response(
            {
                'results': [followups.row(item, now) for item in items[offset:offset + page_size]],
                'count': len(items),
                'page': page,
                'page_size': page_size,
                'timezone': BOOKING_TIMEZONE_NAME,
                'summary': counts,
            },
            status=status.HTTP_200_OK,
        )

