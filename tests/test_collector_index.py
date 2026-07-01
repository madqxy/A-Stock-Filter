import pandas as pd
import pytest
from unittest.mock import patch
from data_collector import get_index_quotes, get_index_kline


def test_get_index_quotes_filters_by_code():
    fake = pd.DataFrame({
        "代码": ["000001", "399001", "000300", "000852", "999999"],
        "名称": ["上证", "深证", "沪深300", "中证1000", "其他"],
        "最新价": [3000.0, 10000.0, 3500.0, 6000.0, 100.0],
        "涨跌幅": [0.5, 1.0, -0.3, 0.2, 0.0],
    })
    with patch("data_collector.ak") as mock_ak:
        mock_ak.stock_zh_index_spot_em.return_value = fake
        df = get_index_quotes()
    assert len(df) == 4
    assert all(df["名称"].str.startswith("[指数]"))
    assert "000999" not in df["代码"].values


def test_get_index_kline_normalizes_columns():
    fake = pd.DataFrame({
        "date":  pd.date_range("2025-01-01", periods=5),
        "open":  [1.0]*5, "close": [2.0]*5,
        "high":  [3.0]*5, "low":   [0.5]*5,
        "volume": [100.0]*5,
    })
    with patch("data_collector.ak") as mock_ak:
        mock_ak.stock_zh_index_daily_em.return_value = fake
        df = get_index_kline("000300")
    assert list(df.columns) == ["date", "open", "close", "high", "low", "volume"]
