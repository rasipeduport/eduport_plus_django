"""
Exam API, ported from the Supabase Hub route handlers + the Learn submit route.

Role rules (see core.permissions.IsAdminMentorOrStudentRead and
core.querysets.scope_exams_by_role): admins manage any student's exams,
mentors only their allocated students', students read their selected
persona's exams and may submit one answer sheet per additional exam, tutors
have no exam access at all.
"""
import uuid
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated

from students.models import Student, StatusChoices
from activity.utils import log_activity
from core.authentication import CSRFExemptSessionAuthentication
from core.permissions import IsAdminOrMentor, IsAdminMentorOrStudentRead, IsStudentUser
from core.querysets import scope_exams_by_role
from core.students import get_account_students, get_usable_students, resolve_selected_student
from core.pagination import paginate_queryset
from sessions.views import SessionFileDownloadView
from .models import (
    Exam,
    ExamStatusChoices,
    ExamFile,
    AdditionalExam,
    AdditionalExamStatusChoices,
    AdditionalExamFile,
    ExamFileKind,
)
from .serializers import ExamSerializer, AdditionalExamSerializer
from .services import (
    ExamStateError,
    derive_chapter_names,
    resolve_exam_slot,
    find_exam_conflict,
    validate_score,
    normalize_recording_link,
    validate_upload_batch,
    store_exam_files,
    store_additional_exam_files,
    discard_file_bytes,
    assert_exam_transition,
    assert_additional_exam_transition,
    collect_score_entries,
    build_scorecard,
    student_zone,
    SCORECARD_RANGES,
)

FEEDBACK_MAX_LENGTH = 2000
TITLE_MAX_LENGTH = 200


def _ctx(request):
    return {'request': request}


def _forbidden(message):
    return Response({"error": "Forbidden", "message": message}, status=status.HTTP_403_FORBIDDEN)


def _can_manage(user, student):
    """Admins manage any student; a mentor only their allocated students."""
    if user.role == 'ADMIN' or user.is_superuser:
        return True
    return user.role == 'MENTOR' and student.mentor_id == user.id


def _student_persona_error(request):
    """The dashboard's trio for a student request with no usable persona."""
    if get_usable_students(request.user).exists():
        return Response(
            {"error": "STUDENT_NOT_SELECTED", "message": "Please select which student you want to view."},
            status=status.HTTP_409_CONFLICT
        )
    if get_account_students(request.user).exists():
        return Response(
            {"error": "STUDENT_ACCESS_ENDED", "message": "Your access to Eduport Plus has ended."},
            status=status.HTTP_403_FORBIDDEN
        )
    return Response(
        {"error": "STUDENT_PROFILE_NOT_FOUND", "message": "Your profile is waiting to be linked with student records."},
        status=status.HTTP_404_NOT_FOUND
    )


def _lookup(model, pk):
    """Row by id, tolerating a malformed id (-> None, the view answers 404)."""
    try:
        return model.objects.select_related('student', 'student__profile', 'student__mentor', 'mentor').get(id=pk)
    except (model.DoesNotExist, ValidationError, ValueError, TypeError):
        return None


def _visible_queryset(model, request):
    """Rows the caller may read: selected persona for students, role scope for staff."""
    qs = model.objects.select_related('student', 'student__profile', 'student__mentor', 'mentor').prefetch_related('files')
    if request.user.role == 'STUDENT':
        student = resolve_selected_student(request)
        return qs.filter(student=student) if student else qs.none()
    return scope_exams_by_role(qs, request.user)


def _status_filter(queryset, raw, choices):
    values = [v.strip().upper() for v in raw.split(',') if v.strip()]
    for v in values:
        if v not in choices.values:
            raise ValueError(f"status must be one of {', '.join(c.lower() for c in choices.values)}")
    return queryset.filter(status__in=values) if values else queryset


def _apply_common_filters(queryset, params, choices, chapter_field):
    from django.db.models import Q
    student_id = params.get('student_id')
    if student_id:
        queryset = queryset.filter(student_id=student_id)
    raw_status = params.get('status')
    if raw_status:
        queryset = _status_filter(queryset, raw_status, choices)
    mentor = params.get('mentor')
    if mentor:
        queryset = queryset.filter(mentor_id=mentor)
    q = (params.get('q') or '').strip()
    if q:
        queryset = queryset.filter(Q(**{f'{chapter_field}__icontains': q}) | Q(student__full_name__icontains=q))
    return queryset


