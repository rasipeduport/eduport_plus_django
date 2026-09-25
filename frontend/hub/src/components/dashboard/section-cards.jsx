import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export function SectionCards({ stats }) {
  const cards = [
    { label: 'Total Enrollments', value: stats?.students ?? 0 },
    { label: 'Active Households', value: stats?.students ?? 0 },
    { label: 'Pending Invites', value: stats?.pending_invitations ?? 0 },
  ];

  return (
    <div className="flex flex-col gap-4 md:flex-row">
      {cards.map((card) => (
        <Card key={card.label} className="flex-1">
          <CardHeader>
            <CardDescription>{card.label}</CardDescription>
            <CardTitle className="text-3xl font-semibold tabular-nums">{card.value}</CardTitle>
          </CardHeader>
        </Card>
      ))}
    </div>
  );
}
