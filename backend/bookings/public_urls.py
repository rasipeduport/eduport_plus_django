from django.urls import path

from .public_views import (
    PublicBookingCalendarView,
    PublicBookingCreateView,
    PublicDemoInviteBookView,
    PublicDemoInviteStateView,
    PublicLeadCreateView,
)

app_name = 'public_bookings'

urlpatterns = [
    path('booking-calendar/<str:booking_type>/', PublicBookingCalendarView.as_view(), name='calendar'),
    path('bookings/<str:booking_type>/', PublicBookingCreateView.as_view(), name='create'),
    # The marketing site's lead forms (the main website's and the landing page's).
    path('leads/', PublicLeadCreateView.as_view(), name='lead'),
    # A Demo invitation's page (bookings.demo_invites): the token in the body, never the path.
    path('demo-invites/state/', PublicDemoInviteStateView.as_view(), name='demo-invite-state'),
    path('demo-invites/book/', PublicDemoInviteBookView.as_view(), name='demo-invite-book'),
]
