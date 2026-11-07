import { Link } from 'react-router-dom';
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  BadgePercent,
  BookMarked,
  Briefcase,
  ChartColumn,
  ClipboardPen,
  LayoutDashboard,
  ReceiptIndianRupee,
  Wallet,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Page } from '@/components/page/page';
import { ComingSoon } from '@/components/page/coming-soon';

// The modules still to come -- the BDE workspace's, then the Admin Hub's
// common Dashboard and Sales & Finance -- each offered in the sidebar, and
// nothing behind it yet but this page. `variant` picks the card beside the
// mascot (components/page/coming-soon): a chart filling in, or plans. The page
// leads back to the Dashboard, or -- for the Dashboard itself -- on to `next`.
const MODULES = {
  sales: {
    icon: ReceiptIndianRupee,
    title: 'My Sales',
    description: 'Track conversions, payments and your sales performance in one place.',
    variant: 'sales',
  },
  plans: {
    icon: BadgePercent,
    title: 'Plans & Pricing',
    description: 'Browse Eduport Plus plans and their pricing, ready to share with parents.',
    variant: 'plans',
  },
  dashboard: {
    icon: LayoutDashboard,
    title: 'Dashboard',
    description: 'One overview of Eduport Plus: admissions, academics and sales together at a glance.',
    variant: 'sales',
    next: { to: '/academics-dashboard', label: 'Open the Academics Dashboard' },
  },
  salesDashboard: {
    icon: ChartColumn,
    title: 'Sales Dashboard',
    description: 'Sales performance across the team: conversions, revenue and targets at a glance.',
    variant: 'sales',
  },
  salesModule: {
    icon: Briefcase,
    title: 'Sales Module',
    description: 'Manage the sales pipeline from a completed demo to an enrolled student.',
    variant: 'plans',
  },
  salesPunching: {
    icon: ClipboardPen,
    title: 'Sales Punching',
    description: 'Record each sale as it closes: the plan, the payment and the BDE who made it.',
    variant: 'plans',
  },
  salesSyllabus: {
    icon: BookMarked,
    title: 'Sales Syllabus',
    description: 'The courses and syllabuses offered to parents, with what each plan includes.',
    variant: 'plans',
  },
  tutorEarnings: {
    icon: Wallet,
    title: 'Tutor Earnings',
    description: 'What each tutor has earned for the classes they taught, month by month.',
    variant: 'sales',
  },
};

/** The Coming Soon page of `module` (a key of MODULES). */
export default function ComingSoonPage({ module }) {
  const { icon, title, description, variant, next } = MODULES[module];
  return (
    <Page>
      <ComingSoon
        variant={variant}
        icon={icon}
        title={title}
        description={description}
        action={
          <Button variant="outline" asChild>
            {next ? (
              <Link to={next.to}>
                {next.label}
                <ArrowRightIcon />
              </Link>
            ) : (
              <Link to="/dashboard">
                <ArrowLeftIcon />
                Back to Dashboard
              </Link>
            )}
          </Button>
        }
      />
    </Page>
  );
}
