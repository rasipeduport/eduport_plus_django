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
migration creating its row.
"""

STAFF = ('ADMIN', 'MENTOR', 'TUTOR')
ADMIN_ONLY = ('ADMIN',)
BDE_ONLY = ('BDE',)

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
