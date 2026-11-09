"""
The Sales Management API for administrators (sales.services):

    GET    /api/sales/syllabi/                          every syllabus, paged and filtered
    POST   /api/sales/syllabi/                          a new syllabus: its draft revision 1
    GET    /api/sales/syllabi/<id>/                     one in full: published revision, draft, history
    POST   /api/sales/syllabi/<id>/draft/               start the next draft of a published syllabus
    PUT    /api/sales/syllabi/<id>/draft/               save the draft
    DELETE /api/sales/syllabi/<id>/draft/               discard the draft of a published syllabus
    POST   /api/sales/syllabi/<id>/publish/             publish the draft (explicit confirmation)
    POST   /api/sales/syllabi/<id>/deactivate/          hide it from the sales to come
    POST   /api/sales/syllabi/<id>/reactivate/          bring it back
    POST   /api/sales/syllabi/<id>/duplicate/           a new syllabus copied from it (or from one revision)
    GET    /api/sales/syllabi/<id>/revisions/<number>/  one revision as it was saved or published
    GET    /api/sales/syllabi/<id>/pdf/                 its PDF: what it offers (sales.downloads)
    GET    /api/sales/syllabi/<id>/revisions/<number>/pdf/  one revision's PDF
    POST   /api/sales/syllabi/pdf-preview/              the PDF of content not yet saved
    GET    /api/sales/pricing/                          the pricing in effect and every version
    POST   /api/sales/pricing/                          the next pricing version, in effect at once

Syllabuses need accounts.manage_sales_syllabi; adding a pricing version
accounts.manage_sales_pricing, and reading the pricing either -- both the
ADMIN role's alone (a superuser holds them too, D1). Errors answer
``{"error": CODE, "message": ..., "fields"?}``, as the Leads API does.
"""
import re

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import page_params
from core.permissions import ByMethod, HasAnyAppPermission, HasAppPermission

from . import services
from .downloads import SyllabusPdfView, pdf_response
from .models import Board, Structure, Syllabus, SyllabusRevision, SyllabusStatus
from .pricing import active_pricing
from .serializers import (
    DraftTokenSerializer, PricingVersionSerializer, SyllabusContentSerializer, SyllabusDraftSerializer,
)

MANAGE_SYLLABI = 'accounts.manage_sales_syllabi'
MANAGE_PRICING = 'accounts.manage_sales_pricing'
GRADE_RE = re.compile(r'[0-9]{1,2}')


def _error(code, message, http_status, **extra):
    return Response({'error': code, 'message': message, **extra}, status=http_status)


def _invalid(serializer, message):
    return _error('VALIDATION_ERROR', message, status.HTTP_400_BAD_REQUEST, fields=serializer.errors)


def _refused(exc):
    return _error(exc.code, exc.message, exc.http_status, **exc.extra)


def _no_syllabus():
    return _error('NOT_FOUND', 'No such syllabus.', status.HTTP_404_NOT_FOUND)


def _detail(syllabus_id, http_status=status.HTTP_200_OK):
    return Response(services.syllabus_detail(syllabus_id), status=http_status)


