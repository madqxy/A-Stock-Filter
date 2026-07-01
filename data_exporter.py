"""
Data export and filtering module.

Excel export uses xlsxwriter to keep numeric types numeric and apply
percentage / amount formats at the cell level (not string conversion).
"""
from datetime import datetime
from typing import Optional

import pandas as pd


_PCT_COLS = ["涨跌幅", "最新换手率", "5日换手率(高/低)", "20日换手率(高/低)"]
_AMOUNT_COLS = ["市值(亿)", "最新成交量(万手)", "5日平均成交量(万手)", "30日平均成交量(万手)"]
_PRICE_COLS = ["最新价", "5日均价", "20日均价", "60日均价", "120日均价"]
_VOLUME_COLS: list[str] = []


# Shared filter registry: display_name -> (internal_type, criteria_dict)
FILTER_REGISTRY: dict[str, tuple[str, dict]] = {
    "放量双金叉盈利":    ("volume_breakout_golden_profit", {"type": "volume_breakout_golden_profit", "volume_multiplier": 1.5, "pe_max": 150, "ma_window": 20, "vs_index": "csi300"}),
    "当前换手率20日最高": ("turnover_above_max",            {"type": "turnover_above_max", "window": 20, "vs_index": "csi300"}),
    "当前换手率20日最低": ("turnover_below_min",            {"type": "turnover_below_min", "window": 20, "vs_index": "csi300"}),
    "右侧拐点买入":      ("right_inflection_buy",          {"type": "right_inflection_buy", "volume_multiplier": 1.2, "vs_index": "csi300"}),
    "均线多头排列":      ("ma_bullish",                    {"type": "ma_bullish", "ma_short": 5, "ma_medium": 20, "ma_long": 60, "vs_index": "csi300"}),
    "放量突破":          ("volume_breakout",               {"type": "volume_breakout", "volume_multiplier": 1.5, "ma_window": 20, "vs_index": "csi300"}),
    "KDJ金叉":           ("kdj_golden_cross",              {"type": "kdj_golden_cross", "vs_index": "csi300"}),
    "MACD金叉":          ("macd_golden_cross",             {"type": "macd_golden_cross", "vs_index": "csi300"}),
}

DEFAULT_FILTER_NAME = "放量双金叉盈利"

def _build_format_map(df: pd.DataFrame) -> dict[str, str]:
    fmt: dict[str, str] = {}
    for c in df.columns:
        if c in _PCT_COLS:
            fmt[c] = '0.00"%"'
        elif c in _AMOUNT_COLS:
            fmt[c] = '#,##0.00'
        elif c in _PRICE_COLS:
            fmt[c] = '0.00'
        elif c in _VOLUME_COLS:
            fmt[c] = '#,##0'
    return fmt


def _to_display_df(df: pd.DataFrame, map_yn: bool = False) -> pd.DataFrame:
    """Prepare a DataFrame for display/export:
    - merge 5/10日换手率 高/低 into a single "高/低" column
    - drop 20/30/60日 turnover extremes (keep data for filtering, hide from display)
    - optionally map KDJ/MACD booleans to 是/否 (GUI-friendly)
    """
    ddf = df.copy()
    cols_5 = ["5日最高换手率", "5日最低换手率"]
    cols_10 = ["10日最高换手率", "10日最低换手率"]
    cols_20 = ["20日最高换手率", "20日最低换手率"]
    cols_30 = ["30日最高换手率", "30日最低换手率"]
    cols_60 = ["60日最高换手率", "60日最低换手率"]
    if all(c in ddf.columns for c in cols_5):
        ddf["5日换手率(高/低)"] = ddf.apply(
            lambda r: f"{r['5日最高换手率']:.2f}/{r['5日最低换手率']:.2f}"
            if pd.notna(r["5日最高换手率"]) else "", axis=1)
    if all(c in ddf.columns for c in cols_10):
        ddf["10日换手率(高/低)"] = ddf.apply(
            lambda r: f"{r['10日最高换手率']:.2f}/{r['10日最低换手率']:.2f}"
            if pd.notna(r["10日最高换手率"]) else "", axis=1)
    drop = [c for c in cols_5 + cols_10 + cols_20 + cols_30 + cols_60 if c in ddf.columns]
    ddf = ddf.drop(columns=drop)
    if map_yn:
        for c in ["KDJ金叉", "MACD金叉"]:
            if c in ddf.columns:
                ddf[c] = ddf[c].map(lambda x: "是" if x else "否")
    return ddf


