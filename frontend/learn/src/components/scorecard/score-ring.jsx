import { motion } from 'framer-motion';
import { Sparkles, TrendingDown, TrendingUp } from 'lucide-react';
import { cn } from '../../lib/utils';
import { scoreTone } from '../../lib/exam-status';

const MILESTONE_THRESHOLD = 90;

/** Animated percentage gauge with the delta chip and the milestone moment (Learn ScoreRing). */
export function ScoreRing({ value, delta, size = 160, label = 'Overall' }) {
  const r = (size - 14) / 2;
  const c = 2 * Math.PI * r;
  const pct = value == null ? 0 : Math.max(0, Math.min(100, value));
  const tone = value == null ? null : scoreTone(value);
  const isMilestone = value != null && value >= MILESTONE_THRESHOLD;

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-border-light)" strokeWidth="10" />
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={tone ? tone.stroke : 'var(--color-border)'}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={c}
            initial={{ strokeDashoffset: c }}
            animate={{ strokeDashoffset: c - (c * pct) / 100 }}
            transition={{ duration: 0.9, ease: 'easeOut' }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn('text-4xl font-bold tabular-nums', tone ? tone.text : 'text-text-muted')}>{value == null ? '–' : `${value}%`}</span>
          <span className="text-text-muted text-xs">{label}</span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {delta != null && (
          <span
            className={cn(
              'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold',
              delta >= 0 ? 'border-primary/15 bg-primary-subtle text-primary-hover' : 'border-danger/15 bg-danger-subtle text-danger'
            )}
          >
            {delta >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {delta > 0 ? '+' : ''}
            {delta} pts
          </span>
        )}
        {isMilestone && (
          <motion.span initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.8, type: 'spring' }} className="border-warning/20 bg-warning-subtle text-warning inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold">
            <Sparkles className="h-3 w-3" />
            Excellent work!
          </motion.span>
        )}
      </div>
    </div>
  );
}
