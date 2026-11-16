"""
Reports for the lead's owner BDE (P9, design F.4 and E.1):

    GET  /api/bde/enquiries/<lead_id>/reports/        the reports on one of the caller's leads, as they print
    GET  /api/bde/bookings/<type>/<id>/report/pdf/     one of them as a PDF, as last saved (reports.downloads)
    POST /api/bde/bookings/<type>/<id>/report/share/   keep that it was just sent to the parent

``<type>`` is demo or diagnostic. Each needs accounts.view_own_lead_reports,
which only the BDE role may hold; a superuser holds it too (decision D1) but
owns no enquiries, so is answered NOT_A_BDE (bookings.views.BdeWorkspaceView).
Keeping a send also needs accounts.share_booking_report.

Ownership is enforced here, never left to the Hub: the lead, or the booking's
lead, is looked up among the caller's own leads only (bookings.enquiries
.own_leads) before anything else is read. Another BDE's lead, one nobody owns,
a booking of the other type and one that does not exist are all answered
alike, 404 NOT_FOUND; a booking of the caller's own lead with no report yet is
404 NO_REPORT. The reports are the ones the tutor and the Admin get
(reports.payloads), and the PDF is the current version, under their rate limit.

Sending a report stays outside the Hub (F.4): WhatsApp opens from the enquiry
page with the parent's number, and the BDE attaches the PDF -- or the device
shares the PDF. The enquiry page then tells report/share/, which keeps the
send (reports.services.record_share) and so ends the BDE's reminder to share
the report (communications.followups); nothing can tell whether the parent
got it.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bookings import enquiries
from bookings.models import BOOKING_MODELS, booking_model
from bookings.public_views import PATH_TYPES
from bookings.scheduling import BOOKING_TIMEZONE_NAME
from bookings.views import BdeWorkspaceView
from core.permissions import HasAppPermission

from .downloads import ReportPdfView, report_pdf_response
from .payloads import lead_report_row
from .services import NoReport, record_share

VIEW_OWN_LEAD_REPORTS = HasAppPermission('accounts.view_own_lead_reports')
SHARE_BOOKING_REPORT = HasAppPermission('accounts.share_booking_report')


class BdeLeadReportsView(BdeWorkspaceView):
    """GET the reports on one of the caller's own leads, newest booking first: {"results", "count", "timezone"}."""
    permission_classes = [IsAuthenticated, VIEW_OWN_LEAD_REPORTS]

    def get(self, request, pk, *args, **kwargs):
        refusal = self.non_bde_refusal(request)
        if refusal:
            return refusal
        lead = enquiries.own_leads(request.user).filter(pk=pk).first()
        if lead is None:
            return _not_found('No such enquiry.')
        rows = [lead_report_row(booking) for booking in _reported_bookings(lead)]
        return Response({'results': rows, 'count': len(rows), 'timezone': BOOKING_TIMEZONE_NAME}, status=status.HTTP_200_OK)


class BdeBookingReportPdfView(ReportPdfView, BdeWorkspaceView):
    """GET the report on a booking of one of the caller's own leads, as a PDF of its current version."""
    permission_classes = [IsAuthenticated, VIEW_OWN_LEAD_REPORTS]

    def get(self, request, booking_type, pk, *args, **kwargs):
        refusal = self.non_bde_refusal(request)
        if refusal:
            return refusal
        try:
            model = booking_model(PATH_TYPES[booking_type])
        except KeyError:
            return _not_found('No such booking.')
        booking = (model.objects.select_related('slot', 'report')
                   .filter(pk=pk, lead__in=enquiries.own_leads(request.user)).first())
        if booking is None:
            return _not_found('No such booking.')
        report = getattr(booking, 'report', None)
        if report is None:
            return Response({'error': 'NO_REPORT', 'message': 'This booking has no report yet.'},
                            status=status.HTTP_404_NOT_FOUND)
        return report_pdf_response(booking, report)


class BdeBookingReportShareView(BdeWorkspaceView):
    """
    POST: the report on a booking of one of the caller's own leads was just
    sent to the parent from the enquiry page (record_share). 201 with the
    version sent; 404 NOT_FOUND, or NO_REPORT for a booking with none yet.
    """
    permission_classes = [IsAuthenticated, VIEW_OWN_LEAD_REPORTS, SHARE_BOOKING_REPORT]

    def post(self, request, booking_type, pk, *args, **kwargs):
        refusal = self.non_bde_refusal(request)
        if refusal:
            return refusal
        try:
            model = booking_model(PATH_TYPES[booking_type])
        except KeyError:
            return _not_found('No such booking.')
        booking = (model.objects.select_related('slot', 'report')
                   .filter(pk=pk, lead__in=enquiries.own_leads(request.user)).first())
        if booking is None:
            return _not_found('No such booking.')
        try:
            share = record_share(booking, request.user)
        except NoReport as exc:
            return Response({'error': exc.code, 'message': exc.message}, status=exc.http_status)
        return Response({'report_version': share.report_version, 'shared_at': share.shared_at.isoformat()},
                        status=status.HTTP_201_CREATED)


def _reported_bookings(lead):
    """The lead's bookings of both types that have a report, newest slot first, as its enquiry lists them."""
    bookings = [
        booking
        for model in BOOKING_MODELS
        for booking in model.objects.filter(lead=lead, report__isnull=False).select_related('slot', 'report')
    ]
    return sorted(bookings, key=lambda booking: (booking.slot.starts_at, booking.created_at), reverse=True)


def _not_found(message):
    return Response({'error': 'NOT_FOUND', 'message': message}, status=status.HTTP_404_NOT_FOUND)
