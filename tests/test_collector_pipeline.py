import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from data_collector import run_pipeline


_FUTURE_DATE = "2026-12-31"


def _fake_kline():
    return pd.DataFrame({
        "date":   pd.date_range(end=_FUTURE_DATE, periods=130, freq="B").strftime("%Y-%m-%d"),
        "open":   10.0, "close": 10.0, "high": 11.0, "low": 9.5, "volume": 1e6,
    })


def _fake_kline_bars():
    dates = pd.date_range(end=_FUTURE_DATE, periods=130, freq="B")
    return [
        [d.strftime("%Y-%m-%d"), "10.0", "10.0", "11.0", "9.5", "1000000"]
        for d in dates
    ]


def _make_mock_session():
    mock = MagicMock()

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        sym = url.split("param=")[1].split(",")[0]
        resp.json.return_value = {"data": {sym: {"qfqday": _fake_kline_bars()}}}
        return resp

    mock.get.side_effect = mock_get
    return mock


def test_run_pipeline_uses_cache_on_second_run(tmp_path):
    from cache import StockCache
    cache = StockCache(base_dir=tmp_path)

    fake_codes = ["000001", "600000"]
    fake_realtime = pd.DataFrame({
        "代码": fake_codes, "名称": ["A", "B"],
        "最新价": [10.0, 20.0], "涨跌幅": [1.0, 2.0],
        "成交量": [1e6, 2e6], "换手率": [0.5, 0.8],
        "市盈率-动态": [5.0, 6.0], "市值": [9e9, 10e9],
    })
    fake_index = pd.DataFrame({
        "代码": ["000001", "399001", "000300", "000852"],
        "名称": ["上证", "深证", "沪深300", "中证1000"],
        "最新价": [3000.0, 10000.0, 3500.0, 6000.0],
        "涨跌幅": [0.5, 1.0, -0.3, 0.2],
    })

    call_count = {"stock_list": 0, "realtime": 0, "hist": 0}

    def fake_stock_list():
        call_count["stock_list"] += 1
        return fake_codes

    def fake_realtime_fn(codes):
        call_count["realtime"] += 1
        return fake_realtime

    def fake_index_spot(**kwargs):
        return fake_index

    def fake_index_daily(symbol):
        return pd.DataFrame({
            "date":  pd.date_range("2025-01-01", periods=130, freq="B"),
            "open": 10.0, "close": 10.0, "high": 11.0, "low": 9.5, "volume": 1e6,
        })

    mock_session = _make_mock_session()

    def counting_get(url, **kwargs):
        call_count["hist"] += 1
        return mock_session.get(url, **kwargs)

    counting_session = MagicMock()
    counting_session.get.side_effect = counting_get

    with patch("data_collector.get_stock_list", side_effect=fake_stock_list), \
         patch("data_collector.get_realtime_quotes", side_effect=fake_realtime_fn), \
         patch("data_collector._http_session", return_value=counting_session), \
         patch("data_collector.ak") as mock_ak:
        mock_ak.stock_zh_index_spot_em.side_effect = fake_index_spot
        mock_ak.stock_zh_index_daily_em.side_effect = fake_index_daily
        result = run_pipeline(cache, force_refresh=True)
        assert len(result["all_data"]) == 4 + 2
        assert cache.completed_codes() == {"000001", "600000"}

        call_count["hist"] = 0
        result2 = run_pipeline(cache, force_refresh=False)
        # Allow 1 probe call to check for new trading day, but no full fetch
        assert call_count["hist"] <= 1
        assert len(result2["all_data"]) == 6
