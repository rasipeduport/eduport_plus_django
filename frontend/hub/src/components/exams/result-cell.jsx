import { cn } from '@/lib/utils';
import { scoreToneClass } from '@/lib/exam-status';

/**
 * An exam result as "X/Y", coloured by performance (green / amber / red on
 * the Learn thresholds). No percentage is shown. Without a usable score it
 * renders the usual dash, uncoloured. The status badge next to it stays a
 * lifecycle colour -- a green "Scored" beside a red "3/33" is intentional.
 */
export function ResultCell({ score, maxScore, className }) {
  const tone = scoreToneClass(score, maxScore);
  if (!tone) return <span className="text-muted-foreground">—</span>;
  return (
    <span className={cn('whitespace-nowrap font-medium tabular-nums', tone, className)}>
      {score}/{maxScore}
    </span>
  );
}
