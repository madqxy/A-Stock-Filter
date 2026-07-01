import pandas as pd
from unittest.mock import patch


def _fake_tencent_response(codes):
    """Mock Tencent batch API response for given codes."""
    rows = []
    for code in codes:
        rows.append({
            "代码": code,
            "名称": f"股票{code}",
            "最新价": 10.5,
            "涨跌幅": 1.5,
            "成交量": 1000000,
            "换手率": 0.5,
            "市盈率-动态": 5.2,
            "市值": 200e8,
        })
    return pd.DataFrame(rows)


def test_get_realtime_quotes_filters_and_normalizes():
    with patch("data_collector._fetch_realtime_tencent") as mock_fetch:
        mock_fetch.return_value = _fake_tencent_response(["000001", "600000"])
        from data_collector import get_realtime_quotes
        df = get_realtime_quotes(["000001", "600000"])
    assert len(df) == 2
    assert list(df["代码"]) == ["000001", "600000"]
    assert "市值" in df.columns


def test_get_realtime_quotes_progress_callback():
    with patch("data_collector._fetch_realtime_tencent") as mock_fetch:
        mock_fetch.return_value = _fake_tencent_response(["000001"])
        from data_collector import get_realtime_quotes
        progress = []
        get_realtime_quotes(["000001"], progress_callback=lambda d, t, m: progress.append(m))
    assert any("实时行情" in m for m in progress)
