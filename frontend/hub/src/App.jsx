import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import AuthProvider from './context/AuthProvider';
import PaymentReturnPage from './pages/PaymentReturnPage';
import AutopayActionPage from './pages/AutopayActionPage';
import SidebarLayout from './layout/SidebarLayout';
import LoginPage from './pages/LoginPage';
import ChangePasswordPage from './pages/ChangePasswordPage';
import NoAccessPage from './pages/NoAccessPage';
import DashboardPage from './pages/DashboardPage';
import StudentsPage from './pages/StudentsPage';
import StudentProfilePage from './pages/StudentProfilePage';
import SessionsPage from './pages/SessionsPage';
import ExamsPage from './pages/ExamsPage';
import HomeworkPage from './pages/HomeworkPage';
import InvitationsPage from './pages/InvitationsPage';
import ActivityPage from './pages/ActivityPage';
import TeamPage from './pages/TeamPage';
import TeamMemberPage from './pages/TeamMemberPage';
import BookingSlotsPage from './pages/BookingSlotsPage';
import BookingsPage from './pages/BookingsPage';
import BookingWorkspacePage from './pages/BookingWorkspacePage';
import RedemoWorkspacePage from './pages/RedemoWorkspacePage';
import TutorBookingsPage from './pages/TutorBookingsPage';
import TutorBookingWorkspacePage from './pages/TutorBookingWorkspacePage';
import TutorMainDashboardPage from './pages/TutorMainDashboardPage';
import TutorAdmissionsDashboardPage from './pages/TutorAdmissionsDashboardPage';
import TutorReportPage from './pages/TutorReportPage';
import BdeDashboardPage from './pages/BdeDashboardPage';
import EnquiriesPage from './pages/EnquiriesPage';
import EnquiryPage from './pages/EnquiryPage';
import LeadsPage from './pages/LeadsPage';
import LeadPage from './pages/LeadPage';
import BdeBookingsPage from './pages/BdeBookingsPage';
import FollowUpsPage from './pages/FollowUpsPage';
import BdeActivityPage from './pages/BdeActivityPage';
import ComingSoonPage from './pages/ComingSoonPage';
import AdmissionsDashboardPage from './pages/AdmissionsDashboardPage';
import SalesSyllabiPage from './pages/SalesSyllabiPage';
import SalesSyllabusPage from './pages/SalesSyllabusPage';
import SalesSyllabusEditorPage from './pages/SalesSyllabusEditorPage';
import SalesPricingPage from './pages/SalesPricingPage';
import PlansPage from './pages/PlansPage';
import PlanPage from './pages/PlanPage';
import QuotesPage from './pages/QuotesPage';
import QuotePage from './pages/QuotePage';
import { canOpenPage, homePage, isAdmin, isBde, isTutor } from './lib/access';
import { legacyBookingsPath, legacyTutorBookingsPath } from './lib/bookings';

/** A link to the former single Bookings page, sent on to its type's page (lib/bookings legacyBookingsPath). */
function LegacyBookings() {
  const { search } = useLocation();
  return <Navigate to={legacyBookingsPath(search)} replace />;
}

/** A link to a tutor's former single My Bookings page, sent on to its booking or its type's page. */
function LegacyTutorBookings() {
  const { search } = useLocation();
  return <Navigate to={legacyTutorBookingsPath(search)} replace />;
}

/**
 * Everything behind sign-in. The account comes from AuthProvider's /me
 * (fetched on every navigation), permissions included, and is handed to each
 * page, so no page guesses what the caller may do.
 */
