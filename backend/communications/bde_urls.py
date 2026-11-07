from django.urls import path

from .bde_views import BdeFollowUpCompleteView, BdeFollowUpsView

app_name = 'bde_communications'

# Under /api/bde/, beside the BDE workspace (bookings.urls): the caller's own leads' follow-ups.
urlpatterns = [
    path('follow-ups/', BdeFollowUpsView.as_view(), name='follow-ups'),
    path('follow-ups/<uuid:pk>/complete/', BdeFollowUpCompleteView.as_view(), name='follow-up-complete'),
]
