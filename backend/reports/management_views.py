"""
Reports for the Admin (design E.1, D.3, D17), read-only:

    GET /api/bookings/<type>/<id>/report/             a booking's report as last saved
    GET /api/bookings/<type>/<id>/report/revisions/   every version of it, oldest first
    GET /api/bookings/<type>/<id>/report/pdf/         the report as a PDF (P7, reports.downloads)
    GET /api/bookings/<type>/<id>/report/revisions/<version>/pdf/   one version as a PDF

``<type>`` is demo or diagnostic. All need accounts.view_all_bookings, which
only the ADMIN role may hold (a superuser holds it too, decision D1): the
Admin reads every report, as the booking pages read every booking. Nobody
writes a report here -- only its assigned tutor does (reports.tutor_views) --
and only the lead's owner BDE sends one to the parent (P9, design F.4). A
booking that does not exist is 404 NOT_FOUND; one without a report, 404
NO_REPORT. The answers are the ones the tutor gets (reports.payloads).
"""
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import booking_model
from bookings.public_views import PATH_TYPES
from core.permissions import HasAppPermission

from .downloads import ReportPdfView, report_pdf_response
from .payloads import report_body, revision_rows

VIEW_ALL_BOOKINGS = HasAppPermission('accounts.view_all_bookings')


class BookingReportView(APIView):
    """GET one booking's report."""
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking, report = _booking_and_report(booking_type, pk)
        if booking is None:
            return _no_booking()
        if report is None:
            return _no_report()
        return Response(report_body(report), status=status.HTTP_200_OK)


class BookingReportRevisionsView(APIView):
    """GET every saved version of one booking's report, oldest first: {"results", "count", "version"}."""
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking, report = _booking_and_report(booking_type, pk)
        if booking is None:
            return _no_booking()
        if report is None:
            return _no_report()
        rows = revision_rows(report)
        return Response({'results': rows, 'count': len(rows), 'version': report.version}, status=status.HTTP_200_OK)


class BookingReportPdfView(ReportPdfView, APIView):
    """GET one booking's report as a PDF: as last saved, or as saved at ``version``."""
    permission_classes = [IsAuthenticated, VIEW_ALL_BOOKINGS]

    def get(self, request, booking_type, pk, version=None, *args, **kwargs):
        booking, report = _booking_and_report(booking_type, pk)
        if booking is None:
            return _no_booking()
        if report is None:
            return _no_report()
        return report_pdf_response(booking, report, version)


def _booking_and_report(booking_type, pk):
    """The ``<type>`` booking ``pk`` (or None) and its report (or None). An unknown type is 404."""
    try:
        model = booking_model(PATH_TYPES[booking_type])
    except KeyError:
        raise NotFound()
    booking = model.objects.select_related('report').filter(pk=pk).first()
    return booking, getattr(booking, 'report', None)


def _no_booking():
    return Response({'error': 'NOT_FOUND', 'message': 'No such booking.'}, status=status.HTTP_404_NOT_FOUND)


def _no_report():
    return Response({'error': 'NO_REPORT', 'message': 'This booking has no report yet.'}, status=status.HTTP_404_NOT_FOUND)
