// What the Hub offers an account, decided by the permissions /me reports
// (backend accounts.authz: the role's group plus individual grants, within the
// role's ceiling; superusers hold every one). One place for the No Access
// gate, the route guards, the sidebar and every in-page action, so they can
// never disagree. The API enforces the same permissions on every request; this
// only decides what the Hub offers. Only the BDE workspace, a tutor's Demo
// and Diagnostic bookings and My Earnings, and the Admin Hub's modules
// read the role as well (see canOpenPage, isBde, isTutor and
// isAdmin): an account holding no permission gets no pages at all, whatever
// its role.
// What the sidebar lists is lib/navigation's, filtered through canOpenPage.

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
  correctSessionOutcome: 'accounts.correct_session_outcome',

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
  changeInvitation: 'accounts.change_invitation',
  withdrawInvitation: 'accounts.withdraw_invitation',

  viewOwnBookingLinks: 'accounts.view_own_booking_links',
  viewOwnEnquiries: 'accounts.view_own_enquiries',
  viewOwnLeadReports: 'accounts.view_own_lead_reports',

  // Every lead, for administrators (backend bookings.lead_views): reading, adding by hand, giving a lead to a BDE.
  viewAllLeads: 'accounts.view_all_leads',
  addLead: 'accounts.add_lead',
  assignLeadOwner: 'accounts.assign_lead_owner',
  // Correcting a lead's student time zone (backend bookings.student_timezones): a BDE their own
  // enquiries', an administrator any lead's. The API checks which leads on every request.
  changeStudentTimezone: 'accounts.change_student_timezone',

  manageBookingSlots: 'accounts.manage_booking_slots',
  viewAllBookings: 'accounts.view_all_bookings',
  assignBookingTutor: 'accounts.assign_booking_tutor',
  viewAssignedBookings: 'accounts.view_assigned_bookings',

  // A booking's parent communication: every booking's (administrators), or a BDE's own leads'.
  viewAllCommunications: 'accounts.view_all_communications',
  viewOwnLeadCommunications: 'accounts.view_own_lead_communications',

  // Sales Management (backend sales app), administrators only: the syllabuses on
  // offer -- writing, previewing, publishing -- and the global pricing.
  manageSalesSyllabi: 'accounts.manage_sales_syllabi',
  manageSalesPricing: 'accounts.manage_sales_pricing',
  // The catalogue on sale (backend accounts.0021), the BDE's and the Admin's: what is quoted to parents.
  viewSalesCatalogue: 'accounts.view_sales_catalogue',
  // Quotes (backend accounts.0022): issuing them (the BDE's and the Admin's), and seeing
  // everyone's and cancelling them (the Admin's alone).
  createSalesQuotes: 'accounts.create_sales_quotes',
  manageSalesQuotes: 'accounts.manage_sales_quotes',
  manageInitialSales: 'accounts.manage_initial_sales',
  // A further purchase for an enrolled student (backend accounts.0026): the student's own
  // mentor, or an administrator. The API checks the mentor on every request.
  createAdditionalPurchases: 'accounts.create_additional_purchases',

  // Tutor Earnings (backend accounts.0030): every tutor's earnings, the rates, payments to
  // tutors and corrections to the ledger -- the administrators' alone, each on its own;
  // and a tutor's own earnings (My Earnings). The API answers a tutor for themselves only.
  viewTutorEarnings: 'accounts.view_tutor_earnings',
  manageTutorRates: 'accounts.manage_tutor_rates',
  manageTutorPayments: 'accounts.manage_tutor_payments',
  correctTutorEarnings: 'accounts.correct_tutor_earnings',
  viewOwnEarnings: 'accounts.view_own_earnings',
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
  // The staff dashboard, or a BDE's own (App.jsx picks by isBde). A BDE's
  // booking links are shared from it, so holding them opens it too.
  '/dashboard': [P.viewStaffDashboard, P.viewOwnEnquiries, P.viewOwnBookingLinks],
  // The staff dashboard under its Admin Hub and Tutor Hub name, Academics
  // Dashboard (administrators and tutors only: each Hub's /dashboard is its own).
  '/academics-dashboard': [P.viewStaffDashboard],
  '/students': STUDENT_VIEW,
  '/sessions': SESSION_VIEW,
  '/exams': EXAM_VIEW,
  '/homework': HOMEWORK_VIEW,
  '/team': [P.viewTeam, P.manageTeam],
  '/invitations': [P.viewInvitations],
  // The activity log, or a BDE's own activity (App.jsx picks by isBde): only a
  // BDE (and a superuser, who holds the log's permissions anyway) holds view_own_enquiries.
  '/activity': [...ACTIVITY_VIEW, P.viewOwnEnquiries],
  // Every lead, whatever brought it in, and the BDE who owns it, for administrators.
  '/leads': [P.viewAllLeads],
  // The admissions pipeline at a glance -- leads, bookings and what awaits action -- for administrators.
  '/admissions': [P.viewAllLeads],
  // Every Demo and Diagnostic booking and the tutor teaching it, for administrators:
  // a page per type (/bookings itself sends to Demo).
  '/bookings': [P.viewAllBookings],
  '/bookings/demo': [P.viewAllBookings],
  '/bookings/diagnostic': [P.viewAllBookings],
  // The Demo and Diagnostic slots parents book, for administrators.
  '/booking-slots': [P.manageBookingSlots],
  // The Demo and Diagnostic bookings a tutor is assigned to teach, their own only: a
  // page per type, each booking opening in its own workspace (the former single
  // page, /my-bookings, sends on to them).
  '/my-bookings': [P.viewAssignedBookings],
  '/my-bookings/demo': [P.viewAssignedBookings],
  '/my-bookings/diagnostic': [P.viewAssignedBookings],
  // A tutor's Admissions Dashboard: those bookings at a glance.
  '/admissions-dashboard': [P.viewAssignedBookings],
  // A tutor's own earnings and the payments recorded for them (Tutor Hub, My Earnings).
  '/my-earnings': [P.viewOwnEarnings],
  // The BDE workspace. Last, so its pages are the home page only of whoever has no other page.
  // My Enquiries, then the Demo and Diagnostic bookings made for those enquiries, what to
  // follow up, and the two modules still to come (My Sales, Plans & Pricing). The
  // follow-ups are the leads' parent communication, which carries the parent's phone
  // number: they open on the communication permission, as their API does.
  '/enquiries': [P.viewOwnEnquiries],
  '/demo-bookings': [P.viewOwnEnquiries],
  '/diagnostic-bookings': [P.viewOwnEnquiries],
  '/follow-ups': [P.viewOwnLeadCommunications],
  '/sales': [P.viewOwnEnquiries],
  // Plans & Pricing: the catalogue on sale, quoted to parents (a Bridge Course by the day too).
  '/plans': [P.viewSalesCatalogue],
  // Quotes, BDE and Admin alike: a BDE's own (My Quotes), every one for whoever manages them.
  '/quotes': [P.createSalesQuotes, P.manageSalesQuotes],
  // The Admin Hub's Sales & Finance modules. The Sales Dashboard reads every
  // student's sales and payments, so it needs both permissions of the API's
  // financial oversight (backend sales.account_views ADMIN_ONLY; see
  // EVERY_PERMISSION_PAGES). Syllabus & Plans and Global Pricing open on their
  // own permissions (backend sales.views); the rest are still to come -- each a
  // Coming Soon page with nothing behind it yet, for whoever holds the staff
  // dashboard. Sales Module and Sales Punching keep their pages but are no
  // longer in the sidebar (lib/navigation). Tutor Earnings opens on its own
  // permission (backend earnings.views).
  '/sales-dashboard': [P.manageInitialSales, P.manageSalesQuotes],
  '/sales-module': [P.viewStaffDashboard],
  '/sales-punching': [P.viewStaffDashboard],
  '/sales-syllabus': [P.manageSalesSyllabi],
  '/sales-pricing': [P.manageSalesPricing],
  '/tutor-earnings': [P.viewTutorEarnings],
};

