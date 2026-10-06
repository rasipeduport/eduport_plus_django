import { useNavigate } from 'react-router-dom';
import { LogOut, Users } from 'lucide-react';
import { useStudent } from '../components/student/student-context';
import { ProfileHeader } from '../components/profile/profile-header';
import { StudentInfoCard } from '../components/profile/student-info-card';
import { MentorCard } from '../components/profile/mentor-card';

export default function ProfilePage() {
  const { selectedStudent, students, user, dashboardStats, logout } = useStudent();
  const navigate = useNavigate();

  if (!selectedStudent) return null;

  const info = {
    mobile: selectedStudent.mobile_number || '—',
    email: user?.email || '—',
    school: selectedStudent.school_name || '—',
    region: [selectedStudent.state, selectedStudent.country].filter(Boolean).join(', ') || '—'
  };

  return (
    <div className="space-y-5 md:space-y-6">
      {/* Profile Header with Initials Avatar */}
      <ProfileHeader
        name={selectedStudent.full_name}
        grade={selectedStudent.grade || ''}
        avatarUrl={null}
      />

      {/* Info + mentor: two columns at tablet width, stacked on phones and desktop */}
      <div className="space-y-5 md:space-y-6 md:max-lg:grid md:max-lg:grid-cols-2 md:max-lg:items-start md:max-lg:gap-6 md:max-lg:space-y-0">
        {/* Student Information Details Card */}
        <StudentInfoCard info={info} />

        {/* Assigned Mentor Card */}
        <MentorCard
          mentorName={dashboardStats?.mentor}
          mentorEmail={dashboardStats?.mentor_email}
          mentorPhone={dashboardStats?.mentor_phone}
        />
      </div>

      {/* Log out actions */}
      <div className="space-y-3 pb-4">
        {students?.length > 1 && (
          <button
            onClick={() => navigate('/select-profile')}
            className="border-border bg-surface-elevated text-text-secondary hover:bg-surface-muted hover:text-text-primary flex h-11 w-full items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold transition-colors duration-150 cursor-pointer"
          >
            <Users className="h-4 w-4" />
            Switch Student
          </button>
        )}
        <button
          onClick={logout}
          className="border-border bg-surface-elevated text-text-secondary hover:bg-surface-muted hover:text-text-primary flex h-11 w-full items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold transition-colors duration-150 cursor-pointer"
        >
          <LogOut className="h-4 w-4" />
          Sign Out
        </button>
      </div>
    </div>
  );
}
