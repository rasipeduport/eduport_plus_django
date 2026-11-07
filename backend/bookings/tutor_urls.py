from django.urls import path

from .tutor_views import TutorBookingDetailView, TutorBookingListView, TutorBookingNotesView, TutorBookingStartView

app_name = 'tutor_bookings'

urlpatterns = [
    path('', TutorBookingListView.as_view(), name='list'),
    path('<str:booking_type>/<uuid:pk>/', TutorBookingDetailView.as_view(), name='detail'),
    path('<str:booking_type>/<uuid:pk>/start/', TutorBookingStartView.as_view(), name='start'),
    # Staff's notes on the booking's lead -- shared by all its bookings (bookings.notes).
    path('<str:booking_type>/<uuid:pk>/notes/', TutorBookingNotesView.as_view(), name='notes'),
]
