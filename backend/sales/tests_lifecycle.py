"""
A syllabus's lifecycle (sales.services, D4): a draft is edited and previewed
while the published revision stays as it was, publishing needs the draft the
Admin confirmed, and nothing published -- a revision, its chapters, a pricing
version -- can ever change (sales.0002), whatever writes to it.
"""
from datetime import timedelta
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from activity.models import ActivityLog

from . import services
from .models import PlanType, PricingVersion, Structure, SyllabusChapter, SyllabusRevision, SyllabusStatus
from .serializers import SyllabusContentSerializer
from .services import SalesError

User = get_user_model()

GRADE_6_CHAPTERS = [
    ('Patterns in Mathematics', 4, 2), ('Lines and Angles', 5, 2), ('Number Play', 4, 2),
    ('Data Handling and Presentation', 3, 2), ('Prime Time', 3, 2), ('Perimeter and Area', 3, 2),
    ('Fractions', 5, 2), ('Playing with Constructions', 4, 2), ('Symmetry', 2, 1), ('The Other Side of Zero', 5, 2),
]


def account(username, role='ADMIN', **extra):
    return User.objects.create_user(
        email=f'{username}@sales.test', username=username, password='Sales-Pass-2026', full_name=username.title(),
        role=role, **extra,
    )


def chapter_wise_payload(**overrides):
    return {
        'title': 'Grade 6 CBSE', 'grade': 6, 'board': 'CBSE', 'syllabus_version': 'New Syllabus',
        'structure': 'CHAPTER_WISE', 'plan_types': ['REGULAR_REVISION', 'REGULAR', 'REVISION'],
        'chapters': [{'name': name, 'regular_classes': regular, 'revision_classes': revision}
                     for name, regular, revision in GRADE_6_CHAPTERS],
        **overrides,
    }


def bridge_payload(**overrides):
    return {
        'title': 'Grade 7 CBSE', 'grade': 7, 'board': 'CBSE', 'structure': 'BRIDGE_COURSE', 'plan_types': [],
        'chapters': [{'name': f'Day {day} topic', 'bridge_classes': 1} for day in range(1, 31)],
        **overrides,
    }


def valid(payload):
    serializer = SyllabusContentSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors
    return serializer.validated_data


def editable(revision):
    """``revision``'s content as a save sends it: its chapters by id."""
    data = services.revision_data(revision)
    return {
        **{field: data[field] for field in services.CONTENT_FIELDS},
        'chapters': [{key: chapter[key] for key in ('id', 'name', *services.COUNT_FIELDS)} for chapter in data['chapters']],
    }


class LifecycleTestCase(TestCase):
    def setUp(self):
        self.admin = account('sales_admin')
        self.syllabus = services.create_syllabus(self.admin, valid(chapter_wise_payload()))

    def detail(self):
        return services.syllabus_detail(self.syllabus.pk)

    def draft(self):
        return SyllabusRevision.objects.get(syllabus=self.syllabus, published_at__isnull=True)

    def publish(self, revision=None):
        revision = revision or self.draft()
        return services.publish(self.admin, self.syllabus.pk, revision.number, revision.updated_at)

    def save(self, revision, **changes):
        content = valid({**editable(revision), **changes})
        return services.save_draft(self.admin, self.syllabus.pk, content, revision.updated_at)


