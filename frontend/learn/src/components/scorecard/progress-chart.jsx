import { useState } from 'react';

const SERIES = [
  { key: 'exam', label: 'Chapter Exams', color: 'var(--color-primary)' },
  { key: 'homework', label: 'Homework', color: 'var(--color-info)' },
];

/** Hand-rolled SVG trend: one line per category over the buckets; null buckets break the line (Learn ProgressChart). */
export function ProgressChart({ buckets }) {
  const [hover, setHover] = useState(null);
  const width = 640;
  const height = 220;
  const pad = { t: 16, r: 16, b: 32, l: 36 };
  const plotW = width - pad.l - pad.r;
  const plotH = height - pad.t - pad.b;
  const n = buckets.length;
  const xAt = (i) => pad.l + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const yAt = (v) => pad.t + (1 - Math.max(0, Math.min(100, v)) / 100) * plotH;

  const pathFor = (key) => {
    let d = '';
    let open = false;
    buckets.forEach((b, i) => {
      const v = b[key];
      if (v == null) {
        open = false;
        return;
      }
      d += `${open ? 'L' : 'M'}${xAt(i)} ${yAt(v)} `;
      open = true;
    });
    return d.trim();
  };

  const visible = SERIES.filter((s) => buckets.some((b) => b[s.key] != null));

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-4">
        {visible.map((s) => (
          <span key={s.key} className="text-text-muted inline-flex items-center gap-1.5 text-xs">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full min-w-[320px]" role="img" aria-label="Score trend">
          {[0, 50, 100].map((g) => (
            <g key={g}>
              <line x1={pad.l} x2={width - pad.r} y1={yAt(g)} y2={yAt(g)} stroke="var(--color-border-light)" strokeDasharray={g === 0 ? undefined : '3 4'} />
              <text x={pad.l - 8} y={yAt(g) + 4} textAnchor="end" fontSize="10" fill="var(--color-text-muted)">
                {g}
              </text>
            </g>
          ))}
          {visible.map((s) => (
            <path key={s.key} d={pathFor(s.key)} fill="none" stroke={s.color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          ))}
          {buckets.map((b, i) => (
            <g key={b.key} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={xAt(i) - (n > 1 ? plotW / (n - 1) / 2 : plotW / 2)} y={pad.t} width={n > 1 ? plotW / (n - 1) : plotW} height={plotH} fill="transparent" />
              {visible.map((s) => b[s.key] != null && <circle key={s.key} cx={xAt(i)} cy={yAt(b[s.key])} r={hover === i ? 5 : 3.5} fill={s.color} />)}
              <text x={xAt(i)} y={height - 10} textAnchor="middle" fontSize="10" fill="var(--color-text-muted)">
                {b.label}
              </text>
            </g>
          ))}
          {hover != null && (
            <g>
              <rect x={Math.min(width - 130, Math.max(pad.l, xAt(hover) - 60))} y={pad.t} width={120} height={14 + visible.length * 14} rx="6" fill="var(--color-surface-elevated)" stroke="var(--color-border)" />
              {visible.map((s, j) => (
                <text key={s.key} x={Math.min(width - 130, Math.max(pad.l, xAt(hover) - 60)) + 8} y={pad.t + 14 + j * 14} fontSize="10" fill="var(--color-text-primary)">
                  {s.label}: {buckets[hover][s.key] == null ? '–' : `${buckets[hover][s.key]}%`}
                </text>
              ))}
            </g>
          )}
        </svg>
      </div>
    </div>
  );
}
