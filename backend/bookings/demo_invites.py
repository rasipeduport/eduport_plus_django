"""
Demo invitations: the Diagnostic -> Demo step. Once a tutor has submitted a
Diagnostic's report, an administrator -- or the BDE who owns the lead -- sends
the parent a link to book a Demo for the same child (bookings.models.DemoInvite):
the parent picks a date and a time on the marketing site and types nothing
again, and the Demo is booked for the Diagnostic's own lead
(booking_service.create_invited_demo_booking).

The link is the marketing site's invitation page with the token in its
fragment (invite_url): a browser never sends a fragment to a server, so the
token reaches no access log, analytics hit or link-preview crawler; the page
reads it and passes it on in request bodies only. Opening or previewing the
link changes nothing: only a booking uses the invitation.

Sending again while the invitation is active gives the same link back, for
its whole seven days. Once it has expired, the next send replaces it with a
new one; once it is used or revoked, the next send -- when the child may be
invited again, say after the invited Demo was cancelled -- issues a new one
too. Who may send is the caller's check (an administrator for any lead, a BDE
for their own leads, ``owner_bde``); when is demo_invite_refusal's: a
submitted Diagnostic report, a class and syllabus the Demo page offers, and no
Demo of the child's to come, under way or completed.

Issuing and revoking log ids only, never the token.
"""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from activity.utils import log_activity

from .booking_service import (
    BUSY_SQLSTATES,
    BookingBusy,
    BookingNotOwned,
    _locked_lead,
    _set_lock_timeout,
    demo_invite_refusal,
    invite_by_token,
)
from .models import DemoInvite, DemoInviteStatus, DiagnosticBooking, new_invite_token

# How long a parent has to book with an invitation.
INVITE_VALIDITY = timedelta(days=7)
# The marketing site's invitation page; the token goes in its fragment.
PUBLIC_PATH = '/demo-invite'
# Active, but the child may not book a Demo with it now (demo_invite_refusal):
# what the public lookup answers instead of ACTIVE.
UNAVAILABLE = 'UNAVAILABLE'
# Tokens drawn for one invitation before giving up.
MAX_TOKEN_ATTEMPTS = 5


class InviteIssueError(Exception):
    """No invitation could be issued: every token drawn collided with an existing one."""


def invitable(booking, now):
    """
    Whether the parent of ``booking`` may be sent a Demo invitation from it now:
    a Diagnostic booking demo_invite_refusal has no objection to. Read with its
    lead and report (select_related) to spare the queries.
    """
    return isinstance(booking, DiagnosticBooking) and demo_invite_refusal(booking, booking.lead, now) is None


def invite_url(invite):
    """The URL the parent opens: the invitation page, the token in its fragment."""
    return f"{settings.MARKETING_SITE_URL.rstrip('/')}{PUBLIC_PATH}#{invite.token}"


def issue_invite(diagnostic, actor, *, owner_bde=None, request=None, now=None):
    """
    The active invitation to book a Demo from the Diagnostic booking
    ``diagnostic``, sent by ``actor``; returns (invite, created). An active
    one is returned as it is (created False); otherwise a new one, valid for
    INVITE_VALIDITY, replaces an expired one. With ``owner_bde`` (a BDE
    sending for their own lead) the lead must still be theirs, checked under
    its lock (BookingNotOwned, answered as a booking that does not exist).
    Raises the BookingError demo_invite_refusal names, or BookingBusy.

    Locks the lead first, as every booking of the child does, then the
    Diagnostic's open invitation: two sends for one Diagnostic queue, and the
    second gets the first one's link.
    """
    now = now or timezone.now()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            lead = _locked_lead(diagnostic.lead_id)
            if owner_bde is not None and lead.owner_bde_id != owner_bde.pk:
                raise BookingNotOwned()
            diagnostic = DiagnosticBooking.objects.select_related('report').get(pk=diagnostic.pk)
            refusal = demo_invite_refusal(diagnostic, lead, now)
            if refusal is not None:
                raise refusal
            current = (
                DemoInvite.objects.select_for_update()
                .filter(diagnostic_booking=diagnostic, used_at__isnull=True, revoked_at__isnull=True,
                        replaced_at__isnull=True)
                .first()
            )
            if current is not None and current.status(now) == DemoInviteStatus.ACTIVE:
                return current, False
            if current is not None:
                # Expired: it stays expired, and stops being the Diagnostic's open invitation.
                current.replaced_at = now
                current.save(update_fields=['replaced_at'])
            invite = _create(lead, diagnostic, actor, now)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise

    log_activity(
        action='demo_invite.issue',
        entity_type='demo_invite',
        entity_id=invite.id,
        entity_label='Demo invitation',
        # Ids and instants only: never the token, a name or a phone number.
        context={
            'diagnostic_booking_id': str(diagnostic.id),
            'lead_id': str(lead.id),
            'expires_at': invite.expires_at.isoformat(),
            'replaced_invite_id': str(current.id) if current is not None else None,
        },
        request=request,
        actor=actor,
    )
    return invite, True


