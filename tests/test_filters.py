import pandas as pd
import pytest
from data_exporter import filter_stocks, resolve_filter, DEFAULT_FILTER_NAME


def test_resolve_filter_by_display_name():
    ftype, criteria = resolve_filter("右侧买入")
    assert ftype == "right_buy"
    assert criteria["type"] == "right_buy"


def test_resolve_filter_by_internal_type():
    ftype, criteria = resolve_filter("ma_bullish")
    assert ftype == "ma_bullish"
    assert criteria["type"] == "ma_bullish"


def test_resolve_filter_unknown_falls_back_to_default():
    ftype, criteria = resolve_filter("volume_breakout_golden_profit")
    default_ftype = {"右侧买入": "right_buy"}[DEFAULT_FILTER_NAME]
    assert ftype == default_ftype
    assert criteria["type"] == default_ftype


def test_resolve_filter_returns_copy_of_criteria():
    _, criteria = resolve_filter("right_buy")
    criteria["pe_max"] = 1
    _, criteria2 = resolve_filter("right_buy")
    assert criteria2["pe_max"] != 1



def _df(include_csi300=True, include_stocks=True):
    rows = []
    if include_csi300:
        rows.append({"代码": "000300", "名称": "[指数] 沪深300",
                     "最新价": 3500, "涨跌幅": 1.0,
                     "20日均价": 3400, "20日最高换手率": 0.8,
                     "20日最低换手率": 0.2, "最新换手率": 0.5,
                     "市盈率(TTM)": 12.0, "30日均价": 3400})
    if include_stocks:
        rows.append({"代码": "000001", "名称": "A",
                     "最新价": 11.0, "涨跌幅": 2.0,
                     "20日均价": 10.0, "20日最高换手率": 0.6,
                     "20日最低换手率": 0.3, "最新换手率": 0.7,
                     "5日均价": 10.5, "60日均价": 8.0,
                     "最新成交量(万手)": 2.0, "5日平均成交量(万手)": 1.0,
                     "KDJ金叉": True, "MACD金叉": True,
                     "市盈率(TTM)": 15.0})
        rows.append({"代码": "600000", "名称": "B",
                     "最新价": 10.0, "涨跌幅": 0.5,
                     "20日均价": 11.0, "20日最高换手率": 0.6,
                     "20日最低换手率": 0.3, "最新换手率": 0.7,
                     "5日均价": 10.0, "60日均价": 9.0,
                     "最新成交量(万手)": 2.0, "5日平均成交量(万手)": 1.0,
                     "KDJ金叉": True, "MACD金叉": True,
                     "市盈率(TTM)": 15.0})
    return pd.DataFrame(rows)


def test_filter_right_buy_both_mode():
    df = _df()
    result = filter_stocks(df, {"type": "right_buy", "golden_mode": "both"})
    assert list(result["代码"]) == ["000001"]


def test_filter_handles_negative_csi300():
    df = _df()
    df.loc[df["代码"] == "000300", "涨跌幅"] = -2.0
    result = filter_stocks(df, {"type": "right_buy", "golden_mode": "both"})
    assert "000001" in list(result["代码"])


def test_filter_excludes_index_rows():
    df = _df()
    result = filter_stocks(df, {"type": "right_buy", "golden_mode": "both"})
    assert "000300" not in list(result["代码"])
    assert not any("[指数]" in str(n) for n in result["名称"].tolist())


def test_filter_empty_when_no_csi300():
    df = _df(include_csi300=False)
    result = filter_stocks(df, {"type": "right_buy", "golden_mode": "both"})
    assert "000001" in list(result["代码"])


def test_filter_requires_pe_positive():
    df = _df()
    df.loc[df["代码"] == "000001", "市盈率(TTM)"] = -5.0
    result = filter_stocks(df, {"type": "right_buy", "golden_mode": "both"})
    assert "000001" not in list(result["代码"])


def test_filter_requires_both_golden():
    df = _df()
    df.loc[df["代码"] == "000001", "KDJ金叉"] = False
    result = filter_stocks(df, {"type": "right_buy", "golden_mode": "both"})
    assert "000001" not in list(result["代码"])


def test_filter_right_buy_either_mode():
    df = pd.DataFrame([
        {"代码": "000300", "名称": "[指数] 沪深300", "涨跌幅": 1.0},
        {"代码": "000001", "名称": "A", "涨跌幅": 2.0,
         "最新价": 11.0, "20日均价": 10.0, "5日均价": 10.5,
         "最新成交量(万手)": 2.0, "5日平均成交量(万手)": 1.0,
         "KDJ金叉": False, "MACD金叉": True,
         "市盈率(TTM)": 15.0},
    ])
    result = filter_stocks(df, {"type": "right_buy", "golden_mode": "either"})
    assert "000001" in list(result["代码"])


def test_filter_ma_bullish():
    df = pd.DataFrame([
        {"代码": "000300", "名称": "[指数] 沪深300", "涨跌幅": 1.0},
        {"代码": "000001", "名称": "A", "涨跌幅": 2.0,
         "5日均价": 11.0, "20日均价": 10.0, "60日均价": 9.0},
        {"代码": "600000", "名称": "B", "涨跌幅": 0.5,
         "5日均价": 10.0, "20日均价": 11.0, "60日均价": 9.0},
    ])
    result = filter_stocks(df, {"type": "ma_bullish"})
    assert "000001" in list(result["代码"])
    assert "600000" not in list(result["代码"])


