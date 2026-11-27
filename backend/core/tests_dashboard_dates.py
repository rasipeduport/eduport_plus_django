"""The dashboards' shared dates (core.dashboard_dates): one span read the same way, filtered and bucketed the same way, in IST."""
from datetime import date, datetime, timezone as dt_timezone

from django.test import SimpleTestCase

from core import dashboard_dates as dates

# 20:00 UTC on 26 Nov is 01:30 on 27 Nov in India: "today" is the Indian date.
NOW = datetime(2026, 11, 26, 20, 0, tzinfo=dt_timezone.utc)
TODAY = date(2026, 11, 27)


class ReadSpanTests(SimpleTestCase):
    def test_presets_custom_and_all_time(self):
        self.assertEqual(dates.read_span({}, NOW), ((date(2026, 11, 21), TODAY), []))
        self.assertEqual(dates.read_span({'from': '2024-01-01', 'to': '2026-11-27'}, NOW), ((date(2024, 1, 1), TODAY), []))
        self.assertEqual(dates.read_span({'from': '2026-11-27', 'to': '2026-11-27'}, NOW), ((TODAY, TODAY), []))
        # All Time has no first date at all, not an early one.
        self.assertEqual(dates.read_span({'range': 'all'}, NOW), ((None, TODAY), []))

    def test_what_is_refused_is_named(self):
        cases = [
            ({'from': '2026-11-27'}, ['to']),
            ({'to': '2026-11-27'}, ['from']),
            ({'from': '2026-11-28', 'to': '2026-11-27'}, ['to']),
            ({'from': '27-11-2026', 'to': '2026-11-31'}, ['from', 'to']),
            ({'from': '0202-01-01', 'to': '2026-11-27'}, ['from']),
            ({'from': '2026-01-01', 'to': '2100-01-01'}, ['to']),
            ({'range': '30d'}, ['range']),
            ({'range': ''}, ['range']),
            ({'range': 'all', 'from': '2026-11-01'}, ['range']),
        ]
        for params, invalid in cases:
            with self.subTest(params=params):
                self.assertEqual(dates.read_span(params, NOW), ((None, None), invalid))


class FilterTests(SimpleTestCase):
    def test_instants_are_cut_at_indian_midnight_and_all_time_has_no_lower_bound(self):
        bounded = dates.instant_on_dates('created_at', date(2026, 11, 1), TODAY)
        self.assertEqual(dict(bounded.children), {
            'created_at__lt': datetime(2026, 11, 27, 18, 30, tzinfo=dt_timezone.utc),
            'created_at__gte': datetime(2026, 10, 31, 18, 30, tzinfo=dt_timezone.utc),
        })
        self.assertEqual(dict(dates.instant_on_dates('created_at', None, TODAY).children),
                         {'created_at__lt': datetime(2026, 11, 27, 18, 30, tzinfo=dt_timezone.utc)})
        self.assertEqual(dict(dates.date_on_dates('payment_date', None, TODAY).children), {'payment_date__lte': TODAY})

    def test_shown_range(self):
        self.assertEqual(dates.shown_range(None, TODAY, date(2024, 3, 9)), {'from': '2024-03-09', 'to': '2026-11-27', 'all_time': True})
        self.assertEqual(dates.shown_range(None, TODAY), {'from': None, 'to': '2026-11-27', 'all_time': True})
        self.assertEqual(dates.shown_range(TODAY, TODAY), {'from': '2026-11-27', 'to': '2026-11-27', 'all_time': False})


class BucketTests(SimpleTestCase):
    def test_units_grow_with_the_span_and_buckets_are_cut_to_it(self):
        for first, unit, count in ((date(2026, 10, 28), 'day', 31), (date(2026, 6, 1), 'week', 26),
                                   (date(2025, 1, 1), 'month', 23), (date(2024, 11, 20), 'year', 3)):
            with self.subTest(first=first):
                got_unit, buckets = dates.trend_buckets(first, TODAY)
                self.assertEqual((got_unit, len(buckets)), (unit, count))
                self.assertEqual((buckets[0][1], buckets[-1][2]), (first, TODAY))
        _unit, years = dates.trend_buckets(date(2024, 11, 20), TODAY)
        self.assertEqual([(start, last) for _start, start, last in years],
                         [(date(2024, 11, 20), date(2024, 12, 31)), (date(2025, 1, 1), date(2025, 12, 31)), (TODAY.replace(month=1, day=1), TODAY)])
        self.assertEqual(dates.bucket_start(date(2026, 11, 27), 'week'), date(2026, 11, 23))
