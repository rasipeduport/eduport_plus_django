from django.urls import path

from .management_views import (
    BookingCancelView,
    BookingDetailView,
    BookingHistoryView,
    BookingListView,
    BookingRescheduleView,
    BookingTutorsView,
    BookingTutorView,
    RescheduleOptionsView,
    SlotTutorsView,
)

app_name = 'booking_management'

# <booking_type> is demo or diagnostic (management_views answers 404 for any other).
urlpatterns = [
    path('slots/<uuid:slot_id>/tutors/', SlotTutorsView.as_view(), name='slot-tutors'),
    path('<str:booking_type>/', BookingListView.as_view(), name='list'),
    path('<str:booking_type>/<uuid:pk>/', BookingDetailView.as_view(), name='detail'),
    path('<str:booking_type>/<uuid:pk>/tutors/', BookingTutorsView.as_view(), name='tutors'),
    path('<str:booking_type>/<uuid:pk>/tutor/', BookingTutorView.as_view(), name='tutor'),
    path('<str:booking_type>/<uuid:pk>/history/', BookingHistoryView.as_view(), name='history'),
    path('<str:booking_type>/<uuid:pk>/reschedule-options/', RescheduleOptionsView.as_view(), name='reschedule-options'),
    path('<str:booking_type>/<uuid:pk>/reschedule/', BookingRescheduleView.as_view(), name='reschedule'),
    path('<str:booking_type>/<uuid:pk>/cancel/', BookingCancelView.as_view(), name='cancel'),
]