// Pages for BDE accounts only. A superuser holds their permissions too (D1)
// but owns no links or enquiries, so these pages read the role as well.
const BDE_PAGES = new Set(['/enquiries', '/demo-bookings', '/diagnostic-bookings', '/follow-ups', '/sales', '/plans']);

// Pages for administrators only: the Sales Dashboard, Tutor Earnings and the
// Admin Hub's modules still to come. A mentor or tutor holds
// view_staff_dashboard too, a BDE manage_initial_sales, and a superuser every
// permission, so these read the role as well. (Syllabus & Plans and
// Global Pricing need permissions only administrators hold.)
const ADMIN_PAGES = new Set([
  '/sales-dashboard',
  '/sales-module',
  '/sales-punching',
  '/tutor-earnings',
]);

// Pages that need every one of their permissions, not just any one: the Sales
// Dashboard (a BDE holds manage_initial_sales too, for their own enquiries).
const EVERY_PERMISSION_PAGES = new Set(['/sales-dashboard']);

// Pages for tutors only. A superuser holds accounts.view_assigned_bookings too
// (D1) but is assigned no booking unless they are a tutor, so a tutor's
// bookings read the role as well; the API lists only the caller's own
// bookings either way. A superuser holds view_own_earnings too, so My Earnings
// reads it as well.
const TUTOR_PAGES = new Set([
  '/my-bookings',
  '/my-bookings/demo',
  '/my-bookings/diagnostic',
  '/admissions-dashboard',
  '/my-earnings',
]);

