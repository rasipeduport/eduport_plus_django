from django.urls import path

from .bde_views import BdeFollowUpsView

app_name = 'bde_communications'

# Under /api/bde/, beside the BDE workspace (bookings.urls): the caller's own leads' reminders.
urlpatterns = [
    path('follow-ups/', BdeFollowUpsView.as_view(), name='follow-ups'),
]
