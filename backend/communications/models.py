"""
Parent communication for Demo and Diagnostic bookings (PRD 3.11).

Every booking -- of either type, each from its own table -- follows the same
five steps, owned by the lead's BDE (the Admin when the lead has none):

    1 ACKNOWLEDGEMENT        automatic message, target within 3 hours of booking
    2 CONFIRMATION_REQUEST   message the BDE sends when they choose (target: 12 h before)
    3 PARENT_CONFIRMATION    the BDE records Confirmed / Not Confirmed; the
                             confirmed message waits until it has everything it needs
    4 PRE_ACTIVITY_CALL      the BDE calls, from 15 minutes before until the
                             start, and records how it went; Missed at the
                             start without an outcome; no message
    5 AFTER_ACTIVITY         automatic message once the booking is completed

Each step is a CommunicationTask (one per booking and step), so its deadline,
owner and outcome are always on record. The four message steps send from
MessageTemplate -- eight: a Demo and a Diagnostic one per message step (the
PRD's ten messages count the call too, which has no text) -- whose wording
lives in immutable MessageTemplateVersion rows. A Message is one
message a booking is to get from one template: at most one per booking and
template, which is what keeps an automatic send from ever happening twice.
Its MessageAttempt rows are its send and retry history and its
MessageStatusEvent rows what the provider reported; a CallOutcome is one
outcome the BDE recorded for the 15-minute call. Those four, and the template
versions, are append-only: a trigger refuses every UPDATE and DELETE
(communications.0001).

communications.planner keeps a booking's tasks and messages in step with the
booking, inside the transaction that changes it; communications.services
holds the actions a BDE or the Admin take. Nothing here sends anything: the
sending engine is a later phase. Unlike the booking's history, these rows do
hold the parent's phone number and what each message says, so only the lead's
BDE and the Admin may read them.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Cast
from django.db.models.lookups import StartsWith
from django.utils import timezone

from bookings.models import BookingType


class Step(models.TextChoices):
    ACKNOWLEDGEMENT = 'ACKNOWLEDGEMENT', 'Initial acknowledgement'
    CONFIRMATION_REQUEST = 'CONFIRMATION_REQUEST', 'Confirmation request'
    PARENT_CONFIRMATION = 'PARENT_CONFIRMATION', 'Parent confirmation'
    PRE_ACTIVITY_CALL = 'PRE_ACTIVITY_CALL', 'Pre-activity call'
    AFTER_ACTIVITY = 'AFTER_ACTIVITY', 'After-activity message'


# The steps in order, numbered 1 to 5 as the PRD numbers them.
STEP_NUMBERS = {step: number for number, step in enumerate(Step, start=1)}
# The steps that send the parent a message; the 15-minute call sends none.
MESSAGE_STEPS = (Step.ACKNOWLEDGEMENT, Step.CONFIRMATION_REQUEST, Step.PARENT_CONFIRMATION, Step.AFTER_ACTIVITY)
# Template keys are <BOOKING TYPE>_<this>: DEMO_ACKNOWLEDGEMENT ... DIAGNOSTIC_AFTER_ACTIVITY.
TEMPLATE_KEY_SUFFIXES = {
    Step.ACKNOWLEDGEMENT: 'ACKNOWLEDGEMENT',
    Step.CONFIRMATION_REQUEST: 'CONFIRMATION_REQUEST',
    Step.PARENT_CONFIRMATION: 'CONFIRMED',
    Step.AFTER_ACTIVITY: 'AFTER_ACTIVITY',
}


def template_key(booking_type, step):
    """The key of ``booking_type``'s template for ``step`` (a message step)."""
    return f'{booking_type}_{TEMPLATE_KEY_SUFFIXES[step]}'


def _template_of(booking_type):
    """The message's template key starts with ``booking_type``: DEMO_..., DIAGNOSTIC_..."""
    return Q(StartsWith(Cast('template_id', output_field=models.CharField()), f'{booking_type}_'))


def _one_booking():
    """Exactly one of the two booking columns is set, as in booking_events."""
    return (
        Q(diagnostic_booking__isnull=False, demo_booking__isnull=True)
        | Q(diagnostic_booking__isnull=True, demo_booking__isnull=False)
    )


# ---------------------------------------------------------------- templates