// Pages for administrators and tutors only: the Academics Dashboard (the staff
// dashboard). A mentor holds view_staff_dashboard too, so it reads the role as well.
const ADMIN_AND_TUTOR_PAGES = new Set(['/academics-dashboard']);

/** Whether `user` is a BDE: the Hub then offers the BDE workspace, the BDE dashboard included. */
export function isBde(user) {
  return user?.role === 'BDE';
}

/** Whether `user` is a tutor: the Hub then offers the Tutor Hub -- their dashboard, and the bookings they are assigned to teach. */
export function isTutor(user) {
  return user?.role === 'TUTOR';
}

/** Whether `user` is an administrator: the Hub then offers the Admin Hub's workspace. */
export function isAdmin(user) {
  return user?.role === 'ADMIN';
}

/** Whether the student action menu (components/students/action-cell) offers `user` anything. */
export function hasStudentActions(user) {
  return canAny(user, [P.changeStudentDetails, P.reassignStudentStaff, P.purgeStudent, ...SESSION_VIEW, ...EXAM_VIEW]);
}

/** Whether `user` may open the page at `path` (a top-level path such as '/exams'). */
export function canOpenPage(user, path) {
  if (BDE_PAGES.has(path) && !isBde(user)) return false;
  if (TUTOR_PAGES.has(path) && !isTutor(user)) return false;
  if (ADMIN_PAGES.has(path) && !isAdmin(user)) return false;
  if (ADMIN_AND_TUTOR_PAGES.has(path) && !isAdmin(user) && !isTutor(user)) return false;
  const permissions = PAGE_PERMISSIONS[path];
  if (!permissions) return false;
  return EVERY_PERMISSION_PAGES.has(path) ? permissions.every((permission) => can(user, permission)) : canAny(user, permissions);
}

/** The first page `user` may open -- where the guards send them -- or null when there is none. */
export function homePage(user) {
  return Object.keys(PAGE_PERMISSIONS).find((path) => canOpenPage(user, path)) ?? null;
}
