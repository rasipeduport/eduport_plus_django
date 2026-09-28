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


def make_user(prefix, role):
    return User.objects.create_user(
        email=f"{prefix}_{role.lower()}@eduport.com", password="password123",
        full_name=f"{prefix.title()} {role.title()}", role=role
    )


def make_log(actor, action, entity_type='student', student=None, entity_id=None, **extra):
    """A log row the way activity.utils.log_activity would write it."""
    return ActivityLog.objects.create(
        actor=actor, actor_email=actor.email, actor_name=actor.full_name,
        actor_role=actor.role, action=action, entity_type=entity_type,
        entity_id=entity_id or (str(student.id) if student else 'n/a'),
        entity_label=student.full_name if student else actor.full_name,
        student=student, **extra
    )


class ActivityAccessTests(APITestCase):
    """
    Who may read the log at all: every staff role, and nobody else. Admins get
    the whole log (their oversight tool); mentors and tutors get only their own
    entries, which ActivityStaffScopeTests pins down.
    """

    def setUp(self):
        self.url = reverse('activity:activity-logs-list')
        self.admin = make_user('act', 'ADMIN')
        self.mentor = make_user('act', 'MENTOR')
        self.tutor = make_user('act', 'TUTOR')
        self.student_user = make_user('act', 'STUDENT')
        self.student = Student.objects.create(
            profile=self.student_user, student_code="ACT001",
            full_name="Activity Student", mentor=self.mentor, tutor=self.tutor,
            status=StatusChoices.ACTIVE
        )
        make_log(
            self.admin, 'student.update_status', student=self.student,
            context={"ip": "203.0.113.9", "user_agent": "test-agent"}
        )

    def test_admin_can_read_global_feed_with_actor_options(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["context"]["ip"], "203.0.113.9")
        self.assertEqual(
            {o["id"] for o in res.data["actor_options"]},
            {str(u.id) for u in User.objects.all()}
        )

    def test_admin_can_filter_by_student(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.url, {"student_id": str(self.student.id)})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 1)

    def test_mentor_and_tutor_can_open_the_feed_but_not_the_admins_entry(self):
        """
        The student is theirs, but the entry is the admin's work -- so they get
        an empty, well-formed page rather than a 403 or the admin's row.
        """
        for user in (self.mentor, self.tutor):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user=user)
                for params in ({}, {"student_id": str(self.student.id)}):
                    res = self.client.get(self.url, params)
                    self.assertEqual(res.status_code, status.HTTP_200_OK)
                    self.assertEqual(res.data["count"], 0)
                    self.assertEqual(res.data["results"], [])
                    self.assertEqual(res.data["actor_options"], [])

    def test_student_cannot_read(self):
        self.client.force_authenticate(user=self.student_user)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn("results", res.data)

    def test_anonymous_cannot_read(self):
        res = self.client.get(self.url)
        self.assertIn(res.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class ActivityStaffScopeTests(APITestCase):
    """
    Mentors and tutors see only the entries they wrote themselves. The scope is
    applied before any query parameter, so no filter -- actor, student, search,
    type -- can reach another person's entries.
    """

    def setUp(self):
        self.url = reverse('activity:activity-logs-list')
        self.admin = make_user('scope', 'ADMIN')
        self.mentor_a = make_user('scope_a', 'MENTOR')
        self.mentor_b = make_user('scope_b', 'MENTOR')
        self.tutor_a = make_user('scope_a', 'TUTOR')
        self.tutor_b = make_user('scope_b', 'TUTOR')
        self.parent = make_user('scope', 'STUDENT')
        self.student_a = Student.objects.create(
            profile=self.parent, student_code="SCP001", full_name="Student A",
            mentor=self.mentor_a, tutor=self.tutor_a, status=StatusChoices.ACTIVE
        )
        self.student_b = Student.objects.create(
            profile=self.parent, student_code="SCP002", full_name="Student B",
            mentor=self.mentor_b, tutor=self.tutor_b, status=StatusChoices.ACTIVE
        )

        # One entry per person, each touching a student the others also work with.
        self.log_admin = make_log(self.admin, 'student.update_quota', student=self.student_a)
        self.log_mentor_a = make_log(self.mentor_a, 'session.create', entity_type='session', student=self.student_a)
        self.log_mentor_b = make_log(self.mentor_b, 'session.cancel', entity_type='session', student=self.student_b)
        self.log_tutor_a = make_log(self.tutor_a, 'session.update_links', entity_type='session', student=self.student_a)
        self.log_tutor_b = make_log(self.tutor_b, 'session.update_links', entity_type='session', student=self.student_b)
        self.log_student = make_log(self.parent, 'session.rate', entity_type='session', student=self.student_a)
        # Mentor A's sign-in: theirs, but held back from the default feed.
        self.log_signin = make_log(
            self.mentor_a, 'user.sign_in', entity_type='profile', entity_id=str(self.mentor_a.id)
        )
        self.change_logs = {
            str(log.id) for log in (
                self.log_admin, self.log_mentor_a, self.log_mentor_b,
                self.log_tutor_a, self.log_tutor_b, self.log_student,
            )
        }

    def _ids(self, user, **params):
        self.client.force_authenticate(user=user)
        res = self.client.get(self.url, params)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], len(res.data["results"]))
        return {row["id"] for row in res.data["results"]}

    def test_admin_sees_every_entry(self):
        self.assertEqual(self._ids(self.admin), self.change_logs)

    def test_mentor_sees_only_own_entries(self):
        self.assertEqual(self._ids(self.mentor_a), {str(self.log_mentor_a.id)})
        self.assertEqual(self._ids(self.mentor_b), {str(self.log_mentor_b.id)})

    def test_tutor_sees_only_own_entries(self):
        self.assertEqual(self._ids(self.tutor_a), {str(self.log_tutor_a.id)})
        self.assertEqual(self._ids(self.tutor_b), {str(self.log_tutor_b.id)})

    def test_mentor_cannot_reach_other_entries_through_query_parameters(self):
        me, own = self.mentor_a, {str(self.log_mentor_a.id)}
        # Naming another actor (either spelling of the parameter) yields nothing.
        self.assertEqual(self._ids(me, actor=str(self.mentor_b.id)), set())
        self.assertEqual(self._ids(me, actor_id=str(self.admin.id)), set())
        # A student the caller does not work with, and a search for a
        # colleague's name, are equally empty.
        self.assertEqual(self._ids(me, student_id=str(self.student_b.id)), set())
        self.assertEqual(self._ids(me, q=self.mentor_b.full_name), set())
        # The caller's own student's history holds only the caller's entry --
        # not the admin's, tutor's or student's on the same student.
        self.assertEqual(self._ids(me, student_id=str(self.student_a.id)), own)
        # Filters that match the caller's own work keep working.
        self.assertEqual(self._ids(me, entity='session'), own)
        self.assertEqual(self._ids(me, action='session.create'), own)
        self.assertEqual(self._ids(me, q=self.mentor_a.full_name), own)
        self.assertEqual(self._ids(me, actor=str(me.id)), own)

    def test_tutor_cannot_reach_other_entries_through_query_parameters(self):
        me, own = self.tutor_a, {str(self.log_tutor_a.id)}
        self.assertEqual(self._ids(me, actor=str(self.tutor_b.id)), set())
        self.assertEqual(self._ids(me, actor_id=str(self.mentor_a.id)), set())
        self.assertEqual(self._ids(me, student_id=str(self.student_b.id)), set())
        self.assertEqual(self._ids(me, q=self.tutor_b.full_name), set())
        self.assertEqual(self._ids(me, student_id=str(self.student_a.id)), own)
        self.assertEqual(self._ids(me, entity='session'), own)
        self.assertEqual(self._ids(me, action='session.update_links'), own)
        self.assertEqual(self._ids(me, actor=str(me.id)), own)

    def test_own_sign_in_is_reachable_through_the_action_filter(self):
        self.assertEqual(self._ids(self.mentor_a, action='user.sign_in'), {str(self.log_signin.id)})
        # ...and only one's own: mentor B has no sign-in to see.
        self.assertEqual(self._ids(self.mentor_b, action='user.sign_in'), set())

    def test_actor_options_are_admin_only(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.get(self.url)
        self.assertIn(str(self.mentor_b.id), {o["id"] for o in res.data["actor_options"]})
        for user in (self.mentor_a, self.tutor_a):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user=user)
                res = self.client.get(self.url)
                self.assertEqual(res.data["actor_options"], [])


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
