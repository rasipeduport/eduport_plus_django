import logging
import uuid
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.contrib.auth import login, logout, get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from students.models import Student
from activity.models import ActivityLog
from activity.utils import log_activity
from core.authentication import CSRFExemptSessionAuthentication
from core.permissions import IsAdminUser, IsStaffUser
from core.students import (
    get_account_students,
    get_usable_students,
    resolve_selected_student,
    EP_STUDENT_COOKIE,
)
from .serializers import UserSerializer, StudentSerializer
from .services import UserProvisioningService

logger = logging.getLogger(__name__)
User = get_user_model()

# One year, in seconds; the selected-student cookie is a long-lived preference.
EP_STUDENT_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def build_student_payload(request, user):
    """
    Build the student portion of an auth response for a STUDENT account:
    the full list of children, the currently selected child (resolved from the
    ``ep-student-id`` cookie), and that child's id.
    """
    students = list(get_account_students(user))
    selected = resolve_selected_student(request)
    return {
        "student_profiles": StudentSerializer(students, many=True).data,
        "student_profile": StudentSerializer(selected).data if selected else None,
        "selected_student_id": str(selected.id) if selected else None,
    }

def verify_google_token(token: str) -> dict:
    """
    Verifies Google ID Token. If ALLOW_MOCK_AUTH is True and token starts with "mock:",
    allows mock auth of format "mock:email@example.com:Name:Avatar_URL" for dev/test convenience.
    """
    client_id = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
    allow_mock = settings.ALLOW_MOCK_AUTH
    
    if allow_mock and token.startswith("mock:"):
        parts = token.split(":", 3)
        email = parts[1]
        name = parts[2] if len(parts) > 2 else email.split("@")[0]
        picture = parts[3] if len(parts) > 3 else "https://example.com/avatar.png"
        return {"email": email, "name": name, "picture": picture}
        
    if not client_id:
        raise ValueError("GOOGLE_OAUTH_CLIENT_ID settings parameter is not configured.")

    try:
        id_info = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            client_id,
            clock_skew_in_seconds=10
        )
        return {
            "email": id_info.get("email"),
            "name": id_info.get("name"),
            "picture": id_info.get("picture")
        }
    except Exception as e:
        logger.error(f"Google ID Token verification exception: {e}")
        raise ValueError(f"Google token verification failed: {str(e)}")

