import StaffManagementPage from './StaffManagementPage';

const config = {
  variant: 'mentor',
  entityLabel: 'Mentor',
  endpoint: '/api/mentors/?all=true',
  responseKey: 'mentors',
  initialRole: 'MENTOR',
};

export default function MentorsPage() {
  return <StaffManagementPage config={config} />;
}
