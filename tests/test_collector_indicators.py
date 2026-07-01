import pandas as pd
import numpy as np
import pytest
from data_collector import compute_indicators


def _make_kline(n: int, base_price: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame({
        "date":   [f"2025-{(i // 30 + 1):02d}-{(i % 28) + 1:02d}" for i in range(n)],
        "open":   base_price,
        "close":  [base_price + i * 0.01 for i in range(n)],
        "high":   base_price + 0.5,
        "low":    base_price - 0.5,
        "volume": 1_000_000.0,
    })


def test_ma20_none_when_insufficient_data():
    rt = pd.DataFrame({"代码": ["000001"], "名称": ["A"], "最新价": [10.0],
                       "涨跌幅": [1.0], "成交量": [1e6], "换手率": [0.5],
                       "市盈率-动态": [5.0], "市值": [1e9]})
    kline_map = {"000001": _make_kline(10)}
    df = compute_indicators(rt, kline_map)
    row = df.iloc[0]
    assert pd.isna(row["20日均价"])
    assert pd.isna(row["60日均价"])


def test_ma20_correct_when_exact_20():
    rt = pd.DataFrame({"代码": ["000001"], "名称": ["A"], "最新价": [10.0],
                       "涨跌幅": [1.0], "成交量": [1e6], "换手率": [0.5],
                       "市盈率-动态": [5.0], "市值": [1e9]})
    kline_map = {"000001": _make_kline(20, 100.0)}
    df = compute_indicators(rt, kline_map)
    closes = kline_map["000001"]["close"].iloc[-20:]
    expected = round(closes.mean(), 2)
    assert df.iloc[0]["20日均价"] == expected
    assert pd.isna(df.iloc[0]["60日均价"])


def test_turnover_extremes_calculated():
    rt = pd.DataFrame({"代码": ["000001"], "名称": ["A"], "最新价": [10.0],
                       "涨跌幅": [1.0], "成交量": [1_000_000.0],
                       "换手率": [1.0], "市盈率-动态": [5.0], "市值": [1e9]})
    kline_map = {"000001": _make_kline(30)}
    df = compute_indicators(rt, kline_map)
    assert df.iloc[0]["5日最高换手率"] is not None
    assert df.iloc[0]["5日最低换手率"] is not None


def test_empty_kline_returns_na_indicators():
    rt = pd.DataFrame({"代码": ["000001"], "名称": ["A"], "最新价": [10.0],
                       "涨跌幅": [1.0], "成交量": [None], "换手率": [None],
                       "市盈率-动态": [None], "市值": [None]})
    df = compute_indicators(rt, {})
    assert pd.isna(df.iloc[0]["20日均价"])
    assert pd.isna(df.iloc[0]["5日最高换手率"])
