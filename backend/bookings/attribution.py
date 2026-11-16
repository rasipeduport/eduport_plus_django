"""
Resolving a booking's ``ref`` token to the BDE it credits.

Only the token decides: it is looked up in BookingLink (DEVT-5934) and the
link's owner must still be an active BDE (bookings.services.owns_booking_links).
Nothing the parent submits names a BDE. A token that cannot attribute the
booking never blocks it: the booking is kept unattributed, with the reason.
"""
import re
from dataclasses import dataclass

from .models import BookingLink, ReferralStatus
from .services import owns_booking_links

# BookingLink tokens are secrets.token_urlsafe values (22 characters today,
# 64 at most in the column).
TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


@dataclass(frozen=True)
class Referral:
    status: str
    link: BookingLink | None = None

    @property
    def bde(self):
        return self.link.bde if self.status == ReferralStatus.ATTRIBUTED else None


def resolve_referral(ref, booking_type):
    if ref is None or ref == '':
        return Referral(ReferralStatus.NO_REF)
    if not isinstance(ref, str) or not TOKEN_RE.match(ref):
        return Referral(ReferralStatus.INVALID_REF)
    link = BookingLink.objects.select_related('bde').filter(token=ref).first()
    if link is None:
        return Referral(ReferralStatus.UNKNOWN_REF)
    if link.revoked_at is not None:
        return Referral(ReferralStatus.REVOKED_LINK, link)
    if not owns_booking_links(link.bde):
        return Referral(ReferralStatus.INACTIVE_BDE, link)
    if link.booking_type != booking_type:
        return Referral(ReferralStatus.WRONG_TYPE, link)
    return Referral(ReferralStatus.ATTRIBUTED, link)
