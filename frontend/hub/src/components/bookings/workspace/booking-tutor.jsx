import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { HistoryIcon, UserRoundCheckIcon, UsersIcon } from 'lucide-react';

import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, PanelEmpty } from '@/components/dashboard/dashboard-primitives';
import { ErrorState } from '@/components/page/states';
import { bookingError, bookingTutorsUrl, tutorChangeable } from '@/lib/bookings';
import { formatDay } from '@/lib/enquiries';
import { AvailabilityBadge, StartInfo, TutorName } from '../booking-badges';
import { BookingEvents } from '../booking-history';
import { MeetLink } from '../meet-link';

// The timeline's events about who teaches the booking.
const TUTOR_EVENTS = ['TUTOR_ASSIGNED', 'TUTOR_UNASSIGNED', 'MEET_LINK_UPDATED', 'STARTED'];

function Field({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 text-sm first:pt-0 last:pb-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children || <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

/**
 * Every active tutor for the booking's slot, Available or Unavailable with the
 * reason the API gives -- a class or another booking then, never another
 * child's name -- the current one marked (GET /api/bookings/<type>/<id>/tutors/,
 * the list the tutor dialog picks from). Read-only: choosing is the dialog's.
 */
function Availability({ booking, reloadKey }) {
  const [data, setData] = useState(null);
  const [failure, setFailure] = useState(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let active = true;
    setFailure(null);
    api
      .get(bookingTutorsUrl(booking.booking_type, booking.id))
      .then((response) => {
        if (active) setData(response.data);
      })
      .catch((err) => {
        if (active) setFailure(bookingError(err, "Could not load the tutors' availability."));
      });
    return () => {
      active = false;
    };
  }, [booking.booking_type, booking.id, reloadKey, retryKey]);

  const shown = data && data.booking_id === booking.id ? data : null;
  let body;
  if (failure && !shown) body = <ErrorState message={failure.message} onRetry={() => setRetryKey((key) => key + 1)} />;
  else if (!shown) body = <Skeleton className="h-32" aria-busy="true" />;
  else if (!shown.tutors?.length) body = <PanelEmpty icon={UsersIcon} message="No active tutors" />;
  else {
    body = (
      <ul className="divide-y">
        {shown.tutors.map((tutor) => (
          <li key={tutor.id} className="flex flex-wrap items-start justify-between gap-2 py-2.5 first:pt-0 last:pb-0">
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                {tutor.full_name}
                {tutor.current ? <Badge variant="info">Current</Badge> : null}
              </p>
              {tutor.reason ? <p className="text-muted-foreground text-xs">{tutor.reason.message}</p> : null}
            </div>
            <AvailabilityBadge status={tutor.status} />
          </li>
        ))}
      </ul>
    );
  }
  return (
    <Panel icon={UsersIcon} title="Tutor availability" subtitle="Who is free for this booking's slot">
      {body}
    </Panel>
  );
}

/**
 * Who teaches the booking (the administrators' booking workspace): its tutor
 * -- with Assign / Change and Unassign for holders of
 * accounts.assign_booking_tutor while the API says its tutor may change
 * (tutor_changeable: booked, not started by its tutor, its slot not over; why
 * not, when not) -- the tutor's Meet link, which team managers
 * (`canEditMeetLink`, accounts.manage_team) set or change on the tutor's
 * account until the tutor starts the booking or its slot ends, who assigned
 * them and when, and whether the tutor started it; then, for a booking still
 * to come, who is free for its slot, and the timeline's events about its
 * tutor (`history`, useBookingHistory). Assigning opens the workspace's tutor
 * dialog (`onAssign`), unassigning its confirmation (`onUnassign`), the Meet
 * link its dialog (`onEditMeetLink`).
 */
export function BookingTutor({ booking, history, reloadKey, canAssign, canEditMeetLink, canOpenTeam, onAssign, onUnassign, onEditMeetLink }) {
  const changeable = canAssign && tutorChangeable(booking);
  // The tutor's permanent link, while the booking would still take it: booked, not started by its tutor and
  // not ended (backend booking_service.set_tutor_meet_link). A started booking keeps its room.
  const meetLinkEditable =
    canEditMeetLink && Boolean(booking.tutor) && booking.status === 'BOOKED' && !booking.started_at && !booking.slot?.ended;
  const toCome = booking.status === 'BOOKED' && !booking.slot?.ended;

  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-2 lg:items-start">
      <Panel
        icon={UserRoundCheckIcon}
        title="Assigned tutor"
        action={
          changeable ? (
            <div className="flex gap-2">
              {booking.tutor ? (
                <Button variant="outline" size="sm" onClick={onUnassign}>
                  Unassign
                </Button>
              ) : null}
              <Button size="sm" onClick={onAssign}>
                {booking.tutor ? 'Change tutor' : 'Assign tutor'}
              </Button>
            </div>
          ) : null
        }
      >
        <dl className="divide-y">
          <Field label="Teaching">
            <span className="flex flex-wrap items-center gap-2">
              <TutorName booking={booking} />
              {booking.tutor && canOpenTeam ? (
                <Link to={`/team/${booking.tutor.id}`} className="text-link text-xs font-normal hover:underline">
                  View profile
                </Link>
              ) : null}
            </span>
          </Field>
          {booking.tutor ? (
            <>
              <Field label="Meet link">
                <span className="flex flex-col items-start gap-1">
                  <MeetLink link={booking.tutor_meet_link} />
                  {meetLinkEditable ? (
                    <Button variant="link" size="sm" className="h-auto p-0" onClick={onEditMeetLink}>
                      {booking.tutor_meet_link ? 'Change Meet link' : 'Set Meet link'}
                    </Button>
                  ) : null}
                </span>
              </Field>
              <Field label="Assigned by">{booking.tutor_assigned_by?.full_name}</Field>
              <Field label="Assigned on">{formatDay(booking.tutor_assigned_at)}</Field>
            </>
          ) : null}
          {booking.status !== 'RESCHEDULED' ? (
            <Field label="Started">
              <StartInfo booking={booking} showBy />
            </Field>
          ) : null}
        </dl>
        {!tutorChangeable(booking) && booking.tutor_change_refusal ? (
          <p className="text-muted-foreground mt-3 text-xs">{booking.tutor_change_refusal.message}</p>
        ) : null}
      </Panel>

      {toCome ? <Availability booking={booking} reloadKey={reloadKey} /> : null}

      <Panel icon={HistoryIcon} title="Assignment history" subtitle="Oldest first, in Indian time (IST)" className="lg:col-span-2">
        <BookingEvents
          state={history}
          bookingId={booking.id}
          kinds={TUTOR_EVENTS}
          emptyMessage="No tutor has been assigned to this booking yet."
        />
      </Panel>
    </div>
  );
}