class SyllabiView(APIView):
    """
    GET  /api/sales/syllabi/?q=&status=&structure=&board=&grade=&page=&page_size=
         Every syllabus, the latest changed first, always paged:
         {"results", "count", "page", "page_size"}. Each row shows the
         revision it offers (before its first publication, its draft). ``q``
         matches the title; ``status`` is a SyllabusStatus.
    POST /api/sales/syllabi/
         A new syllabus (SyllabusContentSerializer): 201 with it in full, its
         draft revision 1 ready to edit.
    """
    permission_classes = [IsAuthenticated, HasAppPermission(MANAGE_SYLLABI)]

    def get(self, request, *args, **kwargs):
        params = request.query_params
        state = (params.get('status') or '').strip().upper()
        structure = (params.get('structure') or '').strip().upper()
        board = (params.get('board') or '').strip()
        grade = (params.get('grade') or '').strip()
        if state and state not in SyllabusStatus.values:
            return _error('INVALID_INPUT', 'Unknown status.', status.HTTP_400_BAD_REQUEST, fields=['status'])
        if structure and structure not in Structure.values:
            return _error('INVALID_INPUT', 'Unknown structure.', status.HTTP_400_BAD_REQUEST, fields=['structure'])
        if board and board not in Board.values:
            return _error('INVALID_INPUT', 'Unknown board.', status.HTTP_400_BAD_REQUEST, fields=['board'])
        if grade and not GRADE_RE.fullmatch(grade):
            return _error('INVALID_INPUT', 'Unknown grade.', status.HTTP_400_BAD_REQUEST, fields=['grade'])

        syllabi = services.listed(Syllabus.objects.select_related('updated_by'))
        lookups = {}
        if q := (params.get('q') or '').strip():
            lookups['title__icontains'] = q
        if structure:
            lookups['structure'] = structure
        if board:
            lookups['board'] = board
        if grade:
            lookups['grade'] = int(grade)
        if lookups:
            syllabi = services.filter_shown(syllabi, **lookups)
        if state:
            syllabi = services.filter_status(syllabi, state)
        syllabi = syllabi.order_by('-updated_at', 'pk')

        page, page_size = page_params(request)
        offset = (page - 1) * page_size
        return Response(
            {
                'results': services.list_rows(syllabi[offset:offset + page_size]),
                'count': syllabi.count(),
                'page': page,
                'page_size': page_size,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, *args, **kwargs):
        serializer = SyllabusContentSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the syllabus details.')
        syllabus = services.create_syllabus(request.user, serializer.validated_data, request=request)
        return _detail(syllabus.pk, status.HTTP_201_CREATED)


class SyllabusDetailView(APIView):
    """GET /api/sales/syllabi/<id>/: one syllabus in full -- its published revision, its draft, its history."""
    permission_classes = [IsAuthenticated, HasAppPermission(MANAGE_SYLLABI)]

    def get(self, request, pk, *args, **kwargs):
        detail = services.syllabus_detail(pk)
        return Response(detail, status=status.HTTP_200_OK) if detail is not None else _no_syllabus()


class SyllabusDraftView(APIView):
    """
    POST   /api/sales/syllabi/<id>/draft/
           Start the next draft of a published syllabus, copied from its
           published revision: 201 with the syllabus in full, or 409
           DRAFT_EXISTS / NOT_PUBLISHED / SYLLABUS_INACTIVE.
    PUT    /api/sales/syllabi/<id>/draft/ {content..., "updated_at"}
           Save the draft, if it is still the one saved at ``updated_at``
           (else 409 DRAFT_CHANGED). The published revision is untouched.
    DELETE /api/sales/syllabi/<id>/draft/ {"revision", "updated_at"}
           Discard the draft of a published syllabus: 200 with the syllabus.
    """
    permission_classes = [IsAuthenticated, HasAppPermission(MANAGE_SYLLABI)]

    def post(self, request, pk, *args, **kwargs):
        try:
            services.start_draft(request.user, pk, request=request)
        except Syllabus.DoesNotExist:
            return _no_syllabus()
        except services.SalesError as exc:
            return _refused(exc)
        return _detail(pk, status.HTTP_201_CREATED)

    def put(self, request, pk, *args, **kwargs):
        serializer = SyllabusDraftSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the syllabus details.')
        data = serializer.validated_data
        try:
            services.save_draft(request.user, pk, data, data['updated_at'], request=request)
        except Syllabus.DoesNotExist:
            return _no_syllabus()
        except services.SalesError as exc:
            return _refused(exc)
        return _detail(pk)

    def delete(self, request, pk, *args, **kwargs):
        serializer = DraftTokenSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Name the draft to discard.')
        try:
            services.discard_draft(
                request.user, pk, serializer.validated_data['revision'], serializer.validated_data['updated_at'],
                request=request,
            )
        except Syllabus.DoesNotExist:
            return _no_syllabus()
        except services.SalesError as exc:
            return _refused(exc)
        return _detail(pk)


class SyllabusPublishView(APIView):
    """
    POST /api/sales/syllabi/<id>/publish/ {"revision", "updated_at"}
    Publish the draft the Admin confirmed, as they saw it (else 409
    DRAFT_CHANGED). 400 NOT_PUBLISHABLE with ``problems`` when a plan type it
    offers sells no classes. The revision it replaces stays in the history.
    """
    permission_classes = [IsAuthenticated, HasAppPermission(MANAGE_SYLLABI)]

    def post(self, request, pk, *args, **kwargs):
        serializer = DraftTokenSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Name the draft to publish.')
        try:
            services.publish(
                request.user, pk, serializer.validated_data['revision'], serializer.validated_data['updated_at'],
                request=request,
            )
        except Syllabus.DoesNotExist:
            return _no_syllabus()
        except services.SalesError as exc:
            return _refused(exc)
        return _detail(pk)


class SyllabusLifecycleView(APIView):
    """POST /api/sales/syllabi/<id>/deactivate/ and .../reactivate/: 200 with the syllabus, or 409."""
    permission_classes = [IsAuthenticated, HasAppPermission(MANAGE_SYLLABI)]
    lifecycle_action = None

    def post(self, request, pk, *args, **kwargs):
        try:
            getattr(services, self.lifecycle_action)(request.user, pk, request=request)
        except Syllabus.DoesNotExist:
            return _no_syllabus()
        except services.SalesError as exc:
            return _refused(exc)
        return _detail(pk)


class DuplicateSerializer(serializers.Serializer):
    # The revision to copy; left out, what the syllabus offers (published, else its draft).
    revision = serializers.IntegerField(min_value=1, required=False)


class SyllabusDuplicateView(APIView):
    """
    POST /api/sales/syllabi/<id>/duplicate/ {"revision"?}
    201 with the new syllabus in full, its draft a copy of revision
    ``revision`` -- or, without one, of the revision the syllabus offers.
    """
    permission_classes = [IsAuthenticated, HasAppPermission(MANAGE_SYLLABI)]

    def post(self, request, pk, *args, **kwargs):
        serializer = DuplicateSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Name the revision to copy.')
        try:
            copy = services.duplicate(request.user, pk, serializer.validated_data.get('revision'), request=request)
        except Syllabus.DoesNotExist:
            return _no_syllabus()
        except services.SalesError as exc:
            return _refused(exc)
        return _detail(copy.pk, status.HTTP_201_CREATED)


class SyllabusRevisionView(APIView):
    """GET /api/sales/syllabi/<id>/revisions/<number>/: one revision, as saved or published, priced as now."""
    permission_classes = [IsAuthenticated, HasAppPermission(MANAGE_SYLLABI)]

    def get(self, request, pk, number, *args, **kwargs):
        revision = services.revision_detail(pk, number)
        if revision is None:
            return _error('NOT_FOUND', 'This syllabus has no such revision.', status.HTTP_404_NOT_FOUND)
        return Response(revision, status=status.HTTP_200_OK)


class SyllabusPdfDownloadView(SyllabusPdfView, APIView):
    """GET /api/sales/syllabi/<id>/pdf/[?disposition=inline]: the PDF of what it offers -- published, else its draft."""
    permission_classes = [IsAuthenticated, HasAppPermission(MANAGE_SYLLABI)]

    def get(self, request, pk, *args, **kwargs):
        revision = services.shown_revision(pk)
        if revision is None:
            return _no_syllabus()
        return pdf_response(request, services.content_of(revision), suffix=f'-r{revision.number}')


class SyllabusRevisionPdfView(SyllabusPdfView, APIView):
    """GET /api/sales/syllabi/<id>/revisions/<number>/pdf/[?disposition=inline]: one revision's PDF, priced as now."""
    permission_classes = [IsAuthenticated, HasAppPermission(MANAGE_SYLLABI)]

    def get(self, request, pk, number, *args, **kwargs):
        revision = SyllabusRevision.objects.filter(syllabus_id=pk, number=number).first()
        if revision is None:
            return _error('NOT_FOUND', 'This syllabus has no such revision.', status.HTTP_404_NOT_FOUND)
        return pdf_response(request, services.content_of(revision), suffix=f'-r{revision.number}')


class SyllabusPdfPreviewView(SyllabusPdfView, APIView):
    """
    POST /api/sales/syllabi/pdf-preview/[?disposition=inline] (SyllabusContentSerializer)
    The PDF the content would make -- the editor's preview before saving.
    Nothing is kept.
    """
    permission_classes = [IsAuthenticated, HasAppPermission(MANAGE_SYLLABI)]

    def post(self, request, *args, **kwargs):
        serializer = SyllabusContentSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the syllabus details.')
        return pdf_response(request, serializer.validated_data, suffix='-preview')


class PricingView(APIView):
    """
    GET  /api/sales/pricing/
         {"current": the version in effect or null, "versions": every one,
         newest first, each with effective_from and effective_until}.
    POST /api/sales/pricing/ (PricingVersionSerializer)
         The next version, in effect from now on: 201 with the same answer.
         Earlier versions never change.
    """
    permission_classes = [IsAuthenticated, ByMethod(
        GET=HasAnyAppPermission(MANAGE_SYLLABI, MANAGE_PRICING),
        POST=HasAppPermission(MANAGE_PRICING),
    )]

    def get(self, request, *args, **kwargs):
        return Response(self._pricing(), status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = PricingVersionSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer, 'Check the pricing.')
        services.create_pricing_version(request.user, serializer.validated_data, request=request)
        return Response(self._pricing(), status=status.HTTP_201_CREATED)

    @staticmethod
    def _pricing():
        current = active_pricing()
        return {
            'current': services.pricing_data(current) if current else None,
            'versions': services.pricing_history(),
        }
