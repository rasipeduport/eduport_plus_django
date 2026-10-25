from django.urls import path

from .team import (
    TeamListView,
    TeamMemberPermissionsView,
    TeamMemberStatusView,
    TeamMemberView,
    TeamPasswordResetView,
    TeamPermissionCatalogueView,
)

app_name = 'team'

urlpatterns = [
    path('', TeamListView.as_view(), name='list'),
    path('permissions/', TeamPermissionCatalogueView.as_view(), name='permission-catalogue'),
    path('<uuid:pk>/', TeamMemberView.as_view(), name='detail'),
    path('<uuid:pk>/deactivate/', TeamMemberStatusView.as_view(activate=False), name='deactivate'),
    path('<uuid:pk>/reactivate/', TeamMemberStatusView.as_view(activate=True), name='reactivate'),
    path('<uuid:pk>/reset-password/', TeamPasswordResetView.as_view(), name='reset-password'),
    path('<uuid:pk>/permissions/', TeamMemberPermissionsView.as_view(), name='permissions'),
]
