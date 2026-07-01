"""
A-stock data collection pipeline (5 stages).

Stage 1: get_stock_list — list of A-share codes via akshare
Stage 2: get_realtime_quotes — full-market realtime via akshare
Stage 3: get_kline_batch — historical K-line per stock, parallel, cached
Stage 4: compute_indicators — MA20/60/120, volume MA, turnover extremes
Stage 5: handled by data_exporter
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Callable, Optional
import time

import akshare as ak
import numpy as np
import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type,
)
import requests


ProgressCB = Optional[Callable[[int, int, str], None]]
_KLINE_COLS = ["date", "open", "close", "high", "low", "volume"]

# compute_indicators needs at least 120 bars for 120日均线.
# We fetch up to ~168 bars per request (Tencent API limit).
# First run uses a wide date range to ensure enough data; incremental runs add bars over time.
_KLINE_FETCH_WIDE_DAYS = 200   # first run: covers ~140 trading days


def get_stock_list(progress_callback: ProgressCB = None) -> list[str]:
    """
    Fetch A-share code/name list via akshare.
    Returns list of 6-digit codes (no market prefix).
    """
    df = ak.stock_info_a_code_name()
    codes = df["code"].astype(str).str.zfill(6).tolist()
    if progress_callback:
        progress_callback(len(codes), len(codes), f"获取股票清单: {len(codes)} 只")
    return codes


def _fetch_realtime_tencent(codes: list[str]) -> pd.DataFrame:
    """Fetch realtime quotes from Tencent batch API (qt.gtimg.cn).
    Returns DataFrame with columns: 代码, 名称, 最新价, 涨跌幅, 成交量, 换手率, 市盈率-动态, 市值
    """
    rows = []
    failures = 0
    total_batches = 0
    sample_logged = False
    for i in range(0, len(codes), 100):
        total_batches += 1
        batch = codes[i:i + 100]
        syms = ",".join(f"{_market_prefix(c)}{c}" for c in batch)
        try:
            r = requests.get(f"http://qt.gtimg.cn/q={syms}", timeout=10)
            for line in r.text.strip().split(";"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                parts = line.split("=", 1)
                m = __import__("re").search(r'\"(.+)\"', parts[1])
                if not m:
                    continue
                f = m.group(1).split("~")
                if len(f) < 50:
                    continue
                # Log sample for first stock to diagnose field positions
                if not sample_logged and len(f) > 44:
                    print(f"[DIAG] 腾讯API字段示例 (共{len(f)}个字段):")
                    print(f"  [1]名称={f[1]}, [2]代码={f[2]}, [3]最新价={f[3]}")
                    print(f"  [6]成交量={f[6]}, [32]涨跌幅={f[32]}, [38]换手率={f[38]}")
                    print(f"  [39]市盈率={f[39]}, [44]市值={f[44]}")
                    sample_logged = True
                code = f[2].strip().zfill(6)
                rows.append({
                    "代码": code,
                    "名称": f[1] if len(f) > 1 else None,
                    "最新价": float(f[3]) if f[3] else None,
                    "涨跌幅": float(f[32]) if f[32] else None,
                    "成交量": float(f[6]) * 100 if len(f) > 6 and f[6] else None,  # 手 -> 股
                    "换手率": float(f[38]) if f[38] else None,
                    "市盈率-动态": float(f[39]) if f[39] else None,
                    "市值": float(f[44]) * 1e8 if f[44] else None,
                })
        except Exception as e:
            failures += 1
            print(f"[WARN] tencent batch {i//100} failed: {e}")
            continue
    if failures:
        print(f"[WARN] tencent realtime: {failures}/{total_batches} batches failed")
    # Log summary of data quality
    if rows:
        df_check = pd.DataFrame(rows)
        n_no_vol = df_check["成交量"].isna().sum()
        n_no_mcap = df_check["市值"].isna().sum()
        if n_no_vol > 0 or n_no_mcap > 0:
            print(f"[DIAG] 实时数据质量: 成交量缺失={n_no_vol}/{len(rows)}, 市值缺失={n_no_mcap}/{len(rows)}")
    return pd.DataFrame(rows)


_REALTIME_COL_MAP = {
    "代码": "代码",
    "名称": "名称",
    "最新价": "最新价",
    "涨跌幅": "涨跌幅",
    "成交量": "成交量",
    "换手率": "换手率",
    "市盈率-动态": "市盈率-动态",
    "总市值": "市值",
}


def get_realtime_quotes(codes: list[str], progress_callback: ProgressCB = None) -> pd.DataFrame:
    """
    Fetch realtime quotes for given codes from Tencent batch API.
    Returns DataFrame with columns: 代码 名称 最新价 涨跌幅 成交量 换手率 市盈率-动态 市值
    """
    _EXPECTED = ["代码", "名称", "最新价", "涨跌幅", "成交量", "换手率", "市盈率-动态", "市值"]
    
    if progress_callback:
        progress_callback(0, len(codes), f"实时行情 (腾讯): {len(codes)} 只")
    
    df = _fetch_realtime_tencent(codes)
    
    if df.empty:
        print(f"[WARN] get_realtime_quotes: 腾讯 API 返回空数据")
        return pd.DataFrame(columns=_EXPECTED)
    
    # Ensure all expected columns exist
    for c in _EXPECTED:
        if c not in df.columns:
            df[c] = None
    
    # Filter out stocks with no price
    df = df.dropna(subset=["最新价"])
    
    if progress_callback:
        progress_callback(len(df), len(df), f"实时行情: {len(df)} 只")
    
    return df[_EXPECTED].reset_index(drop=True)


def _market_prefix(code: str) -> str:
    """A 股代码市场前缀: 6xxxxx → sh, 83/87/43/920xxx → bj, 其它 → sz"""
    if code.startswith("6"):
        return "sh"
    if code.startswith(("83", "87", "43", "920")):
        return "bj"
    return "sz"


_session: Optional[requests.Session] = None


def _http_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    return _session


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type((requests.RequestException, KeyError, ValueError)),
    reraise=True,
)
def _fetch_kline_one(code: str, start_date: str) -> pd.DataFrame:
    """
    Fetch daily K-line for a single stock via direct HTTP to Tencent fqkline API.
    start_date: YYYYMMDD string.
    Returns DataFrame with columns: date, open, close, high, low, volume.
    """
    sym = f"{_market_prefix(code)}{code}"
    sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    ed = datetime.now().strftime("%Y-%m-%d")
    url = (
        f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={sym},day,{sd},{ed},300,qfq"
    )
    r = _http_session().get(url, timeout=10)
    r.raise_for_status()
    body = r.json().get("data", {}).get(sym)
    if not body:
        return pd.DataFrame(columns=_KLINE_COLS)
    bars = body.get("qfqday") or body.get("day") or []
    if not bars:
        return pd.DataFrame(columns=_KLINE_COLS)
    return pd.DataFrame(
        {
            "date":   [b[0] for b in bars],
            "open":   [float(b[1]) for b in bars],
            "close":  [float(b[2]) for b in bars],
            "high":   [float(b[3]) for b in bars],
            "low":    [float(b[4]) for b in bars],
            "volume": [float(b[5]) for b in bars],
        }
    )


def get_kline_batch(
    fetch_plan: dict[str, str],
    progress_callback: ProgressCB = None,
    max_workers: int = 8,
    on_success: Optional[Callable[[str, pd.DataFrame], None]] = None,
) -> dict[str, pd.DataFrame]:
    """
    Fetch K-line for many codes in rate-limit-friendly batches.
    Processes max_workers requests concurrently, then pauses 100ms between batches.
    fetch_plan: {code: start_date_YYYYMMDD}.
    on_success(code, df) is called per success — used to persist to cache.
    """
    results: dict[str, pd.DataFrame] = {}
    failures: list[tuple[str, str]] = []
    empty_count = 0
    total = len(fetch_plan)
    done = 0
    items = list(fetch_plan.items())

    def _job(code: str, start_date: str):
        try:
            return code, _fetch_kline_one(code, start_date), None
        except Exception as e:
            return code, pd.DataFrame(columns=_KLINE_COLS), str(e)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for i in range(0, total, max_workers):
            batch = items[i:i + max_workers]
            futures = [pool.submit(_job, c, sd) for c, sd in batch]
            for fut in futures:
                code, df, err = fut.result()
                done += 1
                if err:
                    failures.append((code, err))
                elif not df.empty:
                    results[code] = df
                    if on_success:
                        on_success(code, df)
                else:
                    empty_count += 1
                if progress_callback:
                    progress_callback(done, total, f"历史 K 线: {done}/{total}")
            if i + max_workers < total:
                time.sleep(0.1)

    total_failures = empty_count + len(failures)
    if total_failures > total * 0.5:
        msg = (f"[WARN] {total_failures}/{total} 只股票拉取失败 "
               f"(空数据 {empty_count} + 异常 {len(failures)}), "
               f"可能触发数据源限流, 请等待几分钟后重试")
        print(msg)
        if progress_callback:
            progress_callback(done, total, msg)
    else:
        if empty_count:
            print(f"[WARN] {empty_count}/{total} 只股票返回空数据")
        if failures:
            print(f"[WARN] {len(failures)}/{total} stocks failed: {failures[:5]}...")
    return results


def compute_indicators(
    realtime_df: pd.DataFrame,
    kline_map: dict[str, pd.DataFrame],
    progress_callback: ProgressCB = None,
    cache=None,
) -> pd.DataFrame:
    """
    For each stock, compute MA20/60/120, volume MA5/30 (亿), turnover extremes,
    KDJ golden cross, MACD golden cross.
    K-line volume is always in 手 (lots), converted to 股 (shares) internally.
    Total shares are cached for reliability (fallback when realtime data unavailable).
    """
    # Pre-extract realtime columns as numpy arrays for fast per-row access
    rt_codes = realtime_df["代码"].astype(str).to_numpy()
    rt_names = realtime_df["名称"].to_numpy() if "名称" in realtime_df.columns else [None] * len(realtime_df)
    rt_prices = pd.to_numeric(realtime_df.get("最新价"), errors="coerce").to_numpy()
    rt_changes = pd.to_numeric(realtime_df.get("涨跌幅"), errors="coerce").to_numpy()
    rt_vols = pd.to_numeric(realtime_df.get("成交量"), errors="coerce").to_numpy()
    rt_turnovers = pd.to_numeric(realtime_df.get("换手率"), errors="coerce").to_numpy()
    rt_pes = pd.to_numeric(realtime_df.get("市盈率-动态"), errors="coerce").to_numpy()
    rt_mcaps = pd.to_numeric(realtime_df.get("市值"), errors="coerce").to_numpy()

    # Batch fetch cached total shares
    total_shares_cache = {}
    if cache is not None:
        total_shares_cache = cache.get_total_shares_batch(rt_codes.tolist())
    total_shares_to_save = {}

    rows = []
    total = len(realtime_df)
    for done in range(total):
        code = rt_codes[done]
        kl = kline_map.get(code)
        ma5 = ma20 = ma60 = ma120 = None
        vol_5d = vol_30d = None
        to_5_max = to_5_min = to_10_max = to_10_min = None
        to_20_max = to_20_min = to_30_max = to_30_min = None
        to_60_max = to_60_min = None
        kdj_gc = macd_gc = False

        if kl is not None and not kl.empty:
            closes = kl["close"].to_numpy(dtype=float)
            amounts = kl["volume"].to_numpy(dtype=float)
            dates = kl["date"].to_numpy()
            n = closes.size

            if n >= 5:   ma5   = round(float(closes[-5:].mean()), 2)
            if n >= 20:  ma20  = round(float(closes[-20:].mean()), 2)
            if n >= 60:  ma60  = round(float(closes[-60:].mean()), 2)
            if n >= 120: ma120 = round(float(closes[-120:].mean()), 2)

            # Tencent K-line API returns volume in 手 (lots)
            # Keep in 手 for internal calculations, convert to 万手 for display
            amounts_lots = amounts  # 手

            # 平均成交量 (万手)
            if n >= 5:
                vol_5d = round(float(amounts_lots[-5:].mean()) / 1e4, 2)
            if n >= 30:
                vol_30d = round(float(amounts_lots[-30:].mean()) / 1e4, 2)

            # 换手率极值 (包含最新日)
            turnover = rt_turnovers[done]
            volume = rt_vols[done]
            
            # Try to get total shares from cache first
            total_shares = total_shares_cache.get(code)
            
            # If not in cache, calculate from realtime data
            # realtime volume is in 手, convert to 股 for total_shares calculation
            if total_shares is None and pd.notna(turnover) and pd.notna(volume) and float(turnover) > 0:
                volume_shares = float(volume) * 100  # 手 -> 股
                total_shares = volume_shares / (float(turnover) / 100.0)  # 股
                total_shares_to_save[code] = total_shares
            
            # Calculate turnover extremes if we have total shares
            # K-line volume in 手, convert to 股 for turnover calculation
            if total_shares is not None and total_shares > 0:
                amounts_shares = amounts_lots * 100  # 手 -> 股
                to_values = amounts_shares / total_shares * 100  # %
                if n >= 5:
                    to_5_max = round(float(to_values[-5:].max()), 2)
                    to_5_min = round(float(to_values[-5:].min()), 2)
                if n >= 10:
                    to_10_max = round(float(to_values[-10:].max()), 2)
                    to_10_min = round(float(to_values[-10:].min()), 2)
                if n >= 20:
                    to_20_max = round(float(to_values[-20:].max()), 2)
                    to_20_min = round(float(to_values[-20:].min()), 2)
                if n >= 30:
                    to_30_max = round(float(to_values[-30:].max()), 2)
                    to_30_min = round(float(to_values[-30:].min()), 2)
                if n >= 60:
                    to_60_max = round(float(to_values[-60:].max()), 2)
                    to_60_min = round(float(to_values[-60:].min()), 2)

            if "high" in kl.columns and "low" in kl.columns:
                highs = kl["high"].to_numpy(dtype=float)
                lows = kl["low"].to_numpy(dtype=float)
                kdj_gc = _calc_kdj_golden_cross_arr(highs, lows, closes)
            macd_gc = _calc_macd_golden_cross_arr(closes)

        mcap = rt_mcaps[done]
        mcap_yi = round(float(mcap) / 1e8, 2) if pd.notna(mcap) else None

        vol_shares = rt_vols[done]
        latest_vol_wan = None
        if pd.notna(vol_shares):
            try:
                latest_vol_wan = round(float(vol_shares) / 1e6, 2)  # 股 -> 万手 (1万手=1e6股)
            except (TypeError, ValueError):
                pass
        
        # 如果实时数据缺失，从K线数据补充
        if latest_vol_wan is None and kl is not None and not kl.empty:
            # 从最新K线补充成交量
            last_kl_vol = kl["volume"].iloc[-1]  # 手
            if pd.notna(last_kl_vol) and float(last_kl_vol) > 0:
                latest_vol_wan = round(float(last_kl_vol) / 1e4, 2)  # 手 -> 万手
        
        if mcap_yi is None and kl is not None and not kl.empty:
            # 从总股东 * 最新价计算市值
            total_shares = total_shares_cache.get(code)
            if total_shares is not None and pd.notna(rt_prices[done]) and float(rt_prices[done]) > 0:
                mcap_yi = round(float(total_shares) * float(rt_prices[done]) / 1e8, 2)

        pe = rt_pes[done]
        pe_val = float(pe) if pd.notna(pe) else None

        rows.append({
            "代码": code,
            "名称": rt_names[done],
            "最新价": float(rt_prices[done]) if pd.notna(rt_prices[done]) else None,
            "涨跌幅": float(rt_changes[done]) if pd.notna(rt_changes[done]) else None,
            "5日均价": ma5,
            "20日均价": ma20,
            "60日均价": ma60,
            "120日均价": ma120,
            "市盈率": pe_val,
            "市盈率(TTM)": pe_val,
            "市值(亿)": mcap_yi,
            "最新成交量(万手)": latest_vol_wan,
            "最新换手率": float(rt_turnovers[done]) if pd.notna(rt_turnovers[done]) else None,
            "5日平均成交量(万手)": vol_5d,
            "5日最高换手率": to_5_max,
            "5日最低换手率": to_5_min,
            "10日最高换手率": to_10_max,
            "10日最低换手率": to_10_min,
            "30日平均成交量(万手)": vol_30d,
            "20日最高换手率": to_20_max,
            "20日最低换手率": to_20_min,
            "30日最高换手率": to_30_max,
            "30日最低换手率": to_30_min,
            "60日最高换手率": to_60_max,
            "60日最低换手率": to_60_min,
            "KDJ金叉": kdj_gc,
            "MACD金叉": macd_gc,
        })
        if progress_callback and done % 50 == 0:
            progress_callback(done, total, f"指标计算: {done}/{total}")

    if progress_callback:
        progress_callback(total, total, f"指标计算: {total}/{total}")
    
    # Save new total shares to cache
    if cache is not None and total_shares_to_save:
        cache.save_total_shares_batch(total_shares_to_save)
    
    return pd.DataFrame(rows)


def _calc_kdj_golden_cross_arr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> bool:
    """Numpy-vectorized KDJ (standard A-share SMA form). Used by compute_indicators."""
    n = closes.size
    if n < 9:
        return False
    h9 = pd.Series(highs).rolling(9, min_periods=9).max().to_numpy()
    l9 = pd.Series(lows).rolling(9, min_periods=9).min().to_numpy()
    denom = h9 - l9
    rsv = np.where(denom == 0, 50.0, (closes - l9) / denom * 100.0)
    k = 50.0
    d = 50.0
    gold = False
    for i in range(8, n):
        prev_k, prev_d = k, d
        k = (rsv[i] + 2.0 * prev_k) / 3.0
        d = (k + 2.0 * prev_d) / 3.0
        if i >= 9:
            if prev_k <= prev_d and k > d:
                gold = True
            elif prev_k >= prev_d and k < d:
                gold = False
    return gold


def _calc_macd_golden_cross_arr(closes: np.ndarray) -> bool:
    """Numpy-vectorized MACD golden cross (EMA12/26 + DEA9)."""
    n = closes.size
    if n < 26:
        return False
    ema12 = closes[0]
    ema26 = closes[0]
    dif = 0.0
    dea = 0.0
    gold = False
    for i in range(n):
        c = closes[i]
        ema12 = ema12 * 11.0 / 13.0 + c * 2.0 / 13.0
        ema26 = ema26 * 25.0 / 27.0 + c * 2.0 / 27.0
        prev_dif, prev_dea = dif, dea
        dif = ema12 - ema26
        if i == 0:
            dea = dif
        else:
            dea = dea * 8.0 / 10.0 + dif * 2.0 / 10.0
        if i >= 1:
            if prev_dif <= prev_dea and dif > dea:
                gold = True
            elif prev_dif >= prev_dea and dif < dea:
                gold = False
    return gold


_INDICES = {
    "上证指数": "000001",
    "深证成指": "399001",
    "沪深300": "000300",
    "中证1000": "000852",
}


def get_index_quotes(progress_callback: ProgressCB = None) -> pd.DataFrame:
    """Fetch 4 major indices realtime quotes. Tries EM first, then Sina fallback."""
    _SOURCES = [
        ("EM", lambda: ak.stock_zh_index_spot_em(symbol="沪深重要指数")),
        ("Sina", lambda: ak.stock_zh_index_spot()),
    ]
    for src_name, src_fn in _SOURCES:
        for attempt in range(2):
            try:
                df = src_fn()
                rows = []
                for name, code in _INDICES.items():
                    match = df[df["代码"] == code]
                    if match.empty:
                        continue
                    r = match.iloc[0]
                    rows.append({
                        "名称": f"[指数] {name}",
                        "代码": code,
                        "最新价": float(r.get("最新价") or 0),
                        "涨跌幅": float(r.get("涨跌幅") or 0),
                        "成交量": None, "换手率": None, "市盈率-动态": None, "市值": None,
                    })
                if rows:
                    if progress_callback:
                        progress_callback(len(rows), len(rows), f"指数行情: {len(rows)} 个")
                    return pd.DataFrame(rows)
                break
            except Exception:
                if attempt < 1:
                    time.sleep(0.5)
    print("[WARN] get_index_quotes failed — both EM and Sina unavailable")
    return pd.DataFrame()


def _fetch_index_kline_one(code: str, days: int) -> tuple[str, pd.DataFrame]:
    last_exc = None
    for attempt in range(3):
        try:
            df = ak.stock_zh_index_daily_em(symbol=code)
            if df is None or df.empty:
                time.sleep(0.5)
                continue
            out = pd.DataFrame({
                "date":   pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
                "open":   df["open"].astype(float),
                "close":  df["close"].astype(float),
                "high":   df["high"].astype(float),
                "low":    df["low"].astype(float),
                "volume": df["volume"].astype(float),
            })
            return code, out.tail(days).reset_index(drop=True)
        except Exception as e:
            last_exc = e
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
    print(f"[WARN] index kline {code} failed: {last_exc}")
    return code, pd.DataFrame(columns=_KLINE_COLS)


def get_index_kline_batch(codes: list[str], days: int = 130, max_workers: int = 4) -> dict[str, pd.DataFrame]:
    """Fetch index K-lines in parallel. Returns {code: df}."""
    out: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_fetch_index_kline_one, c, days): c for c in codes}
        for fut in as_completed(futs):
            code, df = fut.result()
            if not df.empty:
                out[code] = df
    return out


def get_index_kline(code: str, days: int = 130) -> pd.DataFrame:
    """Backward-compat shim: single index K-line fetch."""
    _, df = _fetch_index_kline_one(code, days)
    return df


def run_pipeline(
    cache,
    force_refresh: bool = False,
    progress_callback: ProgressCB = None,
    max_workers: int = 8,
) -> dict:
    """
    Orchestrate 5-stage pipeline. Returns dict with 'all_data', 'stats', 'cache'.
    """
    stats = {"kline_failures": 0, "realtime_count": 0, "kline_count": 0}

    def _stage(n: int, total: int, msg: str):
        if progress_callback:
            progress_callback(n, total, msg)

    # Stage 1
    _stage(1, 5, "阶段1: 股票清单")
    codes = cache.get_stock_list()
    if not codes or force_refresh:
        codes = get_stock_list()
        cache.save_stock_list(codes)

    # Stage 2
    _stage(2, 5, "阶段2: 实时行情")
    if not force_refresh and cache.is_realtime_fresh():
        realtime_df = cache.load_realtime()
        print(f"   实时行情: 从缓存加载 {len(realtime_df)} 条")
    else:
        realtime_df = get_realtime_quotes(codes)
        cache.save_realtime(realtime_df)
    stats["realtime_count"] = len(realtime_df)
    
    # 诊断实时数据质量
    if not realtime_df.empty:
        n_no_vol = realtime_df["成交量"].isna().sum() if "成交量" in realtime_df.columns else len(realtime_df)
        n_no_mcap = realtime_df["市值"].isna().sum() if "市值" in realtime_df.columns else len(realtime_df)
        n_no_price = realtime_df["最新价"].isna().sum() if "最新价" in realtime_df.columns else len(realtime_df)
        if n_no_vol > 0 or n_no_mcap > 0 or n_no_price > 0:
            print(f"   [DIAG] 实时数据质量: 最新价缺失={n_no_price}, 成交量缺失={n_no_vol}, 市值缺失={n_no_mcap} / 共{len(realtime_df)}条")

    # ---- 过滤 ST/退市 和 总市值 < 80亿 ----
    if progress_callback:
        progress_callback(2, 5, "阶段2.5: 过滤ST/退市/小市值")
    before = len(realtime_df)
    if "名称" in realtime_df.columns:
        st_mask = realtime_df["名称"].str.contains(r"\*?ST|退市", case=False, na=False, regex=True)
        realtime_df = realtime_df[~st_mask].copy()
    if "市值" in realtime_df.columns:
        mcap = realtime_df["市值"].astype(float)
        realtime_df = realtime_df[mcap.notna() & (mcap >= 8_000_000_000)].copy()
    after = len(realtime_df)
    print(f"   过滤: {before} → {after} 只 (剔除 {before - after} 只 ST/退市/小市值)")
    codes = realtime_df["代码"].astype(str).str.zfill(6).tolist()
    # -------------------------------

    # Stage 3 — incremental rolling fetch
    _stage(3, 5, "阶段3: 历史 K 线")
    max_dates = cache.max_kline_date_per_code(codes)
    
    # Get the latest trading day from calendar logic
    latest_trade = cache.latest_trade_date()
    latest_trade_str = latest_trade.strftime("%Y-%m-%d")
    
    # Also check the actual max date in cache (handles holidays/special trading days)
    if max_dates:
        cache_max_date = max(max_dates.values())
        # Use the later of: computed latest trade date OR actual cache max
        # This prevents fetching when cache is ahead of calendar logic
        effective_latest = max(latest_trade_str, cache_max_date)
    else:
        effective_latest = latest_trade_str
    
    if force_refresh:
        # Force refresh: fetch all stocks from wide start
        wide_start = (latest_trade - timedelta(days=_KLINE_FETCH_WIDE_DAYS)).strftime("%Y%m%d")
        fetch_plan = {c: wide_start for c in codes}
        append_only = False
        n_incr = 0
        n_new = len(codes)
        skipped = 0
        print(f"   K线: 强制刷新, 全量拉取 {len(codes)} 只")
    else:
        # Per-stock check: incremental or full fetch
        wide_start = (latest_trade - timedelta(days=_KLINE_FETCH_WIDE_DAYS)).strftime("%Y%m%d")
        fetch_plan = {}
        n_new = 0
        n_incr = 0
        for c in codes:
            md = max_dates.get(c)
            if md and md >= effective_latest:
                # This stock is already up to date, skip
                continue
            elif md:
                # This stock has older data, fetch only new bars from next day
                next_day = date.fromisoformat(md) + timedelta(days=1)
                # Don't fetch if next_day is in the future
                if next_day > date.today():
                    continue
                fetch_plan[c] = next_day.strftime("%Y%m%d")
                n_incr += 1
            else:
                # No cached data for this stock, do wide fetch (full history)
                fetch_plan[c] = wide_start
                n_new += 1
        append_only = True
        skipped = len(codes) - len(fetch_plan)
        
        print(f"   K线诊断: 计算最新={latest_trade_str}, 缓存最新={cache_max_date if max_dates else '无'}, "
              f"有效最新={effective_latest}, 缓存命中={len(max_dates)}/{len(codes)}, "
              f"跳过={skipped}, 增量={n_incr}, 新拉={n_new}")

    if progress_callback:
        parts = []
        if skipped:
            parts.append(f"跳过 {skipped}")
        if n_incr:
            parts.append(f"增量 {n_incr}")
        if n_new:
            parts.append(f"全量 {n_new}")
        progress_callback(
            0, max(len(fetch_plan), 1),
            f"K线: {', '.join(parts)} 只" if parts else "K线: 全部已最新",
        )

    if fetch_plan:
        kline_map = get_kline_batch(
            fetch_plan,
            progress_callback=progress_callback,
            max_workers=max_workers,
            on_success=lambda c, df: cache.save_kline(c, df, append_only=append_only),
        )
        cache.save_kline_batch(kline_map, append_only=append_only)
    else:
        kline_map = {}
    stats["kline_count"] = len(cache.completed_codes())
    
    # 滚动清理：每只股票只保留最近200根K线（足够MA120计算）
    trimmed = cache.trim_kline(keep_bars=200)
    if trimmed > 0:
        print(f"   K线缓存清理: 删除 {trimmed} 条过期数据")

    # Stage 4
    _stage(4, 5, "阶段4: 指标计算")
    # Always load from cache — cache has historical data + newly fetched bars
    # (saved via on_success callback during fetch). This ensures MA calculation
    # has full history even for stocks that only had 1 new bar fetched.
    for c in codes:
        cached = cache.get_kline(c)
        if cached is not None and not cached.empty:
            kline_map[c] = cached
    indicators = compute_indicators(realtime_df, kline_map, progress_callback, cache=cache)
    
    # 诊断指标数据质量
    if not indicators.empty:
        cols_to_check = ["市值(亿)", "最新成交量(万手)", "最新换手率", "5日平均成交量(万手)"]
        missing_info = []
        for col in cols_to_check:
            if col in indicators.columns:
                n_missing = indicators[col].isna().sum()
                if n_missing > 0:
                    missing_info.append(f"{col}缺失={n_missing}")
        if missing_info:
            print(f"   [DIAG] 指标数据质量: {', '.join(missing_info)} / 共{len(indicators)}条")

    # 指数块 (并行拉取 K 线, 复用 SQLite 缓存)
    index_quotes = get_index_quotes()
    idx_kline_map: dict[str, pd.DataFrame] = {}
    if not index_quotes.empty:
        if progress_callback:
            progress_callback(0, 1, "指数 K 线 (并行)")
        icodes = index_quotes["代码"].astype(str).tolist()
        missing: list[str] = []
        for ic in icodes:
            cached = cache.get_kline(ic)
            if cached is not None and not cached.empty:
                idx_kline_map[ic] = cached
            else:
                missing.append(ic)
        if missing:
            fetched = get_index_kline_batch(missing, days=130, max_workers=min(4, len(missing)))
            if fetched:
                cache.save_kline_batch(fetched, is_index=True)
                idx_kline_map.update(fetched)

    index_rows = []
    for _, ir in index_quotes.iterrows():
        icode = ir["代码"]
        ikl = idx_kline_map.get(icode)
        ma5 = ma20 = ma60 = ma120 = None
        kdj_gc = macd_gc = False
        if ikl is not None and not ikl.empty:
            closes = ikl["close"].to_numpy(dtype=float)
            n = closes.size
            if n >= 5:   ma5   = round(float(closes[-5:].mean()), 2)
            if n >= 20:  ma20  = round(float(closes[-20:].mean()), 2)
            if n >= 60:  ma60  = round(float(closes[-60:].mean()), 2)
            if n >= 120: ma120 = round(float(closes[-120:].mean()), 2)
            if "high" in ikl.columns and "low" in ikl.columns and n >= 9:
                kdj_gc = _calc_kdj_golden_cross_arr(
                    ikl["high"].to_numpy(dtype=float),
                    ikl["low"].to_numpy(dtype=float),
                    closes,
                )
            if n >= 26:
                macd_gc = _calc_macd_golden_cross_arr(closes)
        index_rows.append({
            "代码": icode, "名称": ir["名称"], "最新价": ir["最新价"],
            "涨跌幅": ir["涨跌幅"],
            "5日均价": ma5, "20日均价": ma20, "60日均价": ma60, "120日均价": ma120,
            "市盈率": None, "市盈率(TTM)": None, "市值(亿)": None,
            "最新成交量(万手)": None, "最新换手率": None,
            "5日平均成交量(万手)": None, "5日最高换手率": None, "5日最低换手率": None,
            "30日平均成交量(万手)": None, "20日最高换手率": None, "20日最低换手率": None,
            "KDJ金叉": kdj_gc, "MACD金叉": macd_gc,
        })
    index_df = pd.DataFrame(index_rows)

    all_data = pd.concat([index_df, indicators], ignore_index=True, sort=False)
    
    # 诊断MA数据
    ma_cols = ["5日均价", "20日均价", "60日均价", "120日均价"]
    ma_info = []
    for col in ma_cols:
        if col in all_data.columns:
            n_valid = all_data[col].notna().sum()
            ma_info.append(f"{col}有效={n_valid}")
    if ma_info:
        print(f"   [DIAG] MA数据: {', '.join(ma_info)} / 共{len(all_data)}条")
    
    _stage(5, 5, f"完成: {len(all_data)} 条")
    return {"all_data": all_data, "stats": stats, "cache": cache}
