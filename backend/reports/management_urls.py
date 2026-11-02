from django.urls import path

from .management_views import BookingReportPdfView, BookingReportRevisionsView, BookingReportView

app_name = 'booking_reports'

# Under /api/bookings/, beside bookings.booking_urls: <booking_type> is demo or diagnostic.
urlpatterns = [
    path('<str:booking_type>/<uuid:pk>/report/', BookingReportView.as_view(), name='report'),
    path('<str:booking_type>/<uuid:pk>/report/revisions/', BookingReportRevisionsView.as_view(), name='revisions'),
    path('<str:booking_type>/<uuid:pk>/report/pdf/', BookingReportPdfView.as_view(), name='pdf'),
    path(
        '<str:booking_type>/<uuid:pk>/report/revisions/<int:version>/pdf/', BookingReportPdfView.as_view(),
        name='revision_pdf',
    ),
]
