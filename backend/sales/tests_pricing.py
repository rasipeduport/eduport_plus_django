"""
Package prices (sales.pricing): one offer fee per class for every plan, exact
decimals throughout, and the single-payment price -- the only rounded amount
-- rounded to the nearest whole currency unit, a half up (D1). The figures are the reference
PDFs' (AED 45 standard, 35 offer, 5% off the Regular package when paid at once).
"""
from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .models import PlanType, PricingVersion
from .pricing import active_pricing, card_plan_types, packages, plain, plan_classes, single_payment_price

REGULAR, REVISION, CHAPTER_PLAN, BRIDGE, BOTH = (
    PlanType.REGULAR, PlanType.REVISION, PlanType.CHAPTER_PLAN, PlanType.BRIDGE_COURSE, PlanType.REGULAR_REVISION,
)


def pricing(**fields):
    return PricingVersion(**{
        'version': 1, 'currency': 'AED', 'standard_fee': D('45'), 'offer_fee': D('35'),
        'single_payment_percent': D('5'), 'single_payment_plan_types': [REGULAR], **fields,
    })


def chapters(*counts):
    """Chapter-wise rows from (regular, revision) pairs."""
    return [
        {'id': f'c{index}', 'regular_classes': D(str(regular)), 'revision_classes': D(str(revision)), 'bridge_classes': None}
        for index, (regular, revision) in enumerate(counts, start=1)
    ]


# The reference syllabuses' class counts.
GRADE_6_NEW = chapters((4, 2), (5, 2), (4, 2), (3, 2), (3, 2), (3, 2), (5, 2), (4, 2), (2, 1), (5, 2))
GRADE_10 = chapters((4, '1.5'), (4, 2), (6, '2.5'), (6, 3), (6, 3), (6, 2), (4, 2), (7, 3), (4, 2), (7, 3), (4, 1),
                    (6, 3), (4, 1), (4, 1))


def cards(plan_types, rows, version=None):
    return {card.plan_type: card for card in packages(plan_types, rows, version or pricing())}


