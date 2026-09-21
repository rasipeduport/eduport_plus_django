from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.contrib.auth import get_user_model
from core.authentication import CSRFExemptSessionAuthentication
from core.permissions import IsAdminOrMentor
from activity.utils import log_activity
from .models import Invitation, InvitationStatusChoices, InvitationRoleChoices
from .sheets import GoogleSheetsService
from students.models import Student

User = get_user_model()


def _find_student_invitation(email, student_code, status_filter=None):
    """
    Find the invitation for one specific child (a parent email may own several).
    Optionally restrict to a given status (e.g. PENDING).
    """
    qs = Invitation.objects.filter(
        email=email,
        role=InvitationRoleChoices.STUDENT,
        extra_data__student_code=student_code,
    )
    if status_filter is not None:
        qs = qs.filter(status=status_filter)
    return qs.first()

class LookupStudentView(APIView):
    """
    Step 1: Admin or Mentor enters a student code.
    Backend fetches the data from the Google Sheet (range A3:AB of 'enrollment data' tab) on demand.
    Returns the mapped data directly without writing to the database yet.
    """
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrMentor]

    def post(self, request, *args, **kwargs):
        student_code = request.data.get("student_code")
        if not student_code:
            return Response(
                {"error": "INVALID_INPUT", "message": "student_code is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Query Google Sheets using the production mapping
        try:
            student_data = GoogleSheetsService.lookup_student_by_code(student_code)
        except Exception as e:
            return Response(
                {"error": "SHEETS_API_ERROR", "message": f"Google Sheets lookup failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if not student_data:
            return Response(
                {"error": "STUDENT_NOT_FOUND", "message": f"Student with code '{student_code}' not found in the Google Sheet."},
                status=status.HTTP_404_NOT_FOUND
            )

        email = student_data.get("email")
        if not email:
            return Response(
                {"error": "MISSING_EMAIL", "message": "Student record found in sheet but email address is missing."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        student_code = student_data.get("student_code")

        # If this exact child is already enrolled, there is nothing to invite.
        if student_code and Student.objects.filter(student_code=student_code).exists():
            return Response(
                {
                    "error": "STUDENT_ALREADY_ONBOARDED",
                    "message": f"A student with code '{student_code}' is already enrolled.",
                    "student_data": student_data
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # A parent account (role STUDENT) may own several children, so a
        # registered STUDENT email is fine — only a staff account blocks reuse.
        clashing_user = User.objects.filter(email=email).first()
        if clashing_user and clashing_user.role != InvitationRoleChoices.STUDENT:
            return Response(
                {
                    "error": "USER_ALREADY_REGISTERED",
                    "message": f"A user with email '{email}' is already registered in the system.",
                    "student_data": student_data
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # A pending invitation for THIS child can be edited rather than recreated.
        invitation = _find_student_invitation(email, student_code)
        if invitation:
            if invitation.status == InvitationStatusChoices.ACCEPTED:
                return Response(
                    {
                        "error": "INVITATION_ALREADY_ACCEPTED",
                        "message": f"An invitation for '{email}' (code {student_code}) has already been accepted.",
                        "student_data": student_data
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(
                {
                    "status": "exists",
                    "message": f"A pending invitation already exists for this student. You can update it by submitting details.",
                    "student_data": student_data,
                    "invitation": {
                        "id": invitation.id,
                        "email": invitation.email,
                        "role": invitation.role,
                        "status": invitation.status,
                        "extra_data": invitation.extra_data
                    }
                },
                status=status.HTTP_200_OK
            )

        # No invitation exists for this child, return the sheet data to proceed.
        return Response(
            {
                "status": "found",
                "message": "Student record found in Google Sheets.",
                "student_data": student_data
            },
            status=status.HTTP_200_OK
        )



class CreateInvitationView(APIView):
    """
    Step 2: Admin or Mentor selects Mentor/Tutor/Meet Link and submits to create invitation whitelisting for students,
    or whitelists an Admin, Mentor, or Tutor by email directly.
    Also supports listing, editing, and deleting whitelist invitations.
    """
    authentication_classes = [CSRFExemptSessionAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrMentor]

    def get(self, request, *args, **kwargs):
        invitations = Invitation.objects.all().order_by('-created_at')
        data = []
        for inv in invitations:
            invited_by_profile = None
            if inv.invited_by:
                invited_by_profile = {
                    "id": str(inv.invited_by.id),
                    "full_name": inv.invited_by.full_name or "",
                    "email": inv.invited_by.email
                }
            data.append({
                "id": str(inv.id),
                "email": inv.email,
                "role": inv.role,
                "status": inv.status,
                "created_at": inv.created_at.isoformat(),
                "invited_by": inv.invited_by.id if inv.invited_by else None,
                "invited_by_profile": invited_by_profile,
                "extra_data": inv.extra_data
            })
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        data = request.data
        role = data.get("role", "STUDENT").upper()
        email = data.get("email")

        if role not in ("STUDENT", "MENTOR", "TUTOR", "ADMIN"):
            return Response(
                {"error": "INVALID_ROLE", "message": "Invalid invitation role specified."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not email or not email.strip():
            return Response(
                {"error": "INVALID_INPUT", "message": "email is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = email.strip().lower()

        # Enforce role invitation permissions:
        # Admin can invite anyone.
        # Mentors can invite Students only.
        if request.user.role == 'MENTOR' and role != 'STUDENT':
            return Response(
                {"error": "FORBIDDEN", "message": "Mentors can only invite students."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Create or update the Invitation whitelist record
        with transaction.atomic():
            if role == "STUDENT":
                student_code = data.get("student_code")
                full_name = data.get("full_name")
                if not student_code or not full_name:
                    return Response(
                        {"error": "INVALID_INPUT", "message": "student_code and full_name are required fields for students."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # The exact child (by code) must not already be enrolled.
                if Student.objects.filter(student_code=student_code).exists():
                    return Response(
                        {"error": "STUDENT_ALREADY_ONBOARDED", "message": f"A student with code '{student_code}' is already enrolled."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # A registered STUDENT email is the parent; only a staff account blocks reuse.
                clashing_user = User.objects.filter(email=email).first()
                if clashing_user and clashing_user.role != InvitationRoleChoices.STUDENT:
                    return Response(
                        {"error": "USER_ALREADY_REGISTERED", "message": f"User with email '{email}' is already registered."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Assignments must be to ACTIVE staff of the right role
                # (Hub parity: role='mentor'/'tutor' AND deactivated_at IS
                # NULL) — deactivated staff can never receive new students.
                mentor_id = data.get("mentor_id")
                if mentor_id:
                    if not User.objects.filter(
                        id=mentor_id, role='MENTOR',
                        deactivated_at__isnull=True, is_active=True
                    ).exists():
                        return Response(
                            {"error": "INVALID_MENTOR", "message": f"Mentor with ID '{mentor_id}' is not an active mentor."},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                tutor_id = data.get("tutor_id")
                if tutor_id:
                    if not User.objects.filter(
                        id=tutor_id, role='TUTOR',
                        deactivated_at__isnull=True, is_active=True
                    ).exists():
                        return Response(
                            {"error": "INVALID_TUTOR", "message": f"Tutor with ID '{tutor_id}' is not an active tutor."},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                extra_data = {
                    "student_code": student_code,
                    "full_name": full_name,
                    "mobile_number": data.get("mobile_number", ""),
                    "country": data.get("country", ""),
                    "state": data.get("state", ""),
                    "school_name": data.get("school_name", ""),
                    "grade": data.get("grade", ""),
                    "syllabus": data.get("syllabus", ""),
                    "admission_date": data.get("admission_date", ""),
                    "remarks": data.get("remarks", ""),
                    "mentor_id": mentor_id,
                    "tutor_id": tutor_id,
                    "meet_link": data.get("meet_link", "")
                }

                # Match an existing PENDING invitation for THIS child only, so a
                # second child for the same parent email creates a new record.
                invitation = _find_student_invitation(email, student_code)
            else:
                # Staff roles (ADMIN, MENTOR, TUTOR) are 1:1 with an email.
                if User.objects.filter(email=email).exists():
                    return Response(
                        {"error": "USER_ALREADY_REGISTERED", "message": f"User with email '{email}' is already registered."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                full_name = data.get("full_name", "")
                extra_data = {
                    "full_name": full_name,
                    "mobile_number": data.get("mobile_number", "")
                }
                invitation = Invitation.objects.filter(email=email).first()

            if invitation and invitation.status == InvitationStatusChoices.ACCEPTED:
                return Response(
                    {"error": "INVITATION_ALREADY_ACCEPTED", "message": "This invitation has already been accepted."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if invitation:
                invitation.role = role
                invitation.extra_data = extra_data
                invitation.invited_by = request.user
                invitation.status = InvitationStatusChoices.PENDING
                invitation.save()
                status_str = "updated"
                res_status = status.HTTP_200_OK
            else:
                invitation = Invitation.objects.create(
                    email=email,
                    role=role,
                    extra_data=extra_data,
                    invited_by=request.user,
                    status=InvitationStatusChoices.PENDING
                )
                status_str = "created"
                res_status = status.HTTP_201_CREATED

            # Send invitation email
            try:
                from .emails import send_invitation_email
                send_invitation_email(invitation)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to send invitation email to {email}: {e}")

            log_activity(
                action='invitation.create',
                entity_type='invitation',
                entity_id=str(invitation.id),
                entity_label=invitation.email,
                context={"role": invitation.role},
                request=request,
            )

            return Response(
                {
                    "status": status_str,
                    "message": f"Invitation for '{email}' has been successfully {status_str}.",
                    "invitation": {
                        "id": invitation.id,
                        "email": invitation.email,
                        "role": invitation.role,
                        "status": invitation.status
                    }
                },
                status=res_status
            )

    def patch(self, request, *args, **kwargs):
        # Identify by id when provided (a parent email may have several invites);
        # fall back to old_email for backward compatibility.
        invite_id = request.data.get("id")
        old_email = request.data.get("old_email")
        new_email = request.data.get("new_email")

        if not new_email or (not invite_id and not old_email):
            return Response(
                {"error": "INVALID_INPUT", "message": "new_email and one of id or old_email are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_email = new_email.strip().lower()

        if invite_id:
            invitation = Invitation.objects.filter(id=invite_id).first()
        else:
            invitation = Invitation.objects.filter(email=old_email.strip().lower()).first()
        if not invitation:
            return Response(
                {"error": "NOT_FOUND", "message": "Invitation not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        if request.user.role == 'MENTOR' and invitation.role != 'STUDENT':
            return Response(
                {"error": "FORBIDDEN", "message": "Mentors can only modify student invitations."},
                status=status.HTTP_403_FORBIDDEN
            )

        if invitation.status == InvitationStatusChoices.ACCEPTED:
            return Response(
                {"error": "INVITATION_ALREADY_ACCEPTED", "message": "Cannot edit an accepted invitation."},
                status=status.HTTP_400_BAD_REQUEST
            )

        old_email_value = invitation.email

        # A genuine duplicate is the SAME child (student_code) under the new email;
        # staff invites collide on email alone.
        code = (invitation.extra_data or {}).get("student_code")
        clash = Invitation.objects.filter(email=new_email).exclude(id=invitation.id)
        if invitation.role == InvitationRoleChoices.STUDENT and code:
            clash = clash.filter(extra_data__student_code=code)
        if clash.exists():
            return Response(
                {"error": "INVITATION_EXISTS", "message": "An invitation for this student with the new email already exists."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # A registered STUDENT email may still own more children; only a staff
        # account (or a non-student invite targeting it) blocks the change.
        clashing_user = User.objects.filter(email=new_email).first()
        if clashing_user and (invitation.role != InvitationRoleChoices.STUDENT or clashing_user.role != InvitationRoleChoices.STUDENT):
            return Response(
                {"error": "USER_ALREADY_REGISTERED", "message": "A user with the new email is already registered."},
                status=status.HTTP_400_BAD_REQUEST
            )

        invitation.email = new_email
        invitation.save()

        # Send invitation email to the new address
        try:
            from .emails import send_invitation_email
            send_invitation_email(invitation)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to send invitation email to {new_email}: {e}")

        log_activity(
            action='invitation.update_email',
            entity_type='invitation',
            entity_id=str(invitation.id),
            entity_label=new_email,
            changes={"email": {"old": old_email_value, "new": new_email}},
            request=request,
        )

        return Response({
            "status": "updated",
            "message": f"Invitation email updated from {old_email_value} to {new_email}."
        }, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        # Identify by id when provided (a parent email may have several invites);
        # fall back to email for backward compatibility.
        invite_id = request.data.get("id")
        email = request.data.get("email")
        if not invite_id and not email:
            return Response(
                {"error": "INVALID_INPUT", "message": "id or email is required in delete payload."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if invite_id:
            invitation = Invitation.objects.filter(id=invite_id).first()
        else:
            invitation = Invitation.objects.filter(email=email.strip().lower()).first()
        if not invitation:
            return Response(
                {"error": "NOT_FOUND", "message": "Invitation not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        if request.user.role == 'MENTOR' and invitation.role != 'STUDENT':
            return Response(
                {"error": "FORBIDDEN", "message": "Mentors can only delete student invitations."},
                status=status.HTTP_403_FORBIDDEN
            )

        if invitation.status == InvitationStatusChoices.ACCEPTED:
            return Response(
                {"error": "INVITATION_ALREADY_ACCEPTED", "message": "Cannot delete an accepted invitation."},
                status=status.HTTP_400_BAD_REQUEST
            )

        invitation_id = str(invitation.id)
        invitation_email = invitation.email
        invitation.delete()

        log_activity(
            action='invitation.withdraw',
            entity_type='invitation',
            entity_id=invitation_id,
            entity_label=invitation_email,
            request=request,
        )

        return Response({
            "status": "deleted",
            "message": f"Invitation for {email} has been withdrawn."
        }, status=status.HTTP_200_OK)

