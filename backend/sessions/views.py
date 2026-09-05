import uuid
import logging
import re
from datetime import timedelta
from django.db import transaction
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from students.models import Student
from activity.utils import log_activity
from core.authentication import CSRFExemptSessionAuthentication
from core.permissions import IsStaffOrSelfStudent
from core.querysets import scope_sessions_by_role
from core.students import resolve_selected_student
from core.pagination import paginate_queryset
from .models import Session, SessionStatusChoices
from .serializers import SessionSerializer
from .services import (
    ALLOWED_DURATIONS,
    MAX_SERIES_ITEMS,
    normalize_title,
    parse_iso_datetime,
    calculate_credits_used,
    find_conflict,
)

logger = logging.getLogger(__name__)
User = get_user_model()


class SessionsView(APIView):
    """
    GET: List sessions.
    POST: Create one or more sessions.
    PUT: Update a single session.
    """
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsStaffOrSelfStudent]

    def get(self, request, *args, **kwargs):
        queryset = Session.objects.select_related('student', 'student__profile', 'tutor').order_by('-start_time')

        # If the requester is a student, restrict to their own sessions;
        # mentors/tutors are scoped to their allocated students.
        if request.user.role == 'STUDENT':
            student = resolve_selected_student(request)
            if not student:
                return Response({"sessions": []}, status=status.HTTP_200_OK)
            queryset = queryset.filter(student=student)
        else:
            queryset = scope_sessions_by_role(queryset, request.user)

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

        role = request.user.role
        if role == 'TUTOR':
            return Response(
                {"error": "Forbidden", "message": "Tutors cannot create sessions."},
                status=status.HTTP_403_FORBIDDEN
            )
        elif role == 'MENTOR' and student.mentor != request.user:
            return Response(
                {"error": "Forbidden", "message": "You can only manage sessions for your allocated students."},
                status=status.HTTP_403_FORBIDDEN
            )

        if not student.tutor:
            return Response(
                {"error": "This student has no tutor assigned. Assign a tutor before creating a session."},
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
            
            start_time_str = item.get("start_time")
            if not start_time_str:
                return Response(
                    {"error": f"{label}: start_time is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            start_time = parse_iso_datetime(start_time_str)
            if not start_time:
                return Response(
                    {"error": f"{label}: start_time is not a valid date"},
                    status=status.HTTP_400_BAD_REQUEST
                )

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

        # 3. Conflict Checks (overlap: same student OR same tutor)
        for i, v in enumerate(validated_items):
            label = f"Class {i + 1}" if is_series else "This session"
            conflict = find_conflict(student, student.tutor, v["start_time"], v["end_time"])
            if conflict:
                return Response(
                    {"error": f"{label} conflicts with \"{conflict.title}\". Choose a different time."},
                    status=status.HTTP_409_CONFLICT
                )

        # 4. Save sessions
        series_id = uuid.uuid4() if is_series else None
        created_sessions = []
        
        with transaction.atomic():
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

        role = request.user.role

        # Students may only rate their own (currently selected) student's sessions.
        # They cannot change status, links, tutor, or schedule.
        if role == 'STUDENT':
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

        # Tutors are read-only on sessions; only admins and mentors may edit.
        if role == 'TUTOR':
            return Response(
                {"error": "Forbidden", "message": "Tutors cannot edit sessions."},
                status=status.HTTP_403_FORBIDDEN
            )
        if role == 'MENTOR' and session.student.mentor != request.user:
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

        # Staff rating updates get the same 1-5 gate the student path has.
        if 'rating' in data:
            rating_val = data.get("rating")
            if isinstance(rating_val, bool) or not isinstance(rating_val, int) or not (1 <= rating_val <= 5):
                return Response(
                    {"error": "A rating between 1 and 5 is required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Capture state before modifications
        before_state = {
            "status": session.status,
            "title": session.title,
            "tutor": str(session.tutor.id) if session.tutor else None,
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

        # Check Scheduling Conflicts on Rescheduling (same student OR same tutor)
        if new_start_time and new_end_time:
            conflict = find_conflict(
                session.student, session.tutor, new_start_time, new_end_time, exclude_id=session.id
            )
            if conflict:
                return Response(
                    {"error": f"Time conflict with \"{conflict.title}\". Choose a different time."},
                    status=status.HTTP_409_CONFLICT
                )

        # Apply Updates
        allowed_fields = [
            'status', 'title', 'tutor', 'recording_link', 'notes_link',
            'homework_link', 'rating', 'cancellation_reason'
        ]
        
        with transaction.atomic():
            if new_start_time and new_end_time:
                session.start_time = new_start_time
                session.end_time = new_end_time

            for field in allowed_fields:
                if field in data:
                    val = data[field]
                    if field == 'status':
                        session.status = new_status
                    elif field == 'tutor':
                        if val is None:
                            session.tutor = None
                        else:
                            try:
                                session.tutor = User.objects.get(id=val)
                            except User.DoesNotExist:
                                return Response(
                                    {"error": f"Tutor with ID '{val}' not found"},
                                    status=status.HTTP_400_BAD_REQUEST
                                )
                    elif field == 'title' and val:
                        session.title = normalize_title(val)
                    else:
                        setattr(session, field, val)

            session.save()

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
                new_val = str(session.tutor.id) if session.tutor else None
            else:
                new_val = getattr(session, key)

            if old_val != new_val:
                changes[key] = {"old": old_val, "new": new_val}

        if action and changes:
            context = {}
            if new_status == 'CANCELLED' and session.cancellation_reason:
                context['reason'] = session.cancellation_reason
            
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

class CancelSeriesView(APIView):
    """
    POST: Cancel a scheduled class within a series, shifting/renumbering subsequent classes,
    and appending a make-up class to the end of the series.
    """
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsStaffOrSelfStudent]

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

        role = request.user.role
        # Tutors are read-only on sessions; only admins and mentors may cancel.
        if role == 'TUTOR':
            return Response(
                {"error": "Forbidden", "message": "Tutors cannot cancel sessions."},
                status=status.HTTP_403_FORBIDDEN
            )
        if role == 'MENTOR' and target_session.student.mentor != request.user:
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

        # Conflict check for the new make-up session (same student OR same tutor)
        new_last_end_time = new_last_start_time + timedelta(hours=new_last_duration)
        conflict = find_conflict(student, student.tutor, new_last_start_time, new_last_end_time)
        if conflict:
            return Response(
                {"error": f"Make-up class conflicts with \"{conflict.title}\". Choose a different time."},
                status=status.HTTP_409_CONFLICT
            )

        # Perform shifting, renumbering, and creation within a database transaction
        with transaction.atomic():
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