class MessageTemplate(models.Model):
    """
    One of the messages: a booking type's template for one message step.
    Demo and Diagnostic never share one, so editing one never changes the
    other. Its wording is its latest version (current_version).
    """
    key = models.CharField(max_length=40, primary_key=True)
    booking_type = models.CharField(max_length=20, choices=BookingType.choices)
    step = models.CharField(max_length=30, choices=Step.choices)
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'message_templates'
        verbose_name = 'Message template'
        verbose_name_plural = 'Message templates'
        ordering = ['key']
        constraints = [
            models.UniqueConstraint(fields=['booking_type', 'step'], name='message_templates_one_per_step'),
            models.CheckConstraint(
                condition=Q(booking_type__in=BookingType.values),
                name='message_templates_known_type',
            ),
            models.CheckConstraint(
                condition=Q(step__in=MESSAGE_STEPS),
                name='message_templates_message_step',
            ),
        ]

    def __str__(self):
        return self.key

    def current_version(self):
        """The version messages are written from now: the latest."""
        return self.versions.order_by('-version').first()


class MessageTemplateVersion(models.Model):
    """
    One wording of a template. Never changed once saved: an edit adds the next
    version, and the messages already written keep the text they were written
    with. Version 1 of each template is the PRD's text (communications.prd_templates).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(MessageTemplate, on_delete=models.PROTECT, related_name='versions')
    version = models.PositiveIntegerField()
    # Placeholders are {{name}} (communications.rendering.VARIABLES); bold is **text**.
    body = models.TextField()
    # The provider's approved template this version maps to, per provider; empty until one is chosen.
    provider_refs = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=255, blank=True, default='')
    # NULL for the versions a migration seeded.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='message_template_versions'
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'message_template_versions'
        verbose_name = 'Message template version'
        verbose_name_plural = 'Message template versions'
        ordering = ['template', 'version']
        constraints = [
            models.UniqueConstraint(fields=['template', 'version'], name='message_template_versions_one_per_number'),
            models.CheckConstraint(condition=Q(version__gte=1), name='message_template_versions_from_one'),
        ]

    def __str__(self):
        return f'{self.template_id} v{self.version}'


# ---------------------------------------------------------------- tasks

class OwnerRole(models.TextChoices):
    """Who acts on a task: the lead's BDE, or the Admin when the lead has no BDE."""
    BDE = 'BDE', 'BDE'
    ADMIN = 'ADMIN', 'Admin'


class TaskStatus(models.TextChoices):
    OPEN = 'OPEN', 'Open'
    DONE = 'DONE', 'Done'
    CANCELLED = 'CANCELLED', 'Cancelled'
    # Its time ran out (expires_at) with nothing done.
    MISSED = 'MISSED', 'Missed'


class TaskResolution(models.TextChoices):
    """
    How a task closed: what was done, or why it no longer applies. A message
    step closes when the provider accepts the message -- ACCEPTED when it only
    queued it, SENT when it reported it sent. Delivered and Read are the
    message's own states (Message.status), never a task's.
    """
    ACCEPTED = 'ACCEPTED', 'Accepted by the provider (queued, not yet sent)'
    SENT = 'SENT', 'Message sent'
    MARKED_SENT = 'MARKED_SENT', 'Sent manually'
    # A rescheduled booking's acknowledgement: a booking it replaced had its
    # acknowledgement accepted, so no second one goes.
    ALREADY_ACKNOWLEDGED = 'ALREADY_ACKNOWLEDGED', 'Acknowledged for the earlier booking'
    # The confirmation request once the parent has confirmed anyway.
    NOT_NEEDED = 'NOT_NEEDED', 'Not needed'
    CALLED = 'CALLED', 'Called'
    MESSAGED = 'MESSAGED', 'Messaged'
    NO_ANSWER = 'NO_ANSWER', 'No answer'
    # No longer written: the 15-minute call is Missed when its booking's
    # scheduled start comes with no outcome recorded (planner.close_expired);
    # communications.0006 made the calls closed this way before Missed too.
    REMINDED = 'REMINDED', 'Reminder complete'
    BOOKING_CANCELLED = 'BOOKING_CANCELLED', 'Booking cancelled'
    BOOKING_RESCHEDULED = 'BOOKING_RESCHEDULED', 'Booking rescheduled'


