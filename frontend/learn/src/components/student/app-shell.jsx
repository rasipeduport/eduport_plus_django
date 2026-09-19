import { Sidebar } from '../navigation/sidebar';
import { BottomNav } from '../navigation/bottom-nav';
import { EnrollmentBanner } from './enrollment-banner';

export function AppShell({ children }) {
  return (
    <div className="bg-surface min-h-dvh md:flex">
      <Sidebar />
      <main className="min-h-dvh flex-1">
        <div className="mx-auto max-w-2xl px-4 pt-4 pb-28 md:px-6 md:pt-6 md:pb-8 lg:px-8 lg:pt-8 lg:pb-8">
          <EnrollmentBanner />
          {children}
        </div>
      </main>
      <BottomNav />
    </div>
  );
}
