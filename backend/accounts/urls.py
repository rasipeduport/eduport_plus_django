from django.urls import path
from .views import (
    ChangePasswordView,
    CsrfTokenView,
    GoogleLoginView,
    LoginView,
    LogoutView,
    MeView,
    SelectStudentView,
)

app_name = 'accounts'

urlpatterns = [
    path('csrf/', CsrfTokenView.as_view(), name='csrf'),
    path('login/', LoginView.as_view(), name='login'),
    # Google sign-in stays for Learn's students until Phase 7.
    path('google/', GoogleLoginView.as_view(), name='google-login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('select-student/', SelectStudentView.as_view(), name='select-student'),
    path('select-student', SelectStudentView.as_view()),
]