# How a message step is done, and what the BDE may record for the 15-minute call -- and only for it.
MESSAGE_RESOLUTIONS = (
    TaskResolution.ACCEPTED, TaskResolution.SENT, TaskResolution.MARKED_SENT, TaskResolution.ALREADY_ACKNOWLEDGED,
    TaskResolution.NOT_NEEDED,
)
CALL_OUTCOMES = (TaskResolution.CALLED, TaskResolution.MESSAGED, TaskResolution.NO_ANSWER)
CALL_RESOLUTIONS = (*CALL_OUTCOMES, TaskResolution.REMINDED)
DONE_RESOLUTIONS = (*MESSAGE_RESOLUTIONS, *CALL_RESOLUTIONS)
CANCELLED_RESOLUTIONS = (TaskResolution.BOOKING_CANCELLED, TaskResolution.BOOKING_RESCHEDULED)


class CommunicationTask(models.Model):
    """
    One step of one booking's communication: who acts on it, from when
    (active_from), by when (due_at), until when it can still be done
    (expires_at, after which it is Missed), and how it ended. A booking gets
    all five when it is made; the after-activity step's times are set when the
    booking is completed.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnostic_booking = models.ForeignKey(
        'bookings.DiagnosticBooking',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='communication_tasks'
    )
    demo_booking = models.ForeignKey(
        'bookings.DemoBooking',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='communication_tasks'
    )
    step = models.CharField(max_length=30, choices=Step.choices)
    owner_role = models.CharField(max_length=10, choices=OwnerRole.choices)
    # The lead's BDE when the lead had one as the task was made; NULL for the Admin.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='communication_tasks'
    )
    active_from = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.OPEN)
    resolution = models.CharField(max_length=30, choices=TaskResolution.choices, blank=True, default='')
    resolved_at = models.DateTimeField(null=True, blank=True)
    # NULL when the system closed it.
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='resolved_communication_tasks'
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'communication_tasks'
        verbose_name = 'Communication task'
        verbose_name_plural = 'Communication tasks'
        ordering = ['created_at']
        constraints = [
            models.CheckConstraint(condition=_one_booking(), name='communication_tasks_one_booking'),
            models.UniqueConstraint(
                fields=['diagnostic_booking', 'step'], name='communication_tasks_one_per_diag_step',
            ),
            models.UniqueConstraint(fields=['demo_booking', 'step'], name='communication_tasks_one_per_demo_step'),
            models.CheckConstraint(condition=Q(step__in=Step.values), name='communication_tasks_known_step'),
            models.CheckConstraint(condition=Q(status__in=TaskStatus.values), name='communication_tasks_known_status'),
            models.CheckConstraint(
                condition=(
                    Q(owner_role=OwnerRole.BDE, owner__isnull=False)
                    | Q(owner_role=OwnerRole.ADMIN, owner__isnull=True)
                ),
                name='communication_tasks_owner_matches_role',
            ),
            # An open task has no outcome; a closed one says when, and how it ended.
            models.CheckConstraint(
                condition=(
                    Q(status=TaskStatus.OPEN, resolution='', resolved_at__isnull=True, resolved_by__isnull=True)
                    | Q(status=TaskStatus.DONE, resolution__in=DONE_RESOLUTIONS, resolved_at__isnull=False)
                    | Q(status=TaskStatus.CANCELLED, resolution__in=CANCELLED_RESOLUTIONS, resolved_at__isnull=False)
                    | Q(status=TaskStatus.MISSED, resolution='', resolved_at__isnull=False)
                ),
                name='communication_tasks_resolution_matches_status',
            ),
            # Call outcomes and the finished reminder belong to the call, and only they close it as done.
            models.CheckConstraint(
                condition=(
                    (Q(step=Step.PRE_ACTIVITY_CALL) & ~Q(resolution__in=MESSAGE_RESOLUTIONS))
                    | (~Q(step=Step.PRE_ACTIVITY_CALL) & ~Q(resolution__in=CALL_RESOLUTIONS))
                ),
                name='communication_tasks_call_outcomes_for_calls',
            ),
        ]
        indexes = [
            models.Index(fields=['owner', 'status', 'due_at'], name='comm_tasks_owner_idx'),
            models.Index(fields=['owner_role', 'status', 'due_at'], name='comm_tasks_role_idx'),
            models.Index(fields=['status', 'expires_at'], name='comm_tasks_expiry_idx'),
        ]

    def __str__(self):
        return f'{self.get_step_display()} ({self.get_status_display()})'

    @property
    def booking(self):
        return self.diagnostic_booking or self.demo_booking

    @property
    def number(self):
        return STEP_NUMBERS[self.step]


class CallOutcome(models.Model):
    """
    One outcome the BDE recorded for a booking's 15-minute call. Every one is
    kept: a later Called after a No Answer adds a row and erases nothing. The
    task shows the latest.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(CommunicationTask, on_delete=models.PROTECT, related_name='call_outcomes')
    outcome = models.CharField(max_length=20, choices=[(value, TaskResolution(value).label) for value in CALL_OUTCOMES])
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='call_outcomes')
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'communication_call_outcomes'
        verbose_name = 'Call outcome'
        verbose_name_plural = 'Call outcomes'
        ordering = ['recorded_at']
        constraints = [
            models.CheckConstraint(condition=Q(outcome__in=CALL_OUTCOMES), name='communication_call_outcomes_known'),
        ]
        indexes = [
            models.Index(fields=['task', 'recorded_at'], name='comm_call_outcomes_task_idx'),
        ]

    def __str__(self):
        return f'{self.get_outcome_display()} ({self.recorded_at:%Y-%m-%d %H:%M})'