def test_filter_volume_breakout():
    df = pd.DataFrame([
        {"代码": "000300", "名称": "[指数] 沪深300", "涨跌幅": 1.0},
        {"代码": "000001", "名称": "A", "涨跌幅": 2.0,
         "最新价": 11.0, "20日均价": 10.0,
         "最新成交量(万手)": 2.0, "5日平均成交量(万手)": 1.0},
        {"代码": "600000", "名称": "B", "涨跌幅": 0.5,
         "最新价": 10.0, "20日均价": 11.0,
         "最新成交量(万手)": 2.0, "5日平均成交量(万手)": 1.0},
    ])
    result = filter_stocks(df, {"type": "volume_breakout", "volume_multiplier": 1.5})
    assert "000001" in list(result["代码"])
    assert "600000" not in list(result["代码"])


def test_filter_volume_breakout_multiplier():
    df = pd.DataFrame([
        {"代码": "000300", "名称": "[指数] 沪深300", "涨跌幅": 1.0},
        {"代码": "000001", "名称": "A", "涨跌幅": 2.0,
         "最新价": 11.0, "20日均价": 10.0,
         "最新成交量(万手)": 0.2, "5日平均成交量(万手)": 1.0},
    ])
    result = filter_stocks(df, {"type": "volume_breakout", "volume_multiplier": 0.1})
    assert "000001" in list(result["代码"])


def test_filter_stabilize_volume_shrink_no_downtrend():
    """Test stabilize_volume_shrink without downtrend requirement."""
    df = pd.DataFrame([
        {"代码": "000300", "名称": "[指数] 沪深300", "涨跌幅": 1.0},
        {"代码": "000001", "名称": "A", "涨跌幅": 0.5,
         "最新价": 11.0, "20日均价": 10.0,
         "10日最大日波幅": 2.0,
         "最新成交量(万手)": 0.5, "5日平均成交量(万手)": 1.0,
         "市盈率(TTM)": 15.0},
    ])
    # Without downtrend requirement, should pass even though price > MA
    result = filter_stocks(df, {"type": "stabilize_volume_shrink", "require_downtrend": False})
    assert "000001" in list(result["代码"])


def test_filter_stabilize_volume_shrink_with_downtrend():
    """Test stabilize_volume_shrink with downtrend requirement."""
    df = pd.DataFrame([
        {"代码": "000300", "名称": "[指数] 沪深300", "涨跌幅": 1.0},
        {"代码": "000001", "名称": "A", "涨跌幅": 0.5,
         "最新价": 11.0, "20日均价": 10.0,
         "10日最大日波幅": 2.0,
         "最新成交量(万手)": 0.5, "5日平均成交量(万手)": 1.0,
         "市盈率(TTM)": 15.0},
        {"代码": "600000", "名称": "B", "涨跌幅": 0.5,
         "最新价": 9.0, "20日均价": 10.0,
         "10日最大日波幅": 2.0,
         "最新成交量(万手)": 0.5, "5日平均成交量(万手)": 1.0,
         "市盈率(TTM)": 15.0},
    ])
    # With downtrend requirement, only B should pass (price < MA)
    result = filter_stocks(df, {"type": "stabilize_volume_shrink", "require_downtrend": True})
    assert "000001" not in list(result["代码"])
    assert "600000" in list(result["代码"])


def test_filter_stall_volume_drop():
    """Test stall_volume_drop filter - bearish reversal signal with death cross."""
    df = pd.DataFrame([
        {"代码": "000300", "名称": "[指数] 沪深300", "涨跌幅": 1.0},
        # A: 止涨放量下跌 - death cross, price < MA20, change < 0, high volume
        {"代码": "000001", "名称": "A", "涨跌幅": -2.0,
         "最新价": 9.0, "5日均价": 9.5, "20日均价": 10.0,
         "最新成交量(万手)": 2.0, "5日平均成交量(万手)": 1.0,
         "KDJ死叉": True, "MACD死叉": False},
        # B: 正常下跌但缩量 - should not pass
        {"代码": "600000", "名称": "B", "涨跌幅": -1.0,
         "最新价": 9.0, "5日均价": 9.5, "20日均价": 10.0,
         "最新成交量(万手)": 0.5, "5日平均成交量(万手)": 1.0,
         "KDJ死叉": True, "MACD死叉": True},
        # C: 放量上涨 - should not pass
        {"代码": "000002", "名称": "C", "涨跌幅": 2.0,
         "最新价": 11.0, "5日均价": 10.5, "20日均价": 10.0,
         "最新成交量(万手)": 2.0, "5日平均成交量(万手)": 1.0,
         "KDJ死叉": False, "MACD死叉": False},
        # D: 死叉+放量下跌但价格>MA - should not pass
        {"代码": "000003", "名称": "D", "涨跌幅": -2.0,
         "最新价": 11.0, "5日均价": 10.5, "20日均价": 10.0,
         "最新成交量(万手)": 2.0, "5日平均成交量(万手)": 1.0,
         "KDJ死叉": True, "MACD死叉": True},
    ])
    result = filter_stocks(df, {"type": "stall_volume_drop", "volume_multiplier": 1.5})
    # Only A should pass: death cross, price < MA20, change < 0, volume > 1.5 * avg
    assert "000001" in list(result["代码"])
    assert "600000" not in list(result["代码"])  # volume too low
    assert "000002" not in list(result["代码"])  # no death cross, price going up
    assert "000003" not in list(result["代码"])  # price > MA
