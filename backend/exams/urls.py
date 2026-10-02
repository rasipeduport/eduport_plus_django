from django.urls import path
from .views import ExamsView, ChapterNamesView, ExamDetailView, ExamResultView, ExamFileDownloadView

app_name = 'exams'

urlpatterns = [
    path('', ExamsView.as_view(), name='exams-list-create-update'),
    path('chapter-names/', ChapterNamesView.as_view(), name='chapter-names'),
    path('chapter-names', ChapterNamesView.as_view()),
    path('files/<uuid:file_id>/', ExamFileDownloadView.as_view(), name='exam-file'),
    path('files/<uuid:file_id>', ExamFileDownloadView.as_view()),
    path('<uuid:exam_id>/', ExamDetailView.as_view(), name='exam-detail'),
    path('<uuid:exam_id>', ExamDetailView.as_view()),
    path('<uuid:exam_id>/result/', ExamResultView.as_view(), name='exam-result'),
    path('<uuid:exam_id>/result', ExamResultView.as_view()),
]
