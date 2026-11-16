from django.urls import path

from .views import (
    BdeActivityView,
    BdeBookingCancelView,
    BdeBookingsView,
    BdeBookingLinksView,
    BdeDashboardView,
    BdeDemoInviteView,
    BdeEnquiriesView,
    BdeEnquiryDetailView,
    BdeEnquiryHistoryView,
    BdeEnquiryNotesView,
    BdeEnquiryTimezoneView,
    BdeRedemoCloseView,
    BdeRedemoReopenView,
    BdeRedemoView,
)

app_name = 'bookings'

urlpatterns = [
    path('booking-links/', BdeBookingLinksView.as_view(), name='bde-booking-links'),
    path('dashboard/', BdeDashboardView.as_view(), name='bde-dashboard'),
    path('enquiries/', BdeEnquiriesView.as_view(), name='bde-enquiries'),
    path('enquiries/<uuid:pk>/', BdeEnquiryDetailView.as_view(), name='bde-enquiry'),
    # The History of the caller's own enquiry: every change to its bookings, with who and why (bookings.timeline).
    path('enquiries/<uuid:pk>/history/', BdeEnquiryHistoryView.as_view(), name='bde-enquiry-history'),
    # Staff's notes on the caller's own enquiry, shared with its tutors and the administrators (bookings.notes).
    path('enquiries/<uuid:pk>/notes/', BdeEnquiryNotesView.as_view(), name='bde-enquiry-notes'),
    # Correcting the time zone the caller's own enquiry's student books from (bookings.student_timezones).
    path(
        'enquiries/<uuid:pk>/student-timezone/', BdeEnquiryTimezoneView.as_view(),
        name='bde-enquiry-student-timezone',
    ),
    # What has happened to the caller's own leads' bookings, newest first.
    path('activity/', BdeActivityView.as_view(), name='bde-activity'),
    # The caller's own leads' bookings of one type (Demo Bookings, Diagnostic Bookings).
    path('bookings/<str:booking_type>/', BdeBookingsView.as_view(), name='bde-bookings'),
    # Cancelling a booking of the caller's own lead (Q22); ownership checked in the view and the service.
    path('bookings/<str:booking_type>/<uuid:pk>/cancel/', BdeBookingCancelView.as_view(), name='bde-booking-cancel'),
    # A Demo invitation from a Diagnostic of the caller's own lead; ownership checked in the view and the service.
    path('bookings/<str:booking_type>/<uuid:pk>/demo-invite/', BdeDemoInviteView.as_view(), name='bde-demo-invite'),
    # A Re-Demo of a completed Demo of the caller's own lead (bookings.redemos); ownership checked in the
    # view and the service. An administrator then schedules it.
    path('bookings/<str:booking_type>/<uuid:pk>/redemo/', BdeRedemoView.as_view(), name='bde-redemo'),
    # Closing that request while nothing is booked for it, and reopening it; ownership checked as for asking.
    path('bookings/<str:booking_type>/<uuid:pk>/redemo/close/', BdeRedemoCloseView.as_view(), name='bde-redemo-close'),
    path(
        'bookings/<str:booking_type>/<uuid:pk>/redemo/reopen/', BdeRedemoReopenView.as_view(),
        name='bde-redemo-reopen',
    ),
    # The reports on the caller's own leads, and their PDFs, are reports.bde_urls (P9).
]