class CreateTests(LifecycleTestCase):
    def test_a_new_syllabus_is_a_draft_revision_1_with_the_reference_wording(self):
        detail = self.detail()
        self.assertEqual((detail['status'], detail['published'], detail['structure_locked']), (SyllabusStatus.DRAFT, None, False))
        draft = detail['draft']
        self.assertEqual((draft['number'], draft['is_draft'], draft['title']), (1, True, 'Grade 6 CBSE'))
        # Left empty, the two lines keep following the structure and the title (sales.wording).
        self.assertEqual((draft['subtitle'], draft['package_title']), ('', ''))
        self.assertEqual(draft['subtitle_display'], 'Detailed Chapter-Wise 1:1 Learning Plan')
        self.assertEqual(draft['package_title_display'], 'Grade 6 CBSE – 1:1 Tuition Packages & Fee Details')
        self.assertIsNone(detail['reference'])
        self.assertEqual(draft['inclusions'], ['Personalized 1:1 live sessions', 'Structured CBSE aligned learning',
                                               'Dedicated mentor support'])
        # Plan types in PlanType order, each once.
        self.assertEqual(draft['plan_types'], ['REGULAR', 'REVISION', 'REGULAR_REVISION'])
        self.assertEqual([c['position'] for c in draft['chapters']], list(range(1, 11)))
        self.assertEqual(draft['totals'], {'regular': '38', 'revision': '19', 'bridge': '0'})
        self.assertIsNone(draft['packages'])  # no pricing yet
        self.assertEqual(ActivityLog.objects.filter(action='syllabus.create', entity_id=str(self.syllabus.pk)).count(), 1)

    def test_a_bridge_course_is_sold_as_itself(self):
        syllabus = services.create_syllabus(self.admin, valid(bridge_payload(plan_types=['REGULAR'])))
        draft = services.syllabus_detail(syllabus.pk)['draft']
        self.assertEqual(draft['plan_types'], ['BRIDGE_COURSE'])
        self.assertEqual(draft['subtitle_display'], 'Detailed Bridge Course Curriculum')
        self.assertEqual(draft['totals']['bridge'], '30')
        self.assertEqual({c['regular_classes'] for c in draft['chapters']}, {None})


    def test_default_wording_follows_the_title_and_structure_until_the_admin_writes_their_own(self):
        self.save(self.draft(), title='Grade 6 CBSE 2027')
        draft = self.detail()['draft']
        self.assertEqual(draft['package_title_display'], 'Grade 6 CBSE 2027 – 1:1 Tuition Packages & Fee Details')
        self.save(self.draft(), package_title='Grade 6 – Fees', subtitle='Chapter by chapter')
        draft = self.detail()['draft']
        self.assertEqual((draft['package_title_display'], draft['subtitle_display']), ('Grade 6 – Fees', 'Chapter by chapter'))


