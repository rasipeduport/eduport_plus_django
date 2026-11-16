"""
Tutor Earnings (earnings app): administrators see every tutor's earnings
(accounts.view_tutor_earnings), set the rates (manage_tutor_rates), record and
void payments to tutors (manage_tutor_payments) and correct the ledger --
reverse, adjust, or keep an earning in review as earned
(correct_tutor_earnings); a tutor sees their own earnings
(view_own_earnings). Each is held by its role group only and never
individually grantable. Reversed, the five permission rows go, and with them
the role groups' hold on them. No account or earning is touched.
"""
from django.db import migrations

HUB_PERMISSIONS = [
    ('view_tutor_earnings', "View every tutor's earnings"),
    ('manage_tutor_rates', 'Set the tutor earning rates'),
    ('manage_tutor_payments', 'Record and void payments to tutors'),
    ('correct_tutor_earnings', 'Correct tutor earnings'),
    ('view_own_earnings', 'View their own earnings'),
]
GRANTS = {
    'ADMIN': ['view_tutor_earnings', 'manage_tutor_rates', 'manage_tutor_payments', 'correct_tutor_earnings'],
    'TUTOR': ['view_own_earnings'],
}


def grant_tutor_earnings(apps, schema_editor):
    db = schema_editor.connection.alias
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    RoleGroup = apps.get_model('accounts', 'RoleGroup')
    content_type, _ = ContentType.objects.using(db).get_or_create(app_label='accounts', model='hubpermission')
    permissions = {}
    for codename, label in HUB_PERMISSIONS:
        permissions[codename], _ = Permission.objects.using(db).get_or_create(
            content_type=content_type, codename=codename, defaults={'name': label},
        )
    for role, codenames in GRANTS.items():
        RoleGroup.objects.using(db).get(role=role).group.permissions.add(*(permissions[c] for c in codenames))


def revoke_tutor_earnings(apps, schema_editor):
    apps.get_model('auth', 'Permission').objects.using(schema_editor.connection.alias).filter(
        content_type__app_label='accounts', codename__in=[codename for codename, _label in HUB_PERMISSIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0029_correct_session_outcome_permission'),
    ]

    operations = [
        migrations.RunPython(grant_tutor_earnings, revoke_tutor_earnings),
        migrations.AlterModelOptions(
            name='hubpermission',
            options={'default_permissions': (), 'managed': False, 'permissions': [('manage_team', 'Manage staff accounts'), ('view_staff_directory', 'List active mentors and tutors'), ('view_staff_dashboard', 'View the staff dashboard'), ('view_all_students', 'View all students'), ('view_mentored_students', 'View the students they mentor'), ('view_tutored_students', 'View the students they tutor'), ('view_full_student_record', "View a student's full record"), ('change_student_details', "Change a student's details"), ('sync_student_quota', "Sync a student's class quota"), ('reassign_student_staff', "Reassign a student's mentor or tutor"), ('purge_student', 'Delete a student permanently'), ('view_student_notes', 'Read staff notes on students'), ('add_student_note', 'Write staff notes on students'), ('delete_any_student_note', "Delete anyone's staff note"), ('view_all_sessions', 'View all sessions'), ('view_mentored_sessions', 'View the sessions of students they mentor'), ('view_tutored_sessions', 'View the sessions of students they tutor'), ('create_session', 'Schedule sessions'), ('manage_session', 'Manage sessions'), ('cancel_session', 'Cancel sessions'), ('edit_session_notes', 'Add session notes'), ('view_all_exams', 'View all exams'), ('view_mentored_exams', 'View the exams of students they mentor'), ('create_exam', 'Create exams'), ('manage_exam', 'Reschedule exams'), ('cancel_exam', 'Cancel exams'), ('record_exam_result', 'Record exam results'), ('score_additional_exam', 'Score additional exams'), ('view_all_homework', 'View all homework'), ('view_mentored_homework', 'View the homework of students they mentor'), ('view_tutored_homework', 'View the homework of students they tutor'), ('view_homework_submissions', 'View homework submissions before scoring'), ('score_homework', 'Score homework'), ('view_all_activity', 'View all activity'), ('view_own_activity', 'View their own activity'), ('view_activity_actors', 'Filter activity by person'), ('view_invitations', 'View invitations'), ('change_invitation', 'Retrieve initial Learn credentials'), ('withdraw_invitation', 'Withdraw invitations'), ('view_own_booking_links', 'View their own booking links'), ('manage_booking_slots', 'Manage booking slots'), ('view_own_enquiries', 'View their own enquiries'), ('add_enquiry', 'Add enquiries'), ('view_all_bookings', 'View all bookings'), ('assign_booking_tutor', "Assign a booking's tutor"), ('view_assigned_bookings', 'View the bookings assigned to them'), ('create_demo_booking', 'Start a Demo booking for their own lead'), ('reschedule_booking', 'Reschedule a booking'), ('cancel_booking', 'Cancel a booking with a reason'), ('submit_booking_report', 'Submit and edit reports on their bookings'), ('view_own_lead_reports', 'View the reports on their own leads'), ('share_booking_report', 'Record a report sent to a parent'), ('manage_own_conversion', 'Manage conversion on their own leads'), ('manage_team_conversion', "Manage conversion on their team's leads"), ('view_conversion_tracker', 'View the complete Conversion Tracker'), ('manage_conversions', 'Manage conversion on any lead'), ('assign_lead_owner', "Assign or reassign a lead's owner BDE"), ('view_own_lead_communications', "View their own leads' communication"), ('send_lead_communications', 'Send and follow up parent messages'), ('record_parent_confirmation', "Record a parent's confirmation"), ('view_all_communications', "View every booking's communication"), ('manage_message_templates', 'Manage message templates'), ('view_all_leads', 'View all leads'), ('add_lead', 'Add leads'), ('change_student_timezone', "Correct a student's time zone"), ('manage_sales_syllabi', 'Manage syllabuses and plans'), ('manage_sales_pricing', 'Manage the global pricing'), ('view_sales_catalogue', 'View and quote the plans on sale'), ('create_sales_quotes', 'Quote parents and see their own quotes'), ('manage_sales_quotes', 'View and cancel every quote'), ('manage_initial_sales', 'Manage initial sales and payments'), ('create_additional_purchases', 'Create additional purchases for their students'), ('correct_session_outcome', 'Correct a recorded session outcome'), ('view_tutor_earnings', "View every tutor's earnings"), ('manage_tutor_rates', 'Set the tutor earning rates'), ('manage_tutor_payments', 'Record and void payments to tutors'), ('correct_tutor_earnings', 'Correct tutor earnings'), ('view_own_earnings', 'View their own earnings')], 'verbose_name': 'Hub permission', 'verbose_name_plural': 'Hub permissions'},
        ),
    ]
