"""
The authorization matrix: every protected API endpoint, asked by every kind of
caller.

A fixed fixture world (every row has a fixed id, so two runs are comparable)
and a list of scenarios, each one request. Every scenario runs once per caller
kind, inside a savepoint that is rolled back, so no request ever sees another
one's writes. For each "scenario @ caller" a run records the status code, the
error code and message, which fixture records the response mentions and which
fields it carries -- enough to notice a changed decision, a widened or narrowed
scope, or a redacted field.

core.tests_authz_matrix compares a run with the baseline recorded from the
Phase 1 code (commit 3d56003) plus the explicitly approved changes, so the move
to permission-based authorization can show it changed nothing else.

Test-only: nothing here is imported by the application. Google Sheets is
mocked; mail goes to Django's test outbox; uploads land in the test MEDIA_ROOT.
"""
import re
import uuid
from datetime import time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.urls import URLResolver, get_resolver, resolve
from django.utils import timezone
from rest_framework.test import APIClient

from activity.models import ActivityLog
from bookings.models import BookingType, SlotTime
from exams.models import AdditionalExam, AdditionalExamFile, Exam, ExamFile
from homework.models import Homework, HomeworkFile
from invitations.models import Invitation
from invitations.sheets import GoogleSheetsService
from sessions.models import Session, SessionFile
from students.models import Student, StudentNote

User = get_user_model()

PASSWORD = 'Matrix-Pass-2026'
PDF = b'%PDF-1.4\n' + b'0' * 64
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
TZ = 'Asia/Kolkata'
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')

# Every kind of caller. parent_a is the student account acting as persona stu_a.
CALLERS = (
    'anon', 'admin', 'superuser', 'su_mentor', 'su_tutor',
    'mentor_a', 'mentor_b', 'tutor_a', 'tutor_b', 'parent_a', 'unknown',
)
SIGNED_IN = tuple(caller for caller in CALLERS if caller != 'anon')

# Roles added after the baseline was recorded. They are not CALLERS -- the
# baseline has no results for them, and their accounts would change what other
# callers list -- so tests_authz_matrix adds them to a world of their own
# (add_new_role_accounts) and checks that each is answered exactly as the
# account with an unknown role is: no data, no action. The one exception is
# what BDE holds, its own booking links (tests_authz_matrix lists it).
NEW_ROLES = {'bde': 'BDE', 'sales_tl': 'SALES_TL'}


def fixed_id(label):
    return uuid.uuid5(uuid.NAMESPACE_URL, f'eduplus/authz-matrix/{label}')


# ------------------------------------------------------------------ the world

class World:
    """The fixture rows by label, and every fixture id mapped back to its label."""

    def __init__(self):
        self.objects = {}
        self.labels = {}

    def add(self, label, obj):
        self.objects[label] = obj
        self.labels[str(obj.pk)] = label
        return obj

    def __getitem__(self, label):
        return self.objects[label]

    def id(self, label):
        return str(self.objects[label].pk)

    def day(self, days, hour=10):
        """A wall-clock date and time (in TZ) ``days`` from now, as the scheduling forms send them."""
        moment = timezone.localtime(self.now) + timedelta(days=days)
        return moment.strftime('%Y-%m-%d'), f'{hour:02d}:00'

    def utc(self, days, hour=4):
        return (self.now + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)


def sheet_row(code, name, email, paid):
    """One enrolment-sheet row (range A3:AB), as invitations.sheets reads it."""
    row = [''] * 28
    row[1], row[2], row[3] = name, '+910000000001', email
    row[5], row[6], row[7], row[8], row[9], row[10] = 'India', 'Kerala', 'Matrix School', '8', 'CBSE', '2026-01-01'
    row[13] = row[14] = str(paid)
    row[27] = code
    return row


SHEET_ROWS = [
    sheet_row('MX-A', 'Student A', 'parent_a@matrix.test', 40),
    sheet_row('MX-NEW2', 'New Two', 'new2.parent@matrix.test', 12),
]


def add_account(w, label, role, superuser=False, **extra):
    return w.add(label, User.objects.create_user(
        id=fixed_id(label), email=f'{label}@matrix.test', username=label.replace('_', '.'),
        password=PASSWORD, full_name=label.replace('_', ' ').title(), role=role,
        is_superuser=superuser, **extra,
    ))


def add_new_role_accounts(w):
    for label, role in NEW_ROLES.items():
        add_account(w, label, role)


