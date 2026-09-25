import StaffManagementPage from './StaffManagementPage';

const config = {
  variant: 'tutor',
  entityLabel: 'Tutor',
  endpoint: '/api/tutors/?all=true',
  responseKey: 'tutors',
  initialRole: 'TUTOR',
};

export default function TutorsPage() {
  return <StaffManagementPage config={config} />;
}
