import { Sidebar } from '../navigation/sidebar';
import { BottomNav } from '../navigation/bottom-nav';
import { EnrollmentBanner } from './enrollment-banner';

export function AppShell({ children }) {
  return (
    <div className="bg-surface min-h-dvh md:flex">
      <Sidebar />
      <main className="min-h-dvh min-w-0 flex-1">
        <div className="mx-auto w-full max-w-2xl px-4 pt-4 pb-28 md:max-w-3xl md:px-6 md:pt-6 md:pb-8 lg:max-w-2xl lg:px-8 lg:pt-8 lg:pb-8">
          <EnrollmentBanner />
          {children}
        </div>
      </main>
      <BottomNav />
    </div>
  );
}