class DraftRevisionTests(LifecycleTestCase):
    def test_publishing_makes_revision_1_what_the_syllabus_offers(self):
        self.publish()
        detail = self.detail()
        self.assertEqual((detail['status'], detail['draft'], detail['structure_locked']), (SyllabusStatus.PUBLISHED, None, True))
        self.assertEqual(detail['published']['number'], 1)
        self.assertEqual([row['state'] for row in detail['history']], ['PUBLISHED'])

    def test_editing_a_published_syllabus_leaves_its_published_revision_unchanged(self):
        self.publish()
        services.start_draft(self.admin, self.syllabus.pk)
        draft = self.draft()
        self.assertEqual(draft.number, 2)
        chapters = editable(draft)['chapters']
        # Rename one, move the last to the top, drop one, add one.
        chapters[0]['name'] = 'Patterns In Mathematics (Revised)'
        chapters = [chapters[-1], *chapters[:-1]]
        del chapters[3]
        chapters.append({'name': 'Ratio and Proportion', 'regular_classes': '3', 'revision_classes': '1.5'})
        self.save(draft, title='Grade 6 CBSE (2027)', chapters=chapters)

        detail = self.detail()
        published, draft = detail['published'], detail['draft']
        self.assertEqual((published['number'], published['title']), (1, 'Grade 6 CBSE'))
        self.assertEqual([c['name'] for c in published['chapters']], [name for name, _r, _v in GRADE_6_CHAPTERS])
        self.assertEqual(published['totals'], {'regular': '38', 'revision': '19', 'bridge': '0'})
        self.assertEqual(draft['title'], 'Grade 6 CBSE (2027)')
        self.assertEqual([c['name'] for c in draft['chapters']][:3],
                         ['The Other Side of Zero', 'Patterns In Mathematics (Revised)', 'Lines and Angles'])
        self.assertEqual(draft['chapters'][-1]['revision_classes'], '1.5')
        self.assertEqual([c['position'] for c in draft['chapters']], list(range(1, 11)))
        # Number Play (4 + 2) went, Ratio and Proportion (3 + 1.5) came.
        self.assertEqual(draft['totals'], {'regular': '37', 'revision': '18.5', 'bridge': '0'})
        # Kept rows kept their ids; the draft never shares a row with the published revision.
        self.assertEqual(draft['chapters'][1]['id'], chapters[1]['id'])
        self.assertFalse({c['id'] for c in draft['chapters']} & {c['id'] for c in published['chapters']})

        # Published on confirmation: revision 1 stays, superseded and unchanged.
        self.publish()
        detail = self.detail()
        self.assertEqual([(row['number'], row['state']) for row in detail['history']], [(2, 'PUBLISHED'), (1, 'SUPERSEDED')])
        first = services.revision_detail(self.syllabus.pk, 1)
        self.assertEqual((first['title'], first['totals']['revision']), ('Grade 6 CBSE', '19'))

    def test_a_draft_saved_meanwhile_is_neither_overwritten_nor_published(self):
        draft = self.draft()
        self.save(draft, title='Saved by someone else')
        with self.assertRaises(SalesError) as refused:
            self.save(draft, title='Stale')
        self.assertEqual(refused.exception.code, 'DRAFT_CHANGED')
        with self.assertRaises(SalesError) as refused:
            services.publish(self.admin, self.syllabus.pk, draft.number, draft.updated_at)
        self.assertEqual(refused.exception.code, 'DRAFT_CHANGED')
        self.assertEqual(self.draft().title, 'Saved by someone else')

    def test_only_one_draft_and_only_for_a_published_syllabus(self):
        with self.assertRaises(SalesError) as refused:
            services.start_draft(self.admin, self.syllabus.pk)
        self.assertEqual(refused.exception.code, 'DRAFT_EXISTS')
        self.publish()
        services.start_draft(self.admin, self.syllabus.pk)
        with self.assertRaises(SalesError) as refused:
            services.start_draft(self.admin, self.syllabus.pk)
        self.assertEqual(refused.exception.code, 'DRAFT_EXISTS')

    def test_a_draft_changed_meanwhile_is_not_discarded(self):
        self.publish()
        services.start_draft(self.admin, self.syllabus.pk)
        seen = self.draft()
        self.save(seen, title='Saved by someone else')
        with self.assertRaises(SalesError) as refused:
            services.discard_draft(self.admin, self.syllabus.pk, seen.number, seen.updated_at)
        self.assertEqual(refused.exception.code, 'DRAFT_CHANGED')
        self.assertEqual(self.draft().title, 'Saved by someone else')

    def test_discarding_a_draft_keeps_the_published_revision(self):
        draft = self.draft()
        with self.assertRaises(SalesError) as refused:
            services.discard_draft(self.admin, self.syllabus.pk, draft.number, draft.updated_at)
        self.assertEqual(refused.exception.code, 'NEVER_PUBLISHED')
        self.publish()
        services.start_draft(self.admin, self.syllabus.pk)
        draft = self.draft()
        services.discard_draft(self.admin, self.syllabus.pk, draft.number, draft.updated_at)
        detail = self.detail()
        self.assertEqual((detail['status'], detail['draft'], detail['published']['number']), (SyllabusStatus.PUBLISHED, None, 1))
        self.assertFalse(SyllabusChapter.objects.filter(revision_id=draft.pk).exists())

    def test_the_structure_is_fixed_from_the_first_publication(self):
        bridge_chapters = [{'name': 'Day 1', 'bridge_classes': '1'}]
        self.save(self.draft(), structure='BRIDGE_COURSE', plan_types=[], chapters=bridge_chapters)
        self.assertEqual(self.draft().structure, Structure.BRIDGE_COURSE)
        self.publish()
        services.start_draft(self.admin, self.syllabus.pk)
        with self.assertRaises(SalesError) as refused:
            self.save(self.draft(), **chapter_wise_payload())
        self.assertEqual((refused.exception.code, refused.exception.http_status), ('STRUCTURE_LOCKED', 400))

    def test_a_plan_type_selling_no_classes_cannot_be_published(self):
        chapters = [{'name': name, 'regular_classes': regular, 'revision_classes': 0} for name, regular, _v in GRADE_6_CHAPTERS]
        self.save(self.draft(), chapters=chapters)
        with self.assertRaises(SalesError) as refused:
            self.publish()
        self.assertEqual(refused.exception.code, 'NOT_PUBLISHABLE')
        # Revision sells nothing: its card would print AED 0 -- reported once, under Revision.
        self.assertEqual(refused.exception.extra['problems'], ['Revision has no classes: enter its class counts.'])
        # Offered without Revision on its own, Regular + Revision still prints a Revision card.
        self.save(self.draft(), plan_types=['REGULAR', 'REGULAR_REVISION'], chapters=chapters)
        with self.assertRaises(SalesError) as refused:
            self.publish()
        self.assertEqual(refused.exception.extra['problems'],
                         ['Regular + Revision has no Revision classes: enter its class counts.'])
        self.save(self.draft(), plan_types=['REGULAR', 'CHAPTER_PLAN'], chapters=chapters)
        self.publish()

    def test_deactivating_and_reactivating(self):
        self.publish()
        services.deactivate(self.admin, self.syllabus.pk)
        self.assertEqual(self.detail()['status'], SyllabusStatus.INACTIVE)
        for refused_action in (lambda: services.start_draft(self.admin, self.syllabus.pk),
                               lambda: services.deactivate(self.admin, self.syllabus.pk)):
            with self.assertRaises(SalesError):
                refused_action()
        services.reactivate(self.admin, self.syllabus.pk)
        self.assertEqual(self.detail()['status'], SyllabusStatus.PUBLISHED)
        with self.assertRaises(SalesError) as refused:
            services.reactivate(self.admin, self.syllabus.pk)
        self.assertEqual(refused.exception.code, 'NOT_INACTIVE')
        entries = ActivityLog.objects.filter(entity_id=str(self.syllabus.pk)).order_by('created_at')
        self.assertEqual(
            [entry.action for entry in entries],
            ['syllabus.create', 'syllabus.publish', 'syllabus.deactivate', 'syllabus.reactivate'],
        )
        # The log keeps revision numbers, never a syllabus's content; nothing to "Show changes" for.
        self.assertEqual([(entry.changes, entry.context.get('revision')) for entry in entries],
                         [({}, 1), ({}, 1), ({}, 1), ({}, 1)])

    def test_duplicating_copies_what_the_syllabus_offers_or_the_revision_named(self):
        # Never published: what it offers is its draft (the path every preloaded reference draft takes).
        copy = services.duplicate(self.admin, self.syllabus.pk)
        detail = services.syllabus_detail(copy.pk)
        self.assertEqual((detail['status'], detail['draft']['number'], detail['draft']['title']),
                         (SyllabusStatus.DRAFT, 1, 'Grade 6 CBSE (Copy)'))
        self.publish()
        services.start_draft(self.admin, self.syllabus.pk)
        self.save(self.draft(), title='Grade 6 CBSE (2027)')
        # What the list row and the published tab show: revision 1, not the waiting draft.
        copy = services.duplicate(self.admin, self.syllabus.pk)
        detail = services.syllabus_detail(copy.pk)
        self.assertEqual((detail['status'], detail['draft']['number'], detail['draft']['title']),
                         (SyllabusStatus.DRAFT, 1, 'Grade 6 CBSE (Copy)'))
        self.assertEqual(detail['draft']['totals'], {'regular': '38', 'revision': '19', 'bridge': '0'})
        # The draft, when the Admin copies it from its tab.
        copy = services.duplicate(self.admin, self.syllabus.pk, 2)
        self.assertEqual(services.syllabus_detail(copy.pk)['draft']['title'], 'Grade 6 CBSE (2027) (Copy)')
        with self.assertRaises(SalesError) as refused:
            services.duplicate(self.admin, self.syllabus.pk, 9)
        self.assertEqual(refused.exception.code, 'NO_REVISION')
        # The source is untouched: published revision 1 and its draft revision 2.
        self.assertEqual([row['number'] for row in self.detail()['history']], [2, 1])

    def test_the_similar_warning_is_about_the_draft_being_written(self):
        other = services.create_syllabus(self.admin, valid(chapter_wise_payload(title='Grade 7 CBSE', grade=7)))
        self.publish()
        self.assertEqual(self.detail()['similar'], [])
        services.start_draft(self.admin, self.syllabus.pk)
        self.save(self.draft(), grade=7)  # the draft becomes Grade 7, like `other`
        self.assertEqual([row['id'] for row in self.detail()['similar']], [str(other.pk)])

    def test_similar_syllabuses_are_only_a_warning(self):
        other = services.create_syllabus(self.admin, valid(chapter_wise_payload(title='Grade 6 CBSE Crash Course',
                                                                                syllabus_version='new syllabus')))
        services.create_syllabus(self.admin, valid(chapter_wise_payload(syllabus_version='Old Syllabus')))
        self.assertEqual([(row['id'], row['title']) for row in self.detail()['similar']],
                         [(str(other.pk), 'Grade 6 CBSE Crash Course')])
        services.deactivate(self.admin, other.pk)
        self.assertEqual(self.detail()['similar'], [])