def build_world():
    w = World()
    w.now = timezone.now().replace(microsecond=0)

    def user(label, role, superuser=False, **extra):
        return add_account(w, label, role, superuser, **extra)

    user('admin', 'ADMIN')
    user('admin2', 'ADMIN')
    user('superuser', 'ADMIN', superuser=True, is_staff=True)
    user('su_mentor', 'MENTOR', superuser=True)
    user('su_tutor', 'TUTOR', superuser=True)
    for label in ('mentor_a', 'mentor_b', 'mentor_c'):
        user(label, 'MENTOR')
    for label in ('tutor_a', 'tutor_b'):
        user(label, 'TUTOR')
    user('tutor_off', 'TUTOR', is_active=False, deactivated_at=w.now)
    for label in ('parent_a', 'parent_b', 'parent_p'):
        user(label, 'STUDENT')
    user('unknown', 'UNASSIGNED')
    view_team = Permission.objects.get(content_type__app_label='accounts', codename='view_team')
    w['tutor_b'].user_permissions.add(view_team)
    w['mentor_c'].user_permissions.add(view_team)

    def student(label, code, parent, mentor, tutor, status='ACTIVE'):
        return w.add(label, Student.objects.create(
            id=fixed_id(label), profile=w[parent], student_code=code, full_name=label.replace('_', ' ').title(),
            mobile_number='+910000000002', country='India', state='Kerala', school_name='Matrix School',
            grade='8', syllabus='CBSE', mentor=w[mentor], tutor=w[tutor], status=status,
            total_class_quota=50, timezone=TZ, remarks_for_mentor='Matrix remark',
        ))

    student('stu_a', 'MX-A', 'parent_a', 'mentor_a', 'tutor_a')
    student('stu_c', 'MX-C', 'parent_a', 'mentor_a', 'tutor_a', status='EXPIRED')
    student('stu_b', 'MX-B', 'parent_b', 'mentor_b', 'tutor_b')
    student('stu_p', 'MX-P', 'parent_p', 'mentor_b', 'tutor_b')  # no history: purgeable

    def session(label, stu, title, days, status, **extra):
        start = w.utc(days)
        return w.add(label, Session.objects.create(
            id=fixed_id(label), student=w[stu], tutor=w[stu].tutor, title=title, start_time=start,
            end_time=start + timedelta(hours=1), status=status, **extra,
        ))

    series = fixed_id('series_a')
    session('ses_a_s1', 'stu_a', 'Algebra - Class 1', 20, 'SCHEDULED', series_id=series, class_number=1)
    session('ses_a_s2', 'stu_a', 'Algebra - Class 2', 21, 'SCHEDULED', series_id=series, class_number=2)
    session('ses_a_one', 'stu_a', 'Statistics', 22, 'SCHEDULED')
    links = {'notes_link': 'https://n.matrix.test/1', 'recording_link': 'https://r.matrix.test/1',
             'homework_link': 'https://hw.matrix.test/1'}
    session('ses_a_att', 'stu_a', 'Real Numbers', -2, 'ATTENDED', **links)
    session('ses_a_att2', 'stu_a', 'Polynomials', -3, 'ATTENDED', homework_link='https://hw.matrix.test/2')
    session('ses_a_att3', 'stu_a', 'Linear Equations', -4, 'ATTENDED', homework_link='https://hw.matrix.test/3')
    # A day after ses_a_one, so moving ses_a_one to tutor_b is not a clash.
    session('ses_b_one', 'stu_b', 'Geometry', 23, 'SCHEDULED')
    session('ses_b_att', 'stu_b', 'Trigonometry', -2, 'ATTENDED', **links)

    def attach(label, row, data=PDF, ext='.pdf', content_type='application/pdf'):
        row.id = fixed_id(label)
        row.file_name, row.content_type, row.size_bytes, row.extension = f'{label}{ext}', content_type, len(data), ext
        row.file.save(f'{row.id}{ext}', ContentFile(data), save=False)
        row.save()
        return w.add(label, row)

    attach('sf_a', SessionFile(session=w['ses_a_att'], field='notes', uploaded_by=w['tutor_a']))
    attach('sf_b', SessionFile(session=w['ses_b_att'], field='notes', uploaded_by=w['tutor_b']))

    def exam(label, stu, days, status, **extra):
        start = w.utc(days, hour=6)
        return w.add(label, Exam.objects.create(
            id=fixed_id(label), student=w[stu], mentor=w[stu].mentor, chapter_name='Real Numbers',
            start_time=start, end_time=start + timedelta(hours=1), status=status, **extra,
        ))

    exam('exam_a', 'stu_a', 25, 'SCHEDULED')
    exam('exam_a_done', 'stu_a', -5, 'ATTENDED', score=7, max_score=10)
    exam('exam_b', 'stu_b', 25, 'SCHEDULED')
    attach('ef_a', ExamFile(exam=w['exam_a_done'], uploaded_by=w['mentor_a']))

    def additional(label, stu, status, **extra):
        return w.add(label, AdditionalExam.objects.create(
            id=fixed_id(label), student=w[stu], mentor=w[stu].mentor, title=f'Worksheet {label}', status=status, **extra,
        ))

    additional('add_a', 'stu_a', 'SUBMITTED', submitted_at=w.now)
    additional('add_a_assigned', 'stu_a', 'ASSIGNED')
    additional('add_b', 'stu_b', 'SUBMITTED', submitted_at=w.now)
    attach('aqf_a', AdditionalExamFile(additional_exam=w['add_a'], kind='question_paper', uploaded_by=w['mentor_a']))
    attach('aaf_a', AdditionalExamFile(additional_exam=w['add_a'], kind='answer_sheet', uploaded_by=w['parent_a']),
           data=PNG, ext='.png', content_type='image/png')

    def homework(label, ses, status, **extra):
        return w.add(label, Homework.objects.create(
            id=fixed_id(label), session=w[ses], student=w[ses].student, status=status,
            assigned_by=w[ses].student.mentor, **extra,
        ))

    homework('hw_a_sub', 'ses_a_att', 'SUBMITTED', submitted_at=w.now)
    homework('hw_a_scored', 'ses_a_att2', 'SCORED', submitted_at=w.now, scored_by=w['tutor_a'],
             scored_at=w.now, score=8, max_score=10)
    homework('hw_a_assigned', 'ses_a_att3', 'ASSIGNED')
    homework('hw_b', 'ses_b_att', 'SUBMITTED', submitted_at=w.now)
    attach('hwf_a_sub', HomeworkFile(homework=w['hw_a_sub'], uploaded_by=w['parent_a']), data=PNG, ext='.png',
           content_type='image/png')
    attach('hwf_a_scored', HomeworkFile(homework=w['hw_a_scored'], uploaded_by=w['parent_a']), data=PNG, ext='.png',
           content_type='image/png')

    def note(label, stu, author):
        return w.add(label, StudentNote.objects.create(
            id=fixed_id(label), student=w[stu], body=f'Note {label}', author=w[author],
            author_name=w[author].full_name, author_role=w[author].role,
        ))

    note('note_m', 'stu_a', 'mentor_a')
    note('note_t', 'stu_a', 'tutor_a')
    note('note_b', 'stu_b', 'mentor_b')

    w.add('inv_pending', Invitation.objects.create(
        id=fixed_id('inv_pending'), email='pending.parent@matrix.test', role='STUDENT', status='PENDING',
        extra_data={'student_code': 'MX-NEW1', 'full_name': 'New One'}, invited_by=w['admin'],
    ))
    w.add('inv_legacy', Invitation.objects.create(
        id=fixed_id('inv_legacy'), email='legacy.staff@matrix.test', role='MENTOR', status='PENDING',
        extra_data={'full_name': 'Legacy Staff'}, invited_by=w['admin'],
    ))

    def activity(label, actor, stu=None):
        return w.add(label, ActivityLog.objects.create(
            id=fixed_id(label), actor=w[actor], actor_email=w[actor].email, actor_name=w[actor].full_name,
            actor_role=w[actor].role, action='matrix.fixture', entity_type='student' if stu else 'profile',
            entity_id=w.id(stu) if stu else w.id(actor), entity_label=label, student=w[stu] if stu else None,
        ))

    activity('act_admin', 'admin')
    activity('act_mentor_a', 'mentor_a', 'stu_a')
    activity('act_tutor_a', 'tutor_a', 'stu_a')
    activity('act_mentor_b', 'mentor_b', 'stu_b')

    # The booking schedule (bookings app): one evening time per booking type,
    # so the slot-management scenarios have a slot to show and close.
    for booking_type in (BookingType.DEMO, BookingType.DIAGNOSTIC):
        SlotTime.objects.create(booking_type=booking_type, start_time=time(19, 30))
    return w


