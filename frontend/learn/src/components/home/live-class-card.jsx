import { CalendarOff, Clock, Link as LinkIcon, User, Video } from 'lucide-react';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { formatSessionDateTime } from '../../lib/formatting';
import { useStudentZone } from '../student/student-context';

export function LiveClassCard({ meetLink, nextSession, loading }) {
  const zone = useStudentZone();
  if (loading) {
    return (
      <div className="bg-surface-muted h-56 animate-pulse rounded-2xl" />
    );
  }

  if (!nextSession) {
    return (
      <Card>
        <div className="flex flex-col items-center justify-center gap-3 py-6 text-center">
          <div className="bg-surface-muted flex h-12 w-12 items-center justify-center rounded-2xl">
            <CalendarOff className="text-text-muted h-5 w-5" />
          </div>
          <div>
            <p className="text-text-primary text-sm font-semibold">
              No session scheduled
            </p>
            <p className="text-text-muted mt-0.5 text-xs">
              Your next class will appear here once it's booked.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  const { dateLabel, timeLabel } = formatSessionDateTime(
    nextSession.start_time,
    nextSession.end_time,
    zone
  );

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
              {nextSession.title}
            </p>
          </div>
          <div className="bg-primary-subtle ml-4 flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl">
            <Video className="text-primary h-5 w-5" />
          </div>
        </div>

        {/* Time + Tutor */}
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1">
          <div className="text-text-primary inline-flex items-center gap-1.5 text-sm font-semibold">
            <Clock className="text-text-muted h-4 w-4" />
            {timeLabel}
          </div>
          {nextSession.tutor_profile?.full_name && (
            <div className="text-text-muted inline-flex items-center gap-1.5 text-xs">
              <User className="h-3.5 w-3.5" />
              {nextSession.tutor_profile.full_name}
            </div>
          )}
        </div>

        <div className="border-border-light mb-4 border-t" />

        {/* Meet link */}
        {meetLink ? (
          <div className="border-primary/10 bg-primary-subtle/70 mb-4 flex items-center gap-3 rounded-xl border px-4 py-3">
            <div className="bg-primary flex h-7 w-7 shrink-0 items-center justify-center rounded-lg">
              <LinkIcon className="h-3.5 w-3.5 text-white" />
            </div>
            <span className="text-text-secondary truncate text-sm">
              {meetLink.replace(/^https?:\/\//, '')}
            </span>
          </div>
        ) : (
          <div className="border-border-light bg-surface-muted mb-4 flex items-center gap-3 rounded-xl border px-4 py-3">
            <div className="bg-border flex h-7 w-7 shrink-0 items-center justify-center rounded-lg">
              <LinkIcon className="text-text-muted h-3.5 w-3.5" />
            </div>
            <span className="text-text-muted truncate text-sm italic">
              Link not available yet
            </span>
          </div>
        )}

        {/* Join button */}
        <Button
          variant="primary"
          size="lg"
          fullWidth
          icon={<Video className="h-5 w-5" />}
          disabled={!meetLink}
          onClick={() => meetLink && window.open(meetLink, '_blank')}
        >
          Join Meeting
        </Button>
      </div>
    </Card>
  );
}
