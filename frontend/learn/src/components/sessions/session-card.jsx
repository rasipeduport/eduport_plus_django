import { Calendar, Clock, User, GraduationCap, Play, FileText, BookOpen, ChevronDown, Star, CheckCircle2, AlertCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { Link } from 'react-router-dom';
import { Card } from '../ui/card';
import { homeworkStatusBadge } from '../../lib/homework-status';
import { cn } from '../../lib/utils';
import { formatSessionDateTime } from '../../lib/formatting';
import { useStudentZone } from '../student/student-context';
import { useSessionRating } from '../../hooks/useSessionRating';

export function SessionCard({ session, isExpanded, onToggle }) {
  const zone = useStudentZone();
  const attended = session.status === 'attended';
  const { dateLabel, timeLabel } = formatSessionDateTime(
    session.start_time,
    session.end_time,
    zone
  );

  // Which required items are still missing. The API's `missing_content` is
  // the source of truth; a payload without it falls back to the link itself.
  const isMissing = (key, href) =>
    Array.isArray(session.missing_content) ? session.missing_content.includes(key) : !href;

  // Every attended class lists all three items: a missing one is shown as
  // missing rather than dropped, so the student can see what is still to come.
  const resourceLinks = attended
    ? [
        {
          key: 'recording',
          href: session.recording_link,
          icon: Play,
          label: 'Recording',
          color: 'text-primary',
          bg: 'bg-primary-subtle',
          hover: 'hover:border-primary/40 hover:bg-primary/5'
        },
        {
          key: 'notes',
          href: session.notes_link,
          icon: FileText,
          label: 'Notes',
          color: 'text-info',
          bg: 'bg-info-subtle',
          hover: 'hover:border-info/40 hover:bg-info/5'
        },
        {
          key: 'homework',
          href: session.homework_link,
          icon: BookOpen,
          label: 'Homework',
          color: 'text-warning',
          bg: 'bg-warning-subtle',
          hover: 'hover:border-warning/40 hover:bg-warning/5',
          // The lifecycle row behind the link: the tile opens the homework
          // detail (submit / status / score) instead of the raw link.
          to: session.homework ? `/homework/${session.homework.id}` : null,
          sub: session.homework ? homeworkStatusBadge(session.homework).label : null
        }
      ].map((r) => ({ ...r, missing: r.to ? false : isMissing(r.key, r.href) }))
    : [];
  const missingCount = resourceLinks.filter((r) => r.missing).length;

  const { isRated, rating, hoverRating, setHoverRating, isSubmitting, showSuccess, handleRate } = useSessionRating(session);

  return (
    <Card padding="md" className="transition-all duration-200">
      {/* Header / Unexpanded View */}
      <div
        className={cn(
          'flex items-start gap-3.5',
          attended && 'group cursor-pointer select-none'
        )}
        onClick={() => attended && onToggle?.()}
      >
        {/* Left icon badge */}
        <div
          className={cn(
            'flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl transition-colors',
            attended
              ? 'bg-primary-subtle group-hover:bg-primary/20'
              : 'bg-info-subtle'
          )}
        >
          <Calendar
            className={cn(
              'h-5 w-5',
              attended ? 'text-primary' : 'text-info'
            )}
          />
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 flex-1 basis-32">
              <p className="text-text-primary line-clamp-2 text-[15px] leading-snug font-semibold break-words">
                {session.title}
              </p>
              {/* Meta row */}
              <div className="text-text-muted mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <span className="inline-flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5" />
                  <span>
                    {dateLabel}, {timeLabel}
                  </span>
                </span>
                {session.tutor_profile?.full_name && (
                  <span className="inline-flex items-center gap-1">
                    <User className="h-3.5 w-3.5" />
                    {session.tutor_profile.full_name}
                  </span>
                )}
                {session.students?.mentor_profile?.full_name && (
                  <span className="inline-flex items-center gap-1">
                    <GraduationCap className="h-3.5 w-3.5" />
                    {session.students.mentor_profile.full_name}
                  </span>
                )}
              </div>
            </div>

            <div className="ml-auto flex shrink-0 items-center gap-3">
              <span
                className={cn(
                  'shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap',
                  session.status === 'cancelled'
                    ? 'border-danger/15 bg-danger-subtle text-danger'
                    : attended
                    ? 'border-primary/15 bg-primary-subtle text-primary-hover'
                    : 'border-info/15 bg-info-subtle text-info'
                )}
              >
                {session.status === 'cancelled' ? 'Cancelled' : attended ? 'Attended' : 'Scheduled'}
              </span>
              {attended && (
                <button
                  type="button"
                  className="text-text-muted hover:bg-surface-elevated flex h-8 w-8 items-center justify-center rounded-full transition-colors cursor-pointer"
                  aria-label="Toggle details"
                >
                  <ChevronDown
                    className={cn(
                      'h-5 w-5 transition-transform duration-300',
                      isExpanded && 'text-primary -rotate-180'
                    )}
                  />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Expanded View */}
      <AnimatePresence>
        {isExpanded && attended && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="overflow-hidden"
          >
            <div className="pt-4 pb-1">
              <div className="border-border-light mb-4 border-t" />

              {/* Resources */}
              {resourceLinks.length > 0 && (
                <div className="mb-4">
                  <div className="grid grid-cols-3 gap-3">
                    {resourceLinks.map(
                      ({ key, href, icon: Icon, label, color, bg, hover, missing, to, sub }) =>
                        to ? (
                          <Link
                            key={key}
                            to={to}
                            className={cn(
                              'group border-border-light bg-surface-muted flex flex-col items-center justify-center gap-2.5 rounded-xl border p-3 text-center transition-all duration-200',
                              hover
                            )}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <div className={cn('flex h-9 w-9 items-center justify-center rounded-xl transition-transform group-hover:scale-110', bg)}>
                              <Icon className={cn('h-4 w-4', color)} />
                            </div>
                            <span className="text-text-primary text-xs font-semibold">{label}</span>
                            {sub && <span className="text-text-muted -mt-1.5 text-[11px]">{sub}</span>}
                          </Link>
                        ) : missing ? (
                          <div
                            key={key}
                            role="status"
                            aria-label={`${label} missing`}
                            className="border-danger/20 bg-danger-subtle flex flex-col items-center justify-center gap-2.5 rounded-xl border border-dashed p-3 text-center"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <div className="bg-danger-light flex h-9 w-9 items-center justify-center rounded-xl">
                              <AlertCircle className="text-danger h-4 w-4" />
                            </div>
                            <span className="text-text-primary text-xs font-semibold">
                              {label}
                            </span>
                            <span className="text-danger -mt-1.5 text-[11px] font-semibold">
                              Missing
                            </span>
                          </div>
                        ) : (
                          <a
                            key={key}
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={cn(
                              'group border-border-light bg-surface-muted flex flex-col items-center justify-center gap-2.5 rounded-xl border p-3 text-center transition-all duration-200',
                              hover
                            )}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <div
                              className={cn(
                                'flex h-9 w-9 items-center justify-center rounded-xl transition-transform group-hover:scale-110',
                                bg
                              )}
                            >
                              <Icon className={cn('h-4 w-4', color)} />
                            </div>
                            <span className="text-text-primary text-xs font-semibold">
                              {label}
                            </span>
                          </a>
                        )
                    )}
                  </div>
                  {missingCount > 0 && (
                    <p className="text-text-muted mt-2 text-[11px]">
                      Missing items will appear here as soon as they are added.
                    </p>
                  )}
                </div>
              )}

              {/* Rating Section */}
              {!isRated || showSuccess ? (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden"
                >
                  <div
                    className="border-primary/10 bg-primary-subtle/70 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-xl border px-4 py-3"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="text-primary-hover text-sm font-semibold">
                      {showSuccess ? 'Thanks for rating!' : 'Rate your class'}
                    </div>
                    <div className="flex items-center gap-1">
                      {showSuccess ? (
                        <motion.div
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                        >
                          <CheckCircle2 className="text-primary h-6 w-6" />
                        </motion.div>
                      ) : (
                        [1, 2, 3, 4, 5].map((star) => (
                          <button
                            key={star}
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRate(star);
                            }}
                            onMouseEnter={() => setHoverRating(star)}
                            onMouseLeave={() => setHoverRating(0)}
                            disabled={isSubmitting}
                            className={cn(
                              'flex h-9 w-8 items-center justify-center rounded-full transition-transform hover:scale-110 focus:outline-none cursor-pointer',
                              isSubmitting && 'cursor-not-allowed opacity-50'
                            )}
                          >
                            <Star
                              className={cn(
                                'h-6 w-6',
                                star <= (hoverRating || rating)
                                  ? 'text-warning fill-warning'
                                  : 'text-text-muted/40 hover:text-warning/70'
                              )}
                            />
                          </button>
                        ))
                      )}
                    </div>
                  </div>
                </motion.div>
              ) : (
                <div className="border-border-light bg-surface-muted/50 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-xl border px-4 py-3">
                  <div className="text-text-muted text-sm font-medium">
                    Your rating
                  </div>
                  <div className="flex items-center gap-1">
                    {[1, 2, 3, 4, 5].map((star) => (
                      <div key={star}>
                        <Star
                          className={cn(
                            'h-5 w-5',
                            star <= rating ? 'text-warning fill-warning/60' : 'text-text-muted/20'
                          )}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