# --------------------------------------------------------------- scenarios

class Scenario:
    """One request: method, path ({label} and {self} placeholders), body, format, callers."""

    def __init__(self, sid, method, path, body=None, fmt='json', callers=CALLERS, capture=None):
        self.sid, self.method, self.path, self.body, self.fmt = sid, method, path, body, fmt
        self.callers, self.capture = callers, capture


def pdf(name='matrix.pdf'):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


def png(name='matrix.png'):
    return SimpleUploadedFile(name, PNG, content_type='image/png')


def _me(data):
    user = data.get('user') or {}
    return {'role': user.get('role'), 'permissions': user.get('permissions'), 'groups': user.get('groups')}


def _dashboard(data):
    return {key: data.get(key) for key in ('students', 'mentors', 'tutors', 'pending_invitations')}


def _activity(data):
    return {'count': data.get('count'), 'actor_options': len(data.get('actor_options') or [])}


def _homework(data):
    homework = data.get('homework') or {}
    return {'submission_visible': homework.get('submission_visible'), 'submission': len(homework.get('submission') or [])}


def _member(data):
    return {'permissions': data.get('permissions'), 'role': data.get('role')}


# A booking link's token is random, so a run records its shape, not its value.
_LINK_TOKEN_RE = re.compile(r'([?&]ref=)[A-Za-z0-9_-]{22}$')


