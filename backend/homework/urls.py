from django.urls import path
from .views import HomeworkView, HomeworkDetailView, HomeworkSubmitView, HomeworkScoreView, HomeworkFileDownloadView

app_name = 'homework'

urlpatterns = [
    path('', HomeworkView.as_view(), name='homework-list'),
    path('files/<uuid:file_id>/', HomeworkFileDownloadView.as_view(), name='homework-file'),
    path('files/<uuid:file_id>', HomeworkFileDownloadView.as_view()),
    path('<uuid:homework_id>/', HomeworkDetailView.as_view(), name='homework-detail'),
    path('<uuid:homework_id>', HomeworkDetailView.as_view()),
    path('<uuid:homework_id>/submit/', HomeworkSubmitView.as_view(), name='homework-submit'),
    path('<uuid:homework_id>/submit', HomeworkSubmitView.as_view()),
    path('<uuid:homework_id>/score/', HomeworkScoreView.as_view(), name='homework-score'),
    path('<uuid:homework_id>/score', HomeworkScoreView.as_view()),
]
