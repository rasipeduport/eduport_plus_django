"""
The approved application permissions, keyed "app_label.codename".

This is the list of what exists and how far each permission may ever reach --
never who holds it. Who holds what lives in the database: a role's group
(accounts.RoleGroup, seeded by migration 0008) and an account's individual
grants (Team API). The resolver (accounts.authz) only ever counts a permission
listed here, and only for an account whose role the entry's ``roles`` names.
That ceiling holds however a group is configured or a grant was made, so a
misconfiguration can never lift a role above it. Students hold none: Learn
keeps its persona rules.

``grantable`` marks the permissions the Team page may grant to one person; the
rest are carried by role groups only.

accounts.view_team predates the catalogue and lives on the User model; every
other entry lives on the table-less accounts.HubPermission model. A permission
is added here only together with the code that enforces it, and with a new
migration creating its row -- with two planned exceptions: the Demo/Diagnostic
workflow's permissions (Phase 5.2, migration 0015) and the parent
communication permissions (Phase 2A, migration 0017) are seeded ahead of the
phases whose code checks them, as their designs laid out. Each says which
phase that is; none is individually grantable, and none opens anything until
its phase's code asks for it.
"""

STAFF = ('ADMIN', 'MENTOR', 'TUTOR')
ADMIN_ONLY = ('ADMIN',)
TUTOR_ONLY = ('TUTOR',)
BDE_ONLY = ('BDE',)
SALES_TL_ONLY = ('SALES_TL',)
BDE_AND_ADMIN = ('BDE', 'ADMIN')
ADMIN_AND_SALES_TL = ('ADMIN', 'SALES_TL')

VIEW_TEAM = 'accounts.view_team'


def _entry(label, module, roles=STAFF, grantable=False):
    return {'label': label, 'module': module, 'roles': roles, 'grantable': grantable}


