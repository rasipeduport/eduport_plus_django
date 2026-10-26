import logging
import uuid
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, get_user_model, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from students.models import Student
from activity.models import ActivityLog
from activity.utils import log_activity
from core.permissions import HasAppPermission
from core.students import (
    get_account_students,
    get_usable_students,
    resolve_selected_student,
    EP_STUDENT_COOKIE,
)
from .serializers import UserSerializer, StudentSerializer
from .services import UserProvisioningService
from .models import RoleChoices, normalize_username
from .throttles import LoginIPThrottle, PasswordChangeThrottle

logger = logging.getLogger(__name__)
retired_logger = logging.getLogger('accounts.retired_endpoints')
User = get_user_model()

# One year, in seconds; the selected-student cookie is a long-lived preference.
EP_STUDENT_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

# The one answer every failed password login gets. An unknown username, a wrong
# password, a locked or inactive account, a Google-only account (unusable
# password) and a student account are indistinguishable from outside, so the
# endpoint cannot enumerate accounts.
LOGIN_FAILED_RESPONSE = {
    "error": "INVALID_CREDENTIALS",
    "message": "Invalid username or password.",
}

# Google sign-in is for students only (Learn). Staff -- Admin, Mentor and Tutor
# accounts, and any superuser or Django-admin account -- sign in to the Hub with
# their username and password, whichever app or client sends the credential.
# The caller has just proven they own the Google account, so the answer may
# say which kind of account it is.
GOOGLE_STAFF_REFUSED_RESPONSE = {
    "error": "GOOGLE_SIGN_IN_STUDENTS_ONLY",
    "message": "Google sign-in is only for students. Staff sign in to the Hub with their username and password.",
}


def is_student_account(user):
    """Whether Google sign-in may open a session for ``user``: plain student accounts only."""
    return user.role == RoleChoices.STUDENT and not user.is_superuser and not user.is_staff


class StaffInvitationRefused(Exception):
    """Raised inside the provisioning transaction to undo a staff account."""


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

def csrf_token_for(request):
    """
    The (masked) CSRF token for this request's CSRF cookie, for the JSON body.

    The SPAs keep it in memory and send it as X-CSRFToken instead of reading
    the csrftoken cookie through document.cookie, which is impossible when the
    API is served from another host than the SPA and unreliable when another
    application on the same parent domain sets a cookie with the same name.
    The browser still sends the cookie itself; CORS stops other origins from
    reading this body.
    """
    return get_token(getattr(request, '_request', request))


# The backend recorded in new sessions; get_user() loads the user through it on
# every later request. Named explicitly because two backends are configured
# (settings.AUTHENTICATION_BACKENDS) and Google sign-in never calls
# authenticate(), so login() could not pick one by itself.
SESSION_BACKEND = 'accounts.backends.LockoutModelBackend'


def establish_session(request, user):
    """
    Log ``user`` in.

    Django's ``login()`` rotates the session key (session-fixation defence)
    and records the password hash the session was issued against, so a later
    password change or administrator reset signs every *other* session out
    automatically.
    """
    login(request, user, backend=SESSION_BACKEND)


def verify_google_token(token: str) -> dict:
    """
    Verifies a Google ID token (Learn's student sign-in, kept until Phase 7)
    against the configured OAuth client id and returns its email, name and
    picture claims.
    """
    client_id = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')

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

