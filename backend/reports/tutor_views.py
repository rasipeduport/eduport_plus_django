"""
A tutor's reports on the bookings assigned to them (design E.1, D.2):

    GET  /api/tutor/bookings/<type>/<id>/report/             the report as last saved
    POST /api/tutor/bookings/<type>/<id>/report/             submit it, which completes the booking
    PUT  /api/tutor/bookings/<type>/<id>/report/             edit it, naming the ``version`` edited
    GET  /api/tutor/bookings/<type>/<id>/report/revisions/   every version, oldest first
    GET  /api/tutor/bookings/<type>/<id>/report/pdf/         the report as a PDF (P7, reports.downloads)
    GET  /api/tutor/bookings/<type>/<id>/report/revisions/<version>/pdf/   one version as a PDF
    POST /api/tutor/bookings/<type>/<id>/report/preview/     the PDF a submit or edit of the body would make (P8)

``<type>`` is demo or diagnostic. Reading needs accounts.view_assigned_bookings
and writing accounts.submit_booking_report as well -- both the TUTOR role's.
Only the booking's assigned tutor reaches it: any other booking is 404, as one
that does not exist is (bookings.tutor_bookings.assigned_to), and
reports.services checks again under the booking's lock. The rules themselves
-- who, when, how often, which fields -- are reports.services'; these views
only find the booking and answer.

Bodies are JSON objects of exactly the fields the tutor writes
(reports.services.clean_fields); an edit adds ``version``. Anything else -- a
printed name, the status, a version on a submit -- is refused with 400
VALIDATION_ERROR naming it, never dropped. A submit or edit answers
``{"report": {...}, "booking": {"status", "completed_at", ...}}`` (an edit adds
``changed``). Errors answer ``{"error": CODE, "message": ...}``, with the
report's current ``version`` on REPORT_EXISTS and REPORT_VERSION_CONFLICT.
Nothing here names the parent (reports.payloads).
"""
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings import tutor_bookings
from bookings.models import booking_model
from bookings.public_views import PATH_TYPES
from core.permissions import ByMethod, HasAppPermission

from .downloads import ReportPdfView, report_pdf_response, report_preview_response
from .payloads import booking_completion, report_body, revision_rows
from .services import (
    ReportError,
    ReportExists,
    ReportInvalid,
    ReportVersionConflict,
    edit_report,
    preview_content,
    submit_report,
)

VIEW_ASSIGNED_BOOKINGS = HasAppPermission('accounts.view_assigned_bookings')
SUBMIT_BOOKING_REPORT = HasAppPermission('accounts.submit_booking_report')


class TutorReportView(APIView):
    """GET, POST (submit) and PUT (edit) one assigned booking's report."""
    permission_classes = [
        IsAuthenticated,
        VIEW_ASSIGNED_BOOKINGS,
        ByMethod(GET=VIEW_ASSIGNED_BOOKINGS, POST=SUBMIT_BOOKING_REPORT, PUT=SUBMIT_BOOKING_REPORT),
    ]
    parser_classes = [JSONParser]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking = _assigned_booking(request, booking_type, pk)
        if booking is None:
            return _no_booking()
        report = _report_of(booking)
        if report is None:
            return _no_report()
        return Response(report_body(report), status=status.HTTP_200_OK)

    def post(self, request, booking_type, pk, *args, **kwargs):
        booking = _assigned_booking(request, booking_type, pk)
        if booking is None:
            return _no_booking()
        try:
            report = submit_report(booking, request.user, request.data)
        except ReportError as exc:
            return _refusal(exc)
        return Response(
            {'report': report_body(report), 'booking': booking_completion(report.booking)},
            status=status.HTTP_201_CREATED,
        )

    def put(self, request, booking_type, pk, *args, **kwargs):
        booking = _assigned_booking(request, booking_type, pk)
        if booking is None:
            return _no_booking()
        if not isinstance(request.data, dict):
            return _refusal(ReportInvalid({'non_field_errors': ['Send the report as an object of its fields.']}))
        fields = {key: value for key, value in request.data.items() if key != 'version'}
        try:
            report, changed = edit_report(booking, request.user, fields, request.data.get('version'))
        except ReportError as exc:
            return _refusal(exc)
        return Response(
            {'report': report_body(report), 'booking': booking_completion(report.booking), 'changed': changed},
            status=status.HTTP_200_OK,
        )


class TutorReportRevisionsView(APIView):
    """GET every saved version of one assigned booking's report, oldest first: {"results", "count"}."""
    permission_classes = [IsAuthenticated, VIEW_ASSIGNED_BOOKINGS]

    def get(self, request, booking_type, pk, *args, **kwargs):
        booking = _assigned_booking(request, booking_type, pk)
        if booking is None:
            return _no_booking()
        report = _report_of(booking)
        if report is None:
            return _no_report()
        rows = revision_rows(report)
        return Response({'results': rows, 'count': len(rows), 'version': report.version}, status=status.HTTP_200_OK)


class TutorReportPdfView(ReportPdfView, APIView):
    """GET one assigned booking's report as a PDF: as last saved, or as saved at ``version``."""
    permission_classes = [IsAuthenticated, VIEW_ASSIGNED_BOOKINGS]

    def get(self, request, booking_type, pk, version=None, *args, **kwargs):
        booking = _assigned_booking(request, booking_type, pk)
        if booking is None:
            return _no_booking()
        report = _report_of(booking)
        if report is None:
            return _no_report()
        return report_pdf_response(booking, report, version)


class TutorReportPreviewView(ReportPdfView, APIView):
    """
    POST a report's fields -- a submit's body, or an edit's with its
    ``version`` -- and get the PDF they would make, drawn exactly as the saved
    version will be. Nothing is saved: no report, no revision, no history.
    Refused as a save of the same body would be (reports.services.preview_content).
    """
    permission_classes = [IsAuthenticated, VIEW_ASSIGNED_BOOKINGS, SUBMIT_BOOKING_REPORT]
    parser_classes = [JSONParser]

    def post(self, request, booking_type, pk, *args, **kwargs):
        booking = _assigned_booking(request, booking_type, pk)
        if booking is None:
            return _no_booking()
        fields = request.data
        if isinstance(fields, dict):
            fields = {key: value for key, value in fields.items() if key != 'version'}
        try:
            content = preview_content(booking, request.user, fields)
        except ReportError as exc:
            return _refusal(exc)
        return report_preview_response(booking, content)


def _assigned_booking(request, booking_type, pk):
    """The ``<type>`` booking ``pk`` if it is assigned to the caller now, else None. An unknown type is 404."""
    try:
        model = booking_model(PATH_TYPES[booking_type])
    except KeyError:
        raise NotFound()
    return tutor_bookings.assigned_to(request.user, model).filter(pk=pk).first()


def _report_of(booking):
    return getattr(booking, 'report', None)


def _no_booking():
    return Response({'error': 'NOT_FOUND', 'message': 'No such booking.'}, status=status.HTTP_404_NOT_FOUND)


def _no_report():
    return Response({'error': 'NO_REPORT', 'message': 'This booking has no report yet.'}, status=status.HTTP_404_NOT_FOUND)


def _refusal(exc):
    extra = {}
    if isinstance(exc, ReportInvalid):
        extra['fields'] = exc.fields
    if isinstance(exc, (ReportExists, ReportVersionConflict)):
        extra['version'] = exc.version
    return Response({'error': exc.code, 'message': exc.message, **extra}, status=exc.http_status)
