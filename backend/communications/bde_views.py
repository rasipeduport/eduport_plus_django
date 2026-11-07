"""
The BDE workspace's follow-ups (communications.followups), beside the rest of
the workspace under /api/bde/ (bookings.urls):

    GET /api/bde/follow-ups/?due=&step=&enquiry=&page=&page_size=

The open steps of the parent communication on the caller's own leads'
bookings, soonest due first, always paged, with how many are overdue, due
today and upcoming. ``due`` is overdue, today or upcoming; ``step`` a
communication step; ``enquiry`` one of the caller's own leads (any other
finds nothing). Needs accounts.view_own_enquiries and
accounts.view_own_lead_communications -- the follow-ups are the leads'
communication, which carries the parent's phone number; only the BDE role
may hold either, and an account that is not a BDE (a superuser, D1) is
answered NOT_A_BDE before anything is read. Acting on a step is the
booking's communication's (communications.views), which checks its own
permissions for each action.
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
from .models import Step


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
        step = (params.get('step') or '').strip().upper()
        enquiry = (params.get('enquiry') or '').strip()
        invalid = []
        if due and due not in followups.DUE_FILTERS:
            invalid.append('due')
        if step and step not in Step.values:
            invalid.append('step')
        if enquiry:
            try:
                enquiry = uuid.UUID(enquiry)
            except ValueError:
                invalid.append('enquiry')
        if invalid:
            return Response(
                {'error': 'INVALID_INPUT', 'message': 'Check the follow-up filters.', 'fields': invalid},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        tasks = followups.own_open_tasks(request.user)
        if enquiry:
            tasks = followups.for_enquiry(tasks, enquiry)
        rows = followups.filtered(tasks, now, due=due or None, step=step or None)
        page, page_size = page_params(request)
        offset = (page - 1) * page_size
        return Response(
            {
                'results': [followups.followup_row(task, now) for task in rows[offset:offset + page_size]],
                'count': rows.count(),
                'page': page,
                'page_size': page_size,
                'timezone': BOOKING_TIMEZONE_NAME,
                'summary': followups.summary(tasks, now),
            },
            status=status.HTTP_200_OK,
        )
