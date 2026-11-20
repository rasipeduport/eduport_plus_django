"""
Where classes and chapter exams are joined (accounts.meet_links): a normal
session in the Meet room of the tutor it is assigned to (tutor_meet_link), a
chapter exam in the room of the mentor it is assigned to (mentor_meet_link),
in every payload a Join reads -- the Sessions and Exams lists, Start Session,
Learn's dashboard and the Hub's student profile. Never the student's own
link, never someone else's, and nothing in its place when the owner has none.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from exams.models import Exam, ExamStatusChoices
from students.models import StatusChoices, Student

from .models import Session, SessionStatusChoices

User = get_user_model()

TUTOR_A_LINK = 'https://meet.google.com/aaa-aaaa-aaa'
TUTOR_B_LINK = 'https://meet.google.com/bbb-bbbb-bbb'
MENTOR_ONE_LINK = 'https://meet.google.com/mmm-mone-mmm'
MENTOR_TWO_LINK = 'https://meet.google.com/mmm-mtwo-mmm'
STUDENT_LINK = 'https://meet.google.com/sss-ssss-sss'


class MeetRoomWorld(APITestCase):
    def setUp(self):
        def staff(username, role, **extra):
            return User.objects.create_user(
                email=f'{username}@rooms.test', username=username, password='x', full_name=username.title(),
                role=role, is_staff=role == 'ADMIN', **extra,
            )

        self.admin = staff('admin', 'ADMIN')
        self.tutor_a = staff('tutor_a', 'TUTOR', tutor_meet_link=TUTOR_A_LINK)
        self.tutor_b = staff('tutor_b', 'TUTOR', tutor_meet_link=TUTOR_B_LINK)
        self.tutor_none = staff('tutor_none', 'TUTOR')
        self.mentor_one = staff('mentor_one', 'MENTOR', mentor_meet_link=MENTOR_ONE_LINK)
        self.mentor_two = staff('mentor_two', 'MENTOR', mentor_meet_link=MENTOR_TWO_LINK)
        self.mentor_none = staff('mentor_none', 'MENTOR')
        self.student_user = staff('learner', 'STUDENT')
        # The student keeps their own link: no class or exam may join it.
        self.student = Student.objects.create(
            profile=self.student_user, student_code='EDPROOM1', full_name='Room Student', status=StatusChoices.ACTIVE,
            mentor=self.mentor_one, tutor=self.tutor_a, total_class_quota=40, meet_link=STUDENT_LINK,
        )
        self.other_student = Student.objects.create(
            profile=staff('learner_two', 'STUDENT'), student_code='EDPROOM2', full_name='Other Student',
            status=StatusChoices.ACTIVE, mentor=self.mentor_one, tutor=self.tutor_a, total_class_quota=40,
        )
        self.now = timezone.now().replace(microsecond=0)

    def session(self, starts_in, tutor=None, student=None, status_value=SessionStatusChoices.SCHEDULED):
        start = self.now + starts_in
        return Session.objects.create(
            student=student or self.student, tutor=tutor, title='Algebra', status=status_value,
            start_time=start, end_time=start + timedelta(hours=1),
        )

    def exam(self, starts_in, mentor=None, status_value=ExamStatusChoices.SCHEDULED):
        start = self.now + starts_in
        scored = {'score': 8, 'max_score': 10} if status_value == ExamStatusChoices.ATTENDED else {}
        return Exam.objects.create(
            student=self.student, mentor=mentor, chapter_name='Fractions', status=status_value,
            start_time=start, end_time=start + timedelta(hours=1), **scored,
        )

    def get(self, user, path):
        self.client.force_authenticate(user=user)
        response = self.client.get(path)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response

    def rows(self, user, path, key):
        return {row['id']: row for row in self.get(user, path).json()[key]}

    def reassign(self, tutor=None, mentor=None):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post('/api/students/reassign/', {
            'id': str(self.student.id), 'mentor': str((mentor or self.student.mentor).id),
            'tutor': str((tutor or self.student.tutor).id),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.student.refresh_from_db()


class ClassRoomTests(MeetRoomWorld):
    def test_a_class_joins_its_assigned_tutors_room_never_the_students(self):
        upcoming = self.session(timedelta(days=1), tutor=self.tutor_a)
        for user in (self.admin, self.mentor_one, self.tutor_a, self.student_user):
            with self.subTest(caller=user.username):
                response = self.get(user, '/api/sessions/')
                row = {r['id']: r for r in response.json()['sessions']}[str(upcoming.id)]
                self.assertEqual(row['tutor_meet_link'], TUTOR_A_LINK)
                self.assertNotIn('meet_link', row['students'])
                self.assertNotIn(STUDENT_LINK, response.content.decode())

    def test_a_class_whose_tutor_has_no_link_or_that_has_no_tutor_has_no_room(self):
        unlinked = self.session(timedelta(days=1), tutor=self.tutor_none)
        unassigned = self.session(timedelta(days=2))
        response = self.get(self.admin, '/api/sessions/')
        rows = {r['id']: r for r in response.json()['sessions']}
        self.assertIsNone(rows[str(unlinked.id)]['tutor_meet_link'])
        self.assertIsNone(rows[str(unassigned.id)]['tutor_meet_link'])
        # Nothing stands in: not the student's link, not another tutor's.
        for link in (STUDENT_LINK, TUTOR_A_LINK, TUTOR_B_LINK):
            self.assertNotIn(link, response.content.decode())

    def test_the_room_is_the_tutors_link_as_it_is_now(self):
        upcoming = self.session(timedelta(days=1), tutor=self.tutor_a)
        self.client.force_authenticate(user=self.admin)
        new_link = 'https://meet.google.com/new-aaaa-aaa'
        response = self.client.put(f'/api/team/{self.tutor_a.id}/meet-link/', {'tutor_meet_link': new_link}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(self.rows(self.admin, '/api/sessions/', 'sessions')[str(upcoming.id)]['tutor_meet_link'], new_link)

    def test_a_change_of_tutor_moves_classes_to_come_to_the_new_tutors_room_and_keeps_the_past(self):
        to_come = self.session(timedelta(days=2), tutor=self.tutor_a)
        past = self.session(-timedelta(days=2), tutor=self.tutor_a)
        attended = self.session(-timedelta(days=3), tutor=self.tutor_a, status_value=SessionStatusChoices.ATTENDED)
        other_students = self.session(timedelta(days=2), tutor=self.tutor_a, student=self.other_student)
        self.reassign(tutor=self.tutor_b)

        rows = self.rows(self.admin, '/api/sessions/', 'sessions')
        self.assertEqual(rows[str(to_come.id)]['tutor_meet_link'], TUTOR_B_LINK)
        # Past classes keep the tutor who had them, and so that tutor's room.
        self.assertEqual(rows[str(past.id)]['tutor_meet_link'], TUTOR_A_LINK)
        self.assertEqual(rows[str(attended.id)]['tutor_meet_link'], TUTOR_A_LINK)
        # Tutor A keeps their own room for their other students.
        self.assertEqual(rows[str(other_students.id)]['tutor_meet_link'], TUTOR_A_LINK)
        self.assertEqual(User.objects.get(pk=self.tutor_a.pk).tutor_meet_link, TUTOR_A_LINK)
        # The student's own link was neither used nor changed.
        self.assertEqual(Student.objects.get(pk=self.student.pk).meet_link, STUDENT_LINK)

    def test_a_substitute_tutor_brings_their_own_room(self):
        upcoming = self.session(timedelta(days=1), tutor=self.tutor_a)
        self.client.force_authenticate(user=self.admin)
        response = self.client.put('/api/sessions/', {'id': str(upcoming.id), 'tutor': str(self.tutor_b.id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(self.rows(self.admin, '/api/sessions/', 'sessions')[str(upcoming.id)]['tutor_meet_link'], TUTOR_B_LINK)

    def test_start_session_answers_with_the_tutors_room(self):
        soon = self.session(timedelta(minutes=2), tutor=self.tutor_a)
        self.client.force_authenticate(user=self.tutor_a)
        response = self.client.post(f'/api/sessions/{soon.id}/start/', format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()['session']['tutor_meet_link'], TUTOR_A_LINK)
        self.assertNotIn(STUDENT_LINK, response.content.decode())


class ExamRoomTests(MeetRoomWorld):
    def test_a_chapter_exam_joins_its_assigned_mentors_room_never_a_tutors_or_the_students(self):
        upcoming = self.exam(timedelta(days=1), mentor=self.mentor_one)
        for user in (self.admin, self.mentor_one, self.student_user):
            with self.subTest(caller=user.username):
                response = self.get(user, '/api/exams/')
                row = {r['id']: r for r in response.json()['exams']}[str(upcoming.id)]
                self.assertEqual(row['mentor_meet_link'], MENTOR_ONE_LINK)
                self.assertNotIn('meet_link', row['students'])
                for link in (STUDENT_LINK, TUTOR_A_LINK):
                    self.assertNotIn(link, response.content.decode())

    def test_an_exam_whose_mentor_has_no_link_or_that_has_no_mentor_has_no_room(self):
        unlinked = self.exam(timedelta(days=1), mentor=self.mentor_none)
        unassigned = self.exam(timedelta(days=2))
        response = self.get(self.admin, '/api/exams/')
        rows = {r['id']: r for r in response.json()['exams']}
        self.assertIsNone(rows[str(unlinked.id)]['mentor_meet_link'])
        self.assertIsNone(rows[str(unassigned.id)]['mentor_meet_link'])
        for link in (STUDENT_LINK, MENTOR_ONE_LINK, TUTOR_A_LINK):
            self.assertNotIn(link, response.content.decode())

    def test_a_change_of_mentor_moves_scheduled_exams_to_the_new_mentors_room_and_keeps_the_past(self):
        scheduled = self.exam(timedelta(days=2), mentor=self.mentor_one)
        attended = self.exam(-timedelta(days=2), mentor=self.mentor_one, status_value=ExamStatusChoices.ATTENDED)
        self.reassign(mentor=self.mentor_two)
        rows = self.rows(self.admin, '/api/exams/', 'exams')
        self.assertEqual(rows[str(scheduled.id)]['mentor_meet_link'], MENTOR_TWO_LINK)
        self.assertEqual(rows[str(attended.id)]['mentor_meet_link'], MENTOR_ONE_LINK)
        self.assertEqual(User.objects.get(pk=self.mentor_one.pk).mentor_meet_link, MENTOR_ONE_LINK)


class JoinEntryPointTests(MeetRoomWorld):
    def test_learns_dashboard_joins_the_next_class_and_exam_in_their_owners_rooms(self):
        self.session(timedelta(days=1), tutor=self.tutor_a)
        self.exam(timedelta(days=2), mentor=self.mentor_one)
        data = self.get(self.student_user, '/api/student/dashboard/').json()
        self.assertEqual(data['next_session']['tutor_meet_link'], TUTOR_A_LINK)
        self.assertEqual(data['next_exam']['mentor_meet_link'], MENTOR_ONE_LINK)
        self.assertNotIn('meet_link', data['next_session']['students'])
        self.assertNotIn('meet_link', data['next_exam']['students'])

    def test_learns_dashboard_has_no_room_when_the_owner_has_no_link(self):
        self.session(timedelta(days=1), tutor=self.tutor_none)
        self.exam(timedelta(days=2), mentor=self.mentor_none)
        data = self.get(self.student_user, '/api/student/dashboard/').json()
        self.assertIsNone(data['next_session']['tutor_meet_link'])
        self.assertIsNone(data['next_exam']['mentor_meet_link'])

    def test_the_hub_profile_next_up_joins_the_next_class_and_exam_in_their_owners_rooms(self):
        self.session(timedelta(days=1), tutor=self.tutor_a)
        self.exam(timedelta(days=2), mentor=self.mentor_one)
        highlights = self.get(self.admin, f'/api/students/{self.student.id}/profile/').json()['highlights']
        self.assertEqual(highlights['next_session']['tutor_meet_link'], TUTOR_A_LINK)
        self.assertEqual(highlights['next_exam']['mentor_meet_link'], MENTOR_ONE_LINK)

    def test_the_students_own_link_stays_where_it_was_stored(self):
        # Kept for the Students list, Edit Demo Link and the invitation; no Join reads it.
        rows = self.get(self.admin, '/api/students/').json()
        listed = rows if isinstance(rows, list) else rows.get('students', rows.get('results', []))
        self.assertIn(STUDENT_LINK, [row.get('meet_link') for row in listed])


class ClassUnderWayStaysJoinableTests(MeetRoomWorld):
    """
    F4 P2: the next class a Join reads -- Learn's dashboard and the Hub's
    profile "Next up" -- is the next scheduled one not yet ended, so a class
    under way stays there, joinable, until its scheduled end.
    """
    def test_learns_dashboard_keeps_a_class_under_way_until_it_ends(self):
        under_way = self.session(-timedelta(minutes=5), tutor=self.tutor_a)  # ends in 55 minutes
        self.session(timedelta(days=1), tutor=self.tutor_b)
        data = self.get(self.student_user, '/api/student/dashboard/').json()
        self.assertEqual(data['next_session']['id'], str(under_way.id))
        self.assertEqual(data['next_session']['tutor_meet_link'], TUTOR_A_LINK)

    def test_an_ended_class_is_no_longer_next(self):
        self.session(-timedelta(hours=2), tutor=self.tutor_a)  # ended an hour ago, nothing recorded
        later = self.session(timedelta(days=1), tutor=self.tutor_b)
        data = self.get(self.student_user, '/api/student/dashboard/').json()
        self.assertEqual(data['next_session']['id'], str(later.id))
        highlights = self.get(self.admin, f'/api/students/{self.student.id}/profile/').json()['highlights']
        self.assertEqual(highlights['next_session']['id'], str(later.id))

    def test_a_class_under_way_that_is_not_scheduled_is_never_next(self):
        for status_value in (SessionStatusChoices.CANCELLED, SessionStatusChoices.ATTENDED):
            with self.subTest(status=status_value):
                Session.objects.all().delete()
                self.session(-timedelta(minutes=5), tutor=self.tutor_a, status_value=status_value)
                data = self.get(self.student_user, '/api/student/dashboard/').json()
                self.assertIsNone(data['next_session'])
                highlights = self.get(self.admin, f'/api/students/{self.student.id}/profile/').json()['highlights']
                self.assertIsNone(highlights['next_session'])

    def test_the_hub_profile_next_up_keeps_a_class_under_way(self):
        under_way = self.session(-timedelta(minutes=5), tutor=self.tutor_a)
        self.session(timedelta(days=1), tutor=self.tutor_b)
        highlights = self.get(self.admin, f'/api/students/{self.student.id}/profile/').json()['highlights']
        self.assertEqual(highlights['next_session']['id'], str(under_way.id))
        self.assertEqual(highlights['next_session']['tutor_meet_link'], TUTOR_A_LINK)
