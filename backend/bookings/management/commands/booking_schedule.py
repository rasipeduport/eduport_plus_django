"""
    python manage.py booking_schedule show
    python manage.py booking_schedule set    {demo,diagnostic} HH:MM [HH:MM ...] [--apply]
    python manage.py booking_schedule close  {demo,diagnostic} YYYY-MM-DD HH:MM [--reason TEXT] [--apply]
    python manage.py booking_schedule reopen {demo,diagnostic} YYYY-MM-DD HH:MM [--apply]

The booking schedule: the times of day (Indian time) each booking type is
offered -- what the Calendar sheet's header row held -- and single-slot
closures. Nothing is written without --apply, and every change is audited.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings import booking_service
from bookings.models import BookingSlot, BookingType, SlotTime
from core.timezones import DATE_PATTERN, TIME_PATTERN

VIA = 'manage.py booking_schedule'
TYPES = {'demo': BookingType.DEMO, 'diagnostic': BookingType.DIAGNOSTIC}


def _type(value):
    try:
        return TYPES[value.strip().lower()]
    except KeyError:
        raise CommandError(f'Booking type must be one of: {", ".join(TYPES)}.')


def _time(value):
    if not TIME_PATTERN.match(value):
        raise CommandError(f'Times are HH:MM (24-hour), received "{value}".')
    return datetime.strptime(value, '%H:%M').time()


def _date(value):
    if not DATE_PATTERN.match(value):
        raise CommandError(f'Dates are YYYY-MM-DD, received "{value}".')
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        raise CommandError(f'"{value}" is not a real date.')


class Command(BaseCommand):
    help = 'Show or set the Demo and Diagnostic booking schedules, and close or reopen single slots.'

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest='action', required=True)
        actions.add_parser('show', help='Each booking type and its active times.')
        sub = actions.add_parser('set', help='Make these the active times of a booking type.')
        sub.add_argument('booking_type')
        sub.add_argument('times', nargs='+', metavar='HH:MM')
        sub.add_argument('--apply', action='store_true', help='Make the change; without it nothing is written.')
        for name, verb in (('close', 'Close'), ('reopen', 'Reopen')):
            sub = actions.add_parser(name, help=f'{verb} one slot.')
            sub.add_argument('booking_type')
            sub.add_argument('date', metavar='YYYY-MM-DD')
            sub.add_argument('time', metavar='HH:MM')
            sub.add_argument('--apply', action='store_true', help='Make the change; without it nothing is written.')
            if name == 'close':
                sub.add_argument('--reason', default='', help='Why the slot is closed (kept with it).')

    def handle(self, *args, **options):
        action = options['action']
        if action == 'show':
            return self.show()
        booking_type = _type(options['booking_type'])
        if action == 'set':
            return self.set_times(booking_type, sorted({_time(value) for value in options['times']}), options['apply'])
        return self.change_slot(action, booking_type, _date(options['date']), _time(options['time']),
                                options.get('reason', ''), options['apply'])

    def show(self):
        for label, booking_type in TYPES.items():
            times = SlotTime.objects.filter(booking_type=booking_type, is_active=True).order_by('start_time')
            listed = ', '.join(entry.start_time.strftime('%H:%M') for entry in times) or '(no active times)'
            self.stdout.write(f'{label}: {listed}')

    def set_times(self, booking_type, times, apply):
        listed = ', '.join(t.strftime('%H:%M') for t in times)
        if not apply:
            self.stdout.write(f'Would set the {booking_type.lower()} times to {listed}. Re-run with --apply to make the change.')
            return
        added, removed = booking_service.set_schedule(booking_type, times, via=VIA)
        if not (added or removed):
            self.stdout.write(f'Nothing to do: the {booking_type.lower()} times are already {listed}.')
            return
        self.stdout.write(self.style.SUCCESS(
            f'{booking_type.title()} times are now {listed} '
            f'(added {", ".join(t.strftime("%H:%M") for t in added) or "none"}; '
            f'removed {", ".join(t.strftime("%H:%M") for t in removed) or "none"}).'
        ))

    def change_slot(self, action, booking_type, local_date, local_time, reason, apply):
        name = f'{booking_type.lower()} {local_date} {local_time:%H:%M}'
        if action == 'close' and not SlotTime.objects.filter(booking_type=booking_type, start_time=local_time).exists():
            raise CommandError(f'{local_time:%H:%M} is not a {booking_type.lower()} time.')
        if not apply:
            self.stdout.write(f'Would {action} {name}. Re-run with --apply to make the change.')
            return
        if action == 'close':
            _slot, changed = booking_service.close_slot(booking_type, local_date, local_time, reason=reason)
        else:
            _slot, changed = booking_service.reopen_slot(booking_type, local_date, local_time)
        if not changed:
            state = 'closed' if action == 'close' else 'open'
            self.stdout.write(f'Nothing to do: {name} is already {state}.')
            return
        self.stdout.write(self.style.SUCCESS(f'{"Closed" if action == "close" else "Reopened"} {name}.'))
        closed = BookingSlot.objects.filter(booking_type=booking_type, closed_at__isnull=False).count()
        self.stdout.write(f'{closed} {booking_type.lower()} slot(s) are closed.')