def _booking_links(data):
    return [
        {'booking_type': link.get('booking_type'), 'url': _LINK_TOKEN_RE.sub(r'\1<token>', link.get('url') or '')}
        for link in data.get('links') or []
    ]


def _public_booking(w):
    date, _time = w.day(2)
    return {'date': date, 'time': '19:30', 'parent_name': 'Matrix Parent', 'student_name': 'Matrix Child',
            'phone': {'dial_code': '+971', 'number': '0501234567'}, 'school': 'Matrix School',
            'student_class': 'Class 8', 'syllabus': 'CBSE', 'ref': None}


def _create_session(w, stu):
    date, time = w.day(30)
    return {'student_id': w.id(stu), 'base_title': 'Matrix Class', 'series': False, 'timezone': TZ,
            'items': [{'local_date': date, 'local_time': time, 'duration_hours': 1}]}


def _create_exam(w, stu, chapter):
    date, time = w.day(31, hour=11)
    return {'student_id': w.id(stu), 'chapter_name': chapter, 'timezone': TZ, 'local_date': date,
            'local_time': time, 'duration_hours': 1}


def _reschedule_exam(w):
    date, time = w.day(32, hour=11)
    return {'id': w.id('exam_a'), 'timezone': TZ, 'local_date': date, 'local_time': time, 'duration_hours': 1}


ONLY_ANON = ('anon',)