def revoke_invite(invite, actor, *, request=None, now=None):
    """
    Revoke ``invite`` so its link books nothing; returns (invite, changed).
    Only an active invitation changes: a used, expired or revoked one is left
    as it is. The next send for the Diagnostic issues a new link.
    """
    now = now or timezone.now()
    with transaction.atomic():
        invite = DemoInvite.objects.select_for_update().get(pk=invite.pk)
        if invite.status(now) != DemoInviteStatus.ACTIVE:
            return invite, False
        invite.revoked_at = now
        invite.revoked_by = actor
        invite.save(update_fields=['revoked_at', 'revoked_by'])
    log_activity(
        action='demo_invite.revoke',
        entity_type='demo_invite',
        entity_id=invite.id,
        entity_label='Demo invitation',
        context={'diagnostic_booking_id': str(invite.diagnostic_booking_id), 'lead_id': str(invite.lead_id)},
        request=request,
        actor=actor,
    )
    return invite, True


def invite_body(invite, now=None):
    """An invitation as the Hub shows it to whoever sends it: its link, where it stands and how long it lasts."""
    creator = invite.created_by
    return {
        'id': str(invite.id),
        'url': invite_url(invite),
        'status': invite.status(now),
        'created_at': invite.created_at.isoformat(),
        'expires_at': invite.expires_at.isoformat(),
        'created_by': {'id': str(creator.pk), 'full_name': creator.full_name or creator.email} if creator else None,
    }


def public_state(token, now=None):
    """
    What the invitation page shows for ``token``: {"status", "expires_at"},
    or None for a token that names no invitation. ``status`` is the
    invitation's own (DemoInviteStatus), except an active one the child may
    not book a Demo with now -- one already booked through the Demo page, say
    -- which is UNAVAILABLE. Nothing about the child or the parent, and
    nothing is changed: opening the link uses nothing up.
    """
    now = now or timezone.now()
    invite = invite_by_token(token)
    if invite is None:
        return None
    status = invite.status(now)
    if status == DemoInviteStatus.ACTIVE:
        diagnostic = DiagnosticBooking.objects.select_related('report', 'lead').get(pk=invite.diagnostic_booking_id)
        if demo_invite_refusal(diagnostic, diagnostic.lead, now) is not None:
            status = UNAVAILABLE
    return {
        'status': status,
        'expires_at': invite.expires_at.isoformat() if status == DemoInviteStatus.ACTIVE else None,
    }


def _create(lead, diagnostic, actor, now):
    for _attempt in range(MAX_TOKEN_ATTEMPTS):
        try:
            # A savepoint of its own: a token that collides leaves the transaction usable.
            with transaction.atomic():
                return DemoInvite.objects.create(
                    token=new_invite_token(), lead=lead, diagnostic_booking=diagnostic, created_by=actor,
                    created_at=now, expires_at=now + INVITE_VALIDITY,
                )
        except IntegrityError:
            # Under the lead's lock nothing else issues for this Diagnostic, so only the token can collide.
            continue
    raise InviteIssueError(f'No Demo invitation could be issued for booking {diagnostic.pk}: every token collided.')
