import { Link } from 'react-router-dom';
import { ArrowLeftIcon, BadgePercent, ReceiptIndianRupee } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Page } from '@/components/page/page';
import { ComingSoon } from '@/components/page/coming-soon';

// The BDE workspace's modules still to come: offered in the sidebar with a
// Coming Soon badge, and nothing behind them yet but this page.
const MODULES = {
  sales: {
    icon: ReceiptIndianRupee,
    title: 'My Sales',
    description: 'Track conversions, payments and your sales performance in one place.',
  },
  plans: {
    icon: BadgePercent,
    title: 'Plans & Pricing',
    description: 'Browse Eduport Plus plans and their pricing, ready to share with parents.',
  },
};

/** The Coming Soon page of `module` (a key of MODULES). */
export default function ComingSoonPage({ module }) {
  const { icon, title, description } = MODULES[module];
  return (
    <Page>
      <ComingSoon
        variant={module}
        icon={icon}
        title={title}
        description={description}
        action={
          <Button variant="outline" asChild>
            <Link to="/dashboard">
              <ArrowLeftIcon />
              Back to Dashboard
            </Link>
          </Button>
        }
      />
    </Page>
  );
}