SCENARIOS = [
    # --- account basics ---------------------------------------------------
    Scenario('auth.csrf', 'get', '/api/auth/csrf/', callers=('anon', 'admin')),
    Scenario('auth.login.admin', 'post', '/api/auth/login/', {'username': 'admin', 'password': PASSWORD}, callers=ONLY_ANON),
    Scenario('auth.login.mentor', 'post', '/api/auth/login/', {'username': 'mentor.a', 'password': PASSWORD}, callers=ONLY_ANON),
    Scenario('auth.login.student', 'post', '/api/auth/login/', {'username': 'parent.a', 'password': PASSWORD}, callers=ONLY_ANON),
    Scenario('auth.login.unknown_role', 'post', '/api/auth/login/', {'username': 'unknown', 'password': PASSWORD}, callers=ONLY_ANON),
    Scenario('auth.login.wrong', 'post', '/api/auth/login/', {'username': 'admin', 'password': 'wrong-password'}, callers=ONLY_ANON),
    Scenario('auth.google.empty', 'post', '/api/auth/google/', {}, callers=ONLY_ANON),
    Scenario('auth.me', 'get', '/api/auth/me/', capture=_me),
    Scenario('auth.logout', 'post', '/api/auth/logout/'),
    Scenario('auth.change_password.wrong', 'post', '/api/auth/change-password/',
             {'current_password': 'wrong-password', 'new_password': 'Another-Long-Secret-42'}),
    Scenario('auth.select_student.a', 'post', '/api/auth/select-student/', lambda w: {'student_id': w.id('stu_a')}),
    Scenario('auth.select_student.c_expired', 'post', '/api/auth/select-student/', lambda w: {'student_id': w.id('stu_c')}),
    Scenario('auth.select_student.b', 'post', '/api/auth/select-student/', lambda w: {'student_id': w.id('stu_b')}),

    # --- team ---------------------------------------------------------------
    Scenario('team.list', 'get', '/api/team/'),
    Scenario('team.detail', 'get', '/api/team/{mentor_c}/', capture=_member),
    Scenario('team.create.mentor', 'post', '/api/team/', {
        'username': 'matrix.new', 'email': 'matrix.new@matrix.test', 'full_name': 'Matrix New',
        'role': 'MENTOR', 'temporary_password': 'Temporary-Pass-2026!'}),
    Scenario('team.create.admin', 'post', '/api/team/', {
        'username': 'matrix.admin', 'email': 'matrix.admin@matrix.test', 'full_name': 'Matrix Admin',
        'role': 'ADMIN', 'temporary_password': 'Temporary-Pass-2026!'}),
    Scenario('team.update.name', 'patch', '/api/team/{mentor_c}/', {'full_name': 'Renamed Mentor'}, capture=_member),
    Scenario('team.update.role', 'patch', '/api/team/{mentor_c}/', {'role': 'TUTOR'}, capture=_member),
    Scenario('team.update.admin_target', 'patch', '/api/team/{admin2}/', {'full_name': 'Renamed Admin'}),
    Scenario('team.update.self', 'patch', '/api/team/{self}/', {'full_name': 'Renamed Self'}, callers=SIGNED_IN),
    Scenario('team.deactivate', 'post', '/api/team/{mentor_c}/deactivate/', {}),
    Scenario('team.reactivate', 'post', '/api/team/{tutor_off}/reactivate/', {}),
    Scenario('team.reset_password', 'post', '/api/team/{mentor_c}/reset-password/', {'temporary_password': 'Fresh-Start-Secret-77'}),
    Scenario('team.permissions.grant', 'put', '/api/team/{tutor_a}/permissions/', {'permissions': ['accounts.view_team']}, capture=_member),
    Scenario('team.permissions.catalogue', 'get', '/api/team/permissions/'),

    # --- legacy staff endpoints ----------------------------------------------
    Scenario('staff.mentors', 'get', '/api/mentors/'),
    Scenario('staff.tutors', 'get', '/api/tutors/'),
    Scenario('staff.mentors.all', 'get', '/api/mentors/?all=true'),
    Scenario('staff.admins', 'get', '/api/admins/'),
    Scenario('staff.user.update', 'patch', '/api/users/{mentor_c}/', {'full_name': 'Legacy Rename'}),
    Scenario('staff.user.status', 'post', '/api/users/{mentor_c}/status/', {'action': 'deactivate'}),
    Scenario('staff.user.reassign', 'post', '/api/users/{mentor_a}/reassign/', lambda w: {'new_mentor': w.id('mentor_c')}),

    # --- dashboards -----------------------------------------------------------
    Scenario('dashboard.staff', 'get', '/api/dashboard/stats/', capture=_dashboard),
    Scenario('dashboard.student', 'get', '/api/student/dashboard/'),

    # --- students -------------------------------------------------------------
    Scenario('students.list', 'get', '/api/students/'),
    Scenario('students.update.a', 'put', '/api/students/', lambda w: {'id': w.id('stu_a'), 'full_name': 'Matrix Rename'}),
    Scenario('students.update.b', 'put', '/api/students/', lambda w: {'id': w.id('stu_b'), 'full_name': 'Matrix Rename'}),
    Scenario('students.update.quota', 'put', '/api/students/', lambda w: {'id': w.id('stu_a'), 'total_class_quota': 5}),
    Scenario('students.reassign', 'post', '/api/students/reassign/',
             lambda w: {'id': w.id('stu_a'), 'mentor': w.id('mentor_b'), 'tutor': w.id('tutor_a')}),
    Scenario('students.purge', 'delete', '/api/students/{stu_p}/', {'confirm_code': 'MX-P'}),
    Scenario('students.purge.history', 'delete', '/api/students/{stu_a}/', {'confirm_code': 'MX-A'}),
    Scenario('students.profile.a', 'get', '/api/students/{stu_a}/profile/'),
    Scenario('students.profile.b', 'get', '/api/students/{stu_b}/profile/'),
    Scenario('students.profile.c_expired', 'get', '/api/students/{stu_c}/profile/'),
    Scenario('students.sync_quota.a', 'post', '/api/students/{stu_a}/sync-quota/', {}),
    Scenario('students.notes.list.a', 'get', '/api/students/{stu_a}/notes/'),
    Scenario('students.notes.list.b', 'get', '/api/students/{stu_b}/notes/'),
    Scenario('students.notes.add.a', 'post', '/api/students/{stu_a}/notes/', {'body': 'Matrix note'}),
    Scenario('students.notes.edit.mentor_note', 'patch', '/api/students/notes/{note_m}/', {'body': 'Edited note'}),
    Scenario('students.notes.delete.mentor_note', 'delete', '/api/students/notes/{note_m}/'),
    Scenario('students.notes.delete.tutor_note', 'delete', '/api/students/notes/{note_t}/'),

    # --- sessions -------------------------------------------------------------
    Scenario('sessions.list', 'get', '/api/sessions/'),
    Scenario('sessions.list.student_a', 'get', '/api/sessions/?student_id={stu_a}'),
    Scenario('sessions.create.a', 'post', '/api/sessions/', lambda w: _create_session(w, 'stu_a')),
    Scenario('sessions.create.b', 'post', '/api/sessions/', lambda w: _create_session(w, 'stu_b')),
    Scenario('sessions.attend.a', 'put', '/api/sessions/', lambda w: {'id': w.id('ses_a_one'), 'status': 'ATTENDED'}),
    Scenario('sessions.attend.b', 'put', '/api/sessions/', lambda w: {'id': w.id('ses_b_one'), 'status': 'ATTENDED'}),
    Scenario('sessions.notes_link.a', 'put', '/api/sessions/', lambda w: {'id': w.id('ses_a_one'), 'notes_link': 'https://n.matrix.test/new'}),
    Scenario('sessions.notes_link.b', 'put', '/api/sessions/', lambda w: {'id': w.id('ses_b_one'), 'notes_link': 'https://n.matrix.test/new'}),
    Scenario('sessions.rate.a', 'put', '/api/sessions/', lambda w: {'id': w.id('ses_a_att'), 'rating': 4}),
    Scenario('sessions.cancel_put.a', 'put', '/api/sessions/',
             lambda w: {'id': w.id('ses_a_one'), 'status': 'CANCELLED', 'cancellation_reason': 'Matrix'}),
    Scenario('sessions.set_tutor.non_tutor', 'put', '/api/sessions/', lambda w: {'id': w.id('ses_a_one'), 'tutor': w.id('mentor_b')}),
    Scenario('sessions.set_tutor.tutor', 'put', '/api/sessions/', lambda w: {'id': w.id('ses_a_one'), 'tutor': w.id('tutor_b')}),
    Scenario('sessions.reschedule.a', 'put', '/api/sessions/',
             lambda w: {'id': w.id('ses_a_one'), 'start_time': w.utc(35).isoformat(), 'duration_hours': 1}),
    Scenario('sessions.cancel_series.a', 'post', '/api/sessions/cancel/', lambda w: {
        'session_id': w.id('ses_a_s1'), 'cancellation_reason': 'Matrix',
        'new_last_start_time': w.utc(40).isoformat(), 'new_last_duration_hours': 1}),
    Scenario('sessions.cancel_series.b', 'post', '/api/sessions/cancel-series/',
             lambda w: {'session_id': w.id('ses_b_one'), 'cancellation_reason': 'Matrix'}),
    Scenario('sessions.upload.notes.a', 'post', '/api/sessions/{ses_a_att2}/files/notes/', lambda w: {'file': pdf()}, fmt='multipart'),
    Scenario('sessions.upload.recording.a', 'post', '/api/sessions/{ses_a_att2}/files/recording/', lambda w: {'file': pdf()}, fmt='multipart'),
    Scenario('sessions.file.a', 'get', '/api/sessions/files/{sf_a}/'),
    Scenario('sessions.file.b', 'get', '/api/sessions/files/{sf_b}/'),

    # --- exams ----------------------------------------------------------------
    Scenario('exams.list', 'get', '/api/exams/'),
    Scenario('exams.detail.a', 'get', '/api/exams/{exam_a}/'),
    Scenario('exams.detail.b', 'get', '/api/exams/{exam_b}/'),
    Scenario('exams.create.a', 'post', '/api/exams/', lambda w: _create_exam(w, 'stu_a', 'Real Numbers')),
    Scenario('exams.create.b', 'post', '/api/exams/', lambda w: _create_exam(w, 'stu_b', 'Trigonometry')),
    Scenario('exams.reschedule.a', 'put', '/api/exams/', _reschedule_exam),
    Scenario('exams.cancel.a', 'put', '/api/exams/', lambda w: {'id': w.id('exam_a'), 'status': 'CANCELLED', 'cancellation_reason': 'Matrix'}),
    Scenario('exams.result.a', 'post', '/api/exams/{exam_a}/result/', {'score': 8, 'max_score': 10}),
    Scenario('exams.chapter_names.a', 'get', '/api/exams/chapter-names/?student_id={stu_a}'),
    Scenario('exams.file.a', 'get', '/api/exams/files/{ef_a}/'),
    Scenario('additional.list', 'get', '/api/additional-exams/'),
    Scenario('additional.detail.a', 'get', '/api/additional-exams/{add_a}/'),
    Scenario('additional.detail.b', 'get', '/api/additional-exams/{add_b}/'),
    Scenario('additional.create.a', 'post', '/api/additional-exams/',
             lambda w: {'student_id': w.id('stu_a'), 'title': 'Matrix Worksheet', 'files': [pdf()]}, fmt='multipart'),
    Scenario('additional.submit.a', 'post', '/api/additional-exams/{add_a_assigned}/submit/', lambda w: {'files': [png()]}, fmt='multipart'),
    Scenario('additional.score.a', 'post', '/api/additional-exams/{add_a}/score/', {'score': 8, 'max_score': 10}),
    Scenario('additional.score.b', 'post', '/api/additional-exams/{add_b}/score/', {'score': 8, 'max_score': 10}),
    Scenario('additional.file.question', 'get', '/api/additional-exams/files/{aqf_a}/'),
    Scenario('additional.file.answer', 'get', '/api/additional-exams/files/{aaf_a}/'),
    Scenario('student.scorecard', 'get', '/api/student/scorecard/?range=all'),
    Scenario('student.scores', 'get', '/api/student/scores/?range=all'),

    # --- homework -------------------------------------------------------------
    Scenario('homework.list', 'get', '/api/homework/'),
    Scenario('homework.detail.a_submitted', 'get', '/api/homework/{hw_a_sub}/', capture=_homework),
    Scenario('homework.detail.a_scored', 'get', '/api/homework/{hw_a_scored}/', capture=_homework),
    Scenario('homework.detail.b', 'get', '/api/homework/{hw_b}/', capture=_homework),
    Scenario('homework.score.a', 'post', '/api/homework/{hw_a_sub}/score/', {'score': 8, 'max_score': 10}),
    Scenario('homework.score.b', 'post', '/api/homework/{hw_b}/score/', {'score': 8, 'max_score': 10}),
    Scenario('homework.submit.a', 'post', '/api/homework/{hw_a_assigned}/submit/', lambda w: {'files': [png()]}, fmt='multipart'),
    Scenario('homework.file.a_submitted', 'get', '/api/homework/files/{hwf_a_sub}/'),
    Scenario('homework.file.a_scored', 'get', '/api/homework/files/{hwf_a_scored}/'),

    # --- activity -------------------------------------------------------------
    Scenario('activity.list', 'get', '/api/activity/', capture=_activity),
    Scenario('activity.student_a', 'get', '/api/activity/?student_id={stu_a}', capture=_activity),
    Scenario('activity.subject_mentor_a', 'get', '/api/activity/?subject={mentor_a}', capture=_activity),

    # --- invitations ----------------------------------------------------------
    Scenario('invitations.lookup', 'post', '/api/invitations/lookup-student/', {'student_code': 'MX-NEW2'}),
    Scenario('invitations.list', 'get', '/api/invitations/'),
    Scenario('invitations.list.alias', 'get', '/api/invitations/create-student-invitation/'),
    Scenario('invitations.create.student', 'post', '/api/invitations/', lambda w: {
        'role': 'student', 'email': 'new2.parent@matrix.test', 'student_code': 'MX-NEW2', 'full_name': 'New Two',
        'mentor_id': w.id('mentor_a'), 'tutor_id': w.id('tutor_a')}),
    Scenario('invitations.create.staff', 'post', '/api/invitations/', {'role': 'MENTOR', 'email': 'staff.new@matrix.test'}),
    Scenario('invitations.edit_email', 'patch', '/api/invitations/',
             lambda w: {'id': w.id('inv_pending'), 'new_email': 'changed.parent@matrix.test'}),
    Scenario('invitations.withdraw.student', 'delete', '/api/invitations/', lambda w: {'id': w.id('inv_pending')}),
    Scenario('invitations.withdraw.legacy_staff', 'delete', '/api/invitations/', lambda w: {'id': w.id('inv_legacy')}),

    # --- BDE workspace --------------------------------------------------------
    Scenario('bde.booking_links', 'get', '/api/bde/booking-links/', capture=_booking_links),

    # --- public booking API (the marketing site's server key only) ------------
    Scenario('public.booking_calendar', 'get', '/api/public/booking-calendar/demo/'),
    Scenario('public.booking_create', 'post', '/api/public/bookings/demo/', _public_booking),

    # --- booking slots (administrators) ----------------------------------------
    # A date that stays ahead of the clock, so it is always one that may change.
    Scenario('bookings.slot_day', 'get', '/api/booking-slots/demo/2099-01-05/'),
    Scenario('bookings.slot_change', 'post', '/api/booking-slots/demo/2099-01-05/',
             {'action': 'close', 'times': ['19:30'], 'reason': 'Matrix'}),
]