# ============================================================ chapter exams

class ExamsView(APIView):
    """
    GET: list chapter exams (admin: all, mentor: allocated students, student:
         the selected persona). PUT/POST: schedule, reschedule or cancel.
    """
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsAdminMentorOrStudentRead]

    def get(self, request, *args, **kwargs):
        queryset = _visible_queryset(Exam, request).order_by('-start_time')
        params = request.query_params
        try:
            queryset = _apply_common_filters(queryset, params, ExamStatusChoices, 'chapter_name')
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if params.get('from'):
            queryset = queryset.filter(start_time__gte=params['from'])
        if params.get('to'):
            queryset = queryset.filter(start_time__lte=params['to'])

        page_items, meta = paginate_queryset(request, queryset)
        source = queryset if page_items is None else page_items
        data = ExamSerializer(source, many=True, context=_ctx(request)).data
        if meta is not None:
            return Response({"exams": data, **meta}, status=status.HTTP_200_OK)
        return Response({"exams": data}, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        data = request.data
        student_id = data.get("student_id")
        chapter_name = (data.get("chapter_name") or "").strip() if isinstance(data.get("chapter_name"), str) else ""
        if not student_id:
            return Response({"error": "student_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not chapter_name:
            return Response({"error": "A chapter name is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            student = Student.objects.select_related('mentor').get(id=student_id)
        except (Student.DoesNotExist, ValidationError, ValueError):
            return Response({"error": "Student not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _can_manage(request.user, student):
            return _forbidden("You can only manage exams for your allocated students.")
        if student.status == StatusChoices.EXPIRED:
            return _forbidden("This student's enrollment has expired.")

        if chapter_name not in derive_chapter_names(student):
            return Response(
                {"error": "Chapter must be one of the student's sessions"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            start_time, end_time, duration = resolve_exam_slot(data, data.get("timezone"))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        conflict = find_exam_conflict(student, student.mentor, start_time, end_time)
        if conflict:
            return Response(
                {"error": f"This exam conflicts with {conflict}. Choose a different time."},
                status=status.HTTP_409_CONFLICT
            )

        with transaction.atomic():
            exam = Exam.objects.create(
                student=student,
                mentor=student.mentor,
                chapter_name=chapter_name,
                start_time=start_time,
                end_time=end_time,
                status=ExamStatusChoices.SCHEDULED,
            )

        log_activity(
            action='exam.create',
            entity_type='exam',
            entity_id=str(exam.id),
            entity_label=chapter_name,
            student=student,
            context={
                "type": "chapter",
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_hours": duration,
                "timezone": data.get("timezone"),
            },
            request=request,
        )
        return Response({"success": True, "exam": ExamSerializer(exam, context=_ctx(request)).data}, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        data = request.data
        exam_id = data.get("id")
        if not exam_id:
            return Response({"error": "Exam id is required"}, status=status.HTTP_400_BAD_REQUEST)
        exam = _lookup(Exam, exam_id)
        if not exam:
            return Response({"error": "Exam not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _can_manage(request.user, exam.student):
            return _forbidden("You can only manage exams for your allocated students.")

        new_status = None
        if 'status' in data:
            raw = data.get("status")
            new_status = raw.strip().upper() if isinstance(raw, str) else None
            if new_status != ExamStatusChoices.CANCELLED:
                return Response(
                    {"error": "status may only be set to cancelled; results are recorded through the result endpoint"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if not (data.get("cancellation_reason") or "").strip():
                return Response({"error": "A cancellation reason is required"}, status=status.HTTP_400_BAD_REQUEST)

        if exam.status != ExamStatusChoices.SCHEDULED:
            return Response(
                {"error": "Only a scheduled exam can be rescheduled or cancelled"},
                status=status.HTTP_409_CONFLICT
            )

        wants_reschedule = any(k in data for k in ('start_time', 'local_date', 'local_time', 'duration_hours'))
        new_start = new_end = None
        if wants_reschedule:
            has_time = any(k in data for k in ('start_time', 'local_date', 'local_time'))
            if not has_time or 'duration_hours' not in data:
                return Response(
                    {"error": "Both start_time and duration_hours are required to reschedule"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            try:
                new_start, new_end, _ = resolve_exam_slot(data, data.get("timezone"))
            except ValueError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            conflict = find_exam_conflict(exam.student, exam.mentor, new_start, new_end, exclude_exam_id=exam.id)
            if conflict:
                return Response(
                    {"error": f"This exam conflicts with {conflict}. Choose a different time."},
                    status=status.HTTP_409_CONFLICT
                )

        if not wants_reschedule and new_status is None:
            return Response({"error": "No valid fields to update"}, status=status.HTTP_400_BAD_REQUEST)

        before = {
            "status": exam.status.lower(),
            "start_time": exam.start_time.isoformat(),
            "end_time": exam.end_time.isoformat(),
        }
        with transaction.atomic():
            if new_start:
                exam.start_time = new_start
                exam.end_time = new_end
            if new_status:
                try:
                    assert_exam_transition(exam, new_status)
                except ExamStateError as exc:
                    return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
                exam.status = new_status
                exam.cancellation_reason = data.get("cancellation_reason").strip()
            exam.save()

        after = {
            "status": exam.status.lower(),
            "start_time": exam.start_time.isoformat(),
            "end_time": exam.end_time.isoformat(),
        }
        changes = {k: {"old": before[k], "new": after[k]} for k in before if before[k] != after[k]}
        if changes:
            context = {}
            if new_status == ExamStatusChoices.CANCELLED:
                context["reason"] = exam.cancellation_reason
            if new_start and data.get("timezone"):
                context["timezone"] = data.get("timezone")
            log_activity(
                action='exam.cancel' if new_status == ExamStatusChoices.CANCELLED else 'exam.reschedule',
                entity_type='exam',
                entity_id=str(exam.id),
                entity_label=exam.chapter_name,
                student=exam.student,
                changes=changes,
                context=context,
                request=request,
            )
        return Response({"success": True, "exam": ExamSerializer(exam, context=_ctx(request)).data}, status=status.HTTP_200_OK)


class ChapterNamesView(APIView):
    """GET /api/exams/chapter-names/?student_id= -- the dropdown behind New Chapter Exam."""
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrMentor]

    def get(self, request, *args, **kwargs):
        student_id = request.query_params.get('student_id')
        if not student_id:
            return Response({"error": "student_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            student = Student.objects.get(id=student_id)
        except (Student.DoesNotExist, ValidationError, ValueError):
            return Response({"error": "Student not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _can_manage(request.user, student):
            return _forbidden("You can only manage exams for your allocated students.")
        return Response({"chapter_names": derive_chapter_names(student)}, status=status.HTTP_200_OK)


class ExamDetailView(APIView):
    """GET /api/exams/<id>/ -- one exam with its question-paper files."""
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsAdminMentorOrStudentRead]

    def get(self, request, exam_id, *args, **kwargs):
        exam = _visible_queryset(Exam, request).filter(id=exam_id).first()
        if not exam:
            return Response({"error": "Exam not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"exam": ExamSerializer(exam, context=_ctx(request)).data}, status=status.HTTP_200_OK)


class ExamResultView(APIView):
    """
    POST /api/exams/<id>/result/ (multipart): record or edit the result.
    score + max_score (required), optional recording_link, optional `files`
    (question paper), optional `remove_file_ids`. Marks the exam attended on
    the first call; later calls edit it. New uploads are rolled back on
    failure; existing files are only removed after the row update succeeds.
    """
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrMentor]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, exam_id, *args, **kwargs):
        exam = _lookup(Exam, exam_id)
        if not exam:
            return Response({"error": "Exam not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _can_manage(request.user, exam.student):
            return _forbidden("You can only manage exams for your allocated students.")
        if exam.status == ExamStatusChoices.CANCELLED:
            return Response({"error": "A cancelled exam has no result to record"}, status=status.HTTP_409_CONFLICT)

        data = request.data
        try:
            score, max_score = validate_score(data.get("score"), data.get("max_score"))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Absent field = unchanged; present-but-blank = clear.
        recording_link = exam.recording_link
        if 'recording_link' in data:
            try:
                recording_link = normalize_recording_link(data.get("recording_link"))
            except ValueError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        uploads = request.FILES.getlist('files')
        try:
            validated = validate_upload_batch(uploads)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        raw_remove = data.getlist('remove_file_ids') if hasattr(data, 'getlist') else (data.get('remove_file_ids') or [])
        if isinstance(raw_remove, str):
            raw_remove = [raw_remove]
        remove_ids = []
        for value in raw_remove:
            if not value:
                continue
            try:
                remove_ids.append(uuid.UUID(str(value)))
            except (ValueError, TypeError):
                return Response({"error": "remove_file_ids must be valid ids"}, status=status.HTTP_400_BAD_REQUEST)
        to_remove = list(ExamFile.objects.filter(exam=exam, id__in=remove_ids)) if remove_ids else []
        if len(to_remove) != len(set(remove_ids)):
            return Response({"error": "A file to remove does not belong to this exam"}, status=status.HTTP_400_BAD_REQUEST)

        was_scheduled = exam.status == ExamStatusChoices.SCHEDULED
        before = {"score": exam.score, "max_score": exam.max_score, "recording_link": exam.recording_link}
        stored = []
        try:
            with transaction.atomic():
                assert_exam_transition(exam, ExamStatusChoices.ATTENDED)
                stored = store_exam_files(exam, validated, request.user)
                exam.status = ExamStatusChoices.ATTENDED
                exam.score = score
                exam.max_score = max_score
                exam.recording_link = recording_link
                exam.save()
        except ExamStateError as exc:
            discard_file_bytes(stored)
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
        except Exception:
            discard_file_bytes(stored)
            return Response(
                {"error": "Failed to save the exam result. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Removals only after the row update succeeded.
        for row in to_remove:
            row.delete()

        if was_scheduled:
            changes = {
                "status": {"old": "scheduled", "new": "attended"},
                "score": {"old": None, "new": score},
                "max_score": {"old": None, "new": max_score},
            }
            if recording_link:
                changes["recording_link"] = {"old": None, "new": recording_link}
        else:
            after = {"score": score, "max_score": max_score, "recording_link": recording_link}
            changes = {k: {"old": before[k], "new": after[k]} for k in before if before[k] != after[k]}

        log_activity(
            action='exam.mark_attended' if was_scheduled else 'exam.update_result',
            entity_type='exam',
            entity_id=str(exam.id),
            entity_label=exam.chapter_name,
            student=exam.student,
            changes=changes,
            context={"added_files": len(stored), "removed_files": len(to_remove)},
            request=request,
        )
        exam = _lookup(Exam, exam.id)
        return Response({"success": True, "exam": ExamSerializer(exam, context=_ctx(request)).data}, status=status.HTTP_200_OK)


class _FileDownloadBase(APIView):
    """Streams an uploaded exam file to anyone allowed to see its exam."""
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated]
    model = None
    parent_model = None
    parent_attr = None

    def _allowed(self, request, row):
        parent = getattr(row, self.parent_attr)
        user = request.user
        if user.role == 'STUDENT':
            return get_usable_students(user).filter(id=parent.student_id).exists()
        return scope_exams_by_role(self.parent_model.objects.filter(id=parent.id), user).exists()

    def get(self, request, file_id, *args, **kwargs):
        try:
            row = self.model.objects.select_related(self.parent_attr, f'{self.parent_attr}__student').get(id=file_id)
        except self.model.DoesNotExist:
            return Response({"error": "File not found"}, status=status.HTTP_404_NOT_FOUND)
        if not self._allowed(request, row):
            return _forbidden("You do not have access to this file.")
        try:
            size = row.file.size
        except (FileNotFoundError, OSError):
            return Response({"error": "File not found"}, status=status.HTTP_404_NOT_FOUND)
        response = SessionFileDownloadView._ranged_response(request, row, size)
        response['Accept-Ranges'] = 'bytes'
        response['Content-Disposition'] = f'inline; filename="{SessionFileDownloadView._ascii_name(row.file_name)}"'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, max-age=0'
        return response


class ExamFileDownloadView(_FileDownloadBase):
    """GET /api/exams/files/<file_id>/"""
    model = ExamFile
    parent_model = Exam
    parent_attr = 'exam'


class AdditionalExamFileDownloadView(_FileDownloadBase):
    """GET /api/additional-exams/files/<file_id>/ -- question papers and answer sheets."""
    model = AdditionalExamFile
    parent_model = AdditionalExam
    parent_attr = 'additional_exam'


# ============================================================ additional exams

class AdditionalExamsView(APIView):
    """GET: list additional exams. POST (multipart): assign one with its question paper."""
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsAdminMentorOrStudentRead]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, *args, **kwargs):
        queryset = _visible_queryset(AdditionalExam, request).order_by('-created_at')
        try:
            queryset = _apply_common_filters(queryset, request.query_params, AdditionalExamStatusChoices, 'title')
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        page_items, meta = paginate_queryset(request, queryset)
        source = queryset if page_items is None else page_items
        data = AdditionalExamSerializer(source, many=True, context=_ctx(request)).data
        if meta is not None:
            return Response({"additional_exams": data, **meta}, status=status.HTTP_200_OK)
        return Response({"additional_exams": data}, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        data = request.data
        student_id = data.get("student_id")
        title = data.get("title")
        title = title.strip() if isinstance(title, str) else ""
        if not student_id:
            return Response({"error": "student_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not title:
            return Response({"error": "A title is required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(title) > TITLE_MAX_LENGTH:
            return Response({"error": "Title is too long"}, status=status.HTTP_400_BAD_REQUEST)

        uploads = request.FILES.getlist('files')
        try:
            validated = validate_upload_batch(
                uploads, required=True, required_message='At least one question paper file is required'
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            student = Student.objects.select_related('mentor').get(id=student_id)
        except (Student.DoesNotExist, ValidationError, ValueError):
            return Response({"error": "Student not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _can_manage(request.user, student):
            return _forbidden("You can only manage exams for your allocated students.")
        if student.status == StatusChoices.EXPIRED:
            return _forbidden("This student's enrollment has expired.")

        stored = []
        try:
            with transaction.atomic():
                exam = AdditionalExam.objects.create(student=student, mentor=student.mentor, title=title)
                stored = store_additional_exam_files(exam, ExamFileKind.QUESTION_PAPER, validated, request.user)
        except Exception:
            discard_file_bytes(stored)
            return Response(
                {"error": "Failed to create the exam. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        log_activity(
            action='additional_exam.create',
            entity_type='additional_exam',
            entity_id=str(exam.id),
            entity_label=title,
            student=student,
            context={"file_count": len(stored)},
            request=request,
        )
        exam = _lookup(AdditionalExam, exam.id)
        return Response(
            {"success": True, "additional_exam": AdditionalExamSerializer(exam, context=_ctx(request)).data},
            status=status.HTTP_200_OK
        )


class AdditionalExamDetailView(APIView):
    """GET /api/additional-exams/<id>/ -- with files split into question paper / answer sheet."""
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsAdminMentorOrStudentRead]

    def get(self, request, exam_id, *args, **kwargs):
        exam = _visible_queryset(AdditionalExam, request).filter(id=exam_id).first()
        if not exam:
            return Response({"error": "Exam not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {"additional_exam": AdditionalExamSerializer(exam, context=_ctx(request)).data},
            status=status.HTTP_200_OK
        )


class AdditionalExamSubmitView(APIView):
    """
    POST /api/additional-exams/<id>/submit/ (multipart `files`): the student
    uploads their answer sheet ONCE. Only the owning (selected) student, only
    while the exam is still assigned.
    """
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsStudentUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, exam_id, *args, **kwargs):
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
                exam = AdditionalExam.objects.select_for_update().filter(id=exam_id, student=student).first()
                if not exam:
                    return Response({"error": "Exam not found"}, status=status.HTTP_404_NOT_FOUND)
                if exam.status != AdditionalExamStatusChoices.ASSIGNED:
                    return Response(
                        {"error": "This exam has already been submitted"},
                        status=status.HTTP_409_CONFLICT
                    )
                assert_additional_exam_transition(exam, AdditionalExamStatusChoices.SUBMITTED)
                stored = store_additional_exam_files(exam, ExamFileKind.ANSWER_SHEET, validated, request.user)
                exam.status = AdditionalExamStatusChoices.SUBMITTED
                exam.submitted_at = timezone.now()
                exam.save(update_fields=['status', 'submitted_at', 'updated_at'])
        except Exception:
            discard_file_bytes(stored)
            return Response({"error": "Failed to submit. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        log_activity(
            action='additional_exam.submit',
            entity_type='additional_exam',
            entity_id=str(exam.id),
            entity_label=exam.title,
            student=student,
            changes={"status": {"old": "assigned", "new": "submitted"}},
            context={"file_count": len(stored)},
            request=request,
        )
        exam = _lookup(AdditionalExam, exam.id)
        return Response(
            {"success": True, "additional_exam": AdditionalExamSerializer(exam, context=_ctx(request)).data},
            status=status.HTTP_200_OK
        )


class AdditionalExamScoreView(APIView):
    """POST /api/additional-exams/<id>/score/ (JSON): the mentor/admin scores a submitted exam."""
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrMentor]

    def post(self, request, exam_id, *args, **kwargs):
        exam = _lookup(AdditionalExam, exam_id)
        if not exam:
            return Response({"error": "Exam not found"}, status=status.HTTP_404_NOT_FOUND)
        if not _can_manage(request.user, exam.student):
            return _forbidden("You can only manage exams for your allocated students.")
        if exam.status != AdditionalExamStatusChoices.SUBMITTED:
            return Response({"error": "Only a submitted exam can be scored"}, status=status.HTTP_409_CONFLICT)

        data = request.data
        try:
            score, max_score = validate_score(data.get("score"), data.get("max_score"))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        feedback = data.get("feedback")
        if feedback is not None and not isinstance(feedback, str):
            return Response({"error": "feedback must be text"}, status=status.HTTP_400_BAD_REQUEST)
        feedback = (feedback or "").strip() or None
        if feedback and len(feedback) > FEEDBACK_MAX_LENGTH:
            return Response({"error": "Feedback is too long"}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            locked = AdditionalExam.objects.select_for_update().get(id=exam.id)
            if locked.status != AdditionalExamStatusChoices.SUBMITTED:
                return Response({"error": "Only a submitted exam can be scored"}, status=status.HTTP_409_CONFLICT)
            assert_additional_exam_transition(locked, AdditionalExamStatusChoices.SCORED)
            locked.status = AdditionalExamStatusChoices.SCORED
            locked.score = score
            locked.max_score = max_score
            locked.feedback = feedback
            locked.scored_by = request.user
            locked.scored_at = timezone.now()
            locked.save()

        changes = {
            "status": {"old": "submitted", "new": "scored"},
            "score": {"old": None, "new": score},
            "max_score": {"old": None, "new": max_score},
        }
        if feedback:
            changes["feedback"] = {"old": None, "new": feedback}
        log_activity(
            action='additional_exam.score',
            entity_type='additional_exam',
            entity_id=str(exam.id),
            entity_label=exam.title,
            student=exam.student,
            changes=changes,
            request=request,
        )
        exam = _lookup(AdditionalExam, exam.id)
        return Response(
            {"success": True, "additional_exam": AdditionalExamSerializer(exam, context=_ctx(request)).data},
            status=status.HTTP_200_OK
        )


# ============================================================ scorecard

class ScorecardView(APIView):
    """GET /api/student/scorecard/?range=week|month|all -- the Learn progress numbers."""
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsStudentUser]

    def get(self, request, *args, **kwargs):
        student = resolve_selected_student(request)
        if not student:
            return _student_persona_error(request)
        range_key = request.query_params.get('range') or 'month'
        if range_key not in SCORECARD_RANGES:
            range_key = 'month'
        entries = collect_score_entries(student)
        return Response(build_scorecard(entries, range_key, zone=student_zone(student)), status=status.HTTP_200_OK)
