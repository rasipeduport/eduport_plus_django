from django.urls import path

from .tutor_views import TutorBookingDetailView, TutorBookingListView

app_name = 'tutor_bookings'

urlpatterns = [
    path('', TutorBookingListView.as_view(), name='list'),
    path('<uuid:pk>/', TutorBookingDetailView.as_view(), name='detail'),
]