class PackagePriceTests(SimpleTestCase):
    def test_grade_6_new_syllabus_as_its_reference_pdf_prices_it(self):
        priced = cards([REGULAR, REVISION, BOTH], GRADE_6_NEW)
        regular, revision = priced[REGULAR], priced[REVISION]
        self.assertEqual((regular.classes, regular.fee_per_class, regular.total), (D('38'), D('35'), D('1330')))
        # 1,330 less 5% is 1,263.50 exactly: a half rounds up, to 1,264, saving 66.
        self.assertEqual(regular.single_payment, (D('1264'), D('66')))
        self.assertEqual((revision.classes, revision.total, revision.single_payment), (D('19'), D('665'), None))

    def test_grade_10_with_half_revision_classes(self):
        priced = cards([BOTH], GRADE_10)
        self.assertEqual((priced[REGULAR].total, priced[REGULAR].single_payment), (D('2520'), (D('2394'), D('126'))))
        self.assertEqual((priced[REVISION].classes, priced[REVISION].total), (D('30'), D('1050')))

    def test_the_single_payment_price_is_rounded_to_the_nearest_whole_unit_a_half_up(self):
        def price(total, **fields):
            return single_payment_price(D(total), pricing(**fields), REGULAR)
        # Grade 9: 2,765 less 5% is 2,626.75 -> 2,627, saving 138 (as its reference PDF).
        self.assertEqual(price('2765'), (D('2627'), D('138')))
        # Grade 7 (Old): 1,296.75 -> 1,297. Grade 10: 2,394 exactly stays 2,394.
        self.assertEqual(price('1365'), (D('1297'), D('68')))
        self.assertEqual(price('2520'), (D('2394'), D('126')))
        # A half rounds up (1,263.50 -> 1,264), more than a half too (1,045.20 less 5% is 992.94 -> 993), and less
        # than a half rounds down (1,000.40 less 5% is 950.38 -> 950).
        self.assertEqual(price('1330'), (D('1264'), D('66')))
        self.assertEqual(price('1045.20'), (D('993'), D('52.20')))
        self.assertEqual(price('1000.40'), (D('950'), D('50.40')))
        # The saving is always the total less the rounded price, so the two add up to the total.
        for total in ('2765', '1330', '1045.20', '687.375'):
            rounded, saving = price(total)
            self.assertEqual(rounded + saving, D(total), total)

    def test_amounts_stay_exact_until_the_single_payment_price(self):
        version = pricing(offer_fee=D('35.25'), single_payment_plan_types=[REGULAR, REVISION])
        priced = cards([REVISION], chapters((1, '19.5')), version)
        self.assertEqual(priced[REVISION].total, D('687.375'))
        # 687.375 x 0.95 = 653.00625 -> 653; the saving keeps every fil.
        self.assertEqual(priced[REVISION].single_payment, (D('653'), D('34.375')))
        # Nothing is rounded on the way: 14 classes at AED 35.15 are 492.10, less 5% is 467.495 -> 467 (rounding
        # to cents first would give 467.50 and then 468); 119 classes at 35.25 less 4.75% is 3,995.499375 -> 3,995.
        fils = pricing(offer_fee=D('35.15'))
        self.assertEqual(cards([REGULAR], chapters((14, 1)), fils)[REGULAR].single_payment, (D('467'), D('25.10')))
        quarter = pricing(offer_fee=D('35.25'), single_payment_percent=D('4.75'))
        regular = cards([REGULAR], chapters(('59.5', 1), ('59.5', 1)), quarter)[REGULAR]
        self.assertEqual((regular.classes, regular.total, regular.single_payment),
                         (D('119'), D('4194.75'), (D('3995'), D('199.75'))))

    def test_no_privilege_without_a_percentage_or_for_plans_it_does_not_list(self):
        self.assertIsNone(single_payment_price(D('1330'), pricing(single_payment_percent=D('0')), REGULAR))
        self.assertIsNone(single_payment_price(D('665'), pricing(), REVISION))
        self.assertIsNone(single_payment_price(D('1050'), pricing(), BRIDGE))

    def test_the_cards_each_plan_type_shows(self):
        self.assertEqual(card_plan_types([BOTH]), [REGULAR, REVISION])
        self.assertEqual(card_plan_types([REGULAR, CHAPTER_PLAN]), [REGULAR])
        self.assertEqual(card_plan_types([REVISION]), [REVISION])
        self.assertEqual(card_plan_types([CHAPTER_PLAN]), [])  # no Chapter Plan card yet (D6)
        self.assertEqual(card_plan_types([BRIDGE]), [BRIDGE])

    def test_the_classes_each_plan_type_sells(self):
        self.assertEqual(plan_classes(BOTH, GRADE_10), D('102'))
        # A Chapter Plan sells the Regular classes of the chapters chosen.
        self.assertEqual(plan_classes(CHAPTER_PLAN, GRADE_10, chosen=['c1', 'c3']), D('10'))
        self.assertEqual(plan_classes(CHAPTER_PLAN, GRADE_10, chosen=[]), D('0'))
        bridge = [{'regular_classes': None, 'revision_classes': None, 'bridge_classes': D('1')}] * 30
        self.assertEqual(plan_classes(BRIDGE, bridge), D('30'))

    def test_plain_numbers(self):
        self.assertEqual([plain(D(text)) for text in ('38.0', '1.5', '1330.00', '687.375', '0.0', '100')],
                         ['38', '1.5', '1330', '687.375', '0', '100'])


class ActivePricingTests(TestCase):
    def test_the_newest_version_in_effect_applies(self):
        self.assertIsNone(active_pricing())
        admin = get_user_model().objects.create_user(email='p@sales.test', username='p', password='x', role='ADMIN')
        now = timezone.now()
        first = PricingVersion.objects.create(
            version=1, currency='AED', standard_fee=D('45'), offer_fee=D('35'), effective_from=now - timedelta(days=9),
            created_by=admin,
        )
        second = PricingVersion.objects.create(
            version=2, currency='AED', standard_fee=D('50'), offer_fee=D('40'), effective_from=now - timedelta(days=1),
            created_by=admin,
        )
        self.assertEqual(active_pricing(), second)
        self.assertEqual(active_pricing(now - timedelta(days=5)), first)
        self.assertIsNone(active_pricing(now - timedelta(days=10)))
