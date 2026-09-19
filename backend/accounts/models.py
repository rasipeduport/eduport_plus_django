import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone

class RoleChoices(models.TextChoices):
    ADMIN = 'ADMIN', 'Admin'
    MENTOR = 'MENTOR', 'Mentor'
    TUTOR = 'TUTOR', 'Tutor'
    STUDENT = 'STUDENT', 'Student'

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        extra_fields.setdefault('is_active', True)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', RoleChoices.ADMIN)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=255, blank=True, null=True)
    avatar_url = models.URLField(max_length=1024, blank=True, null=True)
    role = models.CharField(
        max_length=20, 
        choices=RoleChoices.choices, 
        default=RoleChoices.STUDENT,
        db_index=True
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    invited_by = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='invited_users'
    )
    
    # Soft-deactivation lifecycle (staff exit). NULL deactivated_at = active.
    # `deactivated_at` is the source of truth; `is_active` is kept mirrored to
    # it so Django's session machinery (ModelBackend.get_user) locks a
    # deactivated user out of an existing session on their next request.
    # `role` stays untouched so historical rows keep correct attribution.
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deactivated_users'
    )
    deactivation_reason = models.TextField(blank=True, null=True)

    # Django-required fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        db_table = 'profiles'
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.email} ({self.role})"
