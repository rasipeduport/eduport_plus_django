from django.urls import path

from .views import (
    PricingView, SyllabiView, SyllabusDetailView, SyllabusDraftView, SyllabusDuplicateView, SyllabusLifecycleView,
    SyllabusPdfDownloadView, SyllabusPdfPreviewView, SyllabusPublishView, SyllabusRevisionPdfView, SyllabusRevisionView,
)

app_name = 'sales'

urlpatterns = [
    path('syllabi/', SyllabiView.as_view(), name='syllabi'),
    path('syllabi/pdf-preview/', SyllabusPdfPreviewView.as_view(), name='pdf_preview'),
    path('syllabi/<uuid:pk>/', SyllabusDetailView.as_view(), name='syllabus'),
    path('syllabi/<uuid:pk>/draft/', SyllabusDraftView.as_view(), name='draft'),
    path('syllabi/<uuid:pk>/publish/', SyllabusPublishView.as_view(), name='publish'),
    path('syllabi/<uuid:pk>/deactivate/', SyllabusLifecycleView.as_view(lifecycle_action='deactivate'), name='deactivate'),
    path('syllabi/<uuid:pk>/reactivate/', SyllabusLifecycleView.as_view(lifecycle_action='reactivate'), name='reactivate'),
    path('syllabi/<uuid:pk>/duplicate/', SyllabusDuplicateView.as_view(), name='duplicate'),
    path('syllabi/<uuid:pk>/revisions/<int:number>/', SyllabusRevisionView.as_view(), name='revision'),
    path('syllabi/<uuid:pk>/pdf/', SyllabusPdfDownloadView.as_view(), name='pdf'),
    path('syllabi/<uuid:pk>/revisions/<int:number>/pdf/', SyllabusRevisionPdfView.as_view(), name='revision_pdf'),
    path('pricing/', PricingView.as_view(), name='pricing'),
]
