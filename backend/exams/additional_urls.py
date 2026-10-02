from django.urls import path
from .views import (
    AdditionalExamsView,
    AdditionalExamDetailView,
    AdditionalExamSubmitView,
    AdditionalExamScoreView,
    AdditionalExamFileDownloadView,
)

app_name = 'additional_exams'

urlpatterns = [
    path('', AdditionalExamsView.as_view(), name='additional-exams-list-create'),
    path('files/<uuid:file_id>/', AdditionalExamFileDownloadView.as_view(), name='additional-exam-file'),
    path('files/<uuid:file_id>', AdditionalExamFileDownloadView.as_view()),
    path('<uuid:exam_id>/', AdditionalExamDetailView.as_view(), name='additional-exam-detail'),
    path('<uuid:exam_id>', AdditionalExamDetailView.as_view()),
    path('<uuid:exam_id>/submit/', AdditionalExamSubmitView.as_view(), name='additional-exam-submit'),
    path('<uuid:exam_id>/submit', AdditionalExamSubmitView.as_view()),
    path('<uuid:exam_id>/score/', AdditionalExamScoreView.as_view(), name='additional-exam-score'),
    path('<uuid:exam_id>/score', AdditionalExamScoreView.as_view()),
]