@method_decorator(csrf_protect, name='dispatch')
class GoogleLoginView(APIView):
    """
    Accepts Google OAuth ID Token (credential JWT), validates against Google servers,
    provisions the user if they are whitelisted via an Invitation, and logs them in.

    Kept for Learn's student sign-in until Phase 7. Staff never sign in here:
    an existing staff account is refused before any session exists, and a
    staff invitation is never redeemed (see GOOGLE_STAFF_REFUSED_RESPONSE).
    Login CSRF is enforced the same way as the password login: the SPA primes
    the token through GET /api/auth/csrf/ before its first POST.
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

        if user and not is_student_account(user):
            log_activity(
                action="user.sign_in_failed",
                entity_type="profile",
                entity_id=str(user.id),
                entity_label=user.full_name or user.username,
                actor=user,
                context={"reason": "google_staff_account"},
                request=request,
            )
            return Response(GOOGLE_STAFF_REFUSED_RESPONSE, status=status.HTTP_403_FORBIDDEN)

        if not user:
            # First login: Onboard user using UserProvisioningService
            try:
                # The pending invitation decides the role. One for staff is
                # never redeemed through Google: the account it created is
                # rolled back and the invitation stays pending.
                with transaction.atomic():
                    user = UserProvisioningService.provision_user(
                        email=email,
                        google_name=name,
                        google_avatar=picture
                    )
                    if not is_student_account(user):
                        raise StaffInvitationRefused()
                is_new_user = True
            except StaffInvitationRefused:
                logger.warning(f"Refused Google sign-in for {email}: a staff invitation is not redeemed through Google.")
                return Response(GOOGLE_STAFF_REFUSED_RESPONSE, status=status.HTTP_403_FORBIDDEN)
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

        # Log session in Django (rotates the session key)
        establish_session(request, user)

        # If user existed, update avatar if Google provided a new one
        if not is_new_user and picture and user.avatar_url != picture:
            user.avatar_url = picture
            user.save(update_fields=['avatar_url'])

        # Write the sign-in to ActivityLog (a new user already gets a user.onboarded log)
        if not is_new_user:
            student = Student.objects.filter(profile=user).first()
            ActivityLog.objects.create(
                actor=user,
                actor_email=user.email,
                actor_name=user.full_name,
                actor_role=user.role,
                action="user.sign_in",
                entity_type="profile",
                entity_id=str(user.id),
                entity_label=user.full_name or user.email,
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

        # login() rotated the CSRF secret; hand the SPA the new token.
        response_data["csrf_token"] = csrf_token_for(request)

        return Response(
            response_data,
            status=status.HTTP_201_CREATED if is_new_user else status.HTTP_200_OK
        )

class CsrfTokenView(APIView):
    """
    GET /api/auth/csrf/ -- issues the CSRF cookie and returns the matching
    token in the body, so an SPA that has not yet called any authenticated
    endpoint (the login page) can send X-CSRFToken on its first POST.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, *args, **kwargs):
        return Response({"csrf_token": csrf_token_for(request)}, status=status.HTTP_200_OK)