# ---------------------------------------------------------------- messages

class MessageStatus(models.TextChoices):
    """
    Where a message stands. Waiting and Pending come before any provider:
    Waiting lacks something it needs (communications.rendering.requirements),
    Pending has it all and waits to be handed over. Queued to Read are what
    the provider reported, and only states it supports are ever recorded.
    """
    WAITING = 'WAITING', 'Waiting'
    PENDING = 'PENDING', 'Pending'
    QUEUED = 'QUEUED', 'Queued'
    SENT = 'SENT', 'Sent'
    DELIVERED = 'DELIVERED', 'Delivered'
    READ = 'READ', 'Read'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'


# Not yet with the parent's provider: what a cancellation or expiry still stops.
UNSENT_STATUSES = (MessageStatus.WAITING, MessageStatus.PENDING, MessageStatus.FAILED)
# Handed to a provider, or sent by hand: the parent has it, or will.
HANDED_OVER_STATUSES = (MessageStatus.QUEUED, MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.READ)
SENT_STATUSES = (MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.READ)
# The failure code of a send whose outcome nobody knows: the provider may have
# taken it, so it is never sent again by itself (communications.sending).
OUTCOME_UNKNOWN = 'OUTCOME_UNKNOWN'
# A delivery failure: the provider accepted the message (so it holds the
# provider's id) and then reported it undelivered -- for the BDE to follow up,
# unlike a send the provider refused. Never cancelled, expired or retried.
DELIVERY_FAILURES = Q(status=MessageStatus.FAILED) & ~Q(provider_message_id='')


class Channel(models.TextChoices):
    """WhatsApp is the only channel: through a provider, or by the BDE by hand."""
    WHATSAPP = 'WHATSAPP', 'WhatsApp'
    # Sent by the BDE from WhatsApp themselves: Sent at most, never Delivered or Read.
    MANUAL_WHATSAPP = 'MANUAL_WHATSAPP', 'WhatsApp (sent manually)'


class MessageCancelReason(models.TextChoices):
    BOOKING_CANCELLED = 'BOOKING_CANCELLED', 'Booking cancelled'
    BOOKING_RESCHEDULED = 'BOOKING_RESCHEDULED', 'Booking rescheduled'
    NOT_NEEDED = 'NOT_NEEDED', 'Not needed'
    # Its sending window (send_before) closed before it went.
    EXPIRED = 'EXPIRED', 'Too late to send'