class ImmutableHistoryTests(LifecycleTestCase):
    """Whatever writes -- the ORM here, raw SQL alike -- a published revision and its chapters never change."""

    def assertRefused(self, write):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                write()

    def test_a_published_revision_and_its_chapters_are_frozen(self):
        revision = self.publish()
        chapter = revision.chapters.first()
        self.assertRefused(lambda: SyllabusRevision.objects.filter(pk=revision.pk).update(title='Rewritten'))
        self.assertRefused(lambda: SyllabusRevision.objects.filter(pk=revision.pk).delete())
        self.assertRefused(lambda: SyllabusChapter.objects.filter(pk=chapter.pk).update(regular_classes=9))
        self.assertRefused(lambda: SyllabusChapter.objects.filter(pk=chapter.pk).delete())
        self.assertRefused(lambda: SyllabusChapter.objects.create(revision=revision, position=11, name='Extra',
                                                                 regular_classes=1, revision_classes=1))
        self.assertEqual(services.revision_detail(self.syllabus.pk, 1)['totals']['regular'], '38')

    def test_a_draft_stays_writable(self):
        draft = self.draft()
        SyllabusRevision.objects.filter(pk=draft.pk).update(title='Still a draft')
        SyllabusChapter.objects.filter(revision=draft, position=1).update(regular_classes=6)

    def test_pricing_versions_are_append_only(self):
        version = services.create_pricing_version(self.admin, {
            'currency': 'AED', 'standard_fee': D('45'), 'offer_fee': D('35'), 'single_payment_percent': D('5'),
            'single_payment_plan_types': [PlanType.REGULAR], 'note': '',
        })
        self.assertRefused(lambda: PricingVersion.objects.filter(pk=version.pk).update(offer_fee=D('30')))
        self.assertRefused(lambda: PricingVersion.objects.filter(pk=version.pk).delete())


