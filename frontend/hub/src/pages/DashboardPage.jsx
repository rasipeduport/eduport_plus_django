import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import api from '@/lib/api';
import { SectionCards } from '@/components/dashboard/section-cards';
import { SignupsChart } from '@/components/dashboard/signups-chart';
import { RecentSignups } from '@/components/dashboard/recent-signups';

export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    (async () => {
      try {
        const response = await api.get('/api/dashboard/stats/');
        if (active) setStats(response.data);
      } catch (error) {
        console.error('Stats loading failed', error);
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="text-muted-foreground size-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="container mx-auto flex flex-col gap-6 px-4 py-16">
      <SectionCards stats={stats} />
      <div className="flex flex-col gap-6 md:flex-row">
        <div className="flex-1">
          <SignupsChart data={stats?.signup_data ?? []} />
        </div>
        <div className="flex-1">
          <RecentSignups data={stats?.recent_signups ?? []} />
        </div>
      </div>
    </div>
  );
}