def export_to_excel(
    df: pd.DataFrame,
    filepath: Optional[str] = None,
    sheet_name: str = "Sheet1",
) -> str:
    """Export DataFrame to Excel with xlsxwriter (preserves numeric types)."""
    if filepath is None:
        filepath = f"stock_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = str(filepath)
    df = _to_display_df(df)
    format_map = _build_format_map(df)
    with pd.ExcelWriter(filepath, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        wb = writer.book
        ws = writer.sheets[sheet_name]
        for idx, col in enumerate(df.columns):
            width = max(12, min(28, len(str(col)) * 2 + 4))
            ws.set_column(idx, idx, width)
            if col in format_map:
                cell_fmt = wb.add_format({"num_format": format_map[col]})
                ws.set_column(idx, idx, width, cell_fmt)
    return filepath


# Index code mapping for vs_index parameter
INDEX_CODE_MAP = {
    "csi300": "000300",      # 沪深300
    "csi500": "000905",      # 中证500
    "csi1000": "000852",     # 中证1000
    "sh000001": "000001",    # 上证指数
    "sz399001": "399001",    # 深证成指
    "star50": "000688",      # 科创50
    "chinext": "399006",     # 创业板指数
}


def _get_index_change(df: pd.DataFrame, index_code: str = "000300") -> float:
    """Get index change by code. Default to 沪深300 (000300)."""
    row = df[df["代码"] == index_code]
    if row.empty:
        return 0.0
    val = row.iloc[0]["涨跌幅"]
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _is_index_row(s: pd.Series) -> bool:
    return "[指数]" in str(s.get("名称", ""))


def filter_stocks(
    df: pd.DataFrame,
    criteria: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Unified filter entry.
    criteria = {
        "type": "price_below_ma" | "turnover_above_max" | "turnover_below_min",
        "ma_window": 20,    # for price_below_ma
        "window": 20,        # for turnover_*
        "vs_index": "csi300" # 对比基准
    }
    """
    criteria = criteria or {"type": "volume_breakout_golden_profit", "vs_index": "csi300"}
    vs_index = criteria.get("vs_index", "csi300")
    index_code = INDEX_CODE_MAP.get(vs_index, "000300")
    index_change = _get_index_change(df, index_code)

    stock_df = df[~df.apply(_is_index_row, axis=1)].copy()
    ftype = criteria["type"]

    if ftype == "volume_breakout_golden_profit":
        vol_mult = criteria.get("volume_multiplier", 1.5)
        pe_max = criteria.get("pe_max", 150)
        ma_win = criteria.get("ma_window", 20)
        ma_col = f"{ma_win}日均价"
        stock_df = stock_df.dropna(subset=["最新价", ma_col, "最新成交量(万手)", "5日平均成交量(万手)",
                                           "KDJ金叉", "MACD金叉", "市盈率(TTM)", "涨跌幅"])
        cond = (stock_df["最新价"] > stock_df[ma_col]) \
               & (stock_df["最新成交量(万手)"] > stock_df["5日平均成交量(万手)"] * vol_mult) \
               & stock_df["KDJ金叉"] & stock_df["MACD金叉"] \
               & (stock_df["市盈率(TTM)"] > 0) & (stock_df["市盈率(TTM)"] < pe_max) \
               & (stock_df["涨跌幅"] > index_change)
        msg = f"放量突破{vol_mult}倍+双金叉+市盈率0~{pe_max}+价>MA{ma_win} 且 涨幅>{index_change:.2f}%(基准)"
    elif ftype == "turnover_above_max":
        win = criteria.get("window", 20)
        col = f"{win}日最高换手率"
        stock_df = stock_df.dropna(subset=[col, "最新换手率", "涨跌幅"])
        cond = (stock_df["最新换手率"] >= stock_df[col]) & (stock_df["涨跌幅"] > index_change)
        msg = f"当前换手率为近{win}日最高 且 涨幅>{index_change:.2f}%(基准)"
    elif ftype == "turnover_below_min":
        win = criteria.get("window", 20)
        col = f"{win}日最低换手率"
        stock_df = stock_df.dropna(subset=[col, "最新换手率", "涨跌幅"])
        cond = (stock_df["最新换手率"] <= stock_df[col]) & (stock_df["涨跌幅"] > index_change)
        msg = f"当前换手率为近{win}日最低 且 涨幅>{index_change:.2f}%(基准)"
    elif ftype == "ma_bullish":
        ma_short = criteria.get("ma_short", 5)
        ma_medium = criteria.get("ma_medium", 20)
        ma_long = criteria.get("ma_long", 60)
        col_short = f"{ma_short}日均价"
        col_medium = f"{ma_medium}日均价"
        col_long = f"{ma_long}日均价"
        stock_df = stock_df.dropna(subset=[col_short, col_medium, col_long, "涨跌幅"])
        cond = (stock_df[col_short] > stock_df[col_medium]) & (stock_df[col_medium] > stock_df[col_long]) & (stock_df["涨跌幅"] > index_change)
        msg = f"均线多头排列(MA{ma_short}>MA{ma_medium}>MA{ma_long}) 且 涨幅>{index_change:.2f}%(基准)"
    elif ftype == "volume_breakout":
        mult = criteria.get("volume_multiplier", 1.5)
        ma_win = criteria.get("ma_window", 20)
        ma_col = f"{ma_win}日均价"
        stock_df = stock_df.dropna(subset=["最新价", ma_col, "最新成交量(万手)", "5日平均成交量(万手)", "涨跌幅"])
        cond = (stock_df["最新价"] > stock_df[ma_col]) & (stock_df["最新成交量(万手)"] > stock_df["5日平均成交量(万手)"] * mult) & (stock_df["涨跌幅"] > index_change)
        msg = f"放量突破(量>{mult}倍均量,价>MA{ma_win}) 且 涨幅>{index_change:.2f}%(基准)"
    elif ftype == "kdj_golden_cross":
        stock_df = stock_df.dropna(subset=["KDJ金叉", "涨跌幅"])
        cond = stock_df["KDJ金叉"] & (stock_df["涨跌幅"] > index_change)
        msg = f"KDJ金叉 且 涨幅>{index_change:.2f}%(基准)"
    elif ftype == "right_inflection_buy":
        vol_mult = criteria.get("volume_multiplier", 1.2)
        stock_df = stock_df.dropna(subset=["最新价", "20日均价", "5日均价",
                                           "最新成交量(万手)", "5日平均成交量(万手)",
                                           "KDJ金叉", "MACD金叉", "涨跌幅"])
        cond = (stock_df["最新价"] > stock_df["20日均价"]) \
               & (stock_df["5日均价"] > stock_df["20日均价"]) \
               & (stock_df["最新成交量(万手)"] > stock_df["5日平均成交量(万手)"] * vol_mult) \
               & (stock_df["KDJ金叉"] | stock_df["MACD金叉"]) \
               & (stock_df["涨跌幅"] > index_change)
        msg = f"右侧拐点买入(价站MA20+MA5>MA20+量>{vol_mult}倍均量+单金叉) 且 涨幅>{index_change:.2f}%(基准)"
    elif ftype == "macd_golden_cross":
        stock_df = stock_df.dropna(subset=["MACD金叉", "涨跌幅"])
        cond = stock_df["MACD金叉"] & (stock_df["涨跌幅"] > index_change)
        msg = f"MACD金叉 且 涨幅>{index_change:.2f}%(基准)"
    else:
        raise ValueError(f"Unknown filter type: {ftype}")

    filtered = stock_df[cond]
    print(f"[筛选] {msg}: {len(filtered)} 只")
    return filtered.reset_index(drop=True)


def filter_export(
    filtered_df: pd.DataFrame,
    filepath: Optional[str] = None,
    filter_type: str = "filtered",
) -> str:
    if filepath is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"{filter_type}_{ts}.xlsx"
    return export_to_excel(filtered_df, filepath, sheet_name=filter_type)
