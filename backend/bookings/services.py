"""
Issuing and reading a BDE's booking links (bookings.models.BookingLink).

``links_for`` is the only way a link comes into being: the BDE workspace asks
for the caller's own links, and a booking type with no active link yet is
issued one there and then. Every later call returns the same links.

Issuing is safe to race. The database holds at most one active link per BDE
and type, so of two requests issuing the same link one inserts and the other
fails and reads the winner's row back. A token that collides with an existing
one (128 random bits: in practice never) is drawn again.
"""
from urllib.parse import urlencode

from django.conf import settings
from django.db import IntegrityError, transaction

from accounts.models import RoleChoices
from activity.utils import log_activity

from .models import BookingLink, BookingType, new_link_token

# The public booking page each type opens on the marketing site.
PUBLIC_PATHS = {
    BookingType.DEMO: '/demo',
    BookingType.DIAGNOSTIC: '/exam',
}

# Tokens drawn for one link before giving up.
MAX_TOKEN_ATTEMPTS = 5


class LinkIssueError(Exception):
    """No link could be issued: every token drawn collided with an existing one."""


def owns_booking_links(user):
    """
    Whether booking links belong to ``user``: an active BDE account.

    Checked on top of accounts.view_own_booking_links, which a superuser holds
    whatever their role (decision D1). A deactivated account, or one whose
    role is no longer BDE, has no usable links.
    """
    return bool(
        user is not None
        and user.is_authenticated
        and user.is_active
        and user.deactivated_at is None
        and user.role == RoleChoices.BDE
    )


def link_url(link):
    """The URL a parent opens: the type's booking page with the link's token as ``ref``."""
    base = settings.MARKETING_SITE_URL.rstrip('/')
    return f"{base}{PUBLIC_PATHS[link.booking_type]}?{urlencode({'ref': link.token})}"


def active_links_by_type(bde):
    """The active links ``bde`` owns, keyed by booking type."""
    return {link.booking_type: link for link in BookingLink.objects.filter(bde=bde, revoked_at__isnull=True)}


def links_for(bde, request=None):
    """
    The active link of every booking type ``bde`` owns, in BookingType order,
    issuing any that does not exist yet. The caller has already checked
    ``owns_booking_links``.
    """
    links = active_links_by_type(bde)
    for booking_type in BookingType.values:
        if booking_type not in links:
            links[booking_type] = _issue(bde, booking_type, request)
    return [links[booking_type] for booking_type in BookingType.values]


def _issue(bde, booking_type, request):
    for _attempt in range(MAX_TOKEN_ATTEMPTS):
        try:
            # A savepoint of its own, so a refused insert leaves any
            # surrounding transaction usable.
            with transaction.atomic():
                link = BookingLink.objects.create(
                    bde=bde, booking_type=booking_type, token=new_link_token(), created_by=bde,
                )
        except IntegrityError:
            # Either a concurrent request issued this link first -- use
            # theirs -- or the token collided, and another is drawn.
            existing = BookingLink.objects.filter(bde=bde, booking_type=booking_type, revoked_at__isnull=True).first()
            if existing is not None:
                return existing
            continue

        # The link's id and type, never its token: the log is readable by
        # every administrator and the token needs no copy outside its row.
        log_activity(
            action='booking_link.issue',
            entity_type='booking_link',
            entity_id=link.id,
            entity_label=link.get_booking_type_display(),
            context={'booking_type': booking_type, 'bde_id': str(bde.id)},
            request=request,
            actor=bde,
        )
        return link
    raise LinkIssueError(f'No {booking_type} link could be issued for account {bde.pk}: every token drawn collided.')
