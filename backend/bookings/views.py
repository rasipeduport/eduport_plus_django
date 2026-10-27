from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import HasAppPermission

from .serializers import BookingLinkSerializer
from .services import links_for, owns_booking_links


class BdeBookingLinksView(APIView):
    """
    GET /api/bde/booking-links/
    The caller's own permanent booking links -- one Demo, one Diagnostic --
    issued on the first request and the same on every request after.

    Nothing in the request chooses whose links are returned (a ``bde_id``
    parameter, say, is never read), so an account only ever sees its own.
    Guarded by accounts.view_own_booking_links, which only the BDE role may
    hold; a superuser holds it as well (decision D1) without being a BDE, so
    links are also only ever issued to an active BDE account.
    """
    permission_classes = [IsAuthenticated, HasAppPermission('accounts.view_own_booking_links')]

    def get(self, request, *args, **kwargs):
        if not owns_booking_links(request.user):
            return Response(
                {
                    "error": "NOT_A_BDE",
                    "message": "Booking links belong to BDE accounts, and this account is not one.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        links = links_for(request.user, request=request)
        return Response({"links": BookingLinkSerializer(links, many=True).data}, status=status.HTTP_200_OK)
