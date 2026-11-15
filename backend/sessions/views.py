import uuid
import logging
import os
import re
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.contrib.auth import get_user_model
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated

from students.models import Student
from activity.utils import log_activity
from accounts.authz import has_app_permission
from core.permissions import HasAnyAppPermission, IsStudentUserFor
from core.querysets import SESSION_VIEW_PERMISSIONS, reaches, scope_sessions
from core.students import get_usable_students, resolve_selected_student
from core.pagination import paginate_queryset
from core.timezones import TimezoneConversionError, is_valid_timezone
from exams.services import find_exam_conflict_for_session
from bookings.booking_service import find_booking_conflict, is_assignable_tutor
from homework.services import HomeworkStateError, assert_assignment_editable, sync_homework_for_session
from . import lifecycle
from .models import Session, SessionStatusChoices, SessionContentField, SessionFile
from .serializers import SessionSerializer, SessionFileSerializer
from .services import (
    ALLOWED_DURATIONS,
    MAX_SERIES_ITEMS,
    normalize_title,
    normalize_link,
    parse_iso_datetime,
    resolve_start_time,
    calculate_credits_used,
    find_conflict,
    find_internal_overlap,
    lock_scheduling,
    conflict_response_data,
    booking_conflict_response_data,
    inactive_tutor_response_data,
    SERIES_ITEMS_OVERLAP,
    apply_content_filter,
    validate_content_upload,
)

logger = logging.getLogger(__name__)
User = get_user_model()

# Whoever holds any of these reaches the sessions endpoints; each write then
# checks its own permission and that the student is within the caller's
# session scope (core.querysets.reaches), answering with its own message.
SESSION_PERMISSIONS = (
    *SESSION_VIEW_PERMISSIONS,
    'accounts.create_session', 'accounts.manage_session', 'accounts.cancel_session',
    'accounts.edit_session_notes',
)


def staff_display_name(user):
    """
    How a staff member is named in an activity diff: the same full-name-else-
    email fallback the Hub uses, so an expanded row reads "Tutor: A -> B"
    rather than showing raw UUIDs.
    """
    if not user:
        return None
    return user.full_name or user.email


def drop_stale_files(session, changed_fields):
    """
    After a link column changes, remove the upload that used to stand behind
    it unless the new value still points at that file. Keeps one set of bytes
    per link and lets "replace the upload with a URL" free the storage.
    """
    names = {f[:-len('_link')] for f in changed_fields}
    for sf in list(session.files.filter(field__in=names)):
        if not sf.matches_link(getattr(session, sf.link_field)):
            sf.delete()