# ------------------------------------------------------------------ running

class _Placeholders(dict):
    def __init__(self, world, caller):
        super().__init__()
        self.world, self.caller = world, caller

    def __missing__(self, key):
        if key == 'self':
            return self.world.id(self.caller)
        return self.world.id(key)


def scenario_path(world, scenario, caller):
    return scenario.path.format_map(_Placeholders(world, caller))


def _mentions(world, data):
    found = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(key)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for match in UUID_RE.findall(value.lower()):
                found.add(world.labels.get(match, 'new'))

    walk(data)
    return sorted(found)


def _field_paths(data, prefix=''):
    paths = set()
    if isinstance(data, dict):
        for key, value in data.items():
            key = 'ID' if UUID_RE.fullmatch(str(key).lower()) else key
            path = f'{prefix}.{key}' if prefix else str(key)
            paths.add(path)
            paths |= _field_paths(value, path)
    elif isinstance(data, list):
        for item in data:
            paths |= _field_paths(item, f'{prefix}[]')
    return paths


def describe(world, response, capture=None):
    result = {'status': response.status_code}
    content_type = response.get('Content-Type', '')
    if 'application/json' not in content_type:
        result['content_type'] = content_type.split(';')[0]
        if getattr(response, 'streaming', False):
            # Consume it: the test client closes a streaming response once its
            # content is read, without the request_finished handler that would
            # close the test transaction's connection.
            b''.join(response.streaming_content)
        return result
    data = response.json()
    if isinstance(data, dict):
        if isinstance(data.get('error'), str):
            result['error'] = data['error']
        if isinstance(data.get('message'), str):
            result['message'] = UUID_RE.sub('<id>', data['message'])
        if isinstance(data.get('detail'), str):
            result['detail'] = data['detail']
    result['records'] = _mentions(world, data)
    result['fields'] = sorted(_field_paths(data))
    if capture is not None and isinstance(data, dict):
        result['capture'] = capture(data)
    return result


