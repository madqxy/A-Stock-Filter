import json
import pandas as pd
from unittest.mock import patch, MagicMock
import pytest


def _fake_kline_bars(n=130):
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    return [
        [d.strftime("%Y-%m-%d"), "10.0", "10.5", "11.0", "9.5", "1000000"]
        for d in dates
    ]


def _make_mock_session(bars=None):
    if bars is None:
        bars = _fake_kline_bars()
    mock = MagicMock()

    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        sym = url.split("param=")[1].split(",")[0]
        resp.json.return_value = {"data": {sym: {"qfqday": bars}}}
        return resp

    mock.get.side_effect = mock_get
    return mock


def test_get_kline_batch_returns_dict():
    with patch("data_collector._http_session", return_value=_make_mock_session()):
        from data_collector import get_kline_batch
        result = get_kline_batch({"000001": "20250101", "600000": "20250101"}, max_workers=2)
    assert set(result.keys()) == {"000001", "600000"}
    assert len(result["000001"]) == 130
    assert result["000001"]["close"].iloc[-1] == 10.5


def test_get_kline_batch_calls_on_success():
    with patch("data_collector._http_session", return_value=_make_mock_session()):
        from data_collector import get_kline_batch
        saved = []
        get_kline_batch(
            {"000001": "20250101"},
            on_success=lambda c, df: saved.append(c),
            max_workers=1,
        )
    assert saved == ["000001"]


def test_get_kline_batch_progress_callback():
    with patch("data_collector._http_session", return_value=_make_mock_session()):
        from data_collector import get_kline_batch
        progress = []
        get_kline_batch(
            {"000001": "20250101", "600000": "20250101"},
            progress_callback=lambda d, t, m: progress.append((d, t)),
            max_workers=2,
        )
    assert progress[-1] == (2, 2)


def test_market_prefix():
    from data_collector import _market_prefix
    assert _market_prefix("000001") == "sz"
    assert _market_prefix("600000") == "sh"
    assert _market_prefix("688001") == "sh"
    assert _market_prefix("300750") == "sz"