class GoogleLoginView(APIView):
    """
    Accepts Google OAuth ID Token (credential JWT), validates against Google servers,
    provisions the user if they are whitelisted via an Invitation, and logs them in.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(ensure_csrf_cookie)  # Sets CSRF cookie on login call
    def post(self, request, *args, **kwargs):
        token = request.data.get("credential")
        if not token:
            return Response(
                {"error": "INVALID_INPUT", "message": "Google credential token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            google_claims = verify_google_token(token)
        except ValueError as e:
            return Response(
                {"error": "INVALID_CREDENTIAL", "message": str(e)},
                status=status.HTTP_401_UNAUTHORIZED
            )

        email = google_claims["email"]
        name = google_claims["name"]
        picture = google_claims["picture"]

        # Check if the email exists in the Invitations table (whitelisted_emails)
        from invitations.models import Invitation
        if not Invitation.objects.filter(email=email).exists():
            return Response(
                {
                    "error": "ACCESS_RESTRICTED",
                    "message": "Access Restricted\n\nYour email is not authorized to access EduPlus.\n\nPlease contact your administrator for access."
                },
                status=status.HTTP_403_FORBIDDEN
            )



        # Search for existing user
        user = User.objects.filter(email=email).first()
        is_new_user = False

        if not user:
            # First login: Onboard user using UserProvisioningService
            try:
                user = UserProvisioningService.provision_user(
                    email=email,
                    google_name=name,
                    google_avatar=picture
                )
                is_new_user = True
            except ValueError as e:
                # Returned if no pending invitation exists, or if student code is missing
                return Response(
                    {"error": "INVITATION_REQUIRED", "message": str(e)},
                    status=status.HTTP_403_FORBIDDEN
                )
            except Exception as e:
                logger.error(f"Error provisioning user {email}: {e}")
                return Response(
                    {"error": "PROVISIONING_FAILED", "message": "Failed to provision user profile."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        # Handle active check
        if not user.is_active:
            return Response(
                {"error": "USER_DISABLED", "message": "This account is inactive. Please contact admin."},
                status=status.HTTP_403_FORBIDDEN
            )

        # For existing student accounts, attach any children invited since their
        # last login (new students provisioned above already have theirs).
        if not is_new_user and user.role == 'STUDENT':
            try:
                UserProvisioningService.attach_pending_students(user, name)
            except ValueError as e:
                logger.warning(f"Could not attach pending students for {email}: {e}")

        # Log session in Django
        login(request, user)

        # If user existed, update avatar if Google provided a new one
        if not is_new_user and picture and user.avatar_url != picture:
            user.avatar_url = picture
            user.save(update_fields=['avatar_url'])

        # Write login to ActivityLog (if not new user, who already gets an ONBOARDED log)
        if not is_new_user:
            student = Student.objects.filter(profile=user).first()
            ActivityLog.objects.create(
                actor=user,
                actor_email=user.email,
                actor_name=user.full_name,
                actor_role=user.role,
                action="LOGIN",
                entity_type="SESSION",
                entity_id=request.session.session_key or "unknown",
                entity_label="User Session",
                student=student
            )

        # Serialize user response details
        user_serializer = UserSerializer(user)
        response_data = {
            "status": "authenticated" if not is_new_user else "onboarded",
            "is_new_user": is_new_user,
            "user": user_serializer.data,
        }

        # Include Student specific info if applicable
        if user.role == 'STUDENT':
            response_data.update(build_student_payload(request, user))

        return Response(
            response_data,
            status=status.HTTP_201_CREATED if is_new_user else status.HTTP_200_OK
        )

class LogoutView(APIView):
    """
    Logs out the authenticated user session.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CSRFExemptSessionAuthentication]

    def post(self, request, *args, **kwargs):
        user = request.user
        session_key = request.session.session_key
        
        # Log logout activity
        student = Student.objects.filter(profile=user).first() if user.role == 'STUDENT' else None
        ActivityLog.objects.create(
            actor=user,
            actor_email=user.email,
            actor_name=user.full_name,
            actor_role=user.role,
            action="LOGOUT",
            entity_type="SESSION",
            entity_id=session_key or "unknown",
            entity_label="User Session",
            student=student
        )

        logout(request)
        response = Response(
            {"status": "logged_out", "message": "Successfully logged out."},
            status=status.HTTP_200_OK
        )
        response.delete_cookie(EP_STUDENT_COOKIE, domain=settings.SESSION_COOKIE_DOMAIN)
        return response