@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    """
    POST /api/auth/login/ -- username + password sign-in for staff accounts.

    Security properties:
      * one generic failure answer (LOGIN_FAILED_RESPONSE) whatever the cause,
        so the endpoint cannot be used to enumerate accounts;
      * the per-account lockout and the failure audit live in the shared
        authentication backend (accounts.backends), which the Django admin
        login uses too; a per-address rate limit (LoginIPThrottle) sits in
        front of it;
      * student accounts are refused here, and only here: they sign in to
        Learn with Google;
      * login CSRF enforced with csrf_protect; the SPA primes the token via
        GET /api/auth/csrf/;
      * Django's login() rotates the session key.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginIPThrottle]

    def post(self, request, *args, **kwargs):
        username = request.data.get("username")
        password = request.data.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return self._invalid_input()
        # The canonical form get_by_natural_key() looks up (NFKC, stripped,
        # lower-case), so every Unicode-equivalent spelling of a username
        # shares one lockout counter.
        username = normalize_username(username)
        if not username or not password:
            return self._invalid_input()

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(LOGIN_FAILED_RESPONSE, status=status.HTTP_400_BAD_REQUEST)

        # Checked after the password, so a student account costs the same
        # hashing as any other and its refusal looks the same.
        if user.role == RoleChoices.STUDENT:
            log_activity(
                action="user.sign_in_failed",
                entity_type="profile",
                entity_id=str(user.id),
                entity_label=user.full_name or user.username,
                actor=user,
                context={"reason": "student_account"},
                request=request,
            )
            return Response(LOGIN_FAILED_RESPONSE, status=status.HTTP_400_BAD_REQUEST)

        establish_session(request, user)

        log_activity(
            action="user.sign_in",
            entity_type="profile",
            entity_id=str(user.id),
            entity_label=user.full_name or user.username,
            context={"method": "password"},
            request=request,
        )

        return Response(
            {
                "status": "authenticated",
                "must_change_password": user.must_change_password,
                "user": UserSerializer(user).data,
                # login() rotated the CSRF secret; the token from before is stale.
                "csrf_token": csrf_token_for(request),
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _invalid_input():
        return Response(
            {"error": "INVALID_INPUT", "message": "Username and password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )


class ChangePasswordView(APIView):
    """
    POST /api/auth/change-password/ -- the signed-in user sets a new password.

    Re-authenticates with the current password, applies AUTH_PASSWORD_VALIDATORS,
    clears the first-login flag, keeps THIS session alive and -- through the
    session hash Django stores at login -- signs every other session out.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [PasswordChangeThrottle]

    def post(self, request, *args, **kwargs):
        current = request.data.get("current_password")
        new = request.data.get("new_password")
        if not isinstance(current, str) or not isinstance(new, str) or not current or not new:
            return Response(
                {"error": "INVALID_INPUT", "message": "current_password and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        if not user.check_password(current):
            return Response(
                {"error": "INVALID_CURRENT_PASSWORD", "message": "The current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new == current:
            return Response(
                {"error": "PASSWORD_REUSED", "message": "The new password must differ from the current one."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_password(new, user=user)
        except DjangoValidationError as exc:
            return Response(
                {
                    "error": "PASSWORD_POLICY",
                    "message": "The new password does not meet the password policy.",
                    "details": list(exc.messages),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new)
        user.must_change_password = False
        user.password_changed_at = timezone.now()
        user.save(update_fields=['password', 'must_change_password', 'password_changed_at', 'updated_at'])
        # Re-key this session to the new hash so it survives; all others die.
        update_session_auth_hash(request._request, user)

        log_activity(
            action="user.password_change",
            entity_type="profile",
            entity_id=str(user.id),
            entity_label=user.full_name or user.username,
            request=request,
        )
        return Response({"status": "password_changed", "must_change_password": False}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    Logs out the authenticated user session. CSRF-protected like every other
    state-changing endpoint (DRF SessionAuthentication).
    """
    permission_classes = [IsAuthenticated]

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
            action="user.sign_out",
            entity_type="profile",
            entity_id=str(user.id),
            entity_label=user.full_name or user.email,
            student=student
        )

        logout(request)
        response = Response(
            {"status": "logged_out", "message": "Successfully logged out."},
            status=status.HTTP_200_OK
        )
        response.delete_cookie(EP_STUDENT_COOKIE, domain=settings.SESSION_COOKIE_DOMAIN)
        return response

@method_decorator(ensure_csrf_cookie, name='dispatch')
class MeView(APIView):
    """
    Returns the profile details of the current logged-in user, including the
    effective permission codenames the SPAs use for their own guards.

    Decorated on ``dispatch`` so the CSRF cookie is (re)issued even when the
    answer is a 403: a reloaded SPA always calls /me first, which keeps the
    token fresh for its next write.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        user_serializer = UserSerializer(user)
        response_data = {
            "user": user_serializer.data,
            "must_change_password": user.must_change_password,
            "csrf_token": csrf_token_for(request),
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

def retired_endpoint(request, replacement):
    """
    Decision D3, step 1: a legacy endpoint the Hub no longer calls answers 410
    Gone to every signed-in caller, and every call is logged with its caller,
    so the cleanup (step 2) can show it has no callers left before its route
    is removed.

    Accepted deviation from the two-step plan (approved 2026-10-26): the
    routes stay until the cleanup, but the code they used to run -- full
    staff records, the details edit, the status change -- was removed in step
    1. It remains in commit 3d56003; Team's own endpoints replace it.
    """
    user = request.user
    retired_logger.warning(
        'Retired endpoint called: %s %s by account %s (role %s, user agent %r)',
        request.method, request.get_full_path(), getattr(user, 'pk', None), getattr(user, 'role', None),
        request.META.get('HTTP_USER_AGENT', ''),
    )
    return Response(
        {"error": "ENDPOINT_RETIRED", "message": f"This endpoint has been retired. {replacement}"},
        status=status.HTTP_410_GONE
    )


class BaseRoleListView(APIView):
    """
    The active, assignable accounts of one role -- the slim list behind the
    mentor/tutor dropdowns (reassign a student, invite a student, hand over a
    departing colleague's students). Needs accounts.view_staff_directory.

    Deactivated staff must not be assignable, so this filters on BOTH
    lifecycle flags -- a row where they disagree (only creatable through the
    Django admin) is treated as deactivated, never as assignable.

    The full-record mode (?all=true: contact details, inviter, student counts
    and pending invitations) is retired (D3); Team (/api/team/) lists staff.
    """
    permission_classes = [IsAuthenticated, HasAppPermission('accounts.view_staff_directory')]
    role = None
    response_key = None

    def get(self, request, *args, **kwargs):
        if request.GET.get('all') == 'true':
            return retired_endpoint(request, 'Staff records are listed by GET /api/team/.')

        slim = User.objects.filter(
            role=self.role, deactivated_at__isnull=True, is_active=True
        ).order_by('-created_at')
        return Response(
            {self.response_key: [
                {"id": str(u.id), "full_name": u.full_name or "", "email": u.email}
                for u in slim
            ]},
            status=status.HTTP_200_OK
        )

class MentorListView(BaseRoleListView):
    """GET /api/mentors/ -- active mentors, for assignment dropdowns."""
    role = 'MENTOR'
    response_key = 'mentors'

class TutorListView(BaseRoleListView):
    """GET /api/tutors/ -- active tutors, for assignment dropdowns."""
    role = 'TUTOR'
    response_key = 'tutors'

class AdminListView(APIView):
    """GET /api/admins/ -- retired (D3); Team lists administrators."""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return retired_endpoint(request, 'Administrators are listed by GET /api/team/?role=ADMIN.')

class UserDetailView(APIView):
    """
    PATCH /api/users/<id>/ -- retired (D3); Team edits staff details.

    There is deliberately no DELETE here. Staff are soft-deactivated, never
    hard-deleted -- deleting a user would cascade away student personas and
    orphan the append-only audit trail. This mirrors the original Hub, which
    removed user deletion entirely.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, *args, **kwargs):
        return retired_endpoint(request, "Staff details are changed through PATCH /api/team/<id>/.")


class StaffStatusView(APIView):
    """POST /api/users/<id>/status/ -- retired (D3); Team deactivates and reactivates staff."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, *args, **kwargs):
        return retired_endpoint(
            request, "Staff are deactivated through POST /api/team/<id>/deactivate/ and reactivated "
                     "through POST /api/team/<id>/reactivate/."
        )


class StaffReassignView(APIView):
    """
    POST /api/users/<id>/reassign/ — bulk hand over every ACTIVE student
    assigned to a departing staff member to a replacement, before deactivating
    them (accounts.manage_team: Team's handover step). Re-points that student's open (SCHEDULED) sessions for a tutor
    handover; completed/cancelled history keeps the old staff pointer for
    attribution, and inactive/expired students are left untouched — mirrors
    the Hub's reassign_all_for_staff RPC.
    """
    permission_classes = [IsAuthenticated, HasAppPermission('accounts.manage_team')]

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
        exams_repointed = 0
        additional_exams_repointed = 0

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
                # Open exam work of the departing mentor's ACTIVE students moves
                # too (before the student pointer flips -- the query keys off it).
                from django.db.models import Q as _Q
                from exams.services import handover_open_exams
                exams_repointed, additional_exams_repointed = handover_open_exams(
                    _Q(student__mentor=old_staff, student__status='ACTIVE'), new_mentor
                )
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
            "exams_repointed": exams_repointed,
            "additional_exams_repointed": additional_exams_repointed,
        }

        log_activity(
            action='staff.reassign_all',
            entity_type='profile',
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

