import { ClipboardList } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { ADDITIONAL_STATUS_VARIANT, additionalExamStatusLabel } from '@/lib/exam-status';
import { ResultCell } from './result-cell';

/** Card table of a student's additional exams (the Hub's AdditionalExamsTable). */
export function AdditionalExamsTable({ rows, showStudent = false, onOpen }) {
  return (
    <div className="border border-[rgba(255,255,255,0.08)] bg-[#0a0a0a] rounded-xl shadow-xl overflow-x-auto w-full">
      {rows.length === 0 ? (
        <div className="py-12 text-center">
          <ClipboardList className="w-8 h-8 mx-auto text-zinc-600 mb-3" />
          <p className="text-zinc-500 text-sm">No additional exams.</p>
        </div>
      ) : (
        <table className="w-full text-left border-collapse text-sm">
          <thead>
            <tr className="border-b border-[rgba(255,255,255,0.08)] bg-[#0f0f0f]">
              <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Title</th>
              {showStudent && <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Student</th>}
              <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Status</th>
              <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Score</th>
              <th className="h-12 px-4 font-semibold text-xs text-zinc-400 align-middle">Created</th>
              <th className="h-12 px-4 w-32"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const status = (r.status || '').toLowerCase();
              return (
                <tr key={r.id} className="hover:bg-[rgba(255,255,255,0.02)] border-b border-[rgba(255,255,255,0.08)] h-[54px] transition-colors">
                  <td className="py-2 px-4 align-middle font-semibold text-white">{r.title}</td>
                  {showStudent && (
                    <td className="py-2 px-4 align-middle">
                      <div className="flex flex-col gap-0.5">
                        <span className="font-medium text-white text-sm">{r.students?.full_name || '—'}</span>
                        <span className="text-xs text-[#a1a1aa] font-mono">{r.students?.student_code || ''}</span>
                      </div>
                    </td>
                  )}
                  <td className="py-2 px-4 align-middle">
                    <Badge variant={ADDITIONAL_STATUS_VARIANT[status] || 'secondary'}>{additionalExamStatusLabel(r)}</Badge>
                  </td>
                  <td className="py-2 px-4 align-middle">
                    <ResultCell score={r.score} maxScore={r.max_score} />
                  </td>
                  <td className="py-2 px-4 align-middle text-zinc-300 whitespace-nowrap">{new Date(r.created_at).toLocaleDateString()}</td>
                  <td className="py-2 px-4 align-middle text-right">
                    <button
                      type="button"
                      onClick={() => onOpen(r)}
                      className="inline-flex items-center h-7 px-2.5 rounded-md border border-white/10 bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-zinc-200 hover:text-white whitespace-nowrap transition-colors"
                    >
                      {status === 'submitted' ? 'Review & score' : 'View'}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