class MeView(APIView):
    """
    Returns the profile details of the current logged-in user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        user_serializer = UserSerializer(user)
        response_data = {
            "user": user_serializer.data
        }

        if user.role == 'STUDENT':
            response_data.update(build_student_payload(request, user))

        return Response(response_data, status=status.HTTP_200_OK)


class SelectStudentView(APIView):
    """
    POST /api/auth/select-student/
    Record which child a parent account is acting on by setting the
    ``ep-student-id`` cookie. Validates that the student belongs to the account.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CSRFExemptSessionAuthentication]

    def post(self, request, *args, **kwargs):
        student_id = request.data.get("student_id")
        if not student_id:
            return Response(
                {"error": "INVALID_INPUT", "message": "student_id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        student = get_usable_students(request.user).filter(id=student_id).first()
        if not student:
            # Distinguish an expired persona (access ended) from one that was
            # never linked to this account.
            if get_account_students(request.user).filter(id=student_id).exists():
                return Response(
                    {"error": "STUDENT_ACCESS_ENDED", "message": "This student's access has ended."},
                    status=status.HTTP_403_FORBIDDEN
                )
            return Response(
                {"error": "NOT_FOUND", "message": "That student is not linked to your account."},
                status=status.HTTP_404_NOT_FOUND
            )

        response = Response(
            {"selected_student_id": str(student.id), "student_profile": StudentSerializer(student).data},
            status=status.HTTP_200_OK
        )
        response.set_cookie(
            EP_STUDENT_COOKIE,
            str(student.id),
            max_age=EP_STUDENT_COOKIE_MAX_AGE,
            domain=settings.SESSION_COOKIE_DOMAIN,
            secure=settings.SESSION_COOKIE_SECURE,
            httponly=True,
            samesite=settings.SESSION_COOKIE_SAMESITE,
        )
        return response

class BaseRoleListView(APIView):
    """
    Lists active users of a single role with their assigned-student counts.

    Subclasses set ``role`` and ``response_key``; roles that own students set
    ``count_relation`` (the reverse FK used to count allocations) which also
    enables the dropdown-compatibility mode (a slim payload unless ?all=true).

    Staff-only: a directory of colleagues is not student-visible data. The full
    record (email, mobile, inviter) is admin-only, so ?all=true is refused for
    the other staff roles rather than quietly downgraded.
    """
    permission_classes = [IsAuthenticated, IsStaffUser]
    role = None
    response_key = None
    count_relation = None

    def _serialize(self, u):
        return {
            "kind": "active",
            "id": str(u.id),
            "full_name": u.full_name or "",
            "email": u.email,
            "avatar_url": u.avatar_url or None,
            "mobile_number": u.mobile_number or "",
            "created_at": u.created_at.isoformat(),
            "invited_by_profile": {
                "id": str(u.invited_by.id),
                "full_name": u.invited_by.full_name or "",
                "email": u.invited_by.email
            } if u.invited_by else None,
            "assigned_students_count": getattr(u, 'assigned_students_count', None),
            "deactivated_at": u.deactivated_at.isoformat() if u.deactivated_at else None
        }

    def get(self, request, *args, **kwargs):
        from django.db.models import Count

        if request.GET.get('all') == 'true' and not IsAdminUser().has_permission(request, self):
            return Response(
                {"error": "FORBIDDEN", "message": "Only admins can list full staff records."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Full records include deactivated staff (shown with a badge, needed
        # for the reactivate flow); the slim dropdown mode below stays
        # active-only so nothing new can be assigned to deactivated staff.
        queryset = User.objects.filter(role=self.role)
        if self.count_relation:
            queryset = queryset.annotate(assigned_students_count=Count(self.count_relation))
        queryset = queryset.order_by('-created_at')

        # Backward compatibility for dropdown selects (which don't pass ?all=true).
        # Deactivated staff must not be assignable, so this filters on BOTH
        # lifecycle flags — a row where they disagree (only creatable through
        # the Django admin) is treated as deactivated, never as assignable.
        if self.count_relation and request.GET.get('all') != 'true':
            slim = queryset.filter(deactivated_at__isnull=True, is_active=True)
            return Response(
                {self.response_key: [
                    {"id": str(u.id), "full_name": u.full_name or "", "email": u.email}
                    for u in slim
                ]},
                status=status.HTTP_200_OK
            )

        return Response(
            {self.response_key: [self._serialize(u) for u in queryset]},
            status=status.HTTP_200_OK
        )

class MentorListView(BaseRoleListView):
    """
    GET /api/mentors/
    Returns list of active mentors with their assigned student counts.
    If ?all=true is passed, returns the full mentor records.
    """
    role = 'MENTOR'
    response_key = 'mentors'
    count_relation = 'mentored_students'

class TutorListView(BaseRoleListView):
    """
    GET /api/tutors/
    Returns list of active tutors with their assigned student counts.
    """
    role = 'TUTOR'
    response_key = 'tutors'
    count_relation = 'tutored_students'

class AdminListView(BaseRoleListView):
    """
    GET /api/admins/
    Returns list of active admins. Admin-only: this view has no slim mode, so
    every response carries the full record.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    role = 'ADMIN'
    response_key = 'admins'
    count_relation = None

class UserDetailView(APIView):
    """
    PATCH /api/users/<id>/ - Edit User name and mobile number.
    DELETE /api/users/<id>/ - Delete User profile.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CSRFExemptSessionAuthentication]

    def patch(self, request, pk, *args, **kwargs):
        if request.user.role != 'ADMIN':
            return Response(
                {"error": "FORBIDDEN", "message": "Only admins can edit user details."},
                status=status.HTTP_403_FORBIDDEN
            )
            
        target_user = get_object_or_404(User, pk=pk)
        
        full_name = request.data.get("full_name")
        mobile_number = request.data.get("mobile_number")
        
        if full_name is not None:
            full_name = full_name.strip()
            if not full_name:
                return Response(
                    {"error": "INVALID_INPUT", "message": "Name cannot be empty."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            target_user.full_name = full_name
            
        if "mobile_number" in request.data:
            target_user.mobile_number = mobile_number.strip() if mobile_number else None
            
        target_user.save()
        
        # Log activity
        ActivityLog.objects.create(
            actor=request.user,
            actor_email=request.user.email,
            actor_name=request.user.full_name,
            actor_role=request.user.role,
            action="USER_UPDATE",
            entity_type="USER",
            entity_id=str(target_user.id),
            entity_label=target_user.full_name or target_user.email,
            student=None,
            context={"changes": {"full_name": target_user.full_name, "mobile_number": target_user.mobile_number}}
        )
        
        return Response({"success": True, "profile": {
            "id": str(target_user.id),
            "full_name": target_user.full_name,
            "mobile_number": target_user.mobile_number,
            "email": target_user.email,
        }}, status=status.HTTP_200_OK)

    # NOTE: there is deliberately no DELETE here. Staff are soft-deactivated
    # (StaffStatusView), never hard-deleted — deleting a user would cascade
    # away student personas and orphan the append-only audit trail. This
    # mirrors the original Hub, which removed user deletion entirely.


class StaffStatusView(APIView):
    """
    POST /api/users/<id>/status/ — deactivate or reactivate a staff member.

    Admin-only. Only mentors and tutors are managed through this flow: admins
    are peers, one admin never deactivates (or reactivates) another. A mentor/
    tutor with ACTIVE students still assigned cannot be deactivated until they
    are handed over (StaffReassignView) — mirrors the Hub's set_staff_active
    RPC guards. Role is never cleared, so historical attribution survives.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    authentication_classes = [CSRFExemptSessionAuthentication]

    def post(self, request, pk, *args, **kwargs):
        action = request.data.get("action")
        if action not in ('deactivate', 'reactivate'):
            return Response(
                {"error": "INVALID_INPUT", "message": "action must be 'deactivate' or 'reactivate'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        reason = request.data.get("reason")
        if reason is not None and not isinstance(reason, str):
            return Response(
                {"error": "INVALID_INPUT", "message": "reason must be a string."},
                status=status.HTTP_400_BAD_REQUEST
            )
        reason = (reason or "").strip() or None
        if reason and len(reason) > 500:
            return Response(
                {"error": "INVALID_INPUT", "message": "reason must be 500 characters or fewer."},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            # Lock the target row so the handover guard and the write are one
            # unit: a concurrent reassign-to-this-user (which locks the
            # replacement row) or second status change serializes against it.
            target = User.objects.select_for_update().filter(pk=pk).first()
            if not target:
                return Response(
                    {"error": "NOT_FOUND", "message": "User not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            if target.role not in ('ADMIN', 'MENTOR', 'TUTOR'):
                return Response(
                    {"error": "INVALID_ROLE", "message": "Only staff can be deactivated."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Admins are peers and out of scope: one admin never deactivates
            # (or reactivates) another.
            if target.role == 'ADMIN':
                return Response(
                    {"error": "FORBIDDEN", "message": "Administrators cannot be deactivated."},
                    status=status.HTTP_403_FORBIDDEN
                )

            was_deactivated = target.deactivated_at is not None

            if action == 'deactivate':
                # Handover guard: no ACTIVE students may still be assigned.
                from django.db.models import Q
                assigned = Student.objects.filter(status='ACTIVE').filter(
                    Q(mentor=target) | Q(tutor=target)
                ).count()
                if assigned > 0:
                    return Response(
                        {
                            "error": "HANDOVER_REQUIRED",
                            "message": f"Reassign this staff member's {assigned} active student(s) before deactivating."
                        },
                        status=status.HTTP_409_CONFLICT
                    )

                target.deactivated_at = timezone.now()
                target.deactivated_by = request.user
                target.deactivation_reason = reason
                target.is_active = False  # kills existing sessions on next request
                target.save(update_fields=['deactivated_at', 'deactivated_by', 'deactivation_reason', 'is_active', 'updated_at'])
            else:
                target.deactivated_at = None
                target.deactivated_by = None
                target.deactivation_reason = None
                target.is_active = True
                target.save(update_fields=['deactivated_at', 'deactivated_by', 'deactivation_reason', 'is_active', 'updated_at'])

        log_activity(
            action='user.reactivate' if action == 'reactivate' else 'user.deactivate',
            entity_type='USER',
            entity_id=str(target.id),
            entity_label=target.full_name or target.email,
            changes={
                "status": {
                    "old": "deactivated" if was_deactivated else "active",
                    "new": "active" if action == 'reactivate' else "deactivated"
                }
            },
            context={"reason": reason},
            request=request,
        )

        return Response({"success": True}, status=status.HTTP_200_OK)


class StaffReassignView(APIView):
    """
    POST /api/users/<id>/reassign/ — bulk hand over every ACTIVE student
    assigned to a departing staff member to a replacement, before deactivating
    them. Re-points that student's open (SCHEDULED) sessions for a tutor
    handover; completed/cancelled history keeps the old staff pointer for
    attribution, and inactive/expired students are left untouched — mirrors
    the Hub's reassign_all_for_staff RPC.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]
    authentication_classes = [CSRFExemptSessionAuthentication]

    def post(self, request, pk, *args, **kwargs):
        from sessions.models import Session, SessionStatusChoices

        old_staff = User.objects.filter(pk=pk).first()
        if not old_staff:
            return Response(
                {"error": "NOT_FOUND", "message": "User not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Validate id format up front (Hub parity: the original route zod-
        # validates both as uuids and returns 400) — a malformed value must
        # not reach the UUIDField filter, where it would raise.
        def parse_uuid(value, field):
            if value in (None, ''):
                return None, None
            try:
                return uuid.UUID(str(value)), None
            except (ValueError, TypeError, AttributeError):
                return None, Response(
                    {"error": "INVALID_INPUT", "message": f"{field} must be a valid id."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        new_mentor_id, err = parse_uuid(request.data.get("new_mentor"), "new_mentor")
        if err:
            return err
        new_tutor_id, err = parse_uuid(request.data.get("new_tutor"), "new_tutor")
        if err:
            return err

        students_mentor_reassigned = 0
        students_tutor_reassigned = 0
        sessions_repointed = 0

        with transaction.atomic():
            mentor_students = Student.objects.filter(mentor=old_staff, status='ACTIVE')
            tutor_students = Student.objects.filter(tutor=old_staff, status='ACTIVE')
            need_mentor = mentor_students.exists()
            need_tutor = tutor_students.exists()

            # Validate BOTH replacements before moving anything, so a failure
            # on either leg leaves the handover untouched (the Hub RPC raises
            # and rolls back the whole transaction; a 409 mid-way here would
            # instead commit the first leg). Replacements must satisfy the
            # both-flags assignability rule, and locking the rows serializes
            # this against a concurrent deactivation of the replacement.
            new_mentor = None
            if need_mentor:
                new_mentor = User.objects.select_for_update().filter(
                    pk=new_mentor_id, role='MENTOR',
                    deactivated_at__isnull=True, is_active=True
                ).first() if new_mentor_id else None
                if not new_mentor:
                    return Response(
                        {
                            "error": "INVALID_REPLACEMENT",
                            "message": "A valid active mentor is required to hand over assigned students."
                        },
                        status=status.HTTP_409_CONFLICT
                    )
            new_tutor = None
            if need_tutor:
                new_tutor = User.objects.select_for_update().filter(
                    pk=new_tutor_id, role='TUTOR',
                    deactivated_at__isnull=True, is_active=True
                ).first() if new_tutor_id else None
                if not new_tutor:
                    return Response(
                        {
                            "error": "INVALID_REPLACEMENT",
                            "message": "A valid active tutor is required to hand over assigned students."
                        },
                        status=status.HTTP_409_CONFLICT
                    )

            if need_mentor:
                students_mentor_reassigned = mentor_students.update(mentor=new_mentor)

            # Tutor handover: re-point open scheduled sessions first, then the
            # student pointer (the session query keys off the student pointer).
            if need_tutor:
                sessions_repointed = Session.objects.filter(
                    student__tutor=old_staff,
                    student__status='ACTIVE',
                    status=SessionStatusChoices.SCHEDULED
                ).update(tutor=new_tutor)
                students_tutor_reassigned = tutor_students.update(tutor=new_tutor)

        summary = {
            "students_mentor_reassigned": students_mentor_reassigned,
            "students_tutor_reassigned": students_tutor_reassigned,
            "sessions_repointed": sessions_repointed,
        }

        log_activity(
            action='staff.reassign_all',
            entity_type='USER',
            entity_id=str(old_staff.id),
            entity_label=old_staff.full_name or old_staff.email,
            context={
                "new_mentor": str(new_mentor_id) if new_mentor_id else None,
                "new_tutor": str(new_tutor_id) if new_tutor_id else None,
                **summary,
            },
            request=request,
        )

        return Response({"success": True, "result": summary}, status=status.HTTP_200_OK)

