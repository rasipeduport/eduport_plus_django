from django.urls import path

from .quote_views import EnquiryPlanView, QuoteCancelView, QuoteDetailView, QuotePdfView, QuotesView

from .views import (
    CatalogueDetailView, CataloguePdfView, CatalogueSelectionPdfView, CatalogueSelectionView, CatalogueView, PricingView, SyllabiView, SyllabusDetailView, SyllabusDraftView, SyllabusDuplicateView, SyllabusLifecycleView,
    SyllabusPdfDownloadView, SyllabusPdfPreviewView, SyllabusPublishView, SyllabusRevisionPdfView, SyllabusRevisionView,
    SyllabusSelectionPdfView, SyllabusSelectionView,
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
    path('syllabi/<uuid:pk>/revisions/<int:number>/selection/', SyllabusSelectionView.as_view(), name='selection'),
    path('syllabi/<uuid:pk>/revisions/<int:number>/selection/pdf/', SyllabusSelectionPdfView.as_view(),
         name='selection_pdf'),
    path('pricing/', PricingView.as_view(), name='pricing'),
    # The catalogue on sale: what BDEs (and administrators) quote parents from.
    path('catalogue/', CatalogueView.as_view(), name='catalogue'),
    path('catalogue/<uuid:pk>/', CatalogueDetailView.as_view(), name='catalogue_syllabus'),
    path('catalogue/<uuid:pk>/pdf/', CataloguePdfView.as_view(), name='catalogue_pdf'),
    path('catalogue/<uuid:pk>/selection/', CatalogueSelectionView.as_view(), name='catalogue_selection'),
    path('catalogue/<uuid:pk>/selection/pdf/', CatalogueSelectionPdfView.as_view(), name='catalogue_selection_pdf'),
    # Quotes: what a parent was quoted, kept as it was issued (sales.quotes).
    path('quotes/', QuotesView.as_view(), name='quotes'),
    path('enquiries/<uuid:pk>/plan/', EnquiryPlanView.as_view(), name='enquiry_plan'),
    path('quotes/<uuid:pk>/', QuoteDetailView.as_view(), name='quote'),
    path('quotes/<uuid:pk>/pdf/', QuotePdfView.as_view(), name='quote_pdf'),
    path('quotes/<uuid:pk>/cancel/', QuoteCancelView.as_view(), name='quote_cancel'),
]
