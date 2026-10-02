import datetime
import uuid
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from students.models import Student
from invitations.models import Invitation, InvitationStatusChoices
from sessions.models import Session, SessionStatusChoices
from sessions.serializers import SessionSerializer
from activity.utils import log_activity
from core.authentication import CSRFExemptSessionAuthentication
from core.permissions import IsAdminUser, IsStaffUser, IsStudentUser
from core.querysets import scope_students_by_role
from core.students import get_account_students, get_usable_students, resolve_selected_student
from core.pagination import paginate_queryset
from core.timezones import is_valid_timezone

User = get_user_model()

# Free-text profile columns the Hub's "Edit Profile" sheet may change. The
# student_code (enrolment key + purge confirmation token) and the linked
# sign-in account are deliberately not in this list.
PROFILE_TEXT_FIELDS = (
    'full_name', 'mobile_number', 'country', 'state',
    'school_name', 'grade', 'syllabus', 'remarks_for_mentor',
)


def _parse_uuid(value, field):
    """
    ``(uuid, None)`` for a valid id, ``(None, None)`` for null/empty, or
    ``(None, 400-response)`` for garbage -- a malformed value must never reach
    a UUIDField filter, where it would raise instead of returning 400.
    """
    if value in (None, ''):
        return None, None
    try:
        return uuid.UUID(str(value)), None
    except (ValueError, TypeError, AttributeError):
        return None, Response(
            {"error": "INVALID_INPUT", "message": f"{field} must be a valid id."},
            status=status.HTTP_400_BAD_REQUEST
        )


def _staff_display(user):
    return (user.full_name or user.email) if user else None


class StaffDashboardStatsView(APIView):
    """
    GET /api/dashboard/stats/
    Returns the numbers of students, mentors, tutors, and pending invitations.
    Also returns sign-up history over the last 7 days and recent signups.
    Visible to: Admin, Mentor, Tutor
    """
    permission_classes = [IsStaffUser]

    def get(self, request, *args, **kwargs):
        # Filter students based on role allocation (mentors/tutors see only theirs)
        student_qs = scope_students_by_role(Student.objects.all(), request.user)

        # Base counts
        students_count = student_qs.count()
        mentors_count = User.objects.filter(role='MENTOR').count()
        tutors_count = User.objects.filter(role='TUTOR').count()
        pending_invites_count = Invitation.objects.filter(status=InvitationStatusChoices.PENDING).count()

        # Build last 7 days signup data (UTC days)
        now_utc = timezone.now()
        day_map = {}
        for i in range(6, -1, -1):
            d = now_utc - datetime.timedelta(days=i)
            day_num = str(int(d.strftime("%d")))
            key = f"{d.strftime('%b')} {day_num}"
            day_map[key] = 0

        since = now_utc - datetime.timedelta(days=6)
        since = since.replace(hour=0, minute=0, second=0, microsecond=0)
        
        signups = student_qs.filter(created_at__gte=since)
        for s in signups:
            created_utc = s.created_at.astimezone(datetime.timezone.utc)
            day_num = str(int(created_utc.strftime("%d")))
            key = f"{created_utc.strftime('%b')} {day_num}"
            if key in day_map:
                day_map[key] += 1

        signup_data = [{"day": day, "signups": count} for day, count in day_map.items()]

        # Recent 5 student signups
        recent = student_qs.select_related('profile').order_by('-created_at')[:5]
        recent_signups = [
            {
                "student_code": s.student_code,
                "full_name": s.full_name,
                "created_at": s.created_at.isoformat(),
                "avatar_url": s.profile.avatar_url if s.profile else None
            }
            for s in recent
        ]

        return Response({
            "students": students_count,
            "mentors": mentors_count,
            "tutors": tutors_count,
            "pending_invitations": pending_invites_count,
            "signup_data": signup_data,
            "recent_signups": recent_signups
        }, status=status.HTTP_200_OK)

