"""
The BDE workspace's follow-ups (communications.followups), beside the rest of
the workspace under /api/bde/ (bookings.urls):

    GET  /api/bde/follow-ups/?state=&due=&type=&enquiry=&page=&page_size=
    POST /api/bde/follow-ups/<id>/complete/   {"outcome": <code>}

What the caller must do next on their own leads -- the five follow-up types,
never the system's own messages -- always paged. ``state`` is open (the
default: soonest due first, with how many are overdue, due today and
upcoming) or closed (Completed and Missed, newest first: one enquiry's only,
so ``enquiry`` is then required); ``due`` is overdue, today or upcoming;
``type`` a follow-up type; ``enquiry`` one of the caller's own leads (any
other finds nothing). Both need accounts.view_own_enquiries and
accounts.view_own_lead_communications -- the follow-ups carry the parent's
phone number; only the BDE role may hold either, and an account that is not a
BDE (a superuser, D1) is answered NOT_A_BDE before anything is read.

Completing is for the two follow-ups no other record holds (a FollowUp): a
new enquiry's call, with how it went (accounts.send_lead_communications), and
a report's discussion (accounts.view_own_lead_reports and
accounts.share_booking_report). Another BDE's follow-up and one that does not
exist are answered alike, 404 NOT_FOUND. The confirmations and the 15-minute
call are acted on through the booking's communication (communications.views),
which checks its own permissions for each action.
"""
import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authz import has_app_permission
from bookings.booking_service import BookingBusy
from bookings.scheduling import BOOKING_TIMEZONE_NAME
from bookings.views import BdeWorkspaceView
from core.pagination import page_params
from core.permissions import HasAppPermission

from . import followups
from .models import FollowUpKind, FollowUpOutcome

PERMISSIONS = [
    IsAuthenticated,
    HasAppPermission('accounts.view_own_enquiries'),
    HasAppPermission('accounts.view_own_lead_communications'),
]


def _error(code, message, http_status, **extra):
    return Response({'error': code, 'message': message, **extra}, status=http_status)


class BdeFollowUpsView(BdeWorkspaceView):
    permission_classes = PERMISSIONS

    def get(self, request, *args, **kwargs):
        refusal = self.non_bde_refusal(request)
        if refusal:
            return refusal
        params = request.query_params
        state = (params.get('state') or followups.OPEN).strip().lower()
        due = (params.get('due') or '').strip().lower()
        follow_up_type = (params.get('type') or '').strip().upper()
        enquiry = (params.get('enquiry') or '').strip()
        invalid = []
        if state not in followups.STATES:
            invalid.append('state')
        if due and (due not in followups.DUE_FILTERS or state == followups.CLOSED):
            invalid.append('due')
        if follow_up_type and follow_up_type not in followups.FollowUpType.values:
            invalid.append('type')
        if enquiry:
            try:
                enquiry = uuid.UUID(enquiry)
            except ValueError:
                invalid.append('enquiry')
        elif state == followups.CLOSED:
            invalid.append('enquiry')
        if invalid:
            return _error('INVALID_INPUT', 'Check the follow-up filters.', status.HTTP_400_BAD_REQUEST, fields=invalid)

        now = timezone.now()
        extra = {}
        if state == followups.CLOSED:
            items = followups.closed_items(request.user, now, enquiry, request)
        else:
            items = followups.open_items(request.user, now, request, enquiry=enquiry or None)
            extra['summary'] = followups.summary(items)
        items = followups.filtered(items, due=due or None, follow_up_type=follow_up_type or None)
        page, page_size = page_params(request)
        offset = (page - 1) * page_size
        return Response(
            {
                'results': [followups.row(item, now, request.user) for item in items[offset:offset + page_size]],
                'count': len(items),
                'page': page,
                'page_size': page_size,
                'timezone': BOOKING_TIMEZONE_NAME,
                **extra,
            },
            status=status.HTTP_200_OK,
        )


class BdeFollowUpCompleteView(BdeWorkspaceView):
    """
    POST /api/bde/follow-ups/<id>/complete/ {"outcome": <code>}
    Complete one of the caller's own FollowUps (followups.complete): a new
    enquiry's call with how it went -- SPOKE, MESSAGED, NOT_INTERESTED or
    WRONG_NUMBER -- or a report's discussion (DISCUSSED, the default). Answers
    the follow-up as it now stands, Completed. 400 INVALID_OUTCOME, 404
    NOT_FOUND, 409 FOLLOW_UP_DONE.
    """
    permission_classes = PERMISSIONS

    def post(self, request, pk, *args, **kwargs):
        refusal = self.non_bde_refusal(request)
        if refusal:
            return refusal
        follow_up = followups.own_follow_ups(request.user).filter(pk=pk).first()
        if follow_up is None:
            missing = followups.FollowUpNotFound
            return _error(missing.code, missing.message, missing.http_status)
        if not all(has_app_permission(request.user, name, request)
                   for name in followups.COMPLETE_PERMISSIONS[follow_up.kind]):
            raise PermissionDenied()
        outcome = request.data.get('outcome') if hasattr(request.data, 'get') else None
        if follow_up.kind == FollowUpKind.REPORT_DISCUSSION and not outcome:
            outcome = FollowUpOutcome.DISCUSSED
        outcome = outcome.strip().upper() if isinstance(outcome, str) else ''
        try:
            follow_up = followups.complete(follow_up, outcome, actor=request.user, owner_bde=request.user)
        except followups.FollowUpError as exc:
            return _error(exc.code, exc.message, exc.http_status)
        except BookingBusy:
            return _error('BOOKING_BUSY', 'This enquiry is being changed right now. Try again in a moment.',
                          status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(followups.row(followups.done_item(follow_up), timezone.now(), request.user),
                        status=status.HTTP_200_OK)
