import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDate } from '@/lib/utils';

export function RecentSignups({ data }) {
  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <CardTitle>Recent Sign-ups</CardTitle>
        <CardDescription>The last 5 students who enrolled</CardDescription>
      </CardHeader>
      <CardContent className="flex-1 p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Student ID</TableHead>
              <TableHead>Name</TableHead>
              <TableHead className="text-right">Joined At</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={3} className="text-muted-foreground py-10 text-center text-sm">
                  No recent sign-ups.
                </TableCell>
              </TableRow>
            ) : (
              data.map((s) => (
                <TableRow key={s.student_code}>
                  <TableCell className="text-muted-foreground font-mono text-xs">{s.student_code}</TableCell>
                  <TableCell className="font-medium">{s.full_name}</TableCell>
                  <TableCell className="text-muted-foreground text-right text-sm">{formatDate(s.created_at)}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
