from django.urls import path

from .bde_views import BdeBookingLinkSharedView, BdeFollowUpsView

app_name = 'bde_communications'

# Under /api/bde/, beside the BDE workspace (bookings.urls): the caller's own leads' reminders, and
# what the enquiry page tells them when a booking link goes to a parent.
urlpatterns = [
    path('follow-ups/', BdeFollowUpsView.as_view(), name='follow-ups'),
    path('enquiries/<uuid:pk>/booking-link-shared/', BdeBookingLinkSharedView.as_view(), name='booking-link-shared'),
]