CATALOGUE = {
    # Team and staff accounts
    VIEW_TEAM: _entry('View the team directory', 'Team', grantable=True),
    'accounts.manage_team': _entry('Manage staff accounts', 'Team', ADMIN_ONLY),
    'accounts.view_staff_directory': _entry('List active mentors and tutors', 'Team'),

    # Dashboard
    'accounts.view_staff_dashboard': _entry('View the staff dashboard', 'Dashboard'),

    # Students
    'accounts.view_all_students': _entry('View all students', 'Students'),
    'accounts.view_mentored_students': _entry('View the students they mentor', 'Students'),
    'accounts.view_tutored_students': _entry('View the students they tutor', 'Students'),
    'accounts.view_full_student_record': _entry("View a student's full record", 'Students'),
    'accounts.change_student_details': _entry("Change a student's details", 'Students'),
    'accounts.sync_student_quota': _entry("Sync a student's class quota", 'Students'),
    'accounts.reassign_student_staff': _entry("Reassign a student's mentor or tutor", 'Students', ADMIN_ONLY),
    'accounts.purge_student': _entry('Delete a student permanently', 'Students', ADMIN_ONLY),
    'accounts.view_student_notes': _entry('Read staff notes on students', 'Students'),
    'accounts.add_student_note': _entry('Write staff notes on students', 'Students'),
    'accounts.delete_any_student_note': _entry("Delete anyone's staff note", 'Students'),

    # Sessions
    'accounts.view_all_sessions': _entry('View all sessions', 'Sessions'),
    'accounts.view_mentored_sessions': _entry('View the sessions of students they mentor', 'Sessions'),
    'accounts.view_tutored_sessions': _entry('View the sessions of students they tutor', 'Sessions'),
    'accounts.create_session': _entry('Schedule sessions', 'Sessions'),
    'accounts.manage_session': _entry('Manage sessions', 'Sessions'),
    'accounts.cancel_session': _entry('Cancel sessions', 'Sessions'),
    'accounts.edit_session_notes': _entry('Add session notes', 'Sessions'),

    # Exams
    'accounts.view_all_exams': _entry('View all exams', 'Exams'),
    'accounts.view_mentored_exams': _entry('View the exams of students they mentor', 'Exams'),
    'accounts.create_exam': _entry('Create exams', 'Exams'),
    'accounts.manage_exam': _entry('Reschedule exams', 'Exams'),
    'accounts.cancel_exam': _entry('Cancel exams', 'Exams'),
    'accounts.record_exam_result': _entry('Record exam results', 'Exams'),
    'accounts.score_additional_exam': _entry('Score additional exams', 'Exams'),

    # Homework
    'accounts.view_all_homework': _entry('View all homework', 'Homework'),
    'accounts.view_mentored_homework': _entry('View the homework of students they mentor', 'Homework'),
    'accounts.view_tutored_homework': _entry('View the homework of students they tutor', 'Homework'),
    'accounts.view_homework_submissions': _entry('View homework submissions before scoring', 'Homework'),
    'accounts.score_homework': _entry('Score homework', 'Homework'),

    # Activity
    'accounts.view_all_activity': _entry('View all activity', 'Activity'),
    'accounts.view_own_activity': _entry('View their own activity', 'Activity'),
    'accounts.view_activity_actors': _entry('Filter activity by person', 'Activity', ADMIN_ONLY),

    # Invitations
    'accounts.view_invitations': _entry('View invitations', 'Invitations'),
    'accounts.create_invitation': _entry('Invite students', 'Invitations'),
    'accounts.change_invitation': _entry("Change an invitation's email", 'Invitations'),
    'accounts.withdraw_invitation': _entry('Withdraw invitations', 'Invitations'),

    # Booking links (the BDE workspace; bookings app)
    'accounts.view_own_booking_links': _entry('View their own booking links', 'Booking links', BDE_ONLY),

    # Booking slots (the public Demo/Diagnostic booking pages; bookings app)
    'accounts.manage_booking_slots': _entry('Manage booking slots', 'Booking slots', ADMIN_ONLY),

    # Enquiries (the BDE workspace: the leads a BDE owns; bookings app)
    'accounts.view_own_enquiries': _entry('View their own enquiries', 'Enquiries', BDE_ONLY),
    'accounts.add_enquiry': _entry('Add enquiries', 'Enquiries', BDE_ONLY),

    # Booking management (Admin / Coordinator: every Demo and Diagnostic
    # booking, its parent and child, and the tutor teaching it; bookings app)
    'accounts.view_all_bookings': _entry('View all bookings', 'Bookings', ADMIN_ONLY),
    'accounts.assign_booking_tutor': _entry("Assign a booking's tutor", 'Bookings', ADMIN_ONLY),

    # My Bookings (the tutor's own: the Demo and Diagnostic bookings assigned
    # to them, with the child and the slot only; bookings app)
    'accounts.view_assigned_bookings': _entry('View the bookings assigned to them', 'Bookings', TUTOR_ONLY),
    # The Demo/Diagnostic workflow (Phase 5.2), seeded by 0015 ahead of its
    # code; the phase that enforces each is noted.
    # Bookings: the Demo handoff -- a BDE sending their own lead's parent a
    # Demo invitation once the Diagnostic report is in (bookings.demo_invites;
    # the Admin sends one with send_lead_communications) -- and cancel and
    # reschedule (P3). Only the Admin reschedules (Q23). The Admin and the
    # owner BDE cancel (Q22): a BDE only the bookings of their own leads, which
    # the cancel and invitation code check -- holding the permission is not enough.
    'accounts.create_demo_booking': _entry('Start a Demo booking for their own lead', 'Bookings', BDE_ONLY),
    'accounts.reschedule_booking': _entry('Reschedule a booking', 'Bookings', ADMIN_ONLY),
    'accounts.cancel_booking': _entry('Cancel a booking with a reason', 'Bookings', BDE_AND_ADMIN),
    # Assessment reports (P6-P9).
    'accounts.submit_booking_report': _entry('Submit and edit reports on their bookings', 'Reports', TUTOR_ONLY),
    'accounts.view_own_lead_reports': _entry('View the reports on their own leads', 'Reports', BDE_ONLY),
    'accounts.share_booking_report': _entry('Record a report sent to a parent', 'Reports', BDE_AND_ADMIN),
    # The Conversion Tracker (P11); the Sales TL's team scope is Q13.
    'accounts.manage_own_conversion': _entry('Manage conversion on their own leads', 'Conversions', BDE_ONLY),
    'accounts.manage_team_conversion': _entry("Manage conversion on their team's leads", 'Conversions', SALES_TL_ONLY),
    'accounts.view_conversion_tracker': _entry('View the complete Conversion Tracker', 'Conversions', ADMIN_AND_SALES_TL),
    'accounts.manage_conversions': _entry('Manage conversion on any lead', 'Conversions', ADMIN_ONLY),
    # Leads: the owner BDE of any lead, given or changed by an administrator
    # (D14; bookings.ownership, enforced since accounts.0018).
    'accounts.assign_lead_owner': _entry("Assign or reassign a lead's owner BDE", 'Leads', ADMIN_ONLY),

    # Parent communication (communications app): seeded in Phase 2A, checked by
    # its APIs (2C). A BDE acts on their own leads' bookings only, which the
    # communication code checks; tutors and Sales TL hold none.
    'accounts.view_own_lead_communications': _entry("View their own leads' communication", 'Communications', BDE_ONLY),
    'accounts.send_lead_communications': _entry('Send and follow up parent messages', 'Communications', BDE_AND_ADMIN),
    'accounts.record_parent_confirmation': _entry("Record a parent's confirmation", 'Communications', BDE_AND_ADMIN),
    'accounts.view_all_communications': _entry("View every booking's communication", 'Communications', ADMIN_ONLY),
    'accounts.manage_message_templates': _entry('Manage message templates', 'Communications', ADMIN_ONLY),

    # Leads (administrators: every lead, whatever brought it in; bookings app),
    # accounts.0018. Giving one its owner BDE is accounts.assign_lead_owner, above.
    'accounts.view_all_leads': _entry('View all leads', 'Leads', ADMIN_ONLY),
    'accounts.add_lead': _entry('Add leads', 'Leads', ADMIN_ONLY),
    # Correcting the time zone a lead's student books from (Student Local
    # Time; bookings.student_timezones), accounts.0019. A BDE corrects their
    # own enquiries only, an administrator any lead they may read
    # (view_all_leads) -- which the code checks; holding this is not enough.
    'accounts.change_student_timezone': _entry("Correct a student's time zone", 'Leads', BDE_AND_ADMIN),

    # Sales Management (sales app), accounts.0020: the syllabuses on offer --
    # writing, previewing and publishing them -- and the global pricing they
    # are sold at, each changed only by administrators. Reading the pricing
    # needs either: the syllabus pages show the packages it prices.
    'accounts.manage_sales_syllabi': _entry('Manage syllabuses and plans', 'Sales', ADMIN_ONLY),
    'accounts.manage_sales_pricing': _entry('Manage the global pricing', 'Sales', ADMIN_ONLY),
}


def allowed_for_role(role):
    """The catalogue permissions an account with ``role`` may hold at most."""
    return {name for name, entry in CATALOGUE.items() if role in entry['roles']}


def grantable_permissions():
    """The permissions the Team page may grant to one person (role groups carry the rest)."""
    return {name for name, entry in CATALOGUE.items() if entry['grantable']}


def hub_permission_meta():
    """(codename, label) of every entry held by accounts.HubPermission, in catalogue order."""
    return [(name.split('.', 1)[1], entry['label']) for name, entry in CATALOGUE.items() if name != VIEW_TEAM]
