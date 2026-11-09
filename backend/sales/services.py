"""
Syllabuses and pricing versions are written only here, each change in one
transaction and recorded in the activity log.

A syllabus's lifecycle (D4):

    create         a new syllabus, its draft revision 1
    start_draft    a published syllabus's next draft, copied from its published revision
    save_draft     the draft as the Admin edited it; the published revision is untouched
    discard_draft  drop the draft of a published syllabus; it offers what it did
    publish        the draft becomes the published revision, on explicit confirmation
    deactivate     hidden from the sales to come; reactivate brings it back
    duplicate      a new syllabus, its draft copied from this one's published revision
                   (or a revision the Admin names; before any publication, the draft)

Every action locks the syllabus row, so two Admins never interleave. A save,
a publish or a discard names the draft the caller saw (its number and when it
was saved); when it changed meanwhile the answer is DRAFT_CHANGED and nothing
changes. The structure is fixed from the first publication on.

Similar syllabuses -- the same grade, board, syllabus version and structure --
are only a warning (D5): titles may tell offerings apart.

A Bridge Course is sold whole or by the day (bridge_selection): the days chosen
are rows of one of its published revisions, named by id -- never copied -- and
choosing every day is the whole course, priced and drawn exactly as before.

The catalogue on sale (catalogue_*) is what BDEs quote from: the active
syllabuses' newest published revisions and the pricing's rates -- never a
draft, a status, a history, the pricing's past versions or who did what.

The activity log keeps a syllabus's revision numbers (in ``context``), never its
content; a pricing version's entry keeps each figure as {"old", "new"}.
"""
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Count, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from activity.utils import log_activity

from .models import (
    TITLE_CHARS, PlanType, PricingVersion, Structure, Syllabus, SyllabusChapter, SyllabusRevision, SyllabusStatus,
)
from .pricing import active_pricing, card_plan_types, chapter_totals, chosen_chapters, packages, plain, plan_classes
from .wording import package_title_of, subtitle_of

CONTENT_FIELDS = (
    'title', 'subtitle', 'package_title', 'grade', 'board', 'syllabus_version', 'structure', 'plan_types', 'inclusions',
)
COUNT_FIELDS = ('regular_classes', 'revision_classes', 'bridge_classes')
COPY_SUFFIX = ' (Copy)'


