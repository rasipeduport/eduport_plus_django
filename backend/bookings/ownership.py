"""
Giving a lead to a BDE: the one place a lead's owner changes once the lead
exists. (Its first owner, if any, comes as it is made: the BDE whose link
brought its first booking, bookings.booking_service, or the BDE who added it,
bookings.enquiries.)

assign_owner is what the administrators' Leads page calls today
(via='admin_leads'), and what any later source of assignments -- a sync from
a CRM whose own rules pick the BDE, say -- calls as well, under its own
``via``: whoever calls it, the same checks, locks, history and follow-on
changes apply, and the BDE's My Leads reads the result.

- The new owner must be an active BDE (bookings.services.owns_booking_links),
  checked under the lock on their account row, so a deactivation or role
  change committing at the same moment is seen.
- The lead row is locked first (FOR NO KEY UPDATE, the lock its bookings
  take), so two assignments of one lead -- or an assignment and a booking --
  queue. ``expected_owner_id`` is the owner the caller saw: when given and no
  longer true, the assignment is refused (OwnerChanged) instead of silently
  undoing the other.
- The old owner's link no longer stands for the lead (owner_link is cleared),
  and owner_assigned_at becomes now: the moment it became the new owner's.
- The lead's bookings' open communication tasks become the new owner's, and
  the unsent parent messages, which sign with the owner, are checked again
  (communications.planner.lead_owner_changed), in the same transaction.
- A new enquiry -- no booking yet -- gets the new owner's reminder to call
  the parent, shown for 24 hours (communications.followups.enquiry_assigned);
  every reminder the lead has goes with it, and the BDE before sees none.
- The change is logged (lead.assign_owner): ids only.

Locks, in order: the lead, the BDE's account, then the lead's messages and
tasks (the planner's order), then its follow-up. Booking writers take the lead before any
account too (a reschedule: the lead, then the tutor's), so none of them waits
on this in a circle.
"""
from django.db import OperationalError, transaction
from django.utils import timezone

from accounts.models import User
from activity.utils import log_activity
from communications import followups, planner

from .booking_service import BUSY_SQLSTATES, BookingBusy, _set_lock_timeout
from .models import Lead
from .services import owns_booking_links

# expected_owner_id when the caller does not check what it replaces.
ANY_OWNER = object()


class OwnershipError(Exception):
    code = 'OWNER_NOT_CHANGED'
    http_status = 400
    message = 'The lead could not be assigned.'


class NotAnActiveBde(OwnershipError):
    code = 'NOT_AN_ACTIVE_BDE'
    message = 'Leads can only be assigned to an active BDE account.'


class OwnerChanged(OwnershipError):
    code = 'OWNER_CHANGED'
    http_status = 409
    message = 'Someone else changed who owns this lead. Check the new owner before assigning it again.'


def assign_owner(lead_id, bde_id, *, actor=None, via, expected_owner_id=ANY_OWNER, request=None, now=None):
    """
    Make the BDE ``bde_id`` the owner of lead ``lead_id``; returns (lead,
    changed). ``changed`` is False when the lead already was theirs: nothing
    is written. Raises Lead.DoesNotExist, NotAnActiveBde, OwnerChanged, or
    BookingBusy when a lock is held past the booking lock timeout.
    """
    now = now or timezone.now()
    try:
        with transaction.atomic():
            _set_lock_timeout()
            lead = Lead.objects.select_for_update(no_key=True).get(pk=lead_id)
            previous = lead.owner_bde_id
            if expected_owner_id is not ANY_OWNER and _id(expected_owner_id) != _id(previous):
                raise OwnerChanged()
            bde = User.objects.select_for_update(no_key=True).filter(pk=bde_id).first()
            if not owns_booking_links(bde):
                raise NotAnActiveBde()
            if previous == bde.pk:
                return lead, False

            lead.owner_bde = bde
            lead.owner_link = None
            lead.owner_assigned_at = now
            lead.save(update_fields=['owner_bde', 'owner_link', 'owner_assigned_at', 'updated_at'])
            planner.lead_owner_changed(lead, now)
            followups.enquiry_assigned(lead, now)
    except OperationalError as exc:
        if getattr(exc.__cause__, 'sqlstate', None) in BUSY_SQLSTATES:
            raise BookingBusy() from exc
        raise

    log_activity(
        action='lead.assign_owner',
        entity_type='lead',
        entity_id=lead.id,
        entity_label=f'{lead.grade} lead',
        context={'previous_owner_id': _id(previous), 'owner_id': str(bde.pk), 'via': via},
        request=request,
        actor=actor,
    )
    return lead, True


def _id(value):
    return str(value) if value is not None else None
