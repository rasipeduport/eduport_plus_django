import datetime
from django.contrib.auth import get_user_model
from django.utils import timezone
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
from core.permissions import IsStaffUser, IsStudentUser
from core.querysets import scope_students_by_role
from core.students import get_account_students, get_usable_students, resolve_selected_student
from core.pagination import paginate_queryset

User = get_user_model()

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
            "last_session": SessionSerializer(last_sess).data if last_sess else None
        }, status=status.HTTP_200_OK)


class StudentListView(APIView):
    """
    GET /api/students/ - List students
      - ADMIN/MENTOR: See all students.
      - TUTOR: See assigned students where status in ('ACTIVE', 'INACTIVE').
    PUT /api/students/ - Update student details (meet link, class quota, status)
      - ADMIN/MENTOR: Allowed.
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

        student.save()

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