class ConstraintTests(LifecycleTestCase):
    """The database's own checks, behind the serializers'."""

    def assertViolates(self, write):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                write()

    def test_chapter_counts(self):
        draft = self.draft()
        row = {'revision': draft, 'position': 50, 'name': 'Extra'}
        self.assertViolates(lambda: SyllabusChapter.objects.create(**row, regular_classes=D('1.3'), revision_classes=1))
        self.assertViolates(lambda: SyllabusChapter.objects.create(**row, regular_classes=-1, revision_classes=1))
        self.assertViolates(lambda: SyllabusChapter.objects.create(**row, regular_classes=1, revision_classes=1,
                                                                  bridge_classes=1))
        self.assertViolates(lambda: SyllabusChapter.objects.create(**row, regular_classes=1))
        SyllabusChapter.objects.create(**row, regular_classes=D('99.5'), revision_classes=D('0.5'))

    def test_revisions(self):
        draft = self.draft()
        self.assertViolates(lambda: SyllabusRevision.objects.filter(pk=draft.pk).update(plan_types=['BRIDGE_COURSE']))
        self.assertViolates(lambda: SyllabusRevision.objects.filter(pk=draft.pk).update(plan_types=[]))
        self.assertViolates(lambda: SyllabusRevision.objects.filter(pk=draft.pk).update(grade=13))
        self.assertViolates(lambda: SyllabusRevision.objects.filter(pk=draft.pk).update(title='  '))
        # A second draft of the same syllabus.
        self.assertViolates(lambda: SyllabusRevision.objects.create(
            syllabus=self.syllabus, number=2, **{f: getattr(draft, f) for f in services.CONTENT_FIELDS},
            created_by=self.admin, updated_by=self.admin,
        ))

    def test_pricing(self):
        base = {'currency': 'AED', 'standard_fee': D('45'), 'created_by': self.admin}
        # A single-payment privilege only on a package card the PDF prints.
        self.assertViolates(lambda: PricingVersion.objects.create(version=1, offer_fee=D('35'),
                                                                  single_payment_plan_types=['REGULAR_REVISION'], **base))
        self.assertViolates(lambda: PricingVersion.objects.create(version=1, offer_fee=D('46'), **base))
        self.assertViolates(lambda: PricingVersion.objects.create(version=1, offer_fee=D('35'), **{**base, 'currency': 'aed'}))
        self.assertViolates(lambda: PricingVersion.objects.create(version=1, offer_fee=D('35'),
                                                                  single_payment_percent=D('100'), **base))


