import logging
from datetime import datetime
from django.db import transaction
from django.utils.dateparse import parse_date
from django.contrib.auth import get_user_model
from invitations.models import Invitation, InvitationStatusChoices, InvitationRoleChoices
from students.models import Student, StatusChoices
from activity.models import ActivityLog

logger = logging.getLogger(__name__)
User = get_user_model()

def parse_admission_date(date_str):
    """
    Tries parsing a date string from Google Sheets with various formats.
    """
    if not date_str:
        return None
    
    # Clean string
    date_str = str(date_str).strip()
    
    # Try standard YYYY-MM-DD
    parsed = parse_date(date_str)
    if parsed:
        return parsed
        
    # Try other formats
    for fmt in ("%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
            
    logger.warning(f"Could not parse admission date string: '{date_str}'")
    return None

def _as_int(value, default=0):
    """A JSON-sourced number as an int, falling back rather than raising."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class UserProvisioningService:
    @staticmethod
    def _create_student_from_invitation(user: User, invitation: Invitation, google_name: str) -> Student:
        """
        Create a single Student row from a STUDENT invitation's extra_data and
        link it to ``user``. Marks the invitation ACCEPTED. Raises ValueError if
        the invitation is missing a student_code.
        """
        extra_data = invitation.extra_data or {}

        student_code = extra_data.get("student_code")
        if not student_code:
            logger.error(f"Student invitation for {invitation.email} is missing student_code in extra_data.")
            raise ValueError("Student code is missing from the invitation data.")

        fullname = extra_data.get("full_name") or google_name or invitation.email.split("@")[0]
        admission_date = parse_admission_date(extra_data.get("admission_date"))

        # Class quota as the enrolment sheet stated it when the invitation was
        # created (invitations.views._sheet_quota_for -> column O, "No of
        # classes paid for"). Coerced here because extra_data is JSON and an
        # invitation written before this key existed simply has no value --
        # the column is NOT NULL, and the scheduled sync corrects it either way.
        initial_quota = _as_int(extra_data.get("total_class_quota"))

        # Resolve Mentor and Tutor if IDs are provided
        mentor = None
        mentor_id = extra_data.get("mentor_id")
        if mentor_id:
            try:
                mentor = User.objects.get(id=mentor_id)
            except User.DoesNotExist:
                logger.warning(f"Mentor with ID {mentor_id} not found during student registration.")

        tutor = None
        tutor_id = extra_data.get("tutor_id")
        if tutor_id:
            try:
                tutor = User.objects.get(id=tutor_id)
            except User.DoesNotExist:
                logger.warning(f"Tutor with ID {tutor_id} not found during student registration.")

        student = Student.objects.create(
            profile=user,
            student_code=student_code,
            full_name=fullname,
            mobile_number=extra_data.get("mobile_number"),
            country=extra_data.get("country"),
            state=extra_data.get("state"),
            school_name=extra_data.get("school_name"),
            grade=extra_data.get("grade"),
            syllabus=extra_data.get("syllabus"),
            admission_date=admission_date,
            total_class_quota=initial_quota,
            mentor=mentor,
            tutor=tutor,
            meet_link=extra_data.get("meet_link", ""),
            status=StatusChoices.ACTIVE
        )

        invitation.status = InvitationStatusChoices.ACCEPTED
        invitation.save(update_fields=['status', 'updated_at'])

        logger.info(f"Student record created for user {user.email} with code {student_code}")
        return student

    @staticmethod
    @transaction.atomic
    def attach_pending_students(user: User, google_name: str = "") -> list:
        """
        Attach every PENDING STUDENT invitation for ``user.email`` as a new
        Student row (one parent account -> many children). Idempotent: an
        invitation whose student_code already exists for this account is simply
        marked ACCEPTED and skipped. Returns the list of newly created students.

        Called on first login (after the account is created) and on every
        subsequent login, so children invited later are picked up automatically.
        """
        created = []
        pending = Invitation.objects.filter(
            email=user.email,
            role=InvitationRoleChoices.STUDENT,
            status=InvitationStatusChoices.PENDING,
        )
        for invitation in pending:
            code = (invitation.extra_data or {}).get("student_code")
            if code and Student.objects.filter(profile=user, student_code=code).exists():
                invitation.status = InvitationStatusChoices.ACCEPTED
                invitation.save(update_fields=['status', 'updated_at'])
                continue
            created.append(
                UserProvisioningService._create_student_from_invitation(user, invitation, google_name)
            )
        return created

    @staticmethod
    @transaction.atomic
    def provision_user(email: str, google_name: str, google_avatar: str) -> User:
        """
        Provisions a User on first login from their PENDING invitation, and
        attaches all of their PENDING student invitations (for STUDENT accounts),
        inside an atomic database transaction.
        """
        logger.info(f"Attempting to provision user profile for email: {email}")

        # 1. Fetch PENDING invitation (used to determine the account's role)
        invitation = Invitation.objects.filter(
            email=email,
            status=InvitationStatusChoices.PENDING
        ).first()

        if not invitation:
            logger.error(f"No pending invitation found for email {email}")
            raise ValueError("No pending invitation found for this email address.")

        extra_data = invitation.extra_data or {}

        # Determine name to use (Google name prioritized, fallback to sheet name)
        fullname = google_name or extra_data.get("full_name") or invitation.email.split("@")[0]

        # 2. Create User Profile
        user = User.objects.create(
            email=email,
            full_name=fullname,
            avatar_url=google_avatar,
            role=invitation.role,
            invited_by=invitation.invited_by,
            is_active=True,
            is_staff=False if invitation.role == InvitationRoleChoices.STUDENT else True
        )
        user.set_unusable_password()
        user.save()

        student = None

        if invitation.role == InvitationRoleChoices.STUDENT:
            # 3. Attach all pending student invitations for this account
            created = UserProvisioningService.attach_pending_students(user, google_name)
            student = created[0] if created else None
        else:
            # Non-student account: a single invitation onboards a single staff user
            invitation.status = InvitationStatusChoices.ACCEPTED
            invitation.save(update_fields=['status', 'updated_at'])

        # 4. Log Activity
        ActivityLog.objects.create(
            actor=user,
            actor_email=user.email,
            actor_name=user.full_name,
            actor_role=user.role,
            action="user.onboarded",
            entity_type="profile",
            entity_id=str(user.id),
            entity_label=user.full_name,
            student=student,
            context={"invitation_id": str(invitation.id)}
        )

        logger.info(f"Successfully onboarded user {email} with role {user.role}")
        return user
