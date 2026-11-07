from django.urls import path

from .management_views import (
    BookingCancelView,
    BookingDemoInviteView,
    BookingDetailView,
    BookingHistoryView,
    BookingListView,
    BookingRedemoView,
    BookingRescheduleView,
    BookingTutorsView,
    BookingTutorView,
    RedemoDetailView,
    RedemoListView,
    RedemoRemarksView,
    RedemoScheduleView,
    RedemoSlotsView,
    RedemoTutorsView,
    RescheduleOptionsView,
    SlotTutorsView,
)

app_name = 'booking_management'

# <booking_type> is demo or diagnostic (management_views answers 404 for any other).
urlpatterns = [
    path('slots/<uuid:slot_id>/tutors/', SlotTutorsView.as_view(), name='slot-tutors'),
    # Re-Demo requests (bookings.redemos), before <booking_type>/ so "redemos" is never read as a type.
    path('redemos/', RedemoListView.as_view(), name='redemos'),
    path('redemos/<uuid:pk>/', RedemoDetailView.as_view(), name='redemo'),
    path('redemos/<uuid:pk>/tutors/', RedemoTutorsView.as_view(), name='redemo-tutors'),
    path('redemos/<uuid:pk>/slots/', RedemoSlotsView.as_view(), name='redemo-slots'),
    path('redemos/<uuid:pk>/schedule/', RedemoScheduleView.as_view(), name='redemo-schedule'),
    path('redemos/<uuid:pk>/remarks/', RedemoRemarksView.as_view(), name='redemo-remarks'),
    path('<str:booking_type>/', BookingListView.as_view(), name='list'),
    path('<str:booking_type>/<uuid:pk>/', BookingDetailView.as_view(), name='detail'),
    path('<str:booking_type>/<uuid:pk>/tutors/', BookingTutorsView.as_view(), name='tutors'),
    path('<str:booking_type>/<uuid:pk>/tutor/', BookingTutorView.as_view(), name='tutor'),
    path('<str:booking_type>/<uuid:pk>/history/', BookingHistoryView.as_view(), name='history'),
    path('<str:booking_type>/<uuid:pk>/reschedule-options/', RescheduleOptionsView.as_view(), name='reschedule-options'),
    path('<str:booking_type>/<uuid:pk>/reschedule/', BookingRescheduleView.as_view(), name='reschedule'),
    path('<str:booking_type>/<uuid:pk>/cancel/', BookingCancelView.as_view(), name='cancel'),
    # A Diagnostic's Demo invitation for its parent (bookings.demo_invites); any other type is 404.
    path('<str:booking_type>/<uuid:pk>/demo-invite/', BookingDemoInviteView.as_view(), name='demo-invite'),
    # Asking for a completed Demo to be taught again (bookings.redemos); any other type is 404.
    path('<str:booking_type>/<uuid:pk>/redemo/', BookingRedemoView.as_view(), name='redemo-request'),
]
