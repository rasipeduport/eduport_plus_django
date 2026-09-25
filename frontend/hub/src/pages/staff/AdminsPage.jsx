import StaffManagementPage from './StaffManagementPage';

const config = {
  variant: 'admin',
  entityLabel: 'Admin',
  endpoint: '/api/admins/',
  responseKey: 'admins',
  initialRole: 'ADMIN',
};

export default function AdminsPage() {
  return <StaffManagementPage config={config} />;
}