function HubRoutes({ user, logout }) {
  // AuthProvider is already on its way to /login (no user) or to Learn (students).
  if (!user || user.role === 'STUDENT') return null;
  // A temporary password must be replaced before anything else. The API enforces the same.
  if (user.must_change_password) return <Navigate to="/change-password" replace />;
  // An account holding no permission that opens a Hub page gets nothing but a way to sign out.
  const home = homePage(user);
  if (!home) return <NoAccessPage user={user} logout={logout} />;

  // Each page opens only for the permissions lib/access lists for it; anyone
  // else lands on the first page they may open.
  const page = (path, element) => (canOpenPage(user, path) ? element : <Navigate to={home} replace />);

  return (
    <SidebarLayout user={user} logout={logout}>
      <Routes>
        {/* A BDE's dashboard is their own enquiries and bookings; an administrator's
            the Admin Hub's common dashboard, still to come (their academics
            dashboard is /academics-dashboard); a tutor's the Tutor Hub's Main
            Dashboard, across their admissions and academic work (each with its
            own dashboard too, below); everyone else's the staff one. */}
        <Route
          path="/dashboard"
          element={page(
            '/dashboard',
            isBde(user) ? (
              <BdeDashboardPage user={user} />
            ) : isAdmin(user) ? (
              <ComingSoonPage module="dashboard" />
            ) : isTutor(user) ? (
              <TutorMainDashboardPage user={user} />
            ) : (
              <DashboardPage user={user} />
            )
          )}
        />
        {/* The staff dashboard as it is, for administrators and tutors: the Admin
            Hub's and the Tutor Hub's Academics Dashboard (a tutor's, the dashboard
            they had at /dashboard before the Tutor Hub). */}
        <Route path="/academics-dashboard" element={page('/academics-dashboard', <DashboardPage user={user} />)} />
        {/* A tutor's Admissions Dashboard: the Demo and Diagnostic bookings they are assigned, at a glance. */}
        <Route
          path="/admissions-dashboard"
          element={page('/admissions-dashboard', <TutorAdmissionsDashboardPage user={user} />)}
        />
        <Route path="/students" element={page('/students', <StudentsPage user={user} />)} />
        {/* One student's full record. Scoped by the API: a mentor or tutor
            opening someone else's student gets a 404. */}
        <Route path="/students/:studentId" element={page('/students', <StudentProfilePage user={user} />)} />
        <Route path="/sessions" element={page('/sessions', <SessionsPage user={user} />)} />
        {/* Exams are a mentor <-> student affair; tutors hold no exam permission. */}
        <Route path="/exams" element={page('/exams', <ExamsPage user={user} />)} />
        {/* Homework review for every staff role; the tutor grades. */}
        <Route path="/homework" element={page('/homework', <HomeworkPage user={user} />)} />
        {/* The former per-role staff pages: Team now manages all
            staff, so old links land on it with the role filtered. */}
        <Route path="/admins" element={<Navigate to="/team?role=ADMIN" replace />} />
        <Route path="/mentors" element={<Navigate to="/team?role=MENTOR" replace />} />
        <Route path="/tutors" element={<Navigate to="/team?role=TUTOR" replace />} />
        <Route path="/invitations" element={page('/invitations', <InvitationsPage user={user} />)} />
        {/* Team Management: holders of accounts.manage_team manage staff
            accounts; staff granted accounts.view_team get the read-only
            directory. The API enforces both. */}
        <Route path="/team" element={page('/team', <TeamPage user={user} />)} />
        <Route path="/team/:memberId" element={page('/team', <TeamMemberPage user={user} />)} />
        {/* The API pins whoever holds only view_own_activity to their own entries.
            A BDE gets their own Activity instead, built on the BDE workspace's APIs. */}
        <Route
          path="/activity"
          element={page('/activity', isBde(user) ? <BdeActivityPage /> : <ActivityPage user={user} />)}
        />
        {/* Demo and Diagnostic bookings for administrators: every booking and
            the tutor teaching it, a page per type (Demo's with its Re-Demo
            requests at ?tab=redemo), each booking opening in its own workspace
            (/bookings/<type>/<id>, below). Each is
            keyed by its type, so moving between them never shows the other's
            rows; the former single page's links (/bookings?type=...) land on
            their type's. The API enforces accounts.view_all_bookings, and
            accounts.assign_booking_tutor for changing a tutor. */}
        <Route path="/bookings" element={page('/bookings', <LegacyBookings />)} />
        <Route
          path="/bookings/demo"
          element={page('/bookings/demo', <BookingsPage key="DEMO" user={user} type="DEMO" />)}
        />
        <Route
          path="/bookings/diagnostic"
          element={page('/bookings/diagnostic', <BookingsPage key="DIAGNOSTIC" user={user} type="DIAGNOSTIC" />)}
        />
        {/* One booking in full, its workspace: opened from its type's list (a
            former ?booking=<id> link lands here too), on the same permission. */}
        <Route
          path="/bookings/demo/:bookingId"
          element={page('/bookings/demo', <BookingWorkspacePage key="DEMO" user={user} type="DEMO" />)}
        />
        {/* One Re-Demo request in full, its workspace: opened from Demo Bookings' Re-Demo requests or a
            booking's workspace (a former ?tab=redemo&redemo=<id> link lands here too), on the same permission. */}
        <Route
          path="/bookings/demo/redemos/:redemoId"
          element={page('/bookings/demo', <RedemoWorkspacePage user={user} />)}
        />
        <Route
          path="/bookings/diagnostic/:bookingId"
          element={page('/bookings/diagnostic', <BookingWorkspacePage key="DIAGNOSTIC" user={user} type="DIAGNOSTIC" />)}
        />
        {/* Booking slots for administrators: close or reopen the Demo and
            Diagnostic slots parents book. The API enforces the same permission
            and keeps every booking. */}
        <Route path="/booking-slots" element={page('/booking-slots', <BookingSlotsPage />)} />
        {/* A tutor's own Demo and Diagnostic bookings: a page per type, each
            keyed by its type so moving between them never shows the other's
            rows, and each booking in its own workspace. The former single page's
            links (/my-bookings, ?booking=<id>&booking_type=<type>) land on their
            type's page or their booking. The API serves only the bookings
            assigned to the caller: any other is answered as one that does not exist. */}
        <Route path="/my-bookings" element={page('/my-bookings', <LegacyTutorBookings />)} />
        <Route
          path="/my-bookings/demo"
          element={page('/my-bookings/demo', <TutorBookingsPage key="DEMO" type="DEMO" />)}
        />
        <Route
          path="/my-bookings/diagnostic"
          element={page('/my-bookings/diagnostic', <TutorBookingsPage key="DIAGNOSTIC" type="DIAGNOSTIC" />)}
        />
        <Route
          path="/my-bookings/demo/:bookingId"
          element={page('/my-bookings/demo', <TutorBookingWorkspacePage key="DEMO" type="DEMO" />)}
        />
        <Route
          path="/my-bookings/diagnostic/:bookingId"
          element={page('/my-bookings/diagnostic', <TutorBookingWorkspacePage key="DIAGNOSTIC" type="DIAGNOSTIC" />)}
        />
        {/* The report on one of those bookings -- a Demo's feedback, a
            Diagnostic's results: written once its class has started, edited
            after (each save a new version), previewed as its PDF. The API
            serves it only to the booking's assigned tutor. */}
        <Route
          path="/my-bookings/:bookingType/:bookingId/report"
          element={page('/my-bookings', <TutorReportPage user={user} />)}
        />
        {/* The Tutor Hub's Hourly Earnings, still to come: nothing behind it yet. */}
        <Route path="/hourly-earnings" element={page('/hourly-earnings', <ComingSoonPage module="hourlyEarnings" />)} />
        {/* A BDE's booking links are shared from their dashboard now (the
            Share Demo / Diagnostic Link cards), so the former page's address
            lands there. */}
        <Route path="/booking-links" element={<Navigate to="/dashboard" replace />} />
        {/* Every lead and its owner BDE, for administrators. */}
        <Route path="/leads" element={page('/leads', <LeadsPage user={user} />)} />
        <Route path="/leads/:leadId" element={page('/leads', <LeadPage user={user} />)} />
        {/* The admissions pipeline for administrators: leads and bookings over
            a date range, today's bookings and what awaits action. */}
        <Route path="/admissions" element={page('/admissions', <AdmissionsDashboardPage user={user} />)} />
        {/* A BDE's own enquiries (My Enquiries). The API serves each BDE only theirs:
            another BDE's enquiry is answered as one that does not exist. */}
        <Route path="/enquiries" element={page('/enquiries', <EnquiriesPage user={user} />)} />
        <Route path="/enquiries/:enquiryId" element={page('/enquiries', <EnquiryPage user={user} />)} />
        {/* The rest of the BDE workspace: the Demo and Diagnostic bookings made
            for their enquiries (each opening in its enquiry's workspace), what to
            follow up (which sends the BDE to the enquiry pages until its own list
            arrives), and My Sales and Plans & Pricing, which are still to come.
            Each booking list is keyed by its type, so moving between them never
            shows the other's rows. */}
        <Route path="/demo-bookings" element={page('/demo-bookings', <BdeBookingsPage key="DEMO" user={user} type="DEMO" />)} />
        <Route
          path="/diagnostic-bookings"
          element={page('/diagnostic-bookings', <BdeBookingsPage key="DIAGNOSTIC" user={user} type="DIAGNOSTIC" />)}
        />
        <Route path="/follow-ups" element={page('/follow-ups', <FollowUpsPage />)} />
        <Route path="/sales" element={page('/sales', <ComingSoonPage module="sales" />)} />
        {/* Plans & Pricing: the catalogue on sale, and one plan quoted (a Bridge Course by the day too). */}
        <Route path="/plans" element={page('/plans', <PlansPage />)} />
        <Route path="/plans/:syllabusId" element={page('/plans', <PlanPage />)} />
        {/* Quotes: a BDE's own, or every one for an administrator, and one quote as it was issued. */}
        <Route path="/quotes" element={page('/quotes', <QuotesPage user={user} />)} />
        <Route path="/quotes/:quoteId" element={page('/quotes', <QuotePage user={user} />)} />
        {/* The Admin Hub's Sales & Finance modules still to come: nothing behind them yet. */}
        <Route path="/sales-dashboard" element={page('/sales-dashboard', <ComingSoonPage module="salesDashboard" />)} />
        <Route path="/sales-module" element={page('/sales-module', <ComingSoonPage module="salesModule" />)} />
        <Route path="/sales-punching" element={page('/sales-punching', <ComingSoonPage module="salesPunching" />)} />
        {/* Syllabus & Plans: every syllabus, a new one, one, and its draft (keyed apart, so saving a
            new syllabus and opening its draft starts the editor afresh); and the Global Pricing. */}
        <Route path="/sales-syllabus" element={page('/sales-syllabus', <SalesSyllabiPage user={user} />)} />
        <Route path="/sales-syllabus/new" element={page('/sales-syllabus', <SalesSyllabusEditorPage key="new" />)} />
        <Route path="/sales-syllabus/:syllabusId" element={page('/sales-syllabus', <SalesSyllabusPage />)} />
        <Route
          path="/sales-syllabus/:syllabusId/edit"
          element={page('/sales-syllabus', <SalesSyllabusEditorPage key="edit" />)}
        />
        <Route path="/sales-pricing" element={page('/sales-pricing', <SalesPricingPage />)} />
        <Route path="/tutor-earnings" element={page('/tutor-earnings', <ComingSoonPage module="tutorEarnings" />)} />
        <Route path="*" element={<Navigate to={home} replace />} />
      </Routes>
    </SidebarLayout>
  );
}

// Router Entry App
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/payment-return" element={<PaymentReturnPage />} />
        <Route path="/autopay/confirm/:token" element={<AutopayActionPage />} />
        {/* A temporary password must be replaced before anything else: this
            page stands alone (no sidebar), and every other Hub route sends an
            account with must_change_password here. The API enforces the same. */}
        <Route
          path="/change-password"
          element={<AuthProvider>{({ user, logout }) => <ChangePasswordPage user={user} logout={logout} />}</AuthProvider>}
        />
        <Route path="/*" element={<AuthProvider>{({ user, logout }) => <HubRoutes user={user} logout={logout} />}</AuthProvider>} />
      </Routes>
    </BrowserRouter>
  );
}
