"""
Homework API: the Hub's /homework page and the Learn detail/submit flow.

Assignment is NOT done here -- it stays in the sessions API (homework link or
upload on the session), which creates the Homework row through
``homework.services.sync_homework_for_session``. These views read the row,
take the student's one-shot submission and the tutor's grade.
"""
from django.db import transaction
from django.db.models import F, Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated

from activity.utils import log_activity
from core.authentication import CSRFExemptSessionAuthentication
from core.pagination import paginate_queryset
from core.permissions import IsAdminOrTutor, IsStaffOrSelfStudent, IsStudentUser
from core.querysets import scope_homework_by_role
from core.students import get_usable_students, resolve_selected_student
from exams.services import discard_file_bytes, validate_upload_batch
from exams.views import _FileDownloadBase, _forbidden, _student_persona_error
from .models import Homework, HomeworkStatusChoices, HomeworkFile
from .serializers import HomeworkSerializer
from .services import HomeworkStateError, can_grade, can_view_submission, score_homework, submit_homework

FEEDBACK_MAX_LENGTH = 2000


def _ctx(request):
    return {'request': request}


def _base_queryset():
    return (
        Homework.objects
        .select_related('session', 'session__tutor', 'student', 'student__profile', 'student__mentor',
                        'student__tutor', 'assigned_by', 'scored_by')
        .prefetch_related('files', 'session__files')
    )


def _visible_queryset(request):
    qs = _base_queryset()
    if request.user.role == 'STUDENT':
        student = resolve_selected_student(request)
        return qs.filter(student=student) if student else qs.none()
    return scope_homework_by_role(qs, request.user)


class HomeworkView(APIView):
    """GET /api/homework/ -- admin: all; mentor/tutor: their students; student: the selected persona."""
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsStaffOrSelfStudent]

    def get(self, request, *args, **kwargs):
        params = request.query_params
        queryset = _visible_queryset(request)

        raw_status = params.get('status')
        if raw_status:
            values = [v.strip().upper() for v in raw_status.split(',') if v.strip()]
            for v in values:
                if v not in HomeworkStatusChoices.values:
                    return Response(
                        {"error": "status must be one of assigned, submitted, scored"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            if values:
                queryset = queryset.filter(status__in=values)
        if params.get('student_id'):
            queryset = queryset.filter(student_id=params['student_id'])
        if params.get('tutor') and request.user.role != 'STUDENT':
            queryset = queryset.filter(student__tutor_id=params['tutor'])
        q = (params.get('q') or '').strip()
        if q:
            queryset = queryset.filter(
                Q(student__full_name__icontains=q) | Q(student__student_code__icontains=q) | Q(session__title__icontains=q)
            )

        # Needs-review first: newest submission on top, unsubmitted rows after.
        queryset = queryset.order_by(F('submitted_at').desc(nulls_last=True), '-assigned_at')

        page_items, meta = paginate_queryset(request, queryset)
        source = queryset if page_items is None else page_items
        data = HomeworkSerializer(source, many=True, context=_ctx(request)).data
        if meta is not None:
            return Response({"homework": data, **meta}, status=status.HTTP_200_OK)
        return Response({"homework": data}, status=status.HTTP_200_OK)


class HomeworkDetailView(APIView):
    """GET /api/homework/<id>/"""
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsStaffOrSelfStudent]

    def get(self, request, homework_id, *args, **kwargs):
        homework = _visible_queryset(request).filter(id=homework_id).first()
        if not homework:
            return Response({"error": "Homework not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"homework": HomeworkSerializer(homework, context=_ctx(request)).data}, status=status.HTTP_200_OK)


class HomeworkSubmitView(APIView):
    """
    POST /api/homework/<id>/submit/ (multipart `files`): the student submits
    their completed homework ONCE -- only the owning (selected) persona, only
    while the homework is still assigned.
    """
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsStudentUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, homework_id, *args, **kwargs):
        student = resolve_selected_student(request)
        if not student:
            return _student_persona_error(request)

        uploads = request.FILES.getlist('files')
        try:
            validated = validate_upload_batch(uploads, required=True, required_message='Add at least one photo')
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        stored = []
        try:
            with transaction.atomic():
                homework = Homework.objects.select_for_update().filter(id=homework_id, student=student).first()
                if not homework:
                    return Response({"error": "Homework not found"}, status=status.HTTP_404_NOT_FOUND)
                try:
                    stored = submit_homework(homework, validated, request.user)
                except HomeworkStateError as exc:
                    return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
        except Exception:
            discard_file_bytes(stored)
            return Response({"error": "Failed to submit. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        log_activity(
            action='homework.submit',
            entity_type='homework',
            entity_id=str(homework.id),
            entity_label=homework.session.title,
            student=student,
            changes={"status": {"old": "assigned", "new": "submitted"}},
            context={"file_count": len(stored)},
            request=request,
        )
        homework = _base_queryset().get(id=homework.id)
        return Response({"success": True, "homework": HomeworkSerializer(homework, context=_ctx(request)).data}, status=status.HTTP_200_OK)


class HomeworkScoreView(APIView):
    """POST /api/homework/<id>/score/ (JSON): the student's tutor or an admin grades a submitted homework."""
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrTutor]

    def post(self, request, homework_id, *args, **kwargs):
        homework = _base_queryset().filter(id=homework_id).first()
        if not homework:
            return Response({"error": "Homework not found"}, status=status.HTTP_404_NOT_FOUND)
        if not can_grade(request.user, homework.student):
            return _forbidden("You can only grade homework for your allocated students.")
        if homework.status != HomeworkStatusChoices.SUBMITTED:
            return Response({"error": "Only a submitted homework can be scored"}, status=status.HTTP_409_CONFLICT)

        data = request.data
        feedback = data.get("feedback")
        if feedback is not None and not isinstance(feedback, str):
            return Response({"error": "feedback must be text"}, status=status.HTTP_400_BAD_REQUEST)
        feedback = (feedback or "").strip() or None
        if feedback and len(feedback) > FEEDBACK_MAX_LENGTH:
            return Response({"error": "Feedback is too long"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                locked = Homework.objects.select_for_update().get(id=homework.id)
                score_homework(locked, data.get("score"), data.get("max_score"), feedback, request.user)
        except HomeworkStateError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        changes = {
            "status": {"old": "submitted", "new": "scored"},
            "score": {"old": None, "new": locked.score},
            "max_score": {"old": None, "new": locked.max_score},
        }
        if feedback:
            changes["feedback"] = {"old": None, "new": feedback}
        log_activity(
            action='homework.score',
            entity_type='homework',
            entity_id=str(homework.id),
            entity_label=homework.session.title,
            student=homework.student,
            changes=changes,
            request=request,
        )
        homework = _base_queryset().get(id=homework.id)
        return Response({"success": True, "homework": HomeworkSerializer(homework, context=_ctx(request)).data}, status=status.HTTP_200_OK)


class HomeworkFileDownloadView(_FileDownloadBase):
    """GET /api/homework/files/<file_id>/ -- submission files, with the mentor-once-scored rule."""
    model = HomeworkFile
    parent_model = Homework
    parent_attr = 'homework'

    def _allowed(self, request, row):
        homework = row.homework
        user = request.user
        if user.role == 'STUDENT':
            return get_usable_students(user).filter(id=homework.student_id).exists()
        if not scope_homework_by_role(Homework.objects.filter(id=homework.id), user).exists():
            return False
        return can_view_submission(user, homework)