class Message(models.Model):
    """
    One message a booking is to get from one template -- at most one per
    booking and template, so an event handled twice never writes a second.
    Retries are attempts of the same message (MessageAttempt), never new rows.

    While unsent, its text, values and recipient follow the booking (rendered
    by communications.planner.refresh_message); once handed over they are
    what was sent and never change.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnostic_booking = models.ForeignKey(
        'bookings.DiagnosticBooking',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='communication_messages'
    )
    demo_booking = models.ForeignKey(
        'bookings.DemoBooking',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='communication_messages'
    )
    task = models.ForeignKey(CommunicationTask, on_delete=models.PROTECT, related_name='messages')
    template = models.ForeignKey(MessageTemplate, on_delete=models.PROTECT, related_name='messages')
    # The version the current text was rendered from; NULL while Waiting.
    template_version = models.ForeignKey(
        MessageTemplateVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='messages'
    )
    status = models.CharField(max_length=20, choices=MessageStatus.choices, default=MessageStatus.WAITING)
    # How it went (or goes): set when it is handed over.
    channel = models.CharField(max_length=20, choices=Channel.choices, blank=True, default='')
    provider = models.CharField(max_length=50, blank=True, default='')
    # The parent's number, "+<dial code><number>" (the lead's phone_key).
    recipient_phone = models.CharField(max_length=20)
    body = models.TextField(blank=True, default='')
    # The values the body was rendered with, by placeholder name.
    variables = models.JSONField(default=dict, blank=True)
    # Not sent before / not sent after (NULL: no limit).
    scheduled_for = models.DateTimeField(null=True, blank=True)
    send_before = models.DateTimeField(null=True, blank=True)
    # Set while a sender is handing it over (the sending engine).
    claimed_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True, default='')
    failure_code = models.CharField(max_length=50, blank=True, default='')
    failure_reason = models.TextField(blank=True, default='')
    cancel_reason = models.CharField(max_length=30, choices=MessageCancelReason.choices, blank=True, default='')
    # Who asked for it (the confirmation request); NULL when the system wrote it.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='created_communication_messages'
    )
    # Who sent it by hand (Channel.MANUAL_WHATSAPP).
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='sent_communication_messages'
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'communication_messages'
        verbose_name = 'Message'
        verbose_name_plural = 'Messages'
        ordering = ['created_at']
        constraints = [
            models.CheckConstraint(condition=_one_booking(), name='communication_messages_one_booking'),
            models.UniqueConstraint(
                fields=['diagnostic_booking', 'template'], name='communication_messages_one_per_diag_template',
            ),
            models.UniqueConstraint(
                fields=['demo_booking', 'template'], name='communication_messages_one_per_demo_template',
            ),
            # A booking's messages come from its own type's templates.
            models.CheckConstraint(
                condition=(
                    (Q(demo_booking__isnull=True) | _template_of(BookingType.DEMO))
                    & (Q(diagnostic_booking__isnull=True) | _template_of(BookingType.DIAGNOSTIC))
                ),
                name='communication_messages_template_of_its_type',
            ),
            models.CheckConstraint(
                condition=Q(status__in=MessageStatus.values),
                name='communication_messages_known_status',
            ),
            models.CheckConstraint(
                condition=Q(channel='') | Q(channel__in=Channel.values),
                name='communication_messages_known_channel',
            ),
            models.CheckConstraint(
                condition=(
                    (Q(status=MessageStatus.CANCELLED) & Q(cancel_reason__in=MessageCancelReason.values)
                     & Q(cancelled_at__isnull=False))
                    | (~Q(status=MessageStatus.CANCELLED) & Q(cancel_reason=''))
                ),
                name='communication_messages_cancel_reason_with_status',
            ),
            # A provider's states carry their moment; a failure says why.
            models.CheckConstraint(
                condition=~Q(status=MessageStatus.QUEUED) | Q(queued_at__isnull=False),
                name='communication_messages_queued_at',
            ),
            models.CheckConstraint(
                condition=~Q(status__in=SENT_STATUSES) | Q(sent_at__isnull=False),
                name='communication_messages_sent_at',
            ),
            models.CheckConstraint(
                condition=~Q(status=MessageStatus.FAILED) | (Q(failed_at__isnull=False) & ~Q(failure_code='')),
                name='communication_messages_failure_recorded',
            ),
            # A message sent by hand is Sent, by someone: nobody can know it was delivered or read.
            models.CheckConstraint(
                condition=(
                    ~Q(channel=Channel.MANUAL_WHATSAPP)
                    | Q(status=MessageStatus.SENT, sent_by__isnull=False)
                ),
                name='communication_messages_manual_is_sent_only',
            ),
            models.UniqueConstraint(
                fields=['provider', 'provider_message_id'],
                condition=~Q(provider_message_id=''),
                name='communication_messages_one_per_provider_id',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'scheduled_for'], name='comm_messages_due_idx'),
            models.Index(fields=['status', 'send_before'], name='comm_messages_expiry_idx'),
        ]

    def __str__(self):
        return f'{self.template_id} ({self.get_status_display()})'

    @property
    def booking(self):
        return self.diagnostic_booking or self.demo_booking

    @property
    def is_delivery_failure(self):
        """Failed after the provider accepted it (DELIVERY_FAILURES), not refused when sent."""
        return self.status == MessageStatus.FAILED and bool(self.provider_message_id)


class AttemptOutcome(models.TextChoices):
    ACCEPTED = 'ACCEPTED', 'Accepted by the provider'
    FAILED = 'FAILED', 'Failed'
    # The sender stopped before it learnt what the provider did: never retried blindly.
    UNKNOWN = 'UNKNOWN', 'Outcome unknown'


class MessageAttempt(models.Model):
    """One try at handing a message to a provider, written once it is over."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(Message, on_delete=models.PROTECT, related_name='attempts')
    number = models.PositiveSmallIntegerField()
    channel = models.CharField(max_length=20, choices=Channel.choices)
    provider = models.CharField(max_length=50)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    outcome = models.CharField(max_length=20, choices=AttemptOutcome.choices)
    provider_message_id = models.CharField(max_length=255, blank=True, default='')
    error_code = models.CharField(max_length=50, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    retryable = models.BooleanField(default=False)
    # NULL for the sender's own attempts; the BDE or Admin who pressed Retry otherwise.
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='message_attempts'
    )

    class Meta:
        db_table = 'communication_message_attempts'
        verbose_name = 'Message attempt'
        verbose_name_plural = 'Message attempts'
        ordering = ['message', 'number']
        constraints = [
            models.UniqueConstraint(fields=['message', 'number'], name='communication_message_attempts_one_per_number'),
            models.CheckConstraint(condition=Q(number__gte=1), name='communication_message_attempts_from_one'),
            models.CheckConstraint(
                condition=Q(outcome__in=AttemptOutcome.values),
                name='communication_message_attempts_known_outcome',
            ),
            models.CheckConstraint(
                condition=Q(channel__in=Channel.values),
                name='communication_message_attempts_known_channel',
            ),
        ]

    def __str__(self):
        return f'Attempt {self.number} ({self.get_outcome_display()})'


