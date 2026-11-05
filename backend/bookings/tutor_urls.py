from django.urls import path

from .tutor_views import TutorBookingDetailView, TutorBookingListView, TutorBookingStartView

app_name = 'tutor_bookings'

urlpatterns = [
    path('', TutorBookingListView.as_view(), name='list'),
    path('<str:booking_type>/<uuid:pk>/', TutorBookingDetailView.as_view(), name='detail'),
    path('<str:booking_type>/<uuid:pk>/start/', TutorBookingStartView.as_view(), name='start'),
]