class SalesError(Exception):
    """A refused action: ``code`` and ``message`` for the API, with its HTTP status."""

    def __init__(self, code, message, http_status=409, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.extra = extra


# ---------------------------------------------------------------- reading

def listed(queryset):
    """
    ``queryset`` (syllabuses) with ``published_id`` -- the revision it offers
    -- ``draft_id``, and ``shown_id``: the revision lists show, the published
    one or, before any, the draft.
    """
    published = (SyllabusRevision.objects.filter(syllabus=OuterRef('pk'), published_at__isnull=False)
                 .order_by('-number').values('pk')[:1])
    draft = SyllabusRevision.objects.filter(syllabus=OuterRef('pk'), published_at__isnull=True).values('pk')[:1]
    return (queryset.annotate(published_id=Subquery(published), draft_id=Subquery(draft))
            .annotate(shown_id=Coalesce('published_id', 'draft_id')))


def status_of(syllabus):
    """Inactive once deactivated, else Published once a revision is, else Draft. ``syllabus`` comes from listed()."""
    if syllabus.deactivated_at is not None:
        return SyllabusStatus.INACTIVE
    return SyllabusStatus.PUBLISHED if syllabus.published_id else SyllabusStatus.DRAFT


def filter_status(queryset, status):
    """``queryset`` (from listed()) narrowed to one SyllabusStatus."""
    if status == SyllabusStatus.INACTIVE:
        return queryset.filter(deactivated_at__isnull=False)
    active = queryset.filter(deactivated_at__isnull=True)
    if status == SyllabusStatus.PUBLISHED:
        return active.filter(published_id__isnull=False)
    return active.filter(published_id__isnull=True)


def filter_shown(queryset, **lookups):
    """``queryset`` (from listed()) narrowed to the syllabuses whose shown revision matches ``lookups``."""
    return queryset.filter(shown_id__in=SyllabusRevision.objects.filter(**lookups).values('pk'))


def with_totals(revisions):
    return revisions.annotate(
        total_regular=Sum('chapters__regular_classes'),
        total_revision=Sum('chapters__revision_classes'),
        total_bridge=Sum('chapters__bridge_classes'),
        chapter_count=Count('chapters'),
    )


def list_rows(syllabi, include_subtitle=False):
    """One list row per syllabus (from listed()): its status and the revision it shows."""
    syllabi = list(syllabi)
    shown = {
        revision.pk: revision
        for revision in with_totals(SyllabusRevision.objects.filter(pk__in=[s.shown_id for s in syllabi]))
    }
    numbers = dict(SyllabusRevision.objects.filter(pk__in=[s.draft_id for s in syllabi if s.draft_id])
                   .values_list('pk', 'number'))
    rows = []
    for syllabus in syllabi:
        revision = shown[syllabus.shown_id]
        rows.append({
            'id': str(syllabus.pk),
            'status': status_of(syllabus),
            'revision': revision.number,
            'published_revision': revision.number if syllabus.published_id else None,
            'draft_revision': numbers.get(syllabus.draft_id),
            'title': revision.title,
            **({'subtitle': subtitle_of({'subtitle': revision.subtitle, 'structure': revision.structure})} if include_subtitle else {}),
            'grade': revision.grade,
            'board': revision.board,
            'syllabus_version': revision.syllabus_version,
            'structure': revision.structure,
            'plan_types': revision.plan_types,
            'chapter_count': revision.chapter_count,
            'totals': {
                'regular': plain(revision.total_regular) if revision.total_regular is not None else None,
                'revision': plain(revision.total_revision) if revision.total_revision is not None else None,
                'bridge': plain(revision.total_bridge) if revision.total_bridge is not None else None,
            },
            'updated_at': syllabus.updated_at,
            'updated_by': _person(syllabus.updated_by),
        })
    return rows


def syllabus_detail(syllabus_id):
    """One syllabus in full: its published revision, its draft, its history and similar syllabuses. None if unknown."""
    syllabus = (listed(Syllabus.objects.filter(pk=syllabus_id))
                .select_related('created_by', 'updated_by', 'deactivated_by').first())
    if syllabus is None:
        return None
    revisions = list(syllabus.revisions.select_related('created_by', 'published_by').order_by('-number'))
    by_id = {revision.pk: revision for revision in revisions}
    pricing = active_pricing()
    published = by_id.get(syllabus.published_id)
    draft = by_id.get(syllabus.draft_id)
    return {
        'id': str(syllabus.pk),
        'status': status_of(syllabus),
        # The reference PDF it was loaded from, to review it against (D8); None when added by hand.
        'reference': syllabus.reference_key,
        # The structure stays as first published (the draft of a published syllabus keeps it).
        'structure_locked': published is not None,
        'created_at': syllabus.created_at,
        'created_by': _person(syllabus.created_by),
        'updated_at': syllabus.updated_at,
        'updated_by': _person(syllabus.updated_by),
        'deactivated_at': syllabus.deactivated_at,
        'deactivated_by': _person(syllabus.deactivated_by),
        'published': revision_data(published, pricing) if published else None,
        'draft': revision_data(draft, pricing) if draft else None,
        'history': [_history_row(revision, syllabus.published_id) for revision in revisions],
        # About what is being written and would be published next: the draft, else the published revision.
        'similar': similar_syllabi(syllabus.pk, draft or published),
        'pricing': pricing_data(pricing) if pricing else None,
    }


def revision_detail(syllabus_id, number):
    """One revision of a syllabus in full, priced as now. None if the syllabus has no such revision."""
    revision = (SyllabusRevision.objects.filter(syllabus_id=syllabus_id, number=number)
                .select_related('created_by', 'updated_by', 'published_by').first())
    return revision_data(revision, active_pricing()) if revision else None


def shown_revision(syllabus_id):
    """What a syllabus offers: its published revision, or its draft before the first publication. None if unknown."""
    syllabus = listed(Syllabus.objects.filter(pk=syllabus_id)).first()
    return SyllabusRevision.objects.get(pk=syllabus.shown_id) if syllabus else None


def content_of(revision):
    """``revision``'s content, as the PDF draws it."""
    return _content_of(revision)


def revision_data(revision, pricing=None):
    """``revision`` with its chapters and totals -- and its packages, when ``pricing`` prices them."""
    chapters = list(revision.chapters.order_by('position'))
    return {
        **content_data(_content_of(revision, chapters), pricing),
        'id': str(revision.pk),
        'number': revision.number,
        'is_draft': revision.is_draft,
        'created_at': revision.created_at,
        'created_by': _person(revision.created_by),
        'updated_at': revision.updated_at,
        'updated_by': _person(revision.updated_by),
        'published_at': revision.published_at,
        'published_by': _person(revision.published_by),
    }


def content_data(content, pricing=None):
    """
    A syllabus's content -- a revision's, or one not yet saved (a preview) --
    as the API answers it: counts and amounts as plain decimal strings.
    """
    chapters = content['chapters']
    totals = chapter_totals(chapters)
    data = {field: content[field] for field in CONTENT_FIELDS}
    # What the PDF prints where the Admin left the line empty (sales.wording).
    data['subtitle_display'] = subtitle_of(content)
    data['package_title_display'] = package_title_of(content)
    data['chapters'] = [
        {
            'id': str(chapter['id']) if chapter.get('id') else None,
            'position': position,
            'name': chapter['name'],
            **{field: plain(chapter.get(field)) for field in COUNT_FIELDS},
        }
        for position, chapter in enumerate(chapters, start=1)
    ]
    data['totals'] = {column: plain(total) for column, total in totals.items()}
    data['packages'] = [_package_data(package) for package in packages(content['plan_types'], chapters, pricing)] if pricing else None
    return data


def bridge_selection(syllabus_id, number, chapter_ids):
    """
    The days of a Bridge Course's published revision ``number`` a purchase is
    for: ``chapter_ids``, days of that revision, each once, at least one, and
    selling some classes. Returns ``(revision, content, selected)``: the
    revision, its content as the PDF draws it, and the chosen ids in the
    course's order -- or None when every day is chosen, the whole course.
    Nothing is written; a SalesError says why a choice is refused.
    """
    syllabus = Syllabus.objects.filter(pk=syllabus_id).first()
    if syllabus is None:
        raise SalesError('NOT_FOUND', 'No such syllabus.', 404)
    revision = syllabus.revisions.filter(number=number).first()
    if revision is None:
        raise SalesError('NOT_FOUND', 'This syllabus has no such revision.', 404)
    if revision.structure != Structure.BRIDGE_COURSE:
        raise SalesError('NOT_A_BRIDGE_COURSE', 'Only a Bridge Course is sold by the day.')
    if revision.published_at is None:
        raise SalesError('NOT_PUBLISHED', f'Revision {revision.number} is a draft: days are sold from a published revision only.')
    _refuse_inactive(syllabus)

    chapters = list(revision.chapters.order_by('position'))
    selected = choose(chapters, chapter_ids, PlanType.BRIDGE_COURSE, revision)
    content = _content_of(revision, chapters)
    return revision, content, (None if len(selected) == len(chapters) else selected)


def choose(chapters, chapter_ids, plan_type, revision):
    """
    The ids of ``chapter_ids`` -- a Bridge Course's days, or a Chapter Plan's
    chapters -- in the course's order: rows of ``revision`` (whose ``chapters``
    they must be), each once, at least one, selling some classes of
    ``plan_type``. A SalesError (INVALID_SELECTION) says what is wrong.
    """
    noun, where = ('day', 'this Bridge Course') if plan_type == PlanType.BRIDGE_COURSE else ('chapter', 'this syllabus')
    wanted = [str(chapter_id) for chapter_id in chapter_ids]
    if not wanted:
        raise _invalid_selection(f'Choose at least one {noun}.')
    if len(set(wanted)) != len(wanted):
        raise _invalid_selection(f'Choose each {noun} once.')
    if set(wanted) - {str(chapter.pk) for chapter in chapters}:
        raise _invalid_selection(f'Choose {noun}s of revision {revision.number} of {where}.')
    selected = [str(chapter.pk) for chapter in chosen_chapters(chapters, wanted)]
    if plan_classes(plan_type, chapters, selected) <= 0:
        raise _invalid_selection(f'The {noun}s chosen have no classes.')
    return selected


def selection_data(revision, content, selected, pricing):
    """
    A Bridge Course bought by the day, as the API answers it: the days chosen
    (their day numbers and classes), their total, and the package priced by
    ``pricing`` -- the whole course's when ``selected`` is None.
    """
    chapters = content['chapters']
    shown = chapters if selected is None else chosen_chapters(chapters, selected)
    days = {id(chapter) for chapter in shown}
    [package] = packages(content['plan_types'], chapters, pricing, selected=selected)
    return {
        'syllabus': str(revision.syllabus_id),
        'revision': revision.number,
        'title': content['title'],
        'full_course': selected is None,
        'days': [
            {'id': str(chapter['id']), 'day': day, 'name': chapter['name'], 'classes': plain(chapter['bridge_classes'])}
            for day, chapter in enumerate(chapters, start=1) if id(chapter) in days
        ],
        'classes': plain(package.classes),
        'pricing': {
            'version': pricing.version, 'currency': pricing.currency,
            'standard_fee': plain(pricing.standard_fee), 'offer_fee': plain(pricing.offer_fee),
        },
        'package': _package_data(package),
    }


# ---------------------------------------------------------------- the catalogue on sale

# What a catalogue row shows of a syllabus on sale (from list_rows, which also has the Admin's workings).
CATALOGUE_ROW_FIELDS = (
    'id', 'revision', 'title', 'subtitle', 'grade', 'board', 'syllabus_version', 'structure', 'plan_types', 'chapter_count', 'totals',
)


def catalogue():
    """The syllabuses on sale (from listed()): active, with a published revision -- the newest, the one sold."""
    return filter_status(listed(Syllabus.objects.all()), SyllabusStatus.PUBLISHED)


def by_grade_and_title(syllabi):
    """``syllabi`` (from catalogue()) in the order a BDE browses them: grade, then the title they are sold under."""
    # Keyed on the syllabus itself, as listed()'s own subquery: a reference to its published_id annotation
    # would nest that annotation's outer reference inside this subquery and read another syllabus's revision.
    sold = SyllabusRevision.objects.filter(syllabus=OuterRef('pk'), published_at__isnull=False).order_by('-number')
    return (syllabi.annotate(sold_grade=Subquery(sold.values('grade')[:1]), sold_title=Subquery(sold.values('title')[:1]))
            .order_by('sold_grade', 'sold_title', 'pk'))


def catalogue_rows(syllabi):
    """One row per syllabus on sale (from catalogue()): its published revision, and nothing of the Admin's workings."""
    return [{field: row[field] for field in CATALOGUE_ROW_FIELDS} for row in list_rows(syllabi, include_subtitle=True)]


def catalogue_revision(syllabus_id):
    """The revision a syllabus on sale sells -- its newest published one -- or None when it is not on sale."""
    syllabus = catalogue().filter(pk=syllabus_id).first()
    return SyllabusRevision.objects.get(pk=syllabus.published_id) if syllabus else None


def catalogue_detail(syllabus_id):
    """
    A syllabus on sale as a BDE quotes it: the revision it sells, its chapters
    (by id, to choose a Bridge Course's days from), totals and packages priced
    as now, and the pricing's rates and privilege. None when it is not on sale.
    """
    revision = catalogue_revision(syllabus_id)
    if revision is None:
        return None
    pricing = active_pricing()
    data = content_data(_content_of(revision), pricing)
    return {
        'id': str(revision.syllabus_id),
        'revision': revision.number,
        'title': data['title'],
        # What the PDF prints: the Admin's line, or the default for the structure and title.
        'subtitle': data['subtitle_display'],
        'package_title': data['package_title_display'],
        **{field: data[field] for field in (
            'grade', 'board', 'syllabus_version', 'structure', 'plan_types', 'inclusions', 'chapters', 'totals', 'packages',
        )},
        'pricing': catalogue_pricing(pricing),
    }


def catalogue_pricing(pricing):
    """The pricing in effect as quoting needs it -- its rates and privilege; no note, author, date or history."""
    if pricing is None:
        return None
    return {
        'version': pricing.version,
        'currency': pricing.currency,
        'standard_fee': plain(pricing.standard_fee),
        'offer_fee': plain(pricing.offer_fee),
        'single_payment_percent': plain(pricing.single_payment_percent),
        'single_payment_plan_types': list(pricing.single_payment_plan_types),
    }


def catalogue_selection(syllabus_id, number, chapter_ids):
    """
    bridge_selection for a syllabus on sale, from the revision it sells:
    ``number`` is the revision the BDE was shown. Once a newer one is
    published the choice is refused (REVISION_CHANGED, with the revision now
    sold) rather than read against rows the BDE never saw.
    """
    on_sale_revision(syllabus_id, number)
    return bridge_selection(syllabus_id, number, chapter_ids)


def on_sale_revision(syllabus_id, number):
    """
    Revision ``number`` of a syllabus on sale, when it is the one it sells: a
    choice made from what a BDE was shown. NOT_FOUND when the syllabus is not
    on sale or sells no such revision; REVISION_CHANGED (with the revision now
    sold) once a newer one is published, rather than read against rows the BDE
    never saw.
    """
    revision = catalogue_revision(syllabus_id)
    if revision is None:
        raise SalesError('NOT_FOUND', 'No such syllabus on sale.', 404)
    if number > revision.number:
        raise SalesError('NOT_FOUND', 'This syllabus sells no such revision.', 404)
    if number != revision.number:
        raise SalesError(
            'REVISION_CHANGED',
            f'This syllabus was updated to revision {revision.number}: reload it and choose the days again.',
            revision=revision.number,
        )
    return revision


def similar_syllabi(syllabus_id, revision):
    """
    The other active syllabuses showing the same grade, board, syllabus
    version and structure as ``revision`` -- a warning, never a refusal (D5).
    """
    if revision is None:
        return []
    others = listed(Syllabus.objects.filter(deactivated_at__isnull=True).exclude(pk=syllabus_id))
    others = list(filter_shown(
        others, grade=revision.grade, board=revision.board, structure=revision.structure,
        syllabus_version__iexact=revision.syllabus_version,
    ).order_by('-updated_at'))
    titles = dict(SyllabusRevision.objects.filter(pk__in=[other.shown_id for other in others]).values_list('pk', 'title'))
    return [
        {'id': str(other.pk), 'title': titles.get(other.shown_id, ''), 'status': status_of(other)}
        for other in others
    ]


def publish_problems(revision):
    """
    Why ``revision`` cannot be published yet: each plan type it offers must
    sell some classes, and so must each package card the PDF prints for it --
    Regular + Revision prints a Regular and a Revision card (D6), so it needs
    both columns, not just their sum.
    """
    chapters = list(revision.chapters.all())
    if not chapters:
        return ['Add at least one chapter.']
    problems = []
    for plan_type in revision.plan_types:
        classes = plan_classes(plan_type, chapters, chosen=[chapter.pk for chapter in chapters])
        if classes <= 0:
            problems.append(f'{PlanType(plan_type).label} has no classes: enter its class counts.')
    if PlanType.REGULAR_REVISION in revision.plan_types:
        for card in card_plan_types([PlanType.REGULAR_REVISION]):
            # A part also offered on its own was reported above.
            if card not in revision.plan_types and plan_classes(card, chapters) <= 0 < plan_classes(
                    PlanType.REGULAR_REVISION, chapters):
                problems.append(f'Regular + Revision has no {PlanType(card).label} classes: enter its class counts.')
    return problems


# ---------------------------------------------------------------- writing

def create_syllabus(actor, content, request=None, reference_key=None):
    """
    A new syllabus, ``content`` (SyllabusContentSerializer's) as its draft
    revision 1 -- loaded from the reference PDF ``reference_key`` names, if any.
    """
    now = timezone.now()
    with transaction.atomic():
        syllabus = Syllabus.objects.create(
            created_by=actor, created_at=now, updated_by=actor, updated_at=now, reference_key=reference_key,
        )
        revision = _new_revision(syllabus, 1, content, actor, now)
    _log('syllabus.create', syllabus, revision, request, actor, **({'reference': reference_key} if reference_key else {}))
    return syllabus


def start_draft(actor, syllabus_id, request=None):
    """The next draft of a published syllabus, copied from its published revision."""
    now = timezone.now()
    with transaction.atomic():
        syllabus = _locked(syllabus_id)
        _refuse_inactive(syllabus)
        if _draft(syllabus):
            raise SalesError('DRAFT_EXISTS', 'This syllabus already has a draft. Open it to keep editing.')
        published = _published(syllabus)
        draft = _new_revision(syllabus, published.number + 1, _content_of(published), actor, now)
        _touch(syllabus, actor, now)
    _log('syllabus.start_draft', syllabus, draft, request, actor)
    return draft


def save_draft(actor, syllabus_id, content, seen_updated_at, request=None):
    """The draft as the Admin edited it (``content``), if it is still the one they saw."""
    now = timezone.now()
    with transaction.atomic():
        syllabus = _locked(syllabus_id)
        _refuse_inactive(syllabus)
        draft = _draft(syllabus)
        if draft is None or draft.updated_at != seen_updated_at:
            raise _draft_changed()
        published = _published(syllabus, required=False)
        if published and content['structure'] != published.structure:
            raise SalesError(
                'STRUCTURE_LOCKED', 'The structure cannot change once the syllabus is published.', 400,
                fields={'structure': ['The structure cannot change once the syllabus is published.']},
            )
        for field in CONTENT_FIELDS:
            setattr(draft, field, content[field])
        draft.updated_by = actor
        draft.updated_at = now
        draft.save(update_fields=[*CONTENT_FIELDS, 'updated_by', 'updated_at'])
        _write_chapters(draft, content['chapters'])
        _touch(syllabus, actor, now)
    _log('syllabus.save_draft', syllabus, draft, request, actor)
    return draft


def discard_draft(actor, syllabus_id, number, seen_updated_at, request=None):
    """Drop the draft of a published syllabus: it keeps offering its published revision."""
    now = timezone.now()
    with transaction.atomic():
        syllabus = _locked(syllabus_id)
        draft = _seen_draft(syllabus, number, seen_updated_at)
        if _published(syllabus, required=False) is None:
            raise SalesError(
                'NEVER_PUBLISHED', 'This draft is the whole syllabus: deactivate the syllabus instead.',
            )
        label = draft.title
        draft.delete()
        _touch(syllabus, actor, now)
    log_activity(
        action='syllabus.discard_draft', entity_type='syllabus', entity_id=syllabus.pk, entity_label=label,
        context={'revision': number}, request=request, actor=actor,
    )


def publish(actor, syllabus_id, number, seen_updated_at, request=None):
    """
    The draft the Admin confirmed becomes the published revision. The one it
    replaces stays, unchanged, in the history.
    """
    now = timezone.now()
    with transaction.atomic():
        syllabus = _locked(syllabus_id)
        _refuse_inactive(syllabus)
        # The draft row itself is locked before it is checked: a chapter write that got in first
        # (its trigger reads the row FOR SHARE) is committed and checked too, and a later one waits
        # for the publication and is refused (sales.0002).
        draft = _seen_draft(syllabus, number, seen_updated_at, lock=True)
        problems = publish_problems(draft)
        if problems:
            raise SalesError('NOT_PUBLISHABLE', problems[0], 400, problems=problems)
        draft.published_at = now
        draft.published_by = actor
        draft.save(update_fields=['published_at', 'published_by'])
        _touch(syllabus, actor, now)
    _log('syllabus.publish', syllabus, draft, request, actor)
    return draft


def deactivate(actor, syllabus_id, request=None):
    """Hide the syllabus from the sales to come. Its revisions, draft included, stay as they are."""
    now = timezone.now()
    with transaction.atomic():
        syllabus = _locked(syllabus_id)
        if syllabus.deactivated_at is not None:
            raise SalesError('ALREADY_INACTIVE', 'This syllabus is already inactive.')
        syllabus.deactivated_at = now
        syllabus.deactivated_by = actor
        syllabus.updated_by = actor
        syllabus.updated_at = now
        syllabus.save(update_fields=['deactivated_at', 'deactivated_by', 'updated_by', 'updated_at'])
    _log('syllabus.deactivate', syllabus, _shown(syllabus), request, actor)
    return syllabus


def reactivate(actor, syllabus_id, request=None):
    """Bring an inactive syllabus back: Published again, or Draft if it never was."""
    now = timezone.now()
    with transaction.atomic():
        syllabus = _locked(syllabus_id)
        if syllabus.deactivated_at is None:
            raise SalesError('NOT_INACTIVE', 'This syllabus is active.')
        syllabus.deactivated_at = None
        syllabus.deactivated_by = None
        syllabus.updated_by = actor
        syllabus.updated_at = now
        syllabus.save(update_fields=['deactivated_at', 'deactivated_by', 'updated_by', 'updated_at'])
    _log('syllabus.reactivate', syllabus, _shown(syllabus), request, actor)
    return syllabus


def duplicate(actor, syllabus_id, number=None, request=None):
    """
    A new syllabus whose draft copies this one: revision ``number`` when given
    (else 404 NO_REVISION), else what it offers -- its published revision, or
    its draft before the first publication.
    """
    now = timezone.now()
    with transaction.atomic():
        source = _locked(syllabus_id)
        if number is not None:
            revision = source.revisions.filter(number=number).first()
            if revision is None:
                raise SalesError('NO_REVISION', 'This syllabus has no such revision.', 404)
        else:
            revision = _shown(source)
        content = _content_of(revision)
        content['title'] = _copy_title(content['title'])
        copy = Syllabus.objects.create(created_by=actor, created_at=now, updated_by=actor, updated_at=now)
        draft = _new_revision(copy, 1, content, actor, now)
    _log('syllabus.duplicate', copy, draft, request, actor, source=str(source.pk), source_revision=revision.number)
    return copy


# ---------------------------------------------------------------- pricing

def create_pricing_version(actor, data, request=None):
    """The next pricing version (PricingVersionSerializer's ``data``), in effect from now on."""
    with transaction.atomic():
        # One writer at a time, so numbers and effective times only ever go up. Reads go on.
        with connection.cursor() as cursor:
            cursor.execute(f'LOCK TABLE {PricingVersion._meta.db_table} IN EXCLUSIVE MODE')
        latest = PricingVersion.objects.order_by('-version').first()
        effective_from = timezone.now()
        if latest and effective_from <= latest.effective_from:
            # Never before the version it replaces, whatever the server clock did:
            # the newest version must be the one that applies (active_pricing).
            effective_from = latest.effective_from + timedelta(microseconds=1)
        version = PricingVersion.objects.create(
            version=latest.version + 1 if latest else 1, effective_from=effective_from, created_by=actor, **data,
        )
    log_activity(
        action='pricing.create_version', entity_type='pricing_version', entity_id=version.pk,
        entity_label=f'Pricing v{version.version}',
        changes=_pricing_changes(latest, version),
        context={'version': version.version, 'previous_version': latest.version if latest else None},
        request=request, actor=actor,
    )
    return version


PRICING_FIELDS = ('currency', 'standard_fee', 'offer_fee', 'single_payment_percent', 'single_payment_plan_types')


def _pricing_changes(previous, version):
    """Each figure ``version`` changed from ``previous`` (every one for the first), as the log keeps them: {"old", "new"}."""
    def value(pricing, field):
        raw = getattr(pricing, field)
        return plain(raw) if field.endswith(('_fee', '_percent')) else raw

    changes = {}
    for field in PRICING_FIELDS:
        old = value(previous, field) if previous else None
        new = value(version, field)
        if old != new:
            changes[field] = {'old': old, 'new': new}
    return changes


def pricing_history():
    """Every pricing version, newest first, each with when it stopped applying (None: it still does)."""
    versions = list(PricingVersion.objects.select_related('created_by').order_by('-version'))
    rows, until = [], None
    for version in versions:
        rows.append({**pricing_data(version), 'effective_until': until})
        until = version.effective_from
    return rows


def pricing_data(version):
    return {
        'id': str(version.pk),
        'version': version.version,
        'currency': version.currency,
        'standard_fee': plain(version.standard_fee),
        'offer_fee': plain(version.offer_fee),
        'single_payment_percent': plain(version.single_payment_percent),
        'single_payment_plan_types': version.single_payment_plan_types,
        'note': version.note,
        'effective_from': version.effective_from,
        'created_by': _person(version.created_by),
    }


# ---------------------------------------------------------------- internals

def _locked(syllabus_id):
    return Syllabus.objects.select_for_update().get(pk=syllabus_id)


def _draft(syllabus, lock=False):
    drafts = syllabus.revisions.filter(published_at__isnull=True)
    return (drafts.select_for_update(no_key=True) if lock else drafts).first()


def _published(syllabus, required=True):
    published = syllabus.revisions.filter(published_at__isnull=False).order_by('-number').first()
    if published is None and required:
        raise SalesError('NOT_PUBLISHED', 'This syllabus has not been published yet: edit its draft.')
    return published


def _shown(syllabus):
    return _published(syllabus, required=False) or _draft(syllabus)


def _seen_draft(syllabus, number, seen_updated_at, lock=False):
    draft = _draft(syllabus, lock=lock)
    if draft is None or draft.number != number or draft.updated_at != seen_updated_at:
        raise _draft_changed()
    return draft


def _draft_changed():
    return SalesError(
        'DRAFT_CHANGED', 'This draft was changed or published meanwhile. Reload it to see the latest version.',
    )


def _invalid_selection(message):
    return SalesError('INVALID_SELECTION', message, 400, fields={'chapter_ids': [message]})


def _refuse_inactive(syllabus):
    if syllabus.deactivated_at is not None:
        raise SalesError('SYLLABUS_INACTIVE', 'This syllabus is inactive. Reactivate it first.')


def _touch(syllabus, actor, now):
    syllabus.updated_by = actor
    syllabus.updated_at = now
    syllabus.save(update_fields=['updated_by', 'updated_at'])


def _new_revision(syllabus, number, content, actor, now):
    revision = SyllabusRevision.objects.create(
        syllabus=syllabus, number=number, created_by=actor, created_at=now, updated_by=actor, updated_at=now,
        **{field: content[field] for field in CONTENT_FIELDS},
    )
    SyllabusChapter.objects.bulk_create([
        SyllabusChapter(revision=revision, position=position, name=chapter['name'],
                        **{field: chapter.get(field) for field in COUNT_FIELDS})
        for position, chapter in enumerate(content['chapters'], start=1)
    ])
    return revision


def _write_chapters(draft, chapters):
    """
    ``draft``'s chapters become ``chapters``, numbered in their order: a row
    naming one of the draft's chapters updates it, any other row is added, and
    the draft's chapters not named are removed. Positions may swap: their
    uniqueness is checked when the transaction commits.
    """
    existing = {str(chapter.pk): chapter for chapter in draft.chapters.all()}
    added = []
    for position, data in enumerate(chapters, start=1):
        values = {'position': position, 'name': data['name'], **{field: data.get(field) for field in COUNT_FIELDS}}
        chapter = existing.pop(str(data['id']), None) if data.get('id') else None
        if chapter is None:
            added.append(SyllabusChapter(revision=draft, **values))
        elif any(getattr(chapter, field) != value for field, value in values.items()):
            for field, value in values.items():
                setattr(chapter, field, value)
            chapter.save(update_fields=list(values))
    if existing:
        SyllabusChapter.objects.filter(pk__in=list(existing)).delete()
    SyllabusChapter.objects.bulk_create(added)


def _content_of(revision, chapters=None):
    """``revision``'s content, in the form SyllabusContentSerializer gives it."""
    chapters = chapters if chapters is not None else revision.chapters.order_by('position')
    return {
        **{field: getattr(revision, field) for field in CONTENT_FIELDS},
        'chapters': [
            {'id': chapter.pk, 'name': chapter.name, **{field: getattr(chapter, field) for field in COUNT_FIELDS}}
            for chapter in chapters
        ],
    }


def _copy_title(title):
    return f'{title[:TITLE_CHARS - len(COPY_SUFFIX)]}{COPY_SUFFIX}'


def _history_row(revision, published_id):
    if revision.published_at is None:
        state = 'DRAFT'
    else:
        state = 'PUBLISHED' if revision.pk == published_id else 'SUPERSEDED'
    return {
        'number': revision.number,
        'state': state,
        'title': revision.title,
        'created_at': revision.created_at,
        'created_by': _person(revision.created_by),
        'published_at': revision.published_at,
        'published_by': _person(revision.published_by),
    }


def _package_data(package):
    return {
        'plan_type': package.plan_type,
        'title': package.title,
        'classes': plain(package.classes),
        'fee_per_class': plain(package.fee_per_class),
        'total': plain(package.total),
        'single_payment': {
            'price': plain(package.single_payment[0]), 'saving': plain(package.single_payment[1]),
        } if package.single_payment else None,
    }


def _person(user):
    return {'id': str(user.pk), 'name': user.full_name or user.username} if user else None


def _log(action, syllabus, revision, request, actor, **context):
    if revision:
        context = {'revision': revision.number, **context}
    log_activity(
        action=action, entity_type='syllabus', entity_id=syllabus.pk,
        entity_label=revision.title if revision else None,
        context=context or None, request=request, actor=actor,
    )
