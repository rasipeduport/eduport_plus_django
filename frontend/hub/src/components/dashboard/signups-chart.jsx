import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';

import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

const chartConfig = {
  signups: {
    label: 'New Students',
    color: 'var(--primary)',
  },
};

export function SignupsChart({ data }) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>New Enrollments</CardTitle>
        <CardDescription>Student sign-ups over the last 7 days</CardDescription>
      </CardHeader>
      <CardContent>
        <div style={{ height: 240 }}>
          <ChartContainer config={chartConfig} className="h-full w-full">
            <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={8} tick={{ fontSize: 12 }} />
              <YAxis tickLine={false} axisLine={false} allowDecimals={false} tickMargin={8} tick={{ fontSize: 12 }} />
              <ChartTooltip cursor={false} content={<ChartTooltipContent hideLabel />} />
              <Bar dataKey="signups" fill="var(--color-signups)" radius={4} />
            </BarChart>
          </ChartContainer>
        </div>
      </CardContent>
    </Card>
  );
}
