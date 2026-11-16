# The model options as makemigrations writes them (accounts.HubPermission's
# permissions, in catalogue order), then the seed added by hand.
#
# Sales Management (sales app): two catalogue entries, both the ADMIN role's
# alone -- accounts.manage_sales_syllabi (write, preview, publish and
# deactivate the syllabuses on offer) and accounts.manage_sales_pricing (add a
# version of the global pricing) -- enforced by /api/sales/ from this
# migration on and granted to the ADMIN role group. Superusers hold every
# permission (D1).
#
# As in 0018 and 0019, the permission rows are made here: on a fresh database
# Django only creates permission rows after every migration has run
# (post_migrate). No account row or individual grant is touched.
from django.db import migrations

# (codename, name) of the HubPermission rows this migration adds.
HUB_PERMISSIONS = [
    ('manage_sales_syllabi', 'Manage syllabuses and plans'),
    ('manage_sales_pricing', 'Manage the global pricing'),
]
# The role groups that carry them.
GRANTS = {'ADMIN': ['manage_sales_syllabi', 'manage_sales_pricing']}


def _hub_permissions(apps, db):
    Permission = apps.get_model('auth', 'Permission')
    return Permission.objects.using(db).filter(content_type__app_label='accounts', content_type__model='hubpermission')


def grant_sales_permissions(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    RoleGroup = apps.get_model('accounts', 'RoleGroup')
    db = schema_editor.connection.alias
    hub_type, _ = ContentType.objects.using(db).get_or_create(app_label='accounts', model='hubpermission')
    permissions = {
        codename: Permission.objects.using(db).get_or_create(
            content_type=hub_type, codename=codename, defaults={'name': name},
        )[0]
        for codename, name in HUB_PERMISSIONS
    }
    for role, codenames in GRANTS.items():
        # Seeded by 0008; a missing role group stops the migration.
        group = RoleGroup.objects.using(db).select_related('group').get(role=role).group
        group.permissions.add(*(permissions[codename] for codename in codenames))


def revoke_sales_permissions(apps, schema_editor):
    db = schema_editor.connection.alias
    # Deleting the rows also takes them off every group (and any grant).
    _hub_permissions(apps, db).filter(codename__in=[codename for codename, _name in HUB_PERMISSIONS]).delete()



class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0019_student_timezone_permission'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='hubpermission',
            options={'default_permissions': (), 'managed': False, 'permissions': [('manage_team', 'Manage staff accounts'), ('view_staff_directory', 'List active mentors and tutors'), ('view_staff_dashboard', 'View the staff dashboard'), ('view_all_students', 'View all students'), ('view_mentored_students', 'View the students they mentor'), ('view_tutored_students', 'View the students they tutor'), ('view_full_student_record', "View a student's full record"), ('change_student_details', "Change a student's details"), ('sync_student_quota', "Sync a student's class quota"), ('reassign_student_staff', "Reassign a student's mentor or tutor"), ('purge_student', 'Delete a student permanently'), ('view_student_notes', 'Read staff notes on students'), ('add_student_note', 'Write staff notes on students'), ('delete_any_student_note', "Delete anyone's staff note"), ('view_all_sessions', 'View all sessions'), ('view_mentored_sessions', 'View the sessions of students they mentor'), ('view_tutored_sessions', 'View the sessions of students they tutor'), ('create_session', 'Schedule sessions'), ('manage_session', 'Manage sessions'), ('cancel_session', 'Cancel sessions'), ('edit_session_notes', 'Add session notes'), ('view_all_exams', 'View all exams'), ('view_mentored_exams', 'View the exams of students they mentor'), ('create_exam', 'Create exams'), ('manage_exam', 'Reschedule exams'), ('cancel_exam', 'Cancel exams'), ('record_exam_result', 'Record exam results'), ('score_additional_exam', 'Score additional exams'), ('view_all_homework', 'View all homework'), ('view_mentored_homework', 'View the homework of students they mentor'), ('view_tutored_homework', 'View the homework of students they tutor'), ('view_homework_submissions', 'View homework submissions before scoring'), ('score_homework', 'Score homework'), ('view_all_activity', 'View all activity'), ('view_own_activity', 'View their own activity'), ('view_activity_actors', 'Filter activity by person'), ('view_invitations', 'View invitations'), ('create_invitation', 'Invite students'), ('change_invitation', "Change an invitation's email"), ('withdraw_invitation', 'Withdraw invitations'), ('view_own_booking_links', 'View their own booking links'), ('manage_booking_slots', 'Manage booking slots'), ('view_own_enquiries', 'View their own enquiries'), ('add_enquiry', 'Add enquiries'), ('view_all_bookings', 'View all bookings'), ('assign_booking_tutor', "Assign a booking's tutor"), ('view_assigned_bookings', 'View the bookings assigned to them'), ('create_demo_booking', 'Start a Demo booking for their own lead'), ('reschedule_booking', 'Reschedule a booking'), ('cancel_booking', 'Cancel a booking with a reason'), ('submit_booking_report', 'Submit and edit reports on their bookings'), ('view_own_lead_reports', 'View the reports on their own leads'), ('share_booking_report', 'Record a report sent to a parent'), ('manage_own_conversion', 'Manage conversion on their own leads'), ('manage_team_conversion', "Manage conversion on their team's leads"), ('view_conversion_tracker', 'View the complete Conversion Tracker'), ('manage_conversions', 'Manage conversion on any lead'), ('assign_lead_owner', "Assign or reassign a lead's owner BDE"), ('view_own_lead_communications', "View their own leads' communication"), ('send_lead_communications', 'Send and follow up parent messages'), ('record_parent_confirmation', "Record a parent's confirmation"), ('view_all_communications', "View every booking's communication"), ('manage_message_templates', 'Manage message templates'), ('view_all_leads', 'View all leads'), ('add_lead', 'Add leads'), ('change_student_timezone', "Correct a student's time zone"), ('manage_sales_syllabi', 'Manage syllabuses and plans'), ('manage_sales_pricing', 'Manage the global pricing')], 'verbose_name': 'Hub permission', 'verbose_name_plural': 'Hub permissions'},
        ),
        migrations.RunPython(grant_sales_permissions, revoke_sales_permissions),
    ]
