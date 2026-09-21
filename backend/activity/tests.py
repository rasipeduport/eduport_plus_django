from django.contrib.auth import get_user_model
from django.contrib.admin.sites import AdminSite
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from students.models import Student, StatusChoices
from .admin import ActivityLogAdmin
from .models import ActivityLog
from .serializers import ActivityLogSerializer

User = get_user_model()


class ActivityAccessTests(APITestCase):
    """
    The activity log is an admin-only oversight tool (Hub parity: the only
    read policy on activity_log is admin-only; mentors and tutors can read
    nothing — not even their own students' history).
    """

    def setUp(self):
        self.url = reverse('activity:activity-logs-list')
        self.admin = User.objects.create_user(
            email="act_admin@eduport.com", password="password123",
            full_name="Activity Admin", role="ADMIN"
        )
        self.mentor = User.objects.create_user(
            email="act_mentor@eduport.com", password="password123",
            full_name="Activity Mentor", role="MENTOR"
        )
        self.tutor = User.objects.create_user(
            email="act_tutor@eduport.com", password="password123",
            full_name="Activity Tutor", role="TUTOR"
        )
        self.student_user = User.objects.create_user(
            email="act_student@eduport.com", password="password123",
            full_name="Activity Student", role="STUDENT"
        )
        self.student = Student.objects.create(
            profile=self.student_user, student_code="ACT001",
            full_name="Activity Student", mentor=self.mentor, tutor=self.tutor,
            status=StatusChoices.ACTIVE
        )
        ActivityLog.objects.create(
            actor=self.admin, actor_email=self.admin.email,
            actor_name=self.admin.full_name, actor_role='ADMIN',
            action='student.update_status', entity_type='student',
            entity_id=str(self.student.id), entity_label=self.student.full_name,
            student=self.student,
            context={"ip": "203.0.113.9", "user_agent": "test-agent"}
        )

    def test_admin_can_read_global_feed_with_actor_options(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)
        self.assertIn("actor_options", res.data)

    def test_admin_can_filter_by_student(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.url, {"student_id": str(self.student.id)})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)

    def test_mentor_cannot_read_global_feed(self):
        self.client.force_authenticate(user=self.mentor)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn("results", res.data)

    def test_mentor_cannot_read_own_students_history(self):
        """
        Ticket correction: in the original, per-student history is admin-only
        too — a mentor gets nothing, even for their own allocated student.
        """
        self.client.force_authenticate(user=self.mentor)
        res = self.client.get(self.url, {"student_id": str(self.student.id)})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn("results", res.data)

    def test_tutor_cannot_read_feed_or_history(self):
        self.client.force_authenticate(user=self.tutor)
        for params in ({}, {"student_id": str(self.student.id)}):
            with self.subTest(params=params):
                res = self.client.get(self.url, params)
                self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_student_cannot_read(self):
        self.client.force_authenticate(user=self.student_user)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_cannot_read(self):
        res = self.client.get(self.url)
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class ActivityAppendOnlyTests(APITestCase):
    """
    The log accepts inserts only: a DB trigger rejects every UPDATE and DELETE
    (a port of the Hub's activity_log_no_mutate trigger), and log rows survive
    the deletion of the entities they reference.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            email="ao_admin@eduport.com", password="password123",
            full_name="AO Admin", role="ADMIN"
        )
        self.student_user = User.objects.create_user(
            email="ao_student@eduport.com", password="password123",
            full_name="AO Student", role="STUDENT"
        )
        self.student = Student.objects.create(
            profile=self.student_user, student_code="AO001",
            full_name="AO Student", status=StatusChoices.ACTIVE
        )
        self.log = ActivityLog.objects.create(
            actor=self.admin, actor_email=self.admin.email,
            actor_name=self.admin.full_name, actor_role='ADMIN',
            action='student.create', entity_type='student',
            entity_id=str(self.student.id), entity_label=self.student.full_name,
            student=self.student
        )

    def test_orm_update_is_rejected(self):
        self.log.action = 'tampered'
        with self.assertRaisesMessage(DatabaseError, 'activity_log is append-only'):
            with transaction.atomic():
                self.log.save()

    def test_queryset_update_is_rejected(self):
        with self.assertRaisesMessage(DatabaseError, 'activity_log is append-only'):
            with transaction.atomic():
                ActivityLog.objects.filter(pk=self.log.pk).update(action='tampered')

    def test_orm_delete_is_rejected(self):
        with self.assertRaisesMessage(DatabaseError, 'activity_log is append-only'):
            with transaction.atomic():
                self.log.delete()
        self.assertTrue(ActivityLog.objects.filter(pk=self.log.pk).exists())

    def test_queryset_delete_is_rejected(self):
        with self.assertRaisesMessage(DatabaseError, 'activity_log is append-only'):
            with transaction.atomic():
                ActivityLog.objects.all().delete()
        self.assertTrue(ActivityLog.objects.filter(pk=self.log.pk).exists())

    def test_raw_sql_update_is_rejected(self):
        with self.assertRaisesMessage(DatabaseError, 'activity_log is append-only'):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE activity_log SET action = 'tampered' WHERE id = %s",
                        [str(self.log.pk)]
                    )

    def test_log_rows_survive_student_deletion(self):
        """
        The FKs carry no DB constraint (Hub parity: the actor FK was dropped),
        so deleting the referenced student neither fails nor mutates the row.
        """
        student_id = self.student.pk
        self.student.delete()
        row = ActivityLog.objects.filter(pk=self.log.pk).values('student_id').first()
        self.assertIsNotNone(row)
        self.assertEqual(row['student_id'], student_id)
        # And the serializer tolerates the now-dangling reference.
        data = ActivityLogSerializer(ActivityLog.objects.get(pk=self.log.pk)).data
        self.assertIsNone(data['student_name'])
        self.assertEqual(str(data['student_id']), str(student_id))

    def test_django_admin_is_read_only(self):
        model_admin = ActivityLogAdmin(ActivityLog, AdminSite())
        request = None  # permissions ignore the request entirely
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
