from django.urls import path
from .views import SessionsView, CancelSeriesView, SessionFileUploadView, SessionFileDownloadView

app_name = 'sessions'

urlpatterns = [
    path('', SessionsView.as_view(), name='sessions-list-create-update'),
    path('cancel-series/', CancelSeriesView.as_view(), name='cancel-series'),
    path('cancel-series', CancelSeriesView.as_view()),
    # Frontend compatibility routes
    path('cancel/', CancelSeriesView.as_view(), name='cancel-series-alias'),
    path('cancel', CancelSeriesView.as_view()),
    # Uploaded session content: attach a file to one content field, and the
    # authenticated download the stored link points at.
    path('<uuid:session_id>/files/<str:field>/', SessionFileUploadView.as_view(), name='session-file-upload'),
    path('<uuid:session_id>/files/<str:field>', SessionFileUploadView.as_view()),
    path('files/<uuid:file_id>/', SessionFileDownloadView.as_view(), name='session-file'),
    path('files/<uuid:file_id>', SessionFileDownloadView.as_view()),
]
