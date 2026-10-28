// What the Hub offers an account, decided by the permissions /me reports
// (backend accounts.authz: the role's group plus individual grants, within the
// role's ceiling; superusers hold every one). One place for the No Access
// gate, the route guards, the sidebar and every in-page action, so they can
// never disagree. The API enforces the same permissions on every request; this
// only decides what the Hub offers. Only the BDE workspace reads the role (see
// canOpenPage): an account holding no permission gets no pages at all, whatever
// its role.

export const PERMISSIONS = {
  viewTeam: 'accounts.view_team',
  manageTeam: 'accounts.manage_team',
  viewStaffDashboard: 'accounts.view_staff_dashboard',

  viewAllStudents: 'accounts.view_all_students',
  viewMentoredStudents: 'accounts.view_mentored_students',
  viewTutoredStudents: 'accounts.view_tutored_students',
  viewFullStudentRecord: 'accounts.view_full_student_record',
  changeStudentDetails: 'accounts.change_student_details',
  syncStudentQuota: 'accounts.sync_student_quota',
  reassignStudentStaff: 'accounts.reassign_student_staff',
  purgeStudent: 'accounts.purge_student',

  viewAllSessions: 'accounts.view_all_sessions',
  viewMentoredSessions: 'accounts.view_mentored_sessions',
  viewTutoredSessions: 'accounts.view_tutored_sessions',
  createSession: 'accounts.create_session',
  manageSession: 'accounts.manage_session',
  cancelSession: 'accounts.cancel_session',
  editSessionNotes: 'accounts.edit_session_notes',

  viewAllExams: 'accounts.view_all_exams',
  viewMentoredExams: 'accounts.view_mentored_exams',
  createExam: 'accounts.create_exam',
  manageExam: 'accounts.manage_exam',
  cancelExam: 'accounts.cancel_exam',
  recordExamResult: 'accounts.record_exam_result',

  viewAllHomework: 'accounts.view_all_homework',
  viewMentoredHomework: 'accounts.view_mentored_homework',
  viewTutoredHomework: 'accounts.view_tutored_homework',
  scoreHomework: 'accounts.score_homework',

  viewAllActivity: 'accounts.view_all_activity',
  viewOwnActivity: 'accounts.view_own_activity',
  viewActivityActors: 'accounts.view_activity_actors',

  viewInvitations: 'accounts.view_invitations',
  createInvitation: 'accounts.create_invitation',
  changeInvitation: 'accounts.change_invitation',
  withdrawInvitation: 'accounts.withdraw_invitation',

  viewOwnBookingLinks: 'accounts.view_own_booking_links',

  manageBookingSlots: 'accounts.manage_booking_slots',
};

const P = PERMISSIONS;

// Any one of these opens some of a module's rows (backend core.querysets).
export const STUDENT_VIEW = [P.viewAllStudents, P.viewMentoredStudents, P.viewTutoredStudents];
export const SESSION_VIEW = [P.viewAllSessions, P.viewMentoredSessions, P.viewTutoredSessions];
export const EXAM_VIEW = [P.viewAllExams, P.viewMentoredExams];
export const HOMEWORK_VIEW = [P.viewAllHomework, P.viewMentoredHomework, P.viewTutoredHomework];
export const ACTIVITY_VIEW = [P.viewAllActivity, P.viewOwnActivity];

/** Whether `user` holds `permission`. */
export function can(user, permission) {
  return Boolean(user?.permissions?.includes(permission));
}

/** Whether `user` holds at least one of `permissions`. */
export function canAny(user, permissions) {
  return permissions.some((permission) => can(user, permission));
}

// Each page opens for whoever holds any of its permissions, in sidebar order.
export const PAGE_PERMISSIONS = {
  '/dashboard': [P.viewStaffDashboard],
  '/students': STUDENT_VIEW,
  '/sessions': SESSION_VIEW,
  '/exams': EXAM_VIEW,
  '/homework': HOMEWORK_VIEW,
  '/team': [P.viewTeam, P.manageTeam],
  '/invitations': [P.viewInvitations],
  '/activity': ACTIVITY_VIEW,
  // The Demo and Diagnostic slots parents book, for administrators.
  '/booking-slots': [P.manageBookingSlots],
  // The BDE workspace. Last, so it is the home page only of whoever has no other page.
  '/booking-links': [P.viewOwnBookingLinks],
};

/** Whether the student action menu (components/students/action-cell) offers `user` anything. */
export function hasStudentActions(user) {
  return canAny(user, [P.changeStudentDetails, P.reassignStudentStaff, P.purgeStudent, ...SESSION_VIEW, ...EXAM_VIEW]);
}

/** Whether `user` may open the page at `path` (a top-level path such as '/exams'). */
export function canOpenPage(user, path) {
  // Booking links belong to BDE accounts only. A superuser holds the
  // permission too (D1) but has no links, so the page is BDE-only.
  if (path === '/booking-links' && user?.role !== 'BDE') return false;
  const permissions = PAGE_PERMISSIONS[path];
  return Boolean(permissions) && canAny(user, permissions);
}

/** The first page `user` may open -- where the guards send them -- or null when there is none. */
export function homePage(user) {
  return Object.keys(PAGE_PERMISSIONS).find((path) => canOpenPage(user, path)) ?? null;
}
