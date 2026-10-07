import { motion, AnimatePresence } from 'framer-motion';
import { Calendar, Clock, User, Play, FileText, BookOpen, Star, CheckCircle2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card } from '../ui/card';
import { homeworkStatusBadge } from '../../lib/homework-status';
import { cn } from '../../lib/utils';
import { formatSessionDateTime } from '../../lib/formatting';
import { useStudentZone } from '../student/student-context';
import { useSessionRating } from '../../hooks/useSessionRating';

export function LastClassCard({ session }) {
  const zone = useStudentZone();
  const { dateLabel, timeLabel } = formatSessionDateTime(
    session.start_time,
    session.end_time,
    zone,
    { relative: 'past' }
  );

  const { isRated, rating, hoverRating, setHoverRating, isSubmitting, showSuccess, handleRate } = useSessionRating(session);

  const resources = [
    {
      href: session.recording_link,
      icon: Play,
      label: 'Recording',
      color: 'text-primary',
      bg: 'bg-primary-subtle',
      hover: 'hover:border-primary/40 hover:bg-primary/5'
    },
    {
      href: session.notes_link,
      icon: FileText,
      label: 'Notes',
      color: 'text-info',
      bg: 'bg-info-subtle',
      hover: 'hover:border-info/40 hover:bg-info/5'
    },
    {
      href: session.homework_link,
      icon: BookOpen,
      label: 'Homework',
      color: 'text-warning',
      bg: 'bg-warning-subtle',
      hover: 'hover:border-warning/40 hover:bg-warning/5',
      to: session.homework ? `/homework/${session.homework.id}` : null,
      sub: session.homework ? homeworkStatusBadge(session.homework).label : null
    }
  ].filter((r) => r.href || r.to);

  return (
    <Card
      className="relative"
      style={{
        backgroundImage:
          'radial-gradient(circle at top right, rgb(255 214 91 / 0.16), transparent 55%)'
      }}
    >
      <div>
        {/* Header: Date + Title and Icon */}
        <div className="mb-3 flex items-start justify-between">
          <div>
            <span className="border-primary/15 bg-primary-subtle text-primary-hover inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold">
              {dateLabel}
            </span>
            <p className="text-text-primary mt-1.5 line-clamp-2 text-2xl font-bold tracking-tight">
              {session.title}
            </p>
          </div>
          <div className="bg-primary-subtle ml-4 flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl">
            <Calendar className="text-primary h-5 w-5" />
          </div>
        </div>

        {/* Time + Tutor */}
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1">
          <div className="text-text-primary inline-flex items-center gap-1.5 text-sm font-semibold">
            <Clock className="text-text-muted h-4 w-4" />
            {timeLabel}
          </div>
          {session.tutor_profile?.full_name && (
            <div className="text-text-muted inline-flex items-center gap-1.5 text-xs">
              <User className="h-3.5 w-3.5" />
              {session.tutor_profile.full_name}
            </div>
          )}
        </div>

        <div className="border-border-light mb-4 border-t" />

        {/* Rating Section - ABOVE the buttons */}
        <AnimatePresence>
          {(!isRated || showSuccess) && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="mb-4 overflow-hidden"
            >
              <div className="border-primary/10 bg-primary-subtle/70 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-xl border px-4 py-3">
                <div className="text-primary-hover text-sm font-semibold">
                  {showSuccess
                    ? 'Thanks for rating!'
                    : 'Rate your session'}
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
                        onClick={() => handleRate(star)}
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
          )}
        </AnimatePresence>

        {/* Rating state when already rated */}
        {isRated && !showSuccess && (
          <div className="border-border-light bg-surface-muted/50 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-xl border px-4 py-3 mb-4">
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

        {/* Resources */}
        {resources.length > 0 && (
          <div className="grid grid-cols-3 gap-3">
            {resources.map(({ href, icon: Icon, label, color, bg, hover, to, sub }) =>
              to ? (
                <Link
                  key={label}
                  to={to}
                  className={cn(
                    'group border-border-light bg-surface-muted flex flex-col items-center justify-center gap-2.5 rounded-xl border p-3 text-center transition-all duration-200',
                    hover
                  )}
                >
                  <div className={cn('flex h-9 w-9 items-center justify-center rounded-xl transition-transform group-hover:scale-110', bg)}>
                    <Icon className={cn('h-4 w-4', color)} />
                  </div>
                  <span className="text-text-primary text-xs font-semibold">{label}</span>
                  {sub && <span className="text-text-muted -mt-1.5 text-[11px]">{sub}</span>}
                </Link>
              ) : (
              <a
                key={label}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  'group border-border-light bg-surface-muted flex flex-col items-center justify-center gap-2.5 rounded-xl border p-3 text-center transition-all duration-200',
                  hover
                )}
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
        )}
      </div>
    </Card>
  );
}