class StudentDashboardView(APIView):
    """
    GET /api/student/dashboard/
    Returns the student's dashboard details including session summaries.
    Visible to: Student
    """
    permission_classes = [IsStudentUser]

    def get(self, request, *args, **kwargs):
        student = resolve_selected_student(request)
        if not student:
            # Distinguish "several usable students, none selected" (pick one)
            # from "every persona is expired" (access ended) from "no students
            # yet" (waiting room).
            if get_usable_students(request.user).exists():
                return Response(
                    {
                        "error": "STUDENT_NOT_SELECTED",
                        "message": "Please select which student you want to view."
                    },
                    status=status.HTTP_409_CONFLICT
                )
            if get_account_students(request.user).exists():
                return Response(
                    {
                        "error": "STUDENT_ACCESS_ENDED",
                        "message": "Your access to Eduport Plus has ended."
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            return Response(
                {
                    "error": "STUDENT_PROFILE_NOT_FOUND",
                    "message": "Your profile is waiting to be linked with student records."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        now = timezone.now()

        # Count of scheduled and attended sessions
        scheduled_count = Session.objects.filter(student=student, status=SessionStatusChoices.SCHEDULED).count()
        attended_count = Session.objects.filter(student=student, status=SessionStatusChoices.ATTENDED).count()

        # Next upcoming class (scheduled, start time in the future)
        next_sess = Session.objects.filter(
            student=student,
            status=SessionStatusChoices.SCHEDULED,
            start_time__gte=now
        ).order_by('start_time').first()

        # Last completed class (attended, sorted desc)
        last_sess = Session.objects.filter(
            student=student,
            status=SessionStatusChoices.ATTENDED
        ).order_by('-start_time').first()

        # Exams for the "Up next" / "Recent" slots (Learn compares them with
        # the next/last session client-side).
        from exams.models import Exam, ExamStatusChoices
        from exams.serializers import ExamSerializer
        next_exam = Exam.objects.filter(
            student=student, status=ExamStatusChoices.SCHEDULED, start_time__gte=now
        ).order_by('start_time').first()
        last_exam = Exam.objects.filter(
            student=student, status=ExamStatusChoices.ATTENDED
        ).order_by('-start_time').first()

        return Response({
            "student_name": student.full_name or request.user.full_name or "",
            "mentor": student.mentor.full_name if student.mentor else None,
            "mentor_email": student.mentor.email if student.mentor else None,
            "mentor_phone": student.mentor.mobile_number if student.mentor else None,
            "tutor": student.tutor.full_name if student.tutor else None,
            "quota": student.total_class_quota,
            "meet_link": student.meet_link or "",
            "scheduled_count": scheduled_count,
            "attended_count": attended_count,
            "next_session": SessionSerializer(next_sess).data if next_sess else None,
            "last_session": SessionSerializer(last_sess).data if last_sess else None,
            "next_exam": ExamSerializer(next_exam, context={'request': request}).data if next_exam else None,
            "last_exam": ExamSerializer(last_exam, context={'request': request}).data if last_exam else None,
        }, status=status.HTTP_200_OK)


class StudentListView(APIView):
    """
    GET /api/students/ - List students
      - ADMIN/MENTOR: See all students.
      - TUTOR: See assigned students where status in ('ACTIVE', 'INACTIVE').
    PUT /api/students/ - Update student details (meet link, class quota, status,
      and the profile fields behind the Hub's "Edit Profile" sheet)
      - ADMIN/MENTOR: Allowed (mentors only for their allocated students).
    """
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsStaffUser]

    def get(self, request, *args, **kwargs):
        role = request.user.role
        is_tutor = role == 'TUTOR'
        is_mentor = role == 'MENTOR'
        
        queryset = Student.objects.select_related('profile', 'mentor', 'tutor').order_by('student_code')
        if is_tutor:
            queryset = queryset.filter(tutor=request.user, status__in=['ACTIVE', 'INACTIVE'])
        elif is_mentor:
            queryset = queryset.filter(mentor=request.user)

        # Opt-in pagination: full list by default, sliced when ?page= is given.
        page_items, meta = paginate_queryset(request, queryset)
        source = queryset if page_items is None else page_items

        data = []
        for s in source:
            data.append({
                "id": str(s.id),
                "student_code": s.student_code,
                "full_name": s.full_name,
                "mobile_number": s.mobile_number or "",
                "country": s.country or "",
                "state": s.state or "",
                "school_name": s.school_name or "",
                "grade": s.grade or "",
                "syllabus": s.syllabus or "",
                "admission_date": s.admission_date.isoformat() if s.admission_date else None,
                "created_at": s.created_at.isoformat(),
                "meet_link": s.meet_link or "",
                "total_class_quota": s.total_class_quota,
                "remarks_for_mentor": s.remarks_for_mentor or "",
                "status": s.status.lower(),
                "status_note": s.status_note or "",
                # Raw value: the scheduling sheet tells "unset" (offer the IST
                # default, say it is unset) apart from an explicit choice.
                "timezone": s.timezone,
                "profile": {
                    "email": s.profile.email if s.profile else "",
                    "avatar_url": s.profile.avatar_url if s.profile else None
                } if s.profile else None,
                "mentor_profile": {
                    "id": str(s.mentor.id),
                    "full_name": s.mentor.full_name or "",
                    "email": s.mentor.email
                } if s.mentor else None,
                "tutor_profile": {
                    "id": str(s.tutor.id),
                    "full_name": s.tutor.full_name or "",
                    "email": s.tutor.email
                } if s.tutor else None,
            })

        if meta is not None:
            return Response({"results": data, **meta}, status=status.HTTP_200_OK)
        return Response(data, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        # Enforce Admin/Mentor permissions for modifications
        if not (request.user.role in ('ADMIN', 'MENTOR') or request.user.is_superuser):
            return Response(
                {"error": "FORBIDDEN", "message": "You do not have permission to update student details."},
                status=status.HTTP_403_FORBIDDEN
            )
            
        student_id = request.data.get("id")
        if not student_id:
            return Response(
                {"error": "INVALID_INPUT", "message": "student id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        student = Student.objects.filter(id=student_id).first()
        if not student:
            return Response(
                {"error": "NOT_FOUND", "message": "Student not found."},
                status=status.HTTP_404_NOT_FOUND
            )
            
        if request.user.role == 'MENTOR' and student.mentor != request.user:
            return Response(
                {"error": "FORBIDDEN", "message": "You can only update details for your allocated students."},
                status=status.HTTP_403_FORBIDDEN
            )
            
        # Capture before-state for activity logging
        before_meet_link = student.meet_link
        before_quota = student.total_class_quota
        before_status = student.status
        before_timezone = student.timezone

        # Update fields if present in request.data
        if "meet_link" in request.data:
            student.meet_link = request.data.get("meet_link")

        if "total_class_quota" in request.data:
            try:
                quota = int(request.data.get("total_class_quota"))
                student.total_class_quota = quota
            except (ValueError, TypeError):
                return Response(
                    {"error": "INVALID_INPUT", "message": "total_class_quota must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # IANA zone the student's sessions are scheduled in (the "New Session"
        # sheet writes it back when the mentor picks a different one). Checked
        # against the runtime's zone database, not an enum; blank/null clears.
        if "timezone" in request.data:
            raw_tz = request.data.get("timezone")
            if raw_tz in (None, ""):
                student.timezone = None
            elif isinstance(raw_tz, str) and is_valid_timezone(raw_tz.strip()):
                student.timezone = raw_tz.strip()
            else:
                return Response(
                    {"error": "INVALID_TIMEZONE", "message": "Unknown time zone."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        new_status = None
        if "status" in request.data:
            raw_status = request.data.get("status")
            new_status = raw_status.upper() if isinstance(raw_status, str) else None
            if new_status not in ('ACTIVE', 'INACTIVE', 'EXPIRED'):
                return Response(
                    {"error": "INVALID_STATUS", "message": "Invalid student status specified."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            student.status = new_status
            if new_status == 'ACTIVE':
                # Clear any prior note when the student is reactivated.
                student.status_note = None
            else:
                note_raw = request.data.get("status_note")
                note = note_raw.strip() if isinstance(note_raw, str) else ""
                if not note:
                    return Response(
                        {
                            "error": "STATUS_NOTE_REQUIRED",
                            "message": "A note is required when marking a student inactive or expired."
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                student.status_note = note

        # Profile details (Edit Profile). Only fields present in the payload
        # are touched; blank text clears the column (null), except the name,
        # which is required.
        profile_changes = {}
        for field in PROFILE_TEXT_FIELDS:
            if field not in request.data:
                continue
            raw = request.data.get(field)
            value = raw.strip() if isinstance(raw, str) else ("" if raw is None else str(raw).strip())
            if field == 'full_name':
                if not value:
                    return Response(
                        {"error": "INVALID_INPUT", "message": "Name cannot be empty."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                value = value or None
            old = getattr(student, field) or None
            if value != old:
                profile_changes[field] = {"old": old, "new": value}
                setattr(student, field, value)

        if "admission_date" in request.data:
            raw = request.data.get("admission_date")
            if raw in (None, ""):
                new_date = None
            else:
                try:
                    new_date = parse_date(str(raw))
                except ValueError:
                    new_date = None
                if new_date is None:
                    return Response(
                        {"error": "INVALID_INPUT", "message": "admission_date must be a date in YYYY-MM-DD format."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            if new_date != student.admission_date:
                profile_changes["admission_date"] = {
                    "old": student.admission_date.isoformat() if student.admission_date else None,
                    "new": new_date.isoformat() if new_date else None,
                }
                student.admission_date = new_date

        student.save()

        if profile_changes:
            log_activity(
                action='student.update_details',
                entity_type='student',
                entity_id=str(student.id),
                entity_label=student.full_name,
                student=student,
                changes=profile_changes,
                request=request,
            )

        # Activity logging (best-effort) — one entry per kind of change
        if "meet_link" in request.data and student.meet_link != before_meet_link:
            log_activity(
                action='student.update_meet_link',
                entity_type='student',
                entity_id=str(student.id),
                entity_label=student.full_name,
                student=student,
                changes={"meet_link": {"old": before_meet_link or "", "new": student.meet_link or ""}},
                request=request,
            )

        if "total_class_quota" in request.data and student.total_class_quota != before_quota:
            log_activity(
                action='student.update_quota',
                entity_type='student',
                entity_id=str(student.id),
                entity_label=student.full_name,
                student=student,
                changes={"total_class_quota": {"old": before_quota, "new": student.total_class_quota}},
                request=request,
            )

        if "timezone" in request.data and student.timezone != before_timezone:
            log_activity(
                action='student.update_timezone',
                entity_type='student',
                entity_id=str(student.id),
                entity_label=student.full_name,
                student=student,
                changes={"timezone": {"old": before_timezone, "new": student.timezone}},
                request=request,
            )

        if new_status and new_status != before_status:
            log_activity(
                action='student.update_status',
                entity_type='student',
                entity_id=str(student.id),
                entity_label=student.full_name,
                student=student,
                changes={
                    "status": {"old": before_status.lower(), "new": student.status.lower()},
                    "status_note": {"new": student.status_note or ""},
                },
                request=request,
            )

        return Response({
            "status": "updated",
            "message": "Student updated successfully."
        }, status=status.HTTP_200_OK)


class StudentReassignView(APIView):
    """
    POST /api/students/reassign/ — change ONE student's mentor and/or tutor.

    Admin-only, mirroring the Hub's reassign_student_staff RPC: the client
    always sends both desired final values (null = unassign). Completed and
    cancelled sessions keep their tutor snapshot for attribution; only open
    (SCHEDULED) sessions are handed over to the new tutor. Replacements must
    be assignable (right role, not deactivated) — the same rule the slim
    /api/mentors and /api/tutors dropdown lists apply. The bulk staff-exit
    handover is a different flow: accounts.StaffReassignView.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    authentication_classes = [CSRFExemptSessionAuthentication]

    def post(self, request, *args, **kwargs):
        student_id, err = _parse_uuid(request.data.get("id"), "id")
        if err:
            return err
        if not student_id:
            return Response(
                {"error": "INVALID_INPUT", "message": "student id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        new_mentor_id, err = _parse_uuid(request.data.get("mentor"), "mentor")
        if err:
            return err
        new_tutor_id, err = _parse_uuid(request.data.get("tutor"), "tutor")
        if err:
            return err

        sessions_repointed = 0
        exams_repointed = 0
        additional_exams_repointed = 0
        with transaction.atomic():
            # Row lock on the student serialises two admins reassigning at once.
            student = Student.objects.select_for_update().filter(id=student_id).first()
            if not student:
                return Response(
                    {"error": "NOT_FOUND", "message": "Student not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            old_mentor = student.mentor
            old_tutor = student.tutor
            mentor_changed = new_mentor_id != student.mentor_id
            tutor_changed = new_tutor_id != student.tutor_id
            if not mentor_changed and not tutor_changed:
                return Response({"success": True, "unchanged": True}, status=status.HTTP_200_OK)

            # Validate BOTH replacements before moving anything (one
            # transaction, no half-reassigned state). Locking the replacement
            # rows serialises this against a concurrent deactivation.
            new_mentor = None
            if mentor_changed and new_mentor_id:
                new_mentor = User.objects.select_for_update().filter(
                    pk=new_mentor_id, role='MENTOR',
                    deactivated_at__isnull=True, is_active=True
                ).first()
                if not new_mentor:
                    return Response(
                        {"error": "INVALID_MENTOR", "message": "Selected mentor is not an active mentor."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            new_tutor = None
            if tutor_changed and new_tutor_id:
                new_tutor = User.objects.select_for_update().filter(
                    pk=new_tutor_id, role='TUTOR',
                    deactivated_at__isnull=True, is_active=True
                ).first()
                if not new_tutor:
                    return Response(
                        {"error": "INVALID_TUTOR", "message": "Selected tutor is not an active tutor."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            update_fields = ['updated_at']
            if mentor_changed:
                # Open mentor work (scheduled chapter exams, assigned/submitted
                # additional exams) follows the new mentor; completed work keeps
                # its snapshot -- the Hub's reassign_student_staff RPC.
                from django.db.models import Q as _Q
                from exams.services import handover_open_exams
                exams_repointed, additional_exams_repointed = handover_open_exams(_Q(student=student), new_mentor)
                student.mentor = new_mentor
                update_fields.append('mentor')
            if tutor_changed:
                sessions_repointed = Session.objects.filter(
                    student=student, status=SessionStatusChoices.SCHEDULED
                ).update(tutor=new_tutor)
                student.tutor = new_tutor
                update_fields.append('tutor')
            student.save(update_fields=update_fields)

        # One audit entry per role that changed; display names in `changes`
        # (they outlive a later staff deletion), ids and counts in `context`.
        label = student.full_name or student.student_code
        if mentor_changed:
            log_activity(
                action='student.reassign_mentor',
                entity_type='student',
                entity_id=str(student.id),
                entity_label=label,
                student=student,
                changes={"mentor": {"old": _staff_display(old_mentor), "new": _staff_display(new_mentor)}},
                context={
                    "old_mentor_id": str(old_mentor.id) if old_mentor else None,
                    "new_mentor_id": str(new_mentor.id) if new_mentor else None,
                    "exams_repointed": exams_repointed,
                    "additional_exams_repointed": additional_exams_repointed,
                },
                request=request,
            )
        if tutor_changed:
            log_activity(
                action='student.reassign_tutor',
                entity_type='student',
                entity_id=str(student.id),
                entity_label=label,
                student=student,
                changes={"tutor": {"old": _staff_display(old_tutor), "new": _staff_display(new_tutor)}},
                context={
                    "old_tutor_id": str(old_tutor.id) if old_tutor else None,
                    "new_tutor_id": str(new_tutor.id) if new_tutor else None,
                    "sessions_repointed": sessions_repointed,
                },
                request=request,
            )

        return Response({
            "success": True,
            "result": {
                "old_mentor": str(old_mentor.id) if old_mentor else None,
                "new_mentor": str(student.mentor_id) if student.mentor_id else None,
                "old_tutor": str(old_tutor.id) if old_tutor else None,
                "new_tutor": str(student.tutor_id) if student.tutor_id else None,
                "sessions_repointed": sessions_repointed,
                "exams_repointed": exams_repointed,
                "additional_exams_repointed": additional_exams_repointed,
            }
        }, status=status.HTTP_200_OK)


class StudentDetailView(APIView):
    """
    DELETE /api/students/<id>/ — permanently remove a student created by
    mistake (the Hub's "Delete permanently").

    Admin-only and narrow on purpose: the caller must retype the student_code,
    and the request is refused (409) when the student has ANY history — today
    that means sessions, chapter exams and additional exams (extend for homework). For
    a real student who has left, the status flow (expired) is the right tool.
    The linked sign-in account is left untouched (a parent account may own
    other students). The append-only activity log takes a snapshot in the
    same transaction; its student FK carries no DB constraint, so the entry
    outlives the row.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    authentication_classes = [CSRFExemptSessionAuthentication]

    def delete(self, request, pk, *args, **kwargs):
        student = Student.objects.filter(pk=pk).first()
        if not student:
            return Response(
                {"error": "NOT_FOUND", "message": "Student not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        confirm_raw = request.data.get("confirm_code")
        confirm = confirm_raw.strip() if isinstance(confirm_raw, str) else ""
        if not confirm:
            return Response(
                {"error": "INVALID_INPUT", "message": "Confirmation is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if confirm != student.student_code:
            return Response(
                {"error": "CODE_MISMATCH", "message": "The student code you entered does not match."},
                status=status.HTTP_400_BAD_REQUEST
            )

        from exams.services import exam_history_exists
        if Session.objects.filter(student=student).exists() or exam_history_exists(student):
            return Response(
                {
                    "error": "HAS_HISTORY",
                    "message": 'This student has sessions or exams and cannot be permanently deleted. '
                               'Set their status to "expired" instead.'
                },
                status=status.HTTP_409_CONFLICT
            )

        with transaction.atomic():
            log_activity(
                action='student.purge',
                entity_type='student',
                entity_id=str(student.id),
                entity_label=student.full_name or student.student_code,
                student=student,
                changes={"student": {"old": f"{student.full_name} ({student.student_code})", "new": None}},
                context={
                    "student_code": student.student_code,
                    "status": student.status.lower(),
                    "mentor": str(student.mentor_id) if student.mentor_id else None,
                    "tutor": str(student.tutor_id) if student.tutor_id else None,
                },
                request=request,
            )
            student.delete()

        return Response({"success": True}, status=status.HTTP_200_OK)
