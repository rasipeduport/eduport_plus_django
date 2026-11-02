from django.urls import path

from .tutor_views import TutorReportPdfView, TutorReportPreviewView, TutorReportRevisionsView, TutorReportView

app_name = 'tutor_reports'

# Under /api/tutor/bookings/, beside bookings.tutor_urls: <booking_type> is demo or diagnostic.
urlpatterns = [
    path('<str:booking_type>/<uuid:pk>/report/', TutorReportView.as_view(), name='report'),
    path('<str:booking_type>/<uuid:pk>/report/revisions/', TutorReportRevisionsView.as_view(), name='revisions'),
    path('<str:booking_type>/<uuid:pk>/report/pdf/', TutorReportPdfView.as_view(), name='pdf'),
    path(
        '<str:booking_type>/<uuid:pk>/report/revisions/<int:version>/pdf/', TutorReportPdfView.as_view(),
        name='revision_pdf',
    ),
    path('<str:booking_type>/<uuid:pk>/report/preview/', TutorReportPreviewView.as_view(), name='preview'),
]