class MessageStatusEvent(models.Model):
    """
    One status the provider reported for a message. A callback delivered twice
    is kept once (dedupe_key); one arriving out of order is kept, but never
    moves the message back.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(Message, on_delete=models.PROTECT, related_name='status_events')
    provider = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=MessageStatus.choices)
    # The provider's own word for it, as received.
    provider_status = models.CharField(max_length=50, blank=True, default='')
    occurred_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    error_code = models.CharField(max_length=50, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    dedupe_key = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'communication_message_status_events'
        verbose_name = 'Message status event'
        verbose_name_plural = 'Message status events'
        ordering = ['received_at']
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=[
                    MessageStatus.QUEUED, MessageStatus.SENT, MessageStatus.DELIVERED,
                    MessageStatus.READ, MessageStatus.FAILED,
                ]),
                name='communication_message_status_events_provider_status',
            ),
        ]
        indexes = [
            models.Index(fields=['message', 'received_at'], name='comm_status_events_msg_idx'),
        ]

    def __str__(self):
        return f'{self.get_status_display()} ({self.received_at:%Y-%m-%d %H:%M})'


class UnmatchedStatusEvent(models.Model):
    """
    A status a provider reported for a message id no message holds yet --
    most often a callback that came before the sender had recorded the id.
    Kept until a message does (communications.status_updates.reconcile), then
    applied to it and removed; one never matched is purged after
    UNMATCHED_RETENTION. It holds the report only: no recipient number, no
    message text.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=50)
    provider_message_id = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=MessageStatus.choices)
    provider_status = models.CharField(max_length=50, blank=True, default='')
    occurred_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    error_code = models.CharField(max_length=50, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    error_temporary = models.BooleanField(null=True, blank=True)
    # The key its MessageStatusEvent will have: a report already kept, either way, is not kept again.
    dedupe_key = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'communication_unmatched_status_events'
        verbose_name = 'Unmatched status event'
        verbose_name_plural = 'Unmatched status events'
        ordering = ['received_at']
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=[
                    MessageStatus.QUEUED, MessageStatus.SENT, MessageStatus.DELIVERED,
                    MessageStatus.READ, MessageStatus.FAILED,
                ]),
                name='communication_unmatched_status_events_provider_status',
            ),
        ]
        indexes = [
            models.Index(fields=['provider', 'provider_message_id'], name='comm_unmatched_msg_idx'),
            models.Index(fields=['received_at'], name='comm_unmatched_received_idx'),
        ]

    def __str__(self):
        return f'{self.get_status_display()} for an unknown message ({self.received_at:%Y-%m-%d %H:%M})'
