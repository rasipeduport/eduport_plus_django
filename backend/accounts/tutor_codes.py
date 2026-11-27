"""
Tutor IDs: EPT0001, EPT0002, ... -- each tutor's permanent Eduport Tutor ID
(accounts.User.tutor_code).

* Issued by allocate_tutor_code(), called from User.save() the first time an
  account is saved as a tutor: created as one (Team, the Django admin,
  create_user) or given the role later. It runs in the same transaction as
  that save, so a save that fails issues nothing -- no gaps -- and a saved
  tutor always has an ID.
* A number is never issued twice. The counter (TutorCodeCounter) holds the
  last one issued and only goes up; the next is one more than the higher of
  it and the highest ID stored, so neither a deleted tutor nor a counter left
  behind (a restored backup, a test database flush) brings a number back.
* Issuing is serialised by a transaction-level advisory lock (class 4; Team
  writes use 3, sessions.services 1 and 2), which also covers the counter row
  not existing yet; the row is locked as well. Every caller takes it last,
  just before the account row is written, so it cannot deadlock with them.
* Once issued an ID never changes: no form or API accepts it, a former tutor
  keeps theirs (and has it again should they teach again), and the database
  refuses a change (migration 0034: profiles_tutor_code_fixed, and a counter
  that cannot go down or be deleted).
"""
import re

from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models import BigIntegerField, Max
from django.db.models.functions import Cast, Substr

TUTOR_CODE_PREFIX = 'EPT'
TUTOR_CODE_DIGITS = 4
TUTOR_CODE_MAX_LENGTH = 16
# The stored form (a CHECK constraint, so PostgreSQL's regex syntax). Wider
# than four digits once EPT9999 has been issued.
TUTOR_CODE_DB_PATTERN = r'^EPT[0-9]{4,}$'
TUTOR_CODE_COUNTER = 'EPT'

_LOCK_CLASS_TUTOR_CODE = 4
_CODE_RE = re.compile(r'EPT([0-9]+)')


def format_tutor_code(number):
    """``7`` -> ``'EPT0007'``."""
    return f'{TUTOR_CODE_PREFIX}{number:0{TUTOR_CODE_DIGITS}d}'


def tutor_code_number(code):
    """``'EPT0007'`` -> ``7``; None for anything else."""
    match = _CODE_RE.fullmatch(code or '')
    return int(match[1]) if match else None


def lock_tutor_codes(connection):
    """Serialise Tutor ID issuing until the current transaction ends (a no-op off PostgreSQL)."""
    if connection.vendor != 'postgresql':
        return
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s, hashtext(%s))', [_LOCK_CLASS_TUTOR_CODE, TUTOR_CODE_COUNTER])


def highest_issued(user_model, using=DEFAULT_DB_ALIAS):
    """The highest Tutor ID number any account holds (0 for none)."""
    top = (
        user_model.objects.using(using)
        .filter(tutor_code__isnull=False)
        .aggregate(top=Max(Cast(Substr('tutor_code', len(TUTOR_CODE_PREFIX) + 1), BigIntegerField())))['top']
    )
    return top or 0


def allocate_tutor_code(using=DEFAULT_DB_ALIAS):
    """
    The next Tutor ID, counted as issued. Only inside a transaction: the
    caller saves it onto the tutor before that transaction commits, and a
    rollback takes the number back with everything else.
    """
    from .models import TutorCodeCounter, User

    connection = connections[using]
    if not connection.in_atomic_block:
        raise RuntimeError('A Tutor ID is issued only inside the transaction that saves it.')
    lock_tutor_codes(connection)
    TutorCodeCounter.objects.using(using).get_or_create(name=TUTOR_CODE_COUNTER)
    counter = TutorCodeCounter.objects.using(using).select_for_update().get(pk=TUTOR_CODE_COUNTER)
    counter.value = max(counter.value, highest_issued(User, using)) + 1
    counter.save(using=using, update_fields=['value'])
    return format_tutor_code(counter.value)


def backfill_tutor_codes(apps, schema_editor):
    """
    Migration 0034: a Tutor ID for every tutor who has none -- deactivated
    ones too -- oldest account first (created_at, then id, so a re-run on the
    same accounts gives the same IDs), after any already issued. Former
    tutors are left as they are. Accounts are locked against writes until the
    migration commits, so none becomes a tutor unseen before its checks are
    in place. Returns the (username, Tutor ID) pairs issued.
    """
    User = apps.get_model('accounts', 'User')
    TutorCodeCounter = apps.get_model('accounts', 'TutorCodeCounter')
    connection = schema_editor.connection
    using = connection.alias

    lock_tutor_codes(connection)
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute(f'LOCK TABLE {connection.ops.quote_name(User._meta.db_table)} IN SHARE ROW EXCLUSIVE MODE')

    counter, _ = TutorCodeCounter.objects.using(using).get_or_create(name=TUTOR_CODE_COUNTER)
    number = max(counter.value, highest_issued(User, using))
    pending = (
        User.objects.using(using)
        .filter(role='TUTOR', tutor_code__isnull=True)
        .order_by('created_at', 'id')
        .values_list('pk', 'username')
    )
    issued = []
    for pk, username in pending:
        number += 1
        code = format_tutor_code(number)
        User.objects.using(using).filter(pk=pk, tutor_code__isnull=True).update(tutor_code=code)
        issued.append((username, code))
    if number != counter.value:
        counter.value = number
        counter.save(using=using, update_fields=['value'])
    return issued
