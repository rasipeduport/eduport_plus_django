import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

/** A revision's chapter table, as the PDF prints it, with its totals. */
export function ChapterTable({ revision }) {
  const bridge = revision.structure === 'BRIDGE_COURSE';
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-16">{bridge ? 'Day' : 'SL'}</TableHead>
            <TableHead>Chapter name</TableHead>
            {bridge ? (
              <TableHead className="w-28">Classes</TableHead>
            ) : (
              <>
                <TableHead className="w-32">Regular classes</TableHead>
                <TableHead className="w-32">Revision classes</TableHead>
              </>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {revision.chapters.map((chapter) => (
            <TableRow key={chapter.id ?? chapter.position}>
              <TableCell className="tabular-nums">{chapter.position}</TableCell>
              <TableCell className="whitespace-normal">{chapter.name}</TableCell>
              {bridge ? (
                <TableCell className="tabular-nums">{chapter.bridge_classes}</TableCell>
              ) : (
                <>
                  <TableCell className="tabular-nums">{chapter.regular_classes}</TableCell>
                  <TableCell className="tabular-nums">{chapter.revision_classes}</TableCell>
                </>
              )}
            </TableRow>
          ))}
          <TableRow className="bg-muted/50 font-medium">
            <TableCell />
            <TableCell>Total</TableCell>
            {bridge ? (
              <TableCell className="tabular-nums">{revision.totals.bridge}</TableCell>
            ) : (
              <>
                <TableCell className="tabular-nums">{revision.totals.regular}</TableCell>
                <TableCell className="tabular-nums">{revision.totals.revision}</TableCell>
              </>
            )}
          </TableRow>
        </TableBody>
      </Table>
    </div>
  );
}
