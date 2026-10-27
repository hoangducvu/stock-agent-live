"""Market-data regressions using fake broker bars; no network or orders."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pandas as pd
from alpaca_trade_api.entity import Bar
from data_feed import DataFeed, _bar_timestamp
from utils import ET


def stamp(value):
    return pd.Timestamp(value, tz=ET)


def bar(value, price=100):
    return Bar(dict(t=stamp(value).tz_convert('UTC').isoformat(),
                    o=price, h=price + 1, l=price - 1, c=price, v=100))


def frame(times, prices=None):
    prices = prices if prices is not None else [100] * len(times)
    return pd.DataFrame([dict(Open=p, High=p+1, Low=p-1, Close=p, Volume=100)
                         for p in prices], index=pd.DatetimeIndex([stamp(t) for t in times]))


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.feed = DataFeed(self.api)
        self.feed.log = Mock()
        self.now = stamp('2026-10-26 10:07').to_pydatetime()
        self.clock = patch('data_feed.now_et', return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.feed.bars_daily['META'] = pd.DataFrame(
            {'Close': [95., 100., 500.]},
            index=pd.to_datetime(['2026-10-22', '2026-10-23', '2026-10-26']))

    def opening_frame(self):
        return frame(['2026-10-26 08:00', '2026-10-26 09:30', '2026-10-26 09:35'],
                     [130, 102, 104])

    def test_gap_uses_friday_close_and_monday_regular_open(self):
        self.feed.bars_5m['META'] = self.opening_frame()
        self.feed.calculate_gaps(['META'])
        self.assertAlmostEqual(self.feed.gaps['META'], .02)
        details = self.feed.gap_details['META']
        self.assertEqual(details['previous_close_date'], '2026-10-23')
        self.assertEqual(details['previous_close'], 100)
        self.assertEqual(details['opening_price'], 102)
        self.assertIn('09:30:00-04:00', details['opening_timestamp'])

    def test_gap_does_not_substitute_later_or_premarket_bar(self):
        self.feed.bars_5m['META'] = self.opening_frame().drop(stamp('2026-10-26 09:30'))
        self.feed.calculate_gaps(['META'])
        self.assertNotIn('META', self.feed.gaps)

    def test_gap_not_available_before_opening_bar_completes(self):
        self.feed.bars_5m['META'] = self.opening_frame()
        with patch('data_feed.now_et', return_value=stamp('2026-10-26 09:33')):
            self.feed.calculate_gaps(['META'])
        self.assertEqual(self.feed.gaps, {})

    def test_gap_ignores_unordered_daily_rows_and_invalid_prices(self):
        self.feed.bars_5m['META'] = self.opening_frame()
        self.feed.bars_daily['META'] = self.feed.bars_daily['META'].iloc[::-1]
        self.feed.calculate_gaps(['META'])
        self.assertAlmostEqual(self.feed.gaps['META'], .02)
        for invalid in [0, -1, float('nan'), float('inf')]:
            self.feed.bars_daily['META'].loc[pd.Timestamp('2026-10-23'), 'Close'] = invalid
            self.feed.calculate_gaps(['META'])
            self.assertNotIn('META', self.feed.gaps)

    def test_new_day_clears_old_gaps(self):
        self.feed.bars_5m['META'] = self.opening_frame()
        self.feed.calculate_gaps(['META'])
        with patch('data_feed.now_et', return_value=stamp('2026-10-27 09:00')):
            self.feed.calculate_gaps(['META'])
        self.assertEqual(self.feed.gaps, {})
        self.assertEqual(self.feed.gap_details, {})

    def test_gap_accepts_utc_intraday_index(self):
        self.feed.bars_5m['META'] = self.opening_frame().tz_convert('UTC')
        self.feed.calculate_gaps(['META'])
        self.assertAlmostEqual(self.feed.gaps['META'], .02)

    def test_string_and_epoch_timestamps_without_sdk_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            parsed = _bar_timestamp(bar('2026-10-26 09:30'))
            epoch = _bar_timestamp(Bar({'t': parsed.timestamp()}))
        self.assertEqual(parsed, stamp('2026-10-26 09:30'))
        self.assertEqual(epoch, parsed)

    def test_historical_5m_excludes_partial_bar_and_sorts(self):
        self.api.get_bars.return_value = [bar('2026-10-26 10:05', 110),
                                          bar('2026-10-26 10:00', 102),
                                          bar('2026-10-26 09:55', 101)]
        self.feed._download_5m('META')
        self.assertEqual(self.feed.bars_5m['META'].index[-1], stamp('2026-10-26 10:00'))
        self.assertEqual(self.feed.last_prices['META'], 102)
        self.assertLess(pd.Timestamp(self.api.get_bars.call_args.kwargs['end']), stamp('2026-10-26 10:05'))

    def test_historical_daily_excludes_current_day(self):
        self.api.get_bars.return_value = [bar('2026-10-26 00:00', 500),
                                          bar('2026-10-23 00:00', 100)]
        self.feed._download_daily('META')
        self.assertEqual(list(self.feed.bars_daily['META'].index.date), [stamp('2026-10-23').date()])

    def test_downloads_use_actual_winter_timezone(self):
        self.api.get_bars.return_value = []
        with patch('data_feed.now_et', return_value=stamp('2026-12-07 10:07')):
            self.feed._download_5m('META')
            self.assertTrue(self.api.get_bars.call_args.kwargs['end'].endswith('-05:00'))
            self.feed._download_daily('META')
            self.assertTrue(self.api.get_bars.call_args.kwargs['end'].endswith('-05:00'))

    def test_poll_backfills_all_missing_completed_bars(self):
        self.feed.bars_5m['META'] = frame(['2026-10-26 09:50'])
        self.api.get_bars.return_value = [bar('2026-10-26 10:05', 110),
                                          bar('2026-10-26 10:00', 103),
                                          bar('2026-10-26 09:55', 102)]
        result = self.feed.poll_latest_bars(['META'])
        self.assertEqual([r[1]['Datetime'] for r in result],
                         [stamp('2026-10-26 09:55'), stamp('2026-10-26 10:00')])
        params = self.api.get_bars.call_args.kwargs
        self.assertEqual(params['sort'], 'asc')
        self.assertEqual(pd.Timestamp(params['start']), stamp('2026-10-26 09:55'))
        self.assertLess(pd.Timestamp(params['end']), stamp('2026-10-26 10:05'))
        self.assertEqual(self.feed.last_prices['META'], 103)

    def test_poll_duplicate_response_cannot_duplicate_rows(self):
        self.feed.bars_5m['META'] = frame(['2026-10-26 10:00'])
        self.api.get_bars.return_value = [bar('2026-10-26 10:00')]
        self.assertEqual(self.feed.poll_latest_bars(['META']), [])
        self.assertEqual(len(self.feed.bars_5m['META']), 1)

    def test_backfill_cannot_rewind_latest_price_or_duplicate_index(self):
        self.feed.bars_5m['META'] = frame(['2026-10-26 10:00'], [120])
        self.feed.append_bar('META', dict(Datetime=stamp('2026-10-26 09:30'),
                                         Open=100, High=101, Low=99, Close=100, Volume=100))
        self.feed.append_bar('META', dict(Datetime=stamp('2026-10-26 09:30'),
                                         Open=100, High=102, Low=98, Close=101, Volume=200))
        self.assertEqual(self.feed.last_prices['META'], 120)
        self.assertTrue(self.feed.bars_5m['META'].index.is_unique)
        self.assertTrue(self.feed.bars_5m['META'].index.is_monotonic_increasing)

    def test_opening_range_excludes_premarket_and_post_10am(self):
        times = ['2026-10-26 09:25'] + [f'2026-10-26 09:{m}' for m in [30,35,40,45,50,55]] + ['2026-10-26 10:00']
        self.feed.bars_5m['META'] = frame(times, [500] + [100]*6 + [600]).iloc[::-1]
        self.feed.compute_opening_ranges(['META'])
        self.assertEqual(self.feed.opening_ranges['META'], dict(high=101, low=99))

    def test_opening_range_requires_all_six_slots(self):
        self.feed.bars_5m['META'] = frame([f'2026-10-26 09:{m}' for m in [25,30,35,40,45,50]])
        self.feed.compute_opening_ranges(['META'])
        self.assertEqual(self.feed.opening_ranges, {})
        self.api.get_bars.return_value = [bar('2026-10-26 09:55')]
        self.feed.download_opening_range_bars(['META'])
        self.feed.compute_opening_ranges(['META'])
        self.assertIn('META', self.feed.opening_ranges)
        params = self.api.get_bars.call_args.kwargs
        self.assertEqual(pd.Timestamp(params['start']), stamp('2026-10-26 09:30'))
        self.assertLess(pd.Timestamp(params['end']), stamp('2026-10-26 10:00'))

    def test_opening_range_not_ready_before_10am(self):
        self.feed.bars_5m['META'] = frame([f'2026-10-26 09:{m}' for m in [30,35,40,45,50,55]])
        with patch('data_feed.now_et', return_value=stamp('2026-10-26 09:59')):
            self.feed.download_opening_range_bars(['META'])
            self.feed.compute_opening_ranges(['META'])
        self.api.get_bars.assert_not_called()
        self.assertEqual(self.feed.opening_ranges, {})


if __name__ == '__main__':
    unittest.main()
