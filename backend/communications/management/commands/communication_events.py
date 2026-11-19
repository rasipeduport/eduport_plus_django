"""
The communication outbox, for an operator (communications.outbox):

    manage.py communication_events                  counts by status, the oldest event still to apply, stuck claims
    manage.py communication_events --failed         the FAILED events: id, kind, subject, attempts, last error
    manage.py communication_events --run            apply what is ready now, as the scheduled job does (one run at a time)
    manage.py communication_events --retry ID ...   put FAILED events back to PENDING (attempts reset)
    manage.py communication_events --retry-failed   the same for every FAILED event

A FAILED event whose streams have any later event that is not FAILED too is
not put back unless --force: applied now, it could undo that later event's work.
"""
from django.core.management.base import BaseCommand

from communications import outbox, tasks
from communications.models import CommunicationEvent, EventStatus


class Command(BaseCommand):
    help = 'Show, run and recover the communication outbox.'

    def add_arguments(self, parser):
        parser.add_argument('--failed', action='store_true', help='List FAILED events.')
        parser.add_argument('--run', action='store_true', help='Apply the events ready now.')
        parser.add_argument('--retry', nargs='+', type=int, metavar='ID', help='Requeue these FAILED events.')
        parser.add_argument('--retry-failed', action='store_true', help='Requeue every FAILED event.')
        parser.add_argument('--force', action='store_true', help='Requeue even when a later event was applied.')

    def handle(self, *args, **options):
        if options['run']:
            # The job itself, so a manual run never applies events beside a scheduled one (single_run).
            self.stdout.write(f'Run: {tasks.process_communication_events()}')
        ids = options['retry'] or []
        if options['retry_failed']:
            ids = list(CommunicationEvent.objects.filter(status=EventStatus.FAILED).values_list('pk', flat=True))
        if ids:
            done, refused = outbox.requeue(ids, force=options['force'])
            self.stdout.write(f'Requeued: {done or "none"}')
            if refused:
                self.stdout.write(self.style.WARNING(
                    f'Not requeued (a later event of the same booking or lead exists; use --force): {refused}'
                ))
        if options['failed']:
            for event in CommunicationEvent.objects.filter(status=EventStatus.FAILED).order_by('pk'):
                self.stdout.write(
                    f'#{event.pk} {event.kind} {event.subject_type}:{event.subject_id} '
                    f'attempts={event.attempts} occurred={event.occurred_at:%Y-%m-%d %H:%M} {event.last_error}'
                )
        health = outbox.health()
        self.stdout.write(f'Events by status: {health["counts"]}')
        self.stdout.write(f'Oldest unfinished: {health["oldest_unfinished_age_seconds"]} s; stuck claims: {health["stuck"]}')