class SessionsView(APIView):
    """
    GET: List sessions.
    POST: Create one or more sessions (accounts.create_session).
    PUT: Update a single session (accounts.manage_session; with only
         accounts.edit_session_notes, just the notes link of a session
         assigned to the caller -- which completes the class once its
         scheduled end has passed, sessions.lifecycle). Students may GET
         their selected student's sessions and PUT a rating.
    """
    permission_classes = [IsAuthenticated, HasAnyAppPermission(*SESSION_PERMISSIONS) | IsStudentUserFor('GET', 'PUT')]

    def get(self, request, *args, **kwargs):
        queryset = (
            Session.objects.select_related('student', 'student__profile', 'tutor', 'homework', 'started_by', 'completed_by')
            .prefetch_related('files')
            .order_by('-start_time')
        )

        # If the requester is a student, restrict to their own sessions;
        # staff to the students their session permissions reach.
        if request.user.role == 'STUDENT':
            student = resolve_selected_student(request)
            if not student:
                return Response({"sessions": []}, status=status.HTTP_200_OK)
            queryset = queryset.filter(student=student)
        else:
            queryset = scope_sessions(queryset, request.user, request)

        # One student's classes (the student profile's Sessions tab, and any
        # caller that wants a single student's list). Applied after the role
        # scoping, so it can only narrow what this caller may already see --
        # the same contract as ?student_id= on the exams and homework lists.
        student_id = request.query_params.get('student_id')
        if student_id:
            try:
                uuid.UUID(str(student_id))
            except (ValueError, TypeError, AttributeError):
                return Response(
                    {"error": "student_id must be a valid id"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            queryset = queryset.filter(student_id=student_id)

        # Post-session content filter (attended rows only), applied after the
        # scoping and before pagination. Absent/blank means no filter.
        content = request.query_params.get('content')
        if content:
            try:
                queryset = apply_content_filter(queryset, content)
            except ValueError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Opt-in pagination: full list by default, sliced when ?page= is given.
        page_items, meta = paginate_queryset(request, queryset)
        source = queryset if page_items is None else page_items

        serializer = SessionSerializer(source, many=True)
        if meta is not None:
            return Response({"sessions": serializer.data, **meta}, status=status.HTTP_200_OK)
        return Response({"sessions": serializer.data}, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        data = request.data
        student_id = data.get("student_id")
        base_title = data.get("base_title")
        series = data.get("series", False)
        items = data.get("items")

        if not student_id or not base_title or not isinstance(items, list):
            return Response(
                {"error": "student_id, base_title, and items are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        normalized_base = normalize_title(base_title)
        if not normalized_base:
            return Response(
                {"error": "base_title cannot be empty"},
                status=status.HTTP_400_BAD_REQUEST
            )

        is_series = bool(series)

        # One zone governs every class in the booking -- it belongs to the
        # student, not to an individual class. Validated against the zone
        # database rather than an enum so the list stays correct as tzdata
        # is updated. Optional: legacy clients still send UTC start_time.
        timezone_name = data.get("timezone")
        if timezone_name is not None and not is_valid_timezone(timezone_name):
            return Response(
                {"error": f'Unknown time zone "{timezone_name}"'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(items) == 0:
            return Response(
                {"error": "At least one class is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not is_series and len(items) != 1:
            return Response(
                {"error": "Non-series submissions must contain exactly one class"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if len(items) > MAX_SERIES_ITEMS:
            return Response(
                {"error": f"A series can contain at most {MAX_SERIES_ITEMS} classes"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1. Fetch Student profile
        try:
            student = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            return Response(
                {"error": "Student not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if not has_app_permission(request.user, 'accounts.create_session', request):
            return Response(
                {"error": "Forbidden", "message": "Tutors cannot create sessions."},
                status=status.HTTP_403_FORBIDDEN
            )
        if not reaches('sessions', request.user, student, request):
            return Response(
                {"error": "Forbidden", "message": "You can only manage sessions for your allocated students."},
                status=status.HTTP_403_FORBIDDEN
            )

        if not student.tutor:
            return Response(
                {"error": "This student has no tutor assigned. Assign a tutor before creating a session."},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Classes are taught only by an active tutor (decision D5).
        if not is_assignable_tutor(student.tutor):
            return Response(
                inactive_tutor_response_data("This series" if is_series else "This session"),
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate items and calculate total requested hours
        validated_items = []
        series_total = 0.0
        for i, item in enumerate(items):
            label = f"Class {i + 1}" if is_series else "class"
            duration = item.get("duration_hours")
            
            # Check duration is valid
            if not isinstance(duration, (int, float)) or duration not in ALLOWED_DURATIONS:
                return Response(
                    {"error": f"{label}: duration_hours must be 0.5, 1, 1.5, or 2"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Each class converts independently against the shared zone: a
            # series spanning a DST change must hold its local start time, so
            # the UTC offsets across it are deliberately not uniform.
            try:
                start_time = resolve_start_time(item, timezone_name, label)
            except TimezoneConversionError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

            # Duration is elapsed time, so it is added to the instant -- a
            # 1-hour class stays 1 hour even across a clock change.
            end_time = start_time + timedelta(hours=duration)
            validated_items.append({
                "start_time": start_time,
                "end_time": end_time,
                "duration_hours": duration
            })
            series_total += float(duration)

        # 2. Check Quota Balance
        credits_used = calculate_credits_used(student)
        total_quota = float(student.total_class_quota)
        remaining = total_quota - credits_used

        if series_total > remaining + 1e-9:
            return Response(
                {"error": f"This {'series' if is_series else 'session'} needs {series_total} credits but only {remaining:.2f} remain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3a. Classes within one request must not overlap each other either:
        # the database check below only sees rows that already exist, so a
        # series with two classes in the same slot would otherwise be saved.
        overlap = find_internal_overlap([(v["start_time"], v["end_time"]) for v in validated_items])
        if overlap:
            first, second = overlap
            return Response(
                {
                    "error": (
                        f"Class {second + 1} overlaps Class {first + 1}. Classes in a series must not "
                        f"overlap each other (back-to-back classes are fine)."
                    ),
                    "code": SERIES_ITEMS_OVERLAP,
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3b + 4. Conflict checks and the inserts share one transaction and
        # one advisory lock per student/tutor: a concurrent booking for the
        # same tutor waits for this one to commit and then sees its rows.
        message_zone = timezone_name or student.timezone
        series_id = uuid.uuid4() if is_series else None
        created_sessions = []

        with transaction.atomic():
            lock_scheduling(student.id, student.tutor_id)
            for i, v in enumerate(validated_items):
                label = f"Class {i + 1}" if is_series else "This session"
                conflict = find_conflict(student, student.tutor, v["start_time"], v["end_time"])
                if conflict:
                    return Response(
                        conflict_response_data(conflict, student, message_zone, label),
                        status=status.HTTP_409_CONFLICT
                    )
                # Tuition is one-to-one: nor over a Demo or Diagnostic booking
                # the tutor teaches (bookings.booking_service.assign_tutor
                # takes the same tutor lock before assigning one).
                booking_conflict = find_booking_conflict(student.tutor, v["start_time"], v["end_time"])
                if booking_conflict:
                    return Response(
                        booking_conflict_response_data(booking_conflict, student.tutor, student, message_zone, label),
                        status=status.HTTP_409_CONFLICT
                    )
                # A class may not overlap one of the student's scheduled exams either.
                exam_conflict = find_exam_conflict_for_session(student, v["start_time"], v["end_time"])
                if exam_conflict:
                    return Response(
                        {"error": f"{label} conflicts with the exam \"{exam_conflict.chapter_name}\". Choose a different time."},
                        status=status.HTTP_409_CONFLICT
                    )

            for idx, v in enumerate(validated_items):
                sess = Session.objects.create(
                    student=student,
                    start_time=v["start_time"],
                    end_time=v["end_time"],
                    title=f"{normalized_base} - Class {idx + 1}" if is_series else normalized_base,
                    tutor=student.tutor,
                    series_id=series_id,
                    class_number=idx + 1 if is_series else None,
                    status=SessionStatusChoices.SCHEDULED
                )
                created_sessions.append(sess)

        # 5. Log Activity
        if created_sessions:
            series_create = is_series and len(created_sessions) > 1
            log_activity(
                action='session.create_series' if series_create else 'session.create',
                entity_type='session',
                entity_id=str(series_id if series_create else created_sessions[0].id),
                entity_label=normalized_base if series_create else created_sessions[0].title,
                student=student,
                context={
                    "count": len(created_sessions),
                    "series_id": str(series_id) if series_id else None,
                    "base_title": normalized_base
                },
                request=request
            )

        serializer = SessionSerializer(created_sessions, many=True)
        return Response({"success": True, "sessions": serializer.data}, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        data = request.data
        session_id = data.get("id")

        if not session_id:
            return Response(
                {"error": "Session id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            session = Session.objects.get(id=session_id)
        except Session.DoesNotExist:
            return Response(
                {"error": "Session not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Students may only rate their own (currently selected) student's sessions.
        # They cannot change status, links, tutor, or schedule.
        if request.user.role == 'STUDENT':
            selected = resolve_selected_student(request)
            if not selected or session.student_id != selected.id:
                return Response(
                    {"error": "Forbidden", "message": "You can only rate your own sessions."},
                    status=status.HTTP_403_FORBIDDEN
                )

            try:
                rating = int(data.get("rating"))
            except (TypeError, ValueError):
                return Response(
                    {"error": "A rating between 1 and 5 is required."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if rating < 1 or rating > 5:
                return Response(
                    {"error": "A rating between 1 and 5 is required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            before_rating = session.rating
            session.rating = rating
            session.save(update_fields=['rating'])

            if before_rating != rating:
                log_activity(
                    action='session.rate',
                    entity_type='session',
                    entity_id=str(session.id),
                    entity_label=session.title,
                    student=session.student,
                    changes={"rating": {"old": before_rating, "new": rating}},
                    request=request,
                )

            return Response(
                {"success": True, "session": SessionSerializer(session).data},
                status=status.HTTP_200_OK
            )

        # Without manage_session, edit_session_notes (tutors) owns exactly one
        # field: the notes link, on sessions within the caller's scope.
        # Everything else (status, recording, homework, schedule, tutor,
        # rating) needs manage_session.
        if not has_app_permission(request.user, 'accounts.manage_session', request):
            if has_app_permission(request.user, 'accounts.edit_session_notes', request):
                return self._tutor_update_notes(request, session, data)
            return Response(
                {"error": "Forbidden", "message": "You do not have permission to edit sessions."},
                status=status.HTTP_403_FORBIDDEN
            )
        if not reaches('sessions', request.user, session.student, request):
            return Response(
                {"error": "Forbidden", "message": "You can only edit sessions for your allocated students."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Validate status: CharField choices are not enforced on save(), so an
        # unchecked value would be persisted as-is.
        new_status = None
        if 'status' in data:
            raw_status = data.get("status")
            new_status = raw_status.upper() if isinstance(raw_status, str) else None
            if new_status not in SessionStatusChoices.values:
                return Response(
                    {"error": "status must be one of SCHEDULED, ATTENDED, or CANCELLED"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if new_status == 'CANCELLED' and not (data.get("cancellation_reason") or "").strip():
                return Response(
                    {"error": "A cancellation reason is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if new_status == 'CANCELLED' and not has_app_permission(request.user, 'accounts.cancel_session', request):
                return Response(
                    {"error": "Forbidden", "message": "You do not have permission to cancel sessions."},
                    status=status.HTTP_403_FORBIDDEN
                )
            # Attendance is a record (sessions.lifecycle): an attended class
            # stays attended, a cancelled one is never marked attended, and a
            # cancelled class its tutor had started is not put back on the
            # schedule -- its start belongs to the time it was cancelled at.
            if new_status != session.status:
                if session.status == SessionStatusChoices.ATTENDED:
                    return Response(
                        {"error": "An attended session's status cannot be changed.", "code": lifecycle.SESSION_ATTENDED},
                        status=status.HTTP_409_CONFLICT
                    )
                if session.status == SessionStatusChoices.CANCELLED and new_status == 'ATTENDED':
                    return Response(
                        {"error": "A cancelled session cannot be marked attended.", "code": lifecycle.SESSION_CANCELLED},
                        status=status.HTTP_409_CONFLICT
                    )
                if session.status == SessionStatusChoices.CANCELLED and session.started_at is not None:
                    return Response(
                        {
                            "error": "This session was started by its tutor before it was cancelled, so it cannot be put back on the schedule.",
                            "code": lifecycle.SESSION_STARTED,
                        },
                        status=status.HTTP_409_CONFLICT
                    )

        # Staff rating updates get the same 1-5 gate the student path has.
        if 'rating' in data:
            rating_val = data.get("rating")
            if isinstance(rating_val, bool) or not isinstance(rating_val, int) or not (1 <= rating_val <= 5):
                return Response(
                    {"error": "A rating between 1 and 5 is required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Resource links are stored normalised (stripped, blank -> null) so the
        # derived content state and the ?content= filter see one "empty".
        link_updates = {}
        for field in ('recording_link', 'notes_link', 'homework_link'):
            if field in data:
                try:
                    link_updates[field] = normalize_link(data[field])
                except ValueError as exc:
                    return Response({"error": f"{field} {exc}"}, status=status.HTTP_400_BAD_REQUEST)

        # The assignment behind a submitted or scored homework is locked.
        if 'homework_link' in link_updates:
            try:
                assert_assignment_editable(session)
            except HomeworkStateError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)

        # Capture state before modifications. The tutor is recorded by display
        # name: `changes` is what the activity feed renders, and a raw UUID
        # there is unreadable. The ids go into `context` below instead.
        before_tutor_id = str(session.tutor.id) if session.tutor else None
        before_state = {
            "status": session.status,
            "title": session.title,
            "tutor": staff_display_name(session.tutor),
            "start_time": session.start_time.isoformat(),
            "end_time": session.end_time.isoformat(),
            "recording_link": session.recording_link,
            "notes_link": session.notes_link,
            "homework_link": session.homework_link,
            "rating": session.rating,
            "cancellation_reason": session.cancellation_reason
        }

        # Resolve end_time math if start_time and duration_hours are specified together
        start_time_str = data.get("start_time")
        duration = data.get("duration_hours")
        new_start_time = None
        new_end_time = None

        if start_time_str and duration is not None:
            if duration not in ALLOWED_DURATIONS:
                return Response(
                    {"error": "duration_hours must be 0.5, 1, 1.5, or 2"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            new_start_time = parse_iso_datetime(start_time_str)
            if not new_start_time:
                return Response(
                    {"error": "start_time is not a valid date"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            new_end_time = new_start_time + timedelta(hours=duration)
            # The time and length a class was booked for are what it counts
            # as once taught (Session.duration_hours): fixed from its tutor's
            # Start, and for good once it is attended.
            if session.status == SessionStatusChoices.ATTENDED:
                return Response(
                    {"error": "An attended session keeps the time it was booked for; it cannot be rescheduled.",
                     "code": lifecycle.SESSION_ATTENDED},
                    status=status.HTTP_409_CONFLICT
                )
            if session.started_at is not None:
                return Response(
                    {"error": "This session has been started by its tutor, so it can no longer be rescheduled.",
                     "code": lifecycle.SESSION_STARTED},
                    status=status.HTTP_409_CONFLICT
                )

        # Attended means the class took place: never before its scheduled end,
        # and never together with a move of that end.
        if new_status == 'ATTENDED' and session.status != SessionStatusChoices.ATTENDED:
            if new_start_time:
                return Response(
                    {"error": "Reschedule a session and mark it attended separately."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if timezone.now() < session.end_time:
                return Response(
                    {"error": "This class has not ended yet. It can be marked attended once it ends.",
                     "code": lifecycle.CLASS_NOT_ENDED, "ends_at": session.end_time.isoformat()},
                    status=status.HTTP_409_CONFLICT
                )

        # A tutor change is resolved before the conflict check so the check
        # runs against the tutor the session will actually have, not the one
        # it had. Only a real change (different id) triggers the check.
        new_tutor = session.tutor
        tutor_changed = False
        if 'tutor' in data:
            # The tutor on an attended or cancelled session is a historical
            # attribution snapshot: the student-level reassignment flows
            # (students.StudentReassignView, accounts.StaffReassignView) hand
            # over only classes still to come that nobody started
            # (sessions.services.transferable_sessions) and leave history
            # untouched, and the per-session field follows the same rule:
            # judged on the status the session has now, then -- for a real
            # change -- refused once its tutor started it or its time is over.
            if session.status != SessionStatusChoices.SCHEDULED:
                return Response(
                    {"error": "Tutor can only be changed for scheduled sessions."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            tutor_val = data.get("tutor")
            if tutor_val is None:
                new_tutor = None
            else:
                try:
                    new_tutor = User.objects.get(id=tutor_val)
                except (User.DoesNotExist, ValueError, ValidationError):
                    return Response(
                        {"error": f"Tutor with ID '{tutor_val}' not found"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            tutor_changed = (new_tutor.id if new_tutor else None) != session.tutor_id
            if tutor_changed and session.started_at is not None:
                return Response(
                    {"error": "This session has been started by its tutor, so its tutor can no longer change.",
                     "code": lifecycle.SESSION_STARTED},
                    status=status.HTTP_409_CONFLICT
                )
            if tutor_changed and (new_end_time or session.end_time) <= timezone.now():
                return Response(
                    {"error": "This session's time has passed; it keeps the tutor it was scheduled with.",
                     "code": lifecycle.SESSION_ENDED},
                    status=status.HTTP_409_CONFLICT
                )
            # A class is handed only to someone who can teach it: an active
            # tutor (decision D5), the rule the student-level reassignment
            # already applies.
            if tutor_changed and new_tutor and not (
                new_tutor.role == 'TUTOR' and new_tutor.is_active and new_tutor.deactivated_at is None
            ):
                return Response(
                    {"error": "Selected tutor is not an active tutor."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # The window the session will occupy after this update.
        effective_start = new_start_time or session.start_time
        effective_end = new_end_time or session.end_time
        # A cancelled or attended class put back to SCHEDULED takes its time
        # again, so it is checked like a new one.
        will_be_scheduled = (new_status or session.status) == SessionStatusChoices.SCHEDULED
        reinstating = will_be_scheduled and session.status != SessionStatusChoices.SCHEDULED
        needs_conflict_check = bool(new_start_time) or tutor_changed or reinstating
        # Only a scheduled class holds its tutor's time.
        holds_tutor = will_be_scheduled and new_tutor is not None

        # Apply Updates
        allowed_fields = [
            'status', 'title', 'tutor', 'recording_link', 'notes_link',
            'homework_link', 'rating', 'cancellation_reason'
        ]

        with transaction.atomic():
            # Scheduling conflicts (same student OR same tutor) are checked
            # under the same lock the create path takes, so a reschedule or a
            # tutor swap cannot race a concurrent booking.
            if needs_conflict_check:
                lock_scheduling(session.student_id, new_tutor.id if new_tutor else None)
            # The row itself, read again under its lock (after the scheduling
            # locks, the order every class write takes them in): a Start or a
            # tutor's completion committed since the checks above would make
            # them stale, so the edit is refused rather than applied over it.
            current = (
                Session.objects.select_for_update(of=('self',))
                .only('status', 'started_at', 'completed_at', 'tutor', 'start_time', 'end_time')
                .get(pk=session.pk)
            )
            guarded = ('status', 'started_at', 'completed_at', 'tutor_id', 'start_time', 'end_time')
            if any(getattr(current, field) != getattr(session, field) for field in guarded):
                return Response(
                    {"error": "This session changed while you were editing it. Reload and try again.",
                     "code": lifecycle.SESSION_CHANGED},
                    status=status.HTTP_409_CONFLICT
                )
            if needs_conflict_check:
                # A new tutor was checked above; the one the class keeps must be active too (decision D5).
                if holds_tutor and not is_assignable_tutor(new_tutor):
                    return Response(inactive_tutor_response_data(), status=status.HTTP_400_BAD_REQUEST)
                conflict = find_conflict(
                    session.student, new_tutor, effective_start, effective_end, exclude_id=session.id
                )
                if conflict:
                    return Response(
                        conflict_response_data(conflict, session.student, None, "This session"),
                        status=status.HTTP_409_CONFLICT
                    )
                # Tuition is one-to-one: nor over a Demo or Diagnostic booking the tutor teaches.
                if holds_tutor:
                    booking_conflict = find_booking_conflict(new_tutor, effective_start, effective_end)
                    if booking_conflict:
                        return Response(
                            booking_conflict_response_data(booking_conflict, new_tutor, session.student, None, "This session"),
                            status=status.HTTP_409_CONFLICT
                        )
            if new_start_time and new_end_time:
                exam_conflict = find_exam_conflict_for_session(session.student, new_start_time, new_end_time)
                if exam_conflict:
                    return Response(
                        {"error": f"Time conflict with the exam \"{exam_conflict.chapter_name}\". Choose a different time."},
                        status=status.HTTP_409_CONFLICT
                    )

            # Only the columns this request writes are saved: the start and the
            # completion belong to the tutor's own writes (sessions.lifecycle).
            written = ['updated_at']
            if new_start_time and new_end_time:
                session.start_time = new_start_time
                session.end_time = new_end_time
                written += ['start_time', 'end_time']

            for field in allowed_fields:
                if field in data:
                    val = data[field]
                    written.append(field)
                    if field == 'status':
                        session.status = new_status
                    elif field == 'tutor':
                        session.tutor = new_tutor
                    elif field == 'title' and val:
                        session.title = normalize_title(val)
                    elif field in link_updates:
                        setattr(session, field, link_updates[field])
                    else:
                        setattr(session, field, val)

            session.save(update_fields=written)
            if link_updates:
                drop_stale_files(session, link_updates.keys())

        # An attended session with homework content gets its Homework row (the
        # lifecycle the /homework page and Learn operate on). One row per
        # session; a later change never creates a second one.
        if 'homework_link' in link_updates or new_status == 'ATTENDED':
            sync_homework_for_session(
                session, request.user, request,
                source='mark_attended' if new_status == 'ATTENDED' else 'links',
            )

        # Audit Logging
        action = None
        if new_status == 'ATTENDED':
            action = 'session.mark_attended'
        elif new_status == 'CANCELLED':
            action = 'session.cancel'
        elif start_time_str:
            action = 'session.reschedule'
        elif any(f in data for f in ('recording_link', 'notes_link', 'homework_link')):
            action = 'session.update_links'
        elif 'rating' in data:
            action = 'session.rate'
        elif 'title' in data or 'tutor' in data:
            action = 'session.update'

        changes = {}
        for key in ['status', 'title', 'tutor', 'start_time', 'end_time', 'recording_link', 'notes_link', 'homework_link', 'rating']:
            old_val = before_state.get(key)
            if key == 'start_time' or key == 'end_time':
                new_val = getattr(session, key).isoformat()
            elif key == 'tutor':
                new_val = staff_display_name(session.tutor)
            else:
                new_val = getattr(session, key)

            if old_val != new_val:
                changes[key] = {"old": old_val, "new": new_val}

        if action and changes:
            context = {}
            if new_status == 'CANCELLED' and session.cancellation_reason:
                context['reason'] = session.cancellation_reason
            if 'tutor' in changes:
                context['old_tutor_id'] = before_tutor_id
                context['new_tutor_id'] = str(session.tutor.id) if session.tutor else None
            
            log_activity(
                action=action,
                entity_type='session',
                entity_id=str(session.id),
                entity_label=before_state['title'],
                student=session.student,
                changes=changes,
                context=context,
                request=request
            )

        serializer = SessionSerializer(session)
        return Response({"success": True, "session": serializer.data}, status=status.HTTP_200_OK)

    def _tutor_update_notes(self, request, session, data):
        """
        The tutor's post-session responsibility: the notes link of a session
        assigned to them, which completes it (sessions.lifecycle). The request
        may carry nothing but `id` and `notes_link`; never on a cancelled
        class. The first notes after the class's scheduled end complete it --
        status ATTENDED, completed_at and completed_by -- whether or not anyone
        started it; before the end they are refused (CLASS_NOT_ENDED), and
        later notes are edits that never complete it again. Logged as
        `session.update_links` (the same entry a mentor's link edit produces)
        and, for the completion, `session.complete`.
        """
        # Whose class it is comes first (checked again under the row's lock below).
        if session.tutor_id is None or session.tutor_id != request.user.id:
            return Response(
                {"error": "You can only add notes to the sessions assigned to you.", "code": lifecycle.NOT_ASSIGNED},
                status=status.HTTP_403_FORBIDDEN
            )
        extra = set(data.keys()) - {'id', 'notes_link'}
        if extra:
            return Response(
                {"error": "Forbidden", "message": "Tutors can only update the notes link."},
                status=status.HTTP_403_FORBIDDEN
            )
        if 'notes_link' not in data:
            return Response({"error": "notes_link is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            notes_link = normalize_link(data.get("notes_link"))
        except ValueError as exc:
            return Response({"error": f"notes_link {exc}"}, status=status.HTTP_400_BAD_REQUEST)
        if not notes_link:
            return Response({"error": "A notes link is required."}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        try:
            with transaction.atomic():
                session, completing = lifecycle.tutor_notes_target(
                    session, request.user, now, "Notes cannot be added to a cancelled session."
                )
                before_notes = session.notes_link
                before_status = session.status
                session.notes_link = notes_link
                fields = ['notes_link', 'updated_at']
                if completing:
                    fields += lifecycle.mark_completed(session, request.user, now)
                session.save(update_fields=fields)
                drop_stale_files(session, ['notes_link'])
        except lifecycle.SessionStateError as exc:
            return Response(exc.response_data(), status=exc.status)

        if before_notes != notes_link:
            log_activity(
                action='session.update_links',
                entity_type='session',
                entity_id=str(session.id),
                entity_label=session.title,
                student=session.student,
                changes={"notes_link": {"old": before_notes, "new": notes_link}},
                request=request,
            )
        if completing:
            # Attended now: its homework row follows, as for a mentor's Mark Attended.
            sync_homework_for_session(session, request.user, request, source='tutor_completion')
            lifecycle.log_completion(session, before_status, request)

        return Response(
            {"success": True, "completed": completing, "session": SessionSerializer(session).data},
            status=status.HTTP_200_OK
        )


class SessionStartView(APIView):
    """
    POST /api/sessions/<session_id>/start/

    Start Session: whoever runs the class -- its assigned tutor, the student's
    mentor or an administrator -- records that it has started, from 5 minutes
    before its scheduled start until its scheduled end, by the server's clock
    (sessions.lifecycle.start_session). Repeating it, by anyone, changes
    nothing (``changed`` false) and logs nothing more. A start is for meeting
    access and activity tracking only: it never completes the class and is
    never needed for that -- only its tutor's own notes are. Reached with
    accounts.edit_session_notes (tutors: then only their assigned sessions) or
    accounts.manage_session (administrators and mentors: then only the
    students within their session scope).
    """
    permission_classes = [IsAuthenticated, HasAnyAppPermission('accounts.edit_session_notes', 'accounts.manage_session')]

    def post(self, request, session_id, *args, **kwargs):
        try:
            with transaction.atomic():
                session, changed = lifecycle.start_session(Session(pk=session_id), request.user, request=request)
        except Session.DoesNotExist:
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)
        except lifecycle.SessionStateError as exc:
            return Response(exc.response_data(), status=exc.status)
        if changed:
            lifecycle.log_start(session, request)
        return Response(
            {"success": True, "changed": changed, "session": SessionSerializer(session).data},
            status=status.HTTP_200_OK
        )


class SessionFileUploadView(APIView):
    """
    POST /api/sessions/<session_id>/files/<field>/  (multipart, one `file`)

    Attach an uploaded PDF / image / video as the session's notes, recording
    or homework. The bytes go to MEDIA_ROOT and the field's link column is
    set to the download view's URL -- so from then on the row is treated
    exactly as if that URL had been pasted (completion, filters, "Open").
    Who may upload to a field mirrors who may set its link through PUT:
    manage_session -> any field on sessions within the caller's session scope,
    edit_session_notes alone -> notes on the sessions assigned to them, which
    complete the class exactly as notes through PUT do (sessions.lifecycle).
    Replaces a previous upload for the same field.
    """
    permission_classes = [IsAuthenticated, HasAnyAppPermission('accounts.manage_session', 'accounts.edit_session_notes')]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, session_id, field, *args, **kwargs):
        if field not in SessionContentField.values:
            return Response({"error": "Unknown content field"}, status=status.HTTP_404_NOT_FOUND)
        try:
            session = Session.objects.select_related('student').get(id=session_id)
        except Session.DoesNotExist:
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

        tutor_notes = not has_app_permission(request.user, 'accounts.manage_session', request)
        if tutor_notes:
            if field != SessionContentField.NOTES:
                return Response(
                    {"error": "Forbidden", "message": "Tutors can only upload notes."},
                    status=status.HTTP_403_FORBIDDEN
                )
            if session.tutor_id is None or session.tutor_id != request.user.id:
                return Response(
                    {"error": "You can only add notes to the sessions assigned to you.", "code": lifecycle.NOT_ASSIGNED},
                    status=status.HTTP_403_FORBIDDEN
                )
        elif not reaches('sessions', request.user, session.student, request):
            return Response(
                {"error": "Forbidden", "message": "You can only edit sessions for your allocated students."},
                status=status.HTTP_403_FORBIDDEN
            )

        if session.status == SessionStatusChoices.CANCELLED:
            return Response(
                {"error": "Content cannot be attached to a cancelled session."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if field == SessionContentField.HOMEWORK:
            try:
                assert_assignment_editable(session)
            except HomeworkStateError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
        # A tutor's notes complete the class, so until it is completed they
        # wait for its scheduled end -- refused before any byte is stored.
        if tutor_notes and lifecycle.completes_on_notes(session) and timezone.now() < session.end_time:
            return Response(
                {"error": "This class has not ended yet. Submit your notes once it ends to complete it.",
                 "code": lifecycle.CLASS_NOT_ENDED, "ends_at": session.end_time.isoformat()},
                status=status.HTTP_409_CONFLICT
            )

        upload = request.FILES.get('file')
        if upload is None:
            return Response({"error": "A file is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            kind, content_type, extension = validate_content_upload(upload)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        link_field = f"{field}_link"
        now = timezone.now()
        completing = False

        try:
            with transaction.atomic():
                # The row again, under its lock: a tutor's checks are made once
                # more against what it is now (sessions.lifecycle).
                if tutor_notes:
                    session, completing = lifecycle.tutor_notes_target(
                        session, request.user, now, "Content cannot be attached to a cancelled session."
                    )
                else:
                    session = lifecycle.locked(session)
                before_link = getattr(session, link_field)
                before_status = session.status
                session_file = self._store(request, session, field, upload, content_type, extension)
                new_link = request.build_absolute_uri(session_file.link_path())
                setattr(session, link_field, new_link)
                fields = [link_field, 'updated_at']
                if completing:
                    fields += lifecycle.mark_completed(session, request.user, now)
                session.save(update_fields=fields)
        except lifecycle.SessionStateError as exc:
            return Response(exc.response_data(), status=exc.status)

        if field == SessionContentField.HOMEWORK:
            sync_homework_for_session(session, request.user, request, source='upload')

        log_activity(
            action='session.update_links',
            entity_type='session',
            entity_id=str(session.id),
            entity_label=session.title,
            student=session.student,
            changes={link_field: {"old": before_link, "new": new_link}},
            context={
                "uploaded_file": session_file.file_name,
                "content_type": content_type,
                "size_bytes": upload.size,
            },
            request=request,
        )
        if completing:
            sync_homework_for_session(session, request.user, request, source='tutor_completion')
            lifecycle.log_completion(session, before_status, request)

        file_data = SessionFileSerializer(session_file).data
        file_data['url'] = new_link
        return Response(
            {"success": True, "completed": completing, "session": SessionSerializer(session).data, "file": file_data},
            status=status.HTTP_200_OK
        )

    @staticmethod
    def _store(request, session, field, upload, content_type, extension):
        """Save ``upload`` as ``session``'s one file for ``field``; the previous one (and its bytes) goes away."""
        for old in list(session.files.filter(field=field)):
            old.delete()
        session_file = SessionFile(
            session=session,
            field=field,
            file_name=os.path.basename(upload.name)[:255] or f"{field}{extension}",
            content_type=content_type,
            size_bytes=upload.size,
            extension=extension,
            uploaded_by=request.user,
        )
        session_file.file.save(f"{session_file.id}{extension}", upload, save=False)
        session_file.save()
        return session_file


_RANGE_RE = re.compile(r'^bytes=(\d*)-(\d*)$')
_STREAM_CHUNK = 64 * 1024


class SessionFileDownloadView(APIView):
    """
    GET /api/sessions/files/<file_id>/

    Streams an uploaded file inline to anyone allowed to see the session it
    belongs to -- the same scoping the sessions list applies, and the
    student's own account. Open to every signed-in account on purpose: the
    scope decides, and a refusal reads "no access to this file". Honours single
    byte-range requests so browsers can seek inside recordings.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, file_id, *args, **kwargs):
        try:
            session_file = SessionFile.objects.select_related('session', 'session__student').get(id=file_id)
        except SessionFile.DoesNotExist:
            return Response({"error": "File not found"}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        if user.role == 'STUDENT':
            allowed = get_usable_students(user).filter(id=session_file.session.student_id).exists()
        else:
            allowed = scope_sessions(
                Session.objects.filter(id=session_file.session_id), user, request
            ).exists()
        if not allowed:
            return Response(
                {"error": "Forbidden", "message": "You do not have access to this file."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            size = session_file.file.size
        except (FileNotFoundError, OSError):
            return Response({"error": "File not found"}, status=status.HTTP_404_NOT_FOUND)

        response = self._ranged_response(request, session_file, size)
        response['Accept-Ranges'] = 'bytes'
        response['Content-Disposition'] = f'inline; filename="{self._ascii_name(session_file.file_name)}"'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, max-age=0'
        return response

    @staticmethod
    def _ascii_name(name):
        cleaned = ''.join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else '_' for ch in name)
        return cleaned or 'file'

    @staticmethod
    def _ranged_response(request, session_file, size):
        match = _RANGE_RE.match(request.META.get('HTTP_RANGE', '') or '')
        if not match:
            handle = session_file.file.open('rb')
            response = FileResponse(handle, content_type=session_file.content_type)
            response['Content-Length'] = str(size)
            return response

        first, last = match.groups()
        if first == '' and last == '':
            start, end = 0, size - 1
        elif first == '':
            # Suffix range: the last N bytes.
            start, end = max(0, size - int(last)), size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        if size == 0 or start >= size or start > end:
            response = HttpResponse(status=416)
            response['Content-Range'] = f'bytes */{size}'
            return response

        handle = session_file.file.open('rb')
        handle.seek(start)
        length = end - start + 1

        def stream():
            try:
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(_STREAM_CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
            finally:
                handle.close()

        response = StreamingHttpResponse(stream(), status=206, content_type=session_file.content_type)
        response['Content-Range'] = f'bytes {start}-{end}/{size}'
        response['Content-Length'] = str(length)
        return response


class CancelSeriesView(APIView):
    """
    POST: Cancel a scheduled class within a series, shifting/renumbering subsequent classes,
    and appending a make-up class to the end of the series (accounts.cancel_session).
    """
    permission_classes = [IsAuthenticated, HasAnyAppPermission(*SESSION_PERMISSIONS)]

    def post(self, request, *args, **kwargs):
        data = request.data
        session_id = data.get("session_id")
        cancellation_reason = (data.get("cancellation_reason") or "").strip()
        new_last_start_time_str = data.get("new_last_start_time")
        new_last_duration = data.get("new_last_duration_hours")

        if not session_id:
            return Response({"error": "session_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not cancellation_reason:
            return Response({"error": "A cancellation reason is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_session = Session.objects.get(id=session_id)
        except Session.DoesNotExist:
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

        if not has_app_permission(request.user, 'accounts.cancel_session', request):
            return Response(
                {"error": "Forbidden", "message": "Tutors cannot cancel sessions."},
                status=status.HTTP_403_FORBIDDEN
            )
        if not reaches('sessions', request.user, target_session.student, request):
            return Response(
                {"error": "Forbidden", "message": "You can only cancel sessions for your allocated students."},
                status=status.HTTP_403_FORBIDDEN
            )

        if target_session.status != SessionStatusChoices.SCHEDULED:
            return Response({"error": "Only scheduled sessions can be cancelled"}, status=status.HTTP_400_BAD_REQUEST)

        student = target_session.student

        # Helper to log final cancellation audit trail
        def log_cancel_operation(renumbered_count, new_session_id):
            changes = {"status": {"old": "scheduled", "new": "cancelled"}}
            context = {
                "reason": cancellation_reason,
                "renumbered_count": renumbered_count,
                "new_session_id": str(new_session_id) if new_session_id else None,
                "series_id": str(target_session.series_id) if target_session.series_id else None
            }
            log_activity(
                action='session.cancel_series' if target_session.series_id else 'session.cancel',
                entity_type='session',
                entity_id=str(target_session.id),
                entity_label=target_session.title,
                student=student,
                changes=changes,
                context=context,
                request=request
            )

        # Scenario A: No series_id or no class number. Fall back to simple cancellation.
        if not target_session.series_id or target_session.class_number is None:
            with transaction.atomic():
                target_session.status = SessionStatusChoices.CANCELLED
                target_session.cancellation_reason = cancellation_reason
                target_session.save()
            
            log_cancel_operation(0, None)
            return Response({"success": True, "renumberedCount": 0, "newSession": None}, status=status.HTTP_200_OK)

        # Scenario B: Part of a series. Fetch subsequent scheduled classes.
        subsequent = Session.objects.filter(
            series_id=target_session.series_id,
            status=SessionStatusChoices.SCHEDULED,
            class_number__gt=target_session.class_number
        ).order_by('class_number')

        if not subsequent.exists():
            with transaction.atomic():
                target_session.status = SessionStatusChoices.CANCELLED
                target_session.cancellation_reason = cancellation_reason
                target_session.save()

            log_cancel_operation(0, None)
            return Response({"success": True, "renumberedCount": 0, "newSession": None}, status=status.HTTP_200_OK)

        # Validate make-up class inputs (since there is a shift, makeup is required)
        if not new_last_start_time_str:
            return Response(
                {"error": "new_last_start_time is required when renumbering a series"},
                status=status.HTTP_400_BAD_REQUEST
            )
        new_last_start_time = parse_iso_datetime(new_last_start_time_str)
        if not new_last_start_time:
            return Response(
                {"error": "new_last_start_time is not a valid date"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not isinstance(new_last_duration, (int, float)) or new_last_duration not in ALLOWED_DURATIONS:
            return Response(
                {"error": "new_last_duration_hours must be 0.5, 1, 1.5, or 2"},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_last_end_time = new_last_start_time + timedelta(hours=new_last_duration)
        # The make-up class is taught by the student's tutor: an active one (decision D5).
        if student.tutor and not is_assignable_tutor(student.tutor):
            return Response(inactive_tutor_response_data("The make-up class"), status=status.HTTP_400_BAD_REQUEST)

        # Conflict check, shifting, renumbering and creation share one
        # transaction and the scheduling lock (see lock_scheduling).
        with transaction.atomic():
            lock_scheduling(student.id, student.tutor_id)
            # The class being cancelled is excluded: the slot it frees is
            # exactly where a make-up class may legitimately be placed.
            conflict = find_conflict(
                student, student.tutor, new_last_start_time, new_last_end_time,
                exclude_id=target_session.id,
            )
            if conflict:
                return Response(
                    conflict_response_data(conflict, student, None, "The make-up class"),
                    status=status.HTTP_409_CONFLICT
                )
            # Tuition is one-to-one: nor over a Demo or Diagnostic booking the tutor teaches.
            booking_conflict = (
                find_booking_conflict(student.tutor, new_last_start_time, new_last_end_time) if student.tutor else None
            )
            if booking_conflict:
                return Response(
                    booking_conflict_response_data(booking_conflict, student.tutor, student, None, "The make-up class"),
                    status=status.HTTP_409_CONFLICT
                )
            exam_conflict = find_exam_conflict_for_session(student, new_last_start_time, new_last_end_time)
            if exam_conflict:
                return Response(
                    {"error": f"Make-up class conflicts with the exam \"{exam_conflict.chapter_name}\". Choose a different time."},
                    status=status.HTTP_409_CONFLICT
                )

            # 1. Cancel target session
            target_session.status = SessionStatusChoices.CANCELLED
            target_session.cancellation_reason = cancellation_reason
            target_session.save()

            # 2. Shift subsequent classes: class_number - 1, and update titles
            max_original_class_num = subsequent.last().class_number
            for s in subsequent:
                old_num = s.class_number
                new_num = old_num - 1
                
                # Replace class number suffix: e.g. "Title - Class 3" -> "Title - Class 2"
                title_base = re.sub(r'\s*-\s*[Cc]lass\s+\d+$', '', s.title)
                s.title = f"{title_base} - Class {new_num}"
                s.class_number = new_num
                s.save()

            # 3. Create the make-up session at the end of the series
            target_base_title = re.sub(r'\s*-\s*[Cc]lass\s+\d+$', '', target_session.title)
            new_session = Session.objects.create(
                student=student,
                tutor=student.tutor,
                series_id=target_session.series_id,
                class_number=max_original_class_num,
                title=f"{target_base_title} - Class {max_original_class_num}",
                start_time=new_last_start_time,
                end_time=new_last_end_time,
                status=SessionStatusChoices.SCHEDULED
            )

        log_cancel_operation(len(subsequent), new_session.id)

        # Format minimal response shape matching frontend expects
        return Response({
            "success": True,
            "renumberedCount": len(subsequent),
            "newSession": {
                "id": str(new_session.id),
                "title": new_session.title,
                "start_time": new_session.start_time.isoformat(),
                "end_time": new_session.end_time.isoformat(),
                "class_number": new_session.class_number
            }
        }, status=status.HTTP_200_OK)
