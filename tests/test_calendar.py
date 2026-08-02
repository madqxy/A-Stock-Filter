from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from unittest.mock import patch

from cache import StockCache
from data_collector import get_trade_calendar

_CST = timezone(timedelta(hours=8))


def _cst(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=_CST)


@pytest.mark.parametrize("now,calendar,expected", [
    # Normal trading day, after close -> today
    (_cst(2026, 5, 6, 16, 0),
     {date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6)}, date(2026, 5, 6)),
    # Weekday public holiday (2026-05-01 Labour Day) after close -> prior trading day
    (_cst(2026, 5, 1, 16, 0),
     {date(2026, 4, 29), date(2026, 4, 30), date(2026, 5, 4)}, date(2026, 4, 30)),
    # Weekend rolling back across a public holiday -> 04-30, not 05-01
    (_cst(2026, 5, 3, 12, 0),
     {date(2026, 4, 29), date(2026, 4, 30), date(2026, 5, 4)}, date(2026, 4, 30)),
    # Intraday (before 15:00 close) -> previous trading day
    (_cst(2026, 5, 6, 10, 0),
     {date(2026, 5, 5), date(2026, 5, 6)}, date(2026, 5, 5)),
])
def test_latest_trade_date_is_holiday_aware(now, calendar, expected, tmp_path):
    cache = StockCache(base_dir=tmp_path)
    with patch("cache._now_cst", return_value=now):
        assert cache.latest_trade_date(calendar=calendar) == expected


def test_latest_trade_date_without_calendar_is_weekend_only(tmp_cache):
    # No calendar passed: weekend logic only, 2026-05-01 is a Friday so it is used.
    now = _cst(2026, 5, 1, 16, 0)
    with patch("cache._now_cst", return_value=now):
        assert tmp_cache.latest_trade_date() == date(2026, 5, 1)


def test_trade_calendar_save_load(tmp_cache):
    assert tmp_cache.load_trade_calendar() == set()
    dates = [date(2026, 4, 30), date(2026, 5, 6)]
    tmp_cache.save_trade_calendar(dates)
    assert tmp_cache.load_trade_calendar() == set(dates)


def test_get_trade_calendar_fetches_once_and_caches(tmp_cache):
    fake = pd.DataFrame({"trade_date": ["2026-05-04", "2026-05-05", "2026-05-06"]})
    with patch("data_collector.ak") as mock_ak:
        mock_ak.tool_trade_date_hist_sina.return_value = fake
        result = get_trade_calendar(tmp_cache)
    assert result == {date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6)}
    assert tmp_cache.load_trade_calendar() == result


def test_get_trade_calendar_reuses_cache_without_refetch(tmp_cache):
    tmp_cache.save_trade_calendar([date(2026, 5, 4)])
    with patch("data_collector.ak") as mock_ak:
        mock_ak.tool_trade_date_hist_sina.side_effect = AssertionError(
            "should not re-fetch when cache already has current year"
        )
        result = get_trade_calendar(tmp_cache)
    assert result == {date(2026, 5, 4)}


def test_get_trade_calendar_returns_none_on_fetch_failure(tmp_cache):
    with patch("data_collector.ak") as mock_ak:
        mock_ak.tool_trade_date_hist_sina.side_effect = ConnectionError("boom")
        result = get_trade_calendar(tmp_cache)
    assert result is None


def test_get_trade_calendar_force_refresh_refetches(tmp_cache):
    # force_refresh=True ignores the cached calendar and pulls fresh dates.
    tmp_cache.save_trade_calendar([date(2026, 5, 4)])
    fresh = pd.DataFrame({"trade_date": ["2026-05-05", "2026-05-06"]})
    with patch("data_collector.ak") as mock_ak:
        mock_ak.tool_trade_date_hist_sina.return_value = fresh
        result = get_trade_calendar(tmp_cache, force_refresh=True)
    assert result == {date(2026, 5, 5), date(2026, 5, 6)}