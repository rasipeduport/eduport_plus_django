from django.urls import path

from .management_views import BookingDetailView, BookingListView, BookingTutorsView, BookingTutorView, SlotTutorsView

app_name = 'booking_management'

urlpatterns = [
    path('', BookingListView.as_view(), name='list'),
    path('slots/<uuid:slot_id>/tutors/', SlotTutorsView.as_view(), name='slot-tutors'),
    path('<uuid:pk>/', BookingDetailView.as_view(), name='detail'),
    path('<uuid:pk>/tutors/', BookingTutorsView.as_view(), name='tutors'),
    path('<uuid:pk>/tutor/', BookingTutorView.as_view(), name='tutor'),
]
