from django.urls import path
from .views import (
    CancelSeriesView,
    SessionFileDownloadView,
    SessionFileUploadView,
    SessionOutcomeCorrectionView,
    SessionOutcomeRevokeView,
    SessionOutcomeView,
    SessionStartView,
    SessionsView,
)

app_name = 'sessions'

urlpatterns = [
    path('', SessionsView.as_view(), name='sessions-list-create-update'),
    path('cancel-series/', CancelSeriesView.as_view(), name='cancel-series'),
    path('cancel-series', CancelSeriesView.as_view()),
    # Frontend compatibility routes
    path('cancel/', CancelSeriesView.as_view(), name='cancel-series-alias'),
    path('cancel', CancelSeriesView.as_view()),
    # Start Session: the assigned tutor, the student's mentor or an administrator,
    # from 5 minutes before the class (sessions.lifecycle).
    path('<uuid:session_id>/start/', SessionStartView.as_view(), name='session-start'),
    path('<uuid:session_id>/start', SessionStartView.as_view()),
    # No-show / Not Conducted, and an administrator's correction or
    # revocation of a recorded outcome (sessions.lifecycle).
    path('<uuid:session_id>/outcome/', SessionOutcomeView.as_view(), name='session-outcome'),
    path('<uuid:session_id>/outcome/correct/', SessionOutcomeCorrectionView.as_view(), name='session-outcome-correct'),
    path('<uuid:session_id>/outcome/revoke/', SessionOutcomeRevokeView.as_view(), name='session-outcome-revoke'),
    # Uploaded session content: attach a file to one content field, and the
    # authenticated download the stored link points at.
    path('<uuid:session_id>/files/<str:field>/', SessionFileUploadView.as_view(), name='session-file-upload'),
    path('<uuid:session_id>/files/<str:field>', SessionFileUploadView.as_view()),
    path('files/<uuid:file_id>/', SessionFileDownloadView.as_view(), name='session-file'),
    path('files/<uuid:file_id>', SessionFileDownloadView.as_view()),
]