class PricingVersionTests(LifecycleTestCase):
    def test_each_change_is_the_next_version_and_history_keeps_every_one(self):
        def change(offer):
            return services.create_pricing_version(self.admin, {
                'currency': 'AED', 'standard_fee': D('45'), 'offer_fee': D(offer), 'single_payment_percent': D('5'),
                'single_payment_plan_types': [PlanType.REGULAR], 'note': f'Offer {offer}',
            })
        first, second = change('35'), change('32.50')
        self.assertEqual((first.version, second.version), (1, 2))
        self.assertLess(first.effective_from, second.effective_from)
        history = services.pricing_history()
        self.assertEqual([(row['version'], row['offer_fee']) for row in history], [(2, '32.5'), (1, '35')])
        self.assertEqual((history[0]['effective_until'], history[1]['effective_until']), (None, second.effective_from))
        # The log keeps each figure as {"old", "new"} -- the first version's old ones empty -- and the numbers in context.
        first_entry, second_entry = ActivityLog.objects.filter(action='pricing.create_version').order_by('created_at')
        self.assertEqual(first_entry.changes['offer_fee'], {'old': None, 'new': '35'})
        self.assertEqual(first_entry.context['previous_version'], None)
        self.assertEqual(second_entry.changes, {'offer_fee': {'old': '35', 'new': '32.5'}})
        self.assertEqual((second_entry.context['version'], second_entry.context['previous_version']), (2, 1))
        # The syllabus is priced at the version in effect.
        regular = self.detail()['draft']['packages'][0]
        self.assertEqual((regular['fee_per_class'], regular['total']), ('32.5', '1235'))
        self.assertEqual(regular['single_payment'], {'price': '1173', 'saving': '62'})

    def test_a_clock_stepping_back_never_lets_an_older_version_apply(self):
        def change(offer):
            return services.create_pricing_version(self.admin, {
                'currency': 'AED', 'standard_fee': D('45'), 'offer_fee': D(offer), 'single_payment_percent': D('0'),
                'single_payment_plan_types': [], 'note': '',
            })
        first = change('35')
        with mock.patch('sales.services.timezone.now', return_value=first.effective_from - timedelta(minutes=5)):
            second = change('30')
        self.assertGreater(second.effective_from, first.effective_from)
        self.assertEqual(services.active_pricing(timezone.now()), second)