def run_scenario(world, scenario, caller):
    cache.clear()  # throttles count in the cache; each request answers for itself
    client = APIClient()
    if caller != 'anon':
        client.force_authenticate(user=User.objects.get(pk=world[caller].pk))
        if caller == 'parent_a':
            client.cookies['ep-student-id'] = world.id('stu_a')
    path = scenario_path(world, scenario, caller)
    body = scenario.body(world) if callable(scenario.body) else scenario.body
    try:
        with transaction.atomic():
            if scenario.method == 'get':
                response = client.get(path)
            else:
                response = getattr(client, scenario.method)(path, body or {}, format=scenario.fmt)
            result = describe(world, response, scenario.capture)
            transaction.set_rollback(True)
    except Exception as exc:  # an unhandled server error is a result too
        result = {'exception': type(exc).__name__}
    return result


def run_matrix(world, like_unknown=()):
    """
    Every scenario as every one of its callers: {"<scenario> @ <caller>": result}.
    With ``like_unknown``, only the scenarios the unknown-role account is a
    caller of, as that account and as each of these.
    """
    results = {}
    with mock.patch.object(GoogleSheetsService, 'fetch_enrollment_rows', return_value=SHEET_ROWS):
        for scenario in SCENARIOS:
            if like_unknown:
                callers = ('unknown', *like_unknown) if 'unknown' in scenario.callers else ()
            else:
                callers = scenario.callers
            for caller in callers:
                results[f'{scenario.sid} @ {caller}'] = run_scenario(world, scenario, caller)
    return results


def exercised_routes(world):
    """The URL routes the scenarios reach, as written in the URLconf."""
    routes = set()
    for scenario in SCENARIOS:
        path = scenario_path(world, scenario, scenario.callers[0]).split('?')[0]
        routes.add(resolve(path).route)
    return routes


def api_url_patterns(patterns=None, prefix=''):
    """(route, URL pattern) for every URL route under /api/, the route as written in the URLconf."""
    for entry in get_resolver().url_patterns if patterns is None else patterns:
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            if route.startswith('api/'):
                yield from api_url_patterns(entry.url_patterns, route)
        elif route.startswith('api/'):
            yield route, entry


def api_routes():
    """Every URL route under /api/, as written in the URLconf (with <params>)."""
    for route, _pattern in api_url_patterns():
        yield route
