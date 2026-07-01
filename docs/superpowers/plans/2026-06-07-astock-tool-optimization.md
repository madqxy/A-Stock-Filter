# A股数据分析工具全线优化 — 实施计划

> **For agentic workers:** 本项目非 git 仓库,跳过 `git commit` 步骤,只保留测试与实现步骤。每完成一个 Task 后口头报告进度。

**Goal:** 将现有 A 股分析工具从"串行 5+ 分钟 + 4 个 P0 Bug"重构为"阶段化管道 + 断点续传 + akshare 数据源 + 完整单测"。

**Architecture:** 5 阶段管道(股票清单 → 实时行情 → 历史 K 线 → 指标计算 → 筛选导出),通过 `cache.py` 持久化(SQLite + parquet),`data_collector.run_pipeline` 编排,GUI/CLI 共享。

**Tech Stack:** Python 3.10+ / akshare / pandas / xlsxwriter / pyarrow / tenacity / pytest / SQLite3 (stdlib)

---

## Task 1: 基础设施 + cache.py 骨架 (TDD)

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `cache.py`
- Create: `tests/test_cache.py`

### Step 1.1: 写 `tests/__init__.py`(空)

```python
```

### Step 1.2: 写 `tests/conftest.py`(共享 fixture)

```python
import pytest
from pathlib import Path
import pandas as pd
from cache import StockCache


@pytest.fixture
def tmp_cache(tmp_path) -> StockCache:
    return StockCache(base_dir=tmp_path)


@pytest.fixture
def sample_kline_df() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=130, freq="B")
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": 10.0,
        "close": [10.0 + i * 0.01 for i in range(130)],
        "high": 11.0,
        "low": 9.5,
        "volume": 1_000_000.0,
    })


@pytest.fixture
def sample_realtime_df() -> pd.DataFrame:
    return pd.DataFrame({
        "代码": ["000001", "600000"],
        "名称": ["平安银行", "浦发银行"],
        "最新价": [10.5, 8.2],
        "涨跌幅": [1.5, -0.8],
    })
```

### Step 1.3: 写 `tests/test_cache.py`(仅放构造函数测试,其余测试在后续 Task 追加)

```python
import pytest
from cache import StockCache


def test_cache_creates_data_dir(tmp_path):
    cache = StockCache(base_dir=tmp_path)
    assert (tmp_path / "data").exists()
    assert (tmp_path / "data" / "history.db").exists()


def test_cache_idempotent_init(tmp_path):
    StockCache(base_dir=tmp_path)
    StockCache(base_dir=tmp_path)  # 第二次不应报错
    assert (tmp_path / "data" / "history.db").exists()
```

### Step 1.4: 写 `cache.py` 最小实现(只支持构造 + 目录/SQLite 创建)

```python
"""
Stock data cache layer: SQLite for K-line history, parquet for daily snapshots.
"""
import sqlite3
import threading
from pathlib import Path
from typing import Optional

import pandas as pd


_SCHEMA = """
CREATE TABLE IF NOT EXISTS kline (
    code    TEXT NOT NULL,
    date    TEXT NOT NULL,
    open    REAL,
    close   REAL,
    high    REAL,
    low     REAL,
    volume  REAL,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_kline_code ON kline(code);
"""


class StockCache:
    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "history.db"
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock, sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()
```

### Step 1.5: 跑测试确认通过

Run: `cd D:\AI-Projects\A股数据分析 && python -m pytest tests/test_cache.py -v`
Expected: 2 passed

---

## Task 2: cache - 股票清单 stock_list.json (TDD)

**Files:**
- Modify: `cache.py`
- Modify: `tests/test_cache.py`

### Step 2.1: 追加测试到 `tests/test_cache.py`

```python
def test_get_stock_list_empty_when_no_cache(tmp_cache):
    assert tmp_cache.get_stock_list() == []


def test_save_and_load_stock_list(tmp_cache):
    codes = ["000001", "600000", "688001"]
    tmp_cache.save_stock_list(codes)
    assert tmp_cache.get_stock_list() == codes


def test_get_stock_list_ttl_respected(tmp_cache):
    tmp_cache.save_stock_list(["000001"])
    # TTL 0 = 立即过期
    assert tmp_cache.get_stock_list(ttl_days=0) == []
    # TTL 7 = 还在
    assert tmp_cache.get_stock_list(ttl_days=7) == ["000001"]
```

### Step 2.2: 跑测试确认失败

Run: `python -m pytest tests/test_cache.py::test_get_stock_list_empty_when_no_cache -v`
Expected: FAIL with `AttributeError: 'StockCache' object has no attribute 'get_stock_list'`

### Step 2.3: 在 `cache.py` 添加方法

```python
import json
import time


class StockCache:
    # ... (保留之前代码)

    def _stock_list_path(self) -> Path:
        return self.data_dir / "stock_list.json"

    def save_stock_list(self, codes: list[str]):
        with self._lock:
            data = {"codes": list(codes), "fetched_at": time.time()}
            self._stock_list_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get_stock_list(self, ttl_days: int = 7) -> list[str]:
        path = self._stock_list_path()
        if not path.exists():
            return []
        with self._lock:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError):
                return []
        age_seconds = time.time() - payload.get("fetched_at", 0)
        if age_seconds > ttl_days * 86400:
            return []
        return list(payload.get("codes", []))
```

### Step 2.4: 跑测试确认通过

Run: `python -m pytest tests/test_cache.py -v`
Expected: 5 passed (含 Task 1 的 2 个)

---

## Task 3: cache - 实时行情 parquet (TDD)

**Files:**
- Modify: `cache.py`
- Modify: `tests/test_cache.py`

### Step 3.1: 追加测试

```python
import pandas as pd


def test_realtime_not_fresh_when_empty(tmp_cache):
    assert tmp_cache.is_realtime_fresh() is False


def test_save_and_load_realtime(tmp_cache, sample_realtime_df):
    path = tmp_cache.save_realtime(sample_realtime_df)
    assert path.exists()
    loaded = tmp_cache.load_realtime()
    assert loaded is not None
    assert list(loaded.columns) == list(sample_realtime_df.columns)
    assert len(loaded) == 2


def test_load_realtime_returns_none_when_no_file(tmp_cache):
    assert tmp_cache.load_realtime() is None


def test_realtime_fresh_after_save(tmp_cache, sample_realtime_df):
    tmp_cache.save_realtime(sample_realtime_df)
    assert tmp_cache.is_realtime_fresh() is True
```

### Step 3.2: 跑测试确认失败

Run: `python -m pytest tests/test_cache.py::test_realtime_not_fresh_when_empty -v`
Expected: FAIL with AttributeError

### Step 3.3: 实现 save/load/is_fresh

```python
from datetime import datetime, date as _date


class StockCache:
    # ...

    def _realtime_path(self, day: Optional[_date] = None) -> Path:
        d = day or datetime.now().date()
        return self.data_dir / f"realtime_{d.strftime('%Y%m%d')}.parquet"

    def save_realtime(self, df: pd.DataFrame, day: Optional[_date] = None) -> Path:
        path = self._realtime_path(day)
        with self._lock:
            df.to_parquet(path, index=False, engine="pyarrow")
        return path

    def load_realtime(self, day: Optional[_date] = None) -> Optional[pd.DataFrame]:
        path = self._realtime_path(day)
        if not path.exists():
            return None
        with self._lock:
            return pd.read_parquet(path, engine="pyarrow")

    def is_realtime_fresh(self) -> bool:
        return self._realtime_path().exists()
```

### Step 3.4: 跑测试确认通过

Run: `python -m pytest tests/test_cache.py -v`
Expected: 9 passed

---

## Task 4: cache - SQLite kline 存取 (TDD)

**Files:**
- Modify: `cache.py`
- Modify: `tests/test_cache.py`

### Step 4.1: 追加测试

```python
def test_save_and_load_kline(tmp_cache, sample_kline_df):
    tmp_cache.save_kline("000001", sample_kline_df)
    loaded = tmp_cache.get_kline("000001")
    assert loaded is not None
    assert len(loaded) == 130
    assert "close" in loaded.columns


def test_get_kline_empty_for_unknown_code(tmp_cache):
    assert tmp_cache.get_kline("999999") is None


def test_save_kline_upserts(tmp_cache, sample_kline_df):
    tmp_cache.save_kline("000001", sample_kline_df)
    sample_kline_df.loc[0, "close"] = 99.99
    tmp_cache.save_kline("000001", sample_kline_df.iloc[[0]])
    loaded = tmp_cache.get_kline("000001")
    assert (loaded["close"] == 99.99).sum() == 1
    assert len(loaded) == 130  # upsert 不应增加行


def test_has_kline(tmp_cache, sample_kline_df):
    assert tmp_cache.has_kline("000001") is False
    tmp_cache.save_kline("000001", sample_kline_df)
    assert tmp_cache.has_kline("000001") is True
```

### Step 4.2: 跑测试确认失败

Run: `python -m pytest tests/test_cache.py::test_save_and_load_kline -v`
Expected: FAIL

### Step 4.3: 实现 SQLite 存取

```python
class StockCache:
    # ...

    def save_kline(self, code: str, df: pd.DataFrame):
        if df.empty:
            return
        rows = [
            (code, str(row["date"]), row["open"], row["close"],
             row["high"], row["low"], row["volume"])
            for _, row in df.iterrows()
        ]
        with self._lock, sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO kline (code, date, open, close, high, low, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()

    def get_kline(self, code: str) -> Optional[pd.DataFrame]:
        with self._lock, sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            cur = conn.execute(
                "SELECT date, open, close, high, low, volume FROM kline "
                "WHERE code = ? ORDER BY date",
                (code,),
            )
            rows = cur.fetchall()
        if not rows:
            return None
        return pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])

    def has_kline(self, code: str) -> bool:
        with self._lock, sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            cur = conn.execute("SELECT 1 FROM kline WHERE code = ? LIMIT 1", (code,))
            return cur.fetchone() is not None
```

### Step 4.4: 跑测试确认通过

Run: `python -m pytest tests/test_cache.py -v`
Expected: 13 passed

---

## Task 5: cache - completed_codes + clear (TDD)

**Files:**
- Modify: `cache.py`
- Modify: `tests/test_cache.py`

### Step 5.1: 追加测试

```python
def test_completed_codes_empty(tmp_cache):
    assert tmp_cache.completed_codes() == set()


def test_completed_codes_returns_set(tmp_cache, sample_kline_df):
    tmp_cache.save_kline("000001", sample_kline_df)
    tmp_cache.save_kline("600000", sample_kline_df)
    assert tmp_cache.completed_codes() == {"000001", "600000"}


def test_clear(tmp_cache, sample_kline_df, sample_realtime_df):
    tmp_cache.save_kline("000001", sample_kline_df)
    tmp_cache.save_realtime(sample_realtime_df)
    tmp_cache.save_stock_list(["000001"])
    tmp_cache.clear()
    assert tmp_cache.completed_codes() == set()
    assert tmp_cache.load_realtime() is None
    assert tmp_cache.get_stock_list() == []
```

### Step 5.2: 跑测试确认失败

Run: `python -m pytest tests/test_cache.py::test_completed_codes_empty -v`
Expected: FAIL

### Step 5.3: 实现 completed_codes + clear

```python
class StockCache:
    # ...

    def completed_codes(self) -> set[str]:
        with self._lock, sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            cur = conn.execute("SELECT DISTINCT code FROM kline")
            return {row[0] for row in cur.fetchall()}

    def clear(self):
        with self._lock:
            if self.db_path.exists():
                self.db_path.unlink()
            for p in self.data_dir.glob("realtime_*.parquet"):
                p.unlink()
            list_path = self._stock_list_path()
            if list_path.exists():
                list_path.unlink()
        self._init_db()
```

### Step 5.4: 跑测试确认通过

Run: `python -m pytest tests/test_cache.py -v`
Expected: 16 passed

---

## Task 6: data_collector - get_stock_list (TDD, mock akshare)

**Files:**
- Modify: `data_collector.py`
- Create: `tests/test_collector_list.py`

### Step 6.1: 写 `data_collector.py` 顶部 imports + 第一个函数

```python
"""
A-stock data collection pipeline (5 stages).

Stage 1: get_stock_list — list of A-share codes via akshare
Stage 2: get_realtime_quotes — full-market realtime via akshare
Stage 3: get_kline_batch — historical K-line per stock, parallel, cached
Stage 4: compute_indicators — MA20/60/120, volume MA, turnover extremes
Stage 5: handled by data_exporter
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional
import time

import akshare as ak
import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type,
)
import requests


ProgressCB = Optional[Callable[[int, int, str], None]]
_KLINE_COLS = ["date", "open", "close", "high", "low", "volume"]


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
```

### Step 6.2: 写 `tests/test_collector_list.py`(用 monkeypatch 模拟 akshare)

```python
import pandas as pd
import pytest
from unittest.mock import patch


def test_get_stock_list_returns_zfilled_codes():
    fake_df = pd.DataFrame({
        "code": ["1", "600000", "688001"],
        "name": ["平安银行", "浦发银行", "中芯国际"],
    })
    with patch("data_collector.ak") as mock_ak:
        mock_ak.stock_info_a_code_name.return_value = fake_df
        from data_collector import get_stock_list
        codes = get_stock_list()
    assert codes == ["000001", "600000", "688001"]


def test_get_stock_list_calls_progress_callback():
    fake_df = pd.DataFrame({"code": ["000001"], "name": ["A"]})
    progress = []
    with patch("data_collector.ak") as mock_ak:
        mock_ak.stock_info_a_code_name.return_value = fake_df
        from data_collector import get_stock_list
        get_stock_list(progress_callback=lambda d, t, m: progress.append((d, t, m)))
    assert progress == [(1, 1, "获取股票清单: 1 只")]
```

### Step 6.3: 跑测试确认通过

Run: `python -m pytest tests/test_collector_list.py -v`
Expected: 2 passed

---

## Task 7: data_collector - get_realtime_quotes (TDD)

**Files:**
- Modify: `data_collector.py`
- Create: `tests/test_collector_realtime.py`

### Step 7.1: 实现 `get_realtime_quotes`

```python
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


def get_realtime_quotes(progress_callback: ProgressCB = None) -> pd.DataFrame:
    """
    Fetch full-market realtime quotes via akshare.
    Returns DataFrame with columns: 代码 名称 最新价 涨跌幅 成交量 换手率 市盈率-动态 市值
    """
    df = ak.stock_zh_a_spot()
    keep = [c for c in _REALTIME_COL_MAP.keys() if c in df.columns]
    df = df[keep].rename(columns=_REALTIME_COL_MAP)
    df = df.dropna(subset=["最新价"])
    df["代码"] = df["代码"].astype(str).str.zfill(6)
    if progress_callback:
        progress_callback(len(df), len(df), f"实时行情: {len(df)} 只")
    return df.reset_index(drop=True)
```

### Step 7.2: 写测试

```python
import pandas as pd
from unittest.mock import patch


def _fake_ak_spot():
    return pd.DataFrame({
        "代码": ["1", "600000", "999999"],  # 999999 will be NaN after filter? No - we'll filter by price
        "名称": ["平安银行", "浦发银行", "ST退"],
        "最新价": [10.5, 8.2, None],  # None 让这一行被 dropna 掉
        "涨跌幅": [1.5, -0.8, 5.0],
        "成交量": [1000000, 800000, 0],
        "换手率": [0.5, 0.3, 0.0],
        "市盈率-动态": [5.2, 6.1, None],
        "总市值": [200e8, 150e8, 0],
    })


def test_get_realtime_quotes_filters_and_normalizes():
    with patch("data_collector.ak") as mock_ak:
        mock_ak.stock_zh_a_spot.return_value = _fake_ak_spot()
        from data_collector import get_realtime_quotes
        df = get_realtime_quotes()
    assert len(df) == 2  # 999999 因价格 None 被剔除
    assert list(df["代码"]) == ["000001", "600000"]
    assert "市值" in df.columns


def test_get_realtime_quotes_progress_callback():
    with patch("data_collector.ak") as mock_ak:
        mock_ak.stock_zh_a_spot.return_value = _fake_ak_spot()
        from data_collector import get_realtime_quotes
        progress = []
        get_realtime_quotes(progress_callback=lambda d, t, m: progress.append(m))
    assert any("实时行情" in m for m in progress)
```

### Step 7.3: 跑测试

Run: `python -m pytest tests/test_collector_realtime.py -v`
Expected: 2 passed

---

## Task 8: data_collector - get_kline_batch with retry + concurrency

**Files:**
- Modify: `data_collector.py`
- Create: `tests/test_collector_kline.py`

### Step 8.1: 实现单只 K 线拉取 + 重试 + 并发

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type((requests.RequestException, KeyError, ValueError)),
    reraise=True,
)
def _fetch_kline_one(code: str) -> pd.DataFrame:
    df = ak.stock_zh_a_hist(
        symbol=code, period="daily", adjust="qfq", start_date="20240101"
    )
    if df is None or df.empty:
        return pd.DataFrame(columns=_KLINE_COLS)
    # akshare 返回列: 日期 开盘 收盘 最高 最低 成交量 成交额 振幅 涨跌幅 涨跌额 换手率
    out = pd.DataFrame({
        "date":   pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d"),
        "open":   df["开盘"].astype(float),
        "close":  df["收盘"].astype(float),
        "high":   df["最高"].astype(float),
        "low":    df["最低"].astype(float),
        "volume": df["成交量"].astype(float),
    })
    return out.tail(130).reset_index(drop=True)


def get_kline_batch(
    codes: list[str],
    progress_callback: ProgressCB = None,
    max_workers: int = 8,
    on_success: Optional[Callable[[str, pd.DataFrame], None]] = None,
) -> dict[str, pd.DataFrame]:
    """
    Fetch K-line for many codes concurrently with retry.
    on_success(code, df) is called per success — used to persist to cache.
    """
    results: dict[str, pd.DataFrame] = {}
    failures: list[tuple[str, str]] = []
    total = len(codes)
    done = 0

    def _job(code: str):
        try:
            return code, _fetch_kline_one(code), None
        except Exception as e:
            return code, pd.DataFrame(columns=_KLINE_COLS), str(e)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_job, c): c for c in codes}
        for fut in as_completed(futures):
            code, df, err = fut.result()
            done += 1
            if err:
                failures.append((code, err))
            elif not df.empty:
                results[code] = df
                if on_success:
                    on_success(code, df)
            if progress_callback:
                progress_callback(done, total, f"历史 K 线: {done}/{total}")

    if failures:
        print(f"[WARN] {len(failures)}/{total} stocks failed: {failures[:5]}...")
    return results
```

### Step 8.2: 写测试(mock 单只 + 测试并发回调)

```python
import pandas as pd
from unittest.mock import patch
import pytest


def _fake_hist():
    dates = pd.date_range("2025-01-01", periods=130, freq="B")
    return pd.DataFrame({
        "日期":  dates,
        "开盘":  10.0,
        "收盘":  10.5,
        "最高":  11.0,
        "最低":  9.5,
        "成交量": 1000000,
        "成交额": 10500000,
        "振幅": 1.5,
        "涨跌幅": 5.0,
        "涨跌额": 0.5,
        "换手率": 0.5,
    })


def test_get_kline_batch_returns_dict():
    with patch("data_collector.ak") as mock_ak:
        mock_ak.stock_zh_a_hist.return_value = _fake_hist()
        from data_collector import get_kline_batch
        result = get_kline_batch(["000001", "600000"], max_workers=2)
    assert set(result.keys()) == {"000001", "600000"}
    assert len(result["000001"]) == 130
    assert result["000001"]["close"].iloc[-1] == 10.5


def test_get_kline_batch_calls_on_success():
    with patch("data_collector.ak") as mock_ak:
        mock_ak.stock_zh_a_hist.return_value = _fake_hist()
        from data_collector import get_kline_batch
        saved = []
        get_kline_batch(
            ["000001"],
            on_success=lambda c, df: saved.append(c),
            max_workers=1,
        )
    assert saved == ["000001"]


def test_get_kline_batch_progress_callback():
    with patch("data_collector.ak") as mock_ak:
        mock_ak.stock_zh_a_hist.return_value = _fake_hist()
        from data_collector import get_kline_batch
        progress = []
        get_kline_batch(
            ["000001", "600000"],
            progress_callback=lambda d, t, m: progress.append((d, t)),
            max_workers=2,
        )
    assert progress[-1] == (2, 2)
```

### Step 8.3: 跑测试

Run: `python -m pytest tests/test_collector_kline.py -v`
Expected: 3 passed

---

## Task 9: data_collector - compute_indicators (TDD)

**Files:**
- Modify: `data_collector.py`
- Create: `tests/test_collector_indicators.py`

### Step 9.1: 实现

```python
def compute_indicators(
    realtime_df: pd.DataFrame,
    kline_map: dict[str, pd.DataFrame],
    progress_callback: ProgressCB = None,
) -> pd.DataFrame:
    """
    For each stock, compute MA20/60/120, volume MA5/30, turnover extremes.
    """
    rows = []
    total = len(realtime_df)
    for idx, r in realtime_df.iterrows():
        code = str(r["代码"])
        kl = kline_map.get(code)
        ma20 = ma60 = ma120 = None
        vol_5d = vol_30d = None
        to_5_max = to_5_min = to_30_max = to_30_min = None

        if kl is not None and not kl.empty:
            closes = kl["close"].astype(float)
            volumes = kl["volume"].astype(float)
            if len(closes) >= 20:
                ma20 = round(closes.iloc[-20:].mean(), 2)
            if len(closes) >= 60:
                ma60 = round(closes.iloc[-60:].mean(), 2)
            if len(closes) >= 120:
                ma120 = round(closes.iloc[-120:].mean(), 2)
            if len(volumes) >= 5:
                vol_5d = round(volumes.iloc[-5:].mean(), 2)
            if len(volumes) >= 30:
                vol_30d = round(volumes.iloc[-30:].mean(), 2)

            turnover = r.get("换手率")
            volume = r.get("成交量")
            if turnover and volume and turnover > 0:
                circ = volume / (turnover / 100.0)
                if len(volumes) >= 5:
                    to5 = volumes.iloc[-5:] / circ * 100
                    to_5_max = round(to5.max(), 2)
                    to_5_min = round(to5.min(), 2)
                if len(volumes) >= 30:
                    to30 = volumes.iloc[-30:] / circ * 100
                    to_30_max = round(to30.max(), 2)
                    to_30_min = round(to30.min(), 2)

        rows.append({
            "代码": code,
            "名称": r.get("名称"),
            "最新价": r.get("最新价"),
            "涨跌幅": r.get("涨跌幅"),
            "20日均价": ma20,
            "60日均价": ma60,
            "120日均价": ma120,
            "市盈率": r.get("市盈率-动态"),
            "市盈率(TTM)": r.get("市盈率-动态"),
            "市值": r.get("市值"),
            "最新成交量": r.get("成交量"),
            "最新换手率": r.get("换手率"),
            "5日平均成交量": vol_5d,
            "5日最高换手率": to_5_max,
            "5日最低换手率": to_5_min,
            "30日平均成交量": vol_30d,
            "30日最高换手率": to_30_max,
            "30日最低换手率": to_30_min,
        })
        if progress_callback and (idx + 1) % 50 == 0:
            progress_callback(idx + 1, total, f"指标计算: {idx+1}/{total}")

    if progress_callback:
        progress_callback(total, total, f"指标计算: {total}/{total}")
    return pd.DataFrame(rows)
```

### Step 9.2: 写测试

```python
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
```

### Step 9.3: 跑测试

Run: `python -m pytest tests/test_collector_indicators.py -v`
Expected: 4 passed

---

## Task 10: data_collector - 指数行情 + 历史

**Files:**
- Modify: `data_collector.py`
- Create: `tests/test_collector_index.py`

### Step 10.1: 实现

```python
_INDICES = {
    "上证指数": "000001",
    "深证成指": "399001",
    "沪深300": "000300",
    "中证1000": "000852",
}


def _index_market_prefix(code: str) -> str:
    return "sh" if code.startswith(("000", "399")) is False or code.startswith("000") else "sh"


def get_index_quotes(progress_callback: ProgressCB = None) -> pd.DataFrame:
    """Fetch 4 major indices realtime quotes."""
    rows = []
    df = ak.stock_zh_index_spot_em(symbol="沪深重要指数")
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
    if progress_callback:
        progress_callback(len(rows), len(rows), f"指数行情: {len(rows)} 个")
    return pd.DataFrame(rows)


def get_index_kline(code: str, days: int = 130) -> pd.DataFrame:
    """Fetch K-line for an index. Returns df with _KLINE_COLS."""
    try:
        df = ak.stock_zh_index_daily_em(symbol=code)
    except Exception:
        return pd.DataFrame(columns=_KLINE_COLS)
    if df is None or df.empty:
        return pd.DataFrame(columns=_KLINE_COLS)
    out = pd.DataFrame({
        "date":   pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
        "open":   df["open"].astype(float),
        "close":  df["close"].astype(float),
        "high":   df["high"].astype(float),
        "low":    df["low"].astype(float),
        "volume": df["volume"].astype(float),
    })
    return out.tail(days).reset_index(drop=True)
```

### Step 10.2: 写测试

```python
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
```

### Step 10.3: 跑测试

Run: `python -m pytest tests/test_collector_index.py -v`
Expected: 2 passed

---

## Task 11: data_collector - run_pipeline 编排

**Files:**
- Modify: `data_collector.py`
- Create: `tests/test_collector_pipeline.py`

### Step 11.1: 实现

```python
def run_pipeline(
    cache,  # StockCache
    force_refresh: bool = False,
    progress_callback: ProgressCB = None,
    max_workers: int = 8,
) -> dict:
    """
    Orchestrate 5-stage pipeline. Returns dict with 'all_data', 'stats', 'cache'.
    """
    stats = {"kline_failures": 0, "realtime_count": 0, "kline_count": 0}
    stage = [0]

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
    else:
        realtime_df = get_realtime_quotes()
        cache.save_realtime(realtime_df)
    stats["realtime_count"] = len(realtime_df)

    # Stage 3
    _stage(3, 5, "阶段3: 历史 K 线")
    pending = set(codes) - cache.completed_codes()
    if force_refresh:
        pending = set(codes)
    if pending:
        kline_map = get_kline_batch(
            list(pending),
            progress_callback=progress_callback,
            max_workers=max_workers,
            on_success=lambda c, df: cache.save_kline(c, df),
        )
    else:
        kline_map = {}
    stats["kline_count"] = cache.completed_codes().__len__()

    # Stage 4
    _stage(4, 5, "阶段4: 指标计算")
    for c in codes:
        if c not in kline_map and cache.has_kline(c):
            kline_map[c] = cache.get_kline(c)
    indicators = compute_indicators(realtime_df, kline_map, progress_callback)

    # 指数块
    index_quotes = get_index_quotes()
    index_rows = []
    for _, ir in index_quotes.iterrows():
        icode = ir["代码"]
        ikl = get_index_kline(icode)
        ma20 = ma60 = ma120 = None
        if not ikl.empty:
            closes = ikl["close"]
            if len(closes) >= 20: ma20 = round(closes.iloc[-20:].mean(), 2)
            if len(closes) >= 60: ma60 = round(closes.iloc[-60:].mean(), 2)
            if len(closes) >= 120: ma120 = round(closes.iloc[-120:].mean(), 2)
        index_rows.append({
            "代码": icode, "名称": ir["名称"], "最新价": ir["最新价"],
            "涨跌幅": ir["涨跌幅"],
            "20日均价": ma20, "60日均价": ma60, "120日均价": ma120,
            "市盈率": None, "市盈率(TTM)": None, "市值": None,
            "最新成交量": None, "最新换手率": None,
            "5日平均成交量": None, "5日最高换手率": None, "5日最低换手率": None,
            "30日平均成交量": None, "30日最高换手率": None, "30日最低换手率": None,
        })
    index_df = pd.DataFrame(index_rows)

    all_data = pd.concat([index_df, indicators], ignore_index=True)
    _stage(5, 5, f"完成: {len(all_data)} 条")
    return {"all_data": all_data, "stats": stats, "cache": cache}
```

### Step 11.2: 写测试(mock 全部数据源)

```python
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from data_collector import run_pipeline


def _fake_kline():
    return pd.DataFrame({
        "date":   pd.date_range("2025-01-01", periods=130, freq="B").strftime("%Y-%m-%d"),
        "open":   10.0, "close": 10.0, "high": 11.0, "low": 9.5, "volume": 1e6,
    })


def test_run_pipeline_uses_cache_on_second_run(tmp_path):
    from cache import StockCache
    cache = StockCache(base_dir=tmp_path)

    fake_codes = ["000001", "600000"]
    fake_realtime = pd.DataFrame({
        "代码": fake_codes, "名称": ["A", "B"],
        "最新价": [10.0, 20.0], "涨跌幅": [1.0, 2.0],
        "成交量": [1e6, 2e6], "换手率": [0.5, 0.8],
        "市盈率-动态": [5.0, 6.0], "市值": [1e9, 2e9],
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

    def fake_realtime_fn():
        call_count["realtime"] += 1
        return fake_realtime

    def fake_hist(symbol, **kwargs):
        call_count["hist"] += 1
        return pd.DataFrame({
            "日期":  pd.date_range("2025-01-01", periods=130, freq="B"),
            "开盘":  10.0, "收盘":  10.0, "最高":  11.0,
            "最低":  9.5, "成交量": 1e6, "成交额": 1e7,
            "振幅": 1.0, "涨跌幅": 1.0, "涨跌额": 0.1, "换手率": 0.5,
        })

    def fake_index_spot(**kwargs):
        return fake_index

    def fake_index_daily(symbol):
        return pd.DataFrame({
            "date":  pd.date_range("2025-01-01", periods=130, freq="B"),
            "open": 10.0, "close": 10.0, "high": 11.0, "low": 9.5, "volume": 1e6,
        })

    with patch("data_collector.get_stock_list", side_effect=fake_stock_list), \
         patch("data_collector.get_realtime_quotes", side_effect=fake_realtime_fn), \
         patch("data_collector.ak") as mock_ak:
        mock_ak.stock_zh_a_hist.side_effect = fake_hist
        mock_ak.stock_zh_index_spot_em.side_effect = fake_index_spot
        mock_ak.stock_zh_index_daily_em.side_effect = fake_index_daily
        # 第一次跑
        result = run_pipeline(cache, force_refresh=True)
        assert len(result["all_data"]) == 4 + 2  # 4 指数 + 2 股票
        assert cache.completed_codes() == {"000001", "600000"}

        # 第二次跑:hist 不应再被调用
        call_count["hist"] = 0
        result2 = run_pipeline(cache, force_refresh=False)
        assert call_count["hist"] == 0  # 走缓存
        assert len(result2["all_data"]) == 6
```

### Step 11.3: 跑测试

Run: `python -m pytest tests/test_collector_pipeline.py -v`
Expected: 1 passed

---

## Task 12: data_exporter - xlsxwriter 格式化

**Files:**
- Modify: `data_exporter.py`
- Create: `tests/test_exporter_format.py`

### Step 12.1: 重写顶部

```python
"""
Data export and filtering module.

Excel export uses xlsxwriter to keep numeric types numeric and apply
percentage / amount formats at the cell level (not string conversion).
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


_PCT_COLS = ["涨跌幅", "最新换手率", "5日最高换手率", "5日最低换手率",
             "30日最高换手率", "30日最低换手率"]
_AMOUNT_COLS = ["市值"]  # 单位:亿元(2 位小数)
_PRICE_COLS = ["最新价", "20日均价", "60日均价", "120日均价"]


def _build_format_map(df: pd.DataFrame) -> dict[str, str]:
    fmt = {}
    for c in df.columns:
        if c in _PCT_COLS:
            fmt[c] = '0.00"%"'
        elif c in _AMOUNT_COLS:
            fmt[c] = '#,##0.00'
        elif c in _PRICE_COLS:
            fmt[c] = '0.00'
        elif c in ["5日平均成交量", "30日平均成交量", "最新成交量"]:
            fmt[c] = '#,##0'
    return fmt
```

### Step 12.2: 重写 export_to_excel

```python
def export_to_excel(
    df: pd.DataFrame,
    filepath: Optional[str] = None,
    sheet_name: str = "Sheet1",
) -> str:
    """Export DataFrame to Excel with xlsxwriter (preserves numeric types)."""
    if filepath is None:
        filepath = f"stock_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = str(filepath)
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
```

### Step 12.3: 写测试

```python
import pandas as pd
from pathlib import Path
from openpyxl import load_workbook
from data_exporter import export_to_excel


def test_export_preserves_numeric_types(tmp_path):
    df = pd.DataFrame({
        "代码": ["000001"],
        "最新价": [10.567],
        "涨跌幅": [5.234],
        "市值": [200e8],
    })
    path = tmp_path / "test.xlsx"
    export_to_excel(df, path)
    wb = load_workbook(path)
    ws = wb.active
    # 数值列保持数字类型
    assert isinstance(ws["B2"].value, float)  # 最新价
    assert isinstance(ws["C2"].value, float)  # 涨跌幅
    assert isinstance(ws["D2"].value, float)  # 市值
    # 涨跌幅单元格应有 num_format 含百分号
    assert "%" in (ws["C2"].number_format or "")


def test_export_filename_default():
    df = pd.DataFrame({"a": [1]})
    path = export_to_excel(df)
    assert Path(path).exists()
    Path(path).unlink()
```

### Step 12.4: 跑测试

Run: `python -m pytest tests/test_exporter_format.py -v`
Expected: 2 passed

---

## Task 13: data_exporter - filter_stocks 统一入口 (TDD)

**Files:**
- Modify: `data_exporter.py`
- Create: `tests/test_filters.py`

### Step 13.1: 实现统一 filter

```python
def _get_csi300_change(df: pd.DataFrame) -> float:
    """精确匹配沪深300 行(按代码),不再靠 str.contains。"""
    row = df[df["代码"] == "000300"]
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
        "window": 30,        # for turnover_*
        "vs_index": "csi300" # 对比基准
    }
    """
    criteria = criteria or {"type": "price_below_ma", "ma_window": 20, "vs_index": "csi300"}
    csi300 = _get_csi300_change(df)

    stock_df = df[~df.apply(_is_index_row, axis=1)].copy()
    ftype = criteria["type"]

    if ftype == "price_below_ma":
        win = criteria.get("ma_window", 20)
        col = f"{win}日均价"
        stock_df = stock_df.dropna(subset=[col, "最新价", "涨跌幅"])
        cond = (stock_df["最新价"] < stock_df[col]) & (stock_df["涨跌幅"] > csi300)
        msg = f"价格<{win}日均线 且 涨幅>{csi300:.2f}%(CSI300)"
    elif ftype == "turnover_above_max":
        win = criteria.get("window", 30)
        col = f"{win}日最高换手率"
        stock_df = stock_df.dropna(subset=[col, "最新换手率", "涨跌幅"])
        cond = (stock_df["最新换手率"] > stock_df[col]) & (stock_df["涨跌幅"] > csi300)
        msg = f"换手率>{win}日最高 且 涨幅>{csi300:.2f}%(CSI300)"
    elif ftype == "turnover_below_min":
        win = criteria.get("window", 30)
        col = f"{win}日最低换手率"
        stock_df = stock_df.dropna(subset=[col, "最新换手率", "涨跌幅"])
        cond = (stock_df["最新换手率"] < stock_df[col]) & (stock_df["涨跌幅"] > csi300)
        msg = f"换手率<{win}日最低 且 涨幅>{csi300:.2f}%(CSI300)"
    else:
        raise ValueError(f"Unknown filter type: {ftype}")

    filtered = stock_df[cond]
    print(f"[筛选] {msg}: {len(filtered)} 只")
    return filtered.reset_index(drop=True)
```

### Step 13.2: 写测试

```python
import pandas as pd
import pytest
from data_exporter import filter_stocks


def _df(include_csi300=True, include_stocks=True):
    rows = []
    if include_csi300:
        rows.append({"代码": "000300", "名称": "[指数] 沪深300",
                     "最新价": 3500, "涨跌幅": 1.0,
                     "20日均价": 3400, "30日最高换手率": 0.8,
                     "30日最低换手率": 0.2, "最新换手率": 0.5})
    if include_stocks:
        rows.append({"代码": "000001", "名称": "A",
                     "最新价": 9.0, "涨跌幅": 2.0,
                     "20日均价": 10.0, "30日最高换手率": 0.6,
                     "30日最低换手率": 0.3, "最新换手率": 0.7})  # 满足全部
        rows.append({"代码": "600000", "名称": "B",
                     "最新价": 11.0, "涨跌幅": 0.5,
                     "20日均价": 10.0, "30日最高换手率": 0.6,
                     "30日最低换手率": 0.3, "最新换手率": 0.7})  # 价格不低
    return pd.DataFrame(rows)


def test_filter_price_below_ma():
    df = _df()
    result = filter_stocks(df, {"type": "price_below_ma", "ma_window": 20})
    assert list(result["代码"]) == ["000001"]


def test_filter_turnover_above_max():
    df = _df()
    result = filter_stocks(df, {"type": "turnover_above_max", "window": 30})
    # 000001: 0.7 > 0.6 且 2.0 > 1.0 → 命中
    assert "000001" in list(result["代码"])


def test_filter_turnover_below_min():
    df = _df()
    # 改 000001 的最新换手率为 0.25(低于 0.3)
    df.loc[df["代码"] == "000001", "最新换手率"] = 0.25
    result = filter_stocks(df, {"type": "turnover_below_min", "window": 30})
    assert "000001" in list(result["代码"])


def test_filter_handles_negative_csi300():
    df = _df()
    df.loc[df["代码"] == "000300", "涨跌幅"] = -2.0
    # 000001 涨幅 2.0 > -2.0,仍命中
    result = filter_stocks(df, {"type": "price_below_ma", "ma_window": 20})
    assert "000001" in list(result["代码"])


def test_filter_excludes_index_rows():
    df = _df()
    result = filter_stocks(df, {"type": "price_below_ma", "ma_window": 20})
    assert "[指数]" not in " ".join(result["名称"].astype(str).tolist())


def test_filter_empty_when_no_csi300(caplog):
    df = _df(include_csi300=False)
    # csi300 默认 0.0,需要涨跌幅 > 0 才命中。000001 涨 2.0 → 仍命中
    result = filter_stocks(df, {"type": "price_below_ma", "ma_window": 20})
    assert "000001" in list(result["代码"])
```

### Step 13.3: 跑测试

Run: `python -m pytest tests/test_filters.py -v`
Expected: 6 passed

---

## Task 14: data_exporter - filter_export

**Files:**
- Modify: `data_exporter.py`
- Create: `tests/test_exporter_filter_export.py`

### Step 14.1: 实现

```python
_FILTER_NAME_MAP = {
    "price_below_ma": "price_below_ma",
    "turnover_above_max": "turnover_above_max",
    "turnover_below_min": "turnover_below_min",
}


def filter_export(
    filtered_df: pd.DataFrame,
    filepath: Optional[str] = None,
    filter_type: str = "filtered",
) -> str:
    if filepath is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"{filter_type}_{ts}.xlsx"
    return export_to_excel(filtered_df, filepath, sheet_name=filter_type)
```

### Step 14.2: 写测试

```python
import pandas as pd
from pathlib import Path
from data_exporter import filter_export


def test_filter_export_creates_file(tmp_path):
    df = pd.DataFrame({"代码": ["000001"], "最新价": [10.0]})
    path = filter_export(df, str(tmp_path / "out.xlsx"), filter_type="price_below_ma")
    assert Path(path).exists()
```

### Step 14.3: 跑测试

Run: `python -m pytest tests/test_exporter_filter_export.py -v`
Expected: 1 passed

---

## Task 15: gui_app - 修复 4 个 P0 Bug

**Files:**
- Modify: `gui_app.py`

### Step 15.1: 修改 `__init__` 加 `current_filter` 和 `is_collecting`

替换 `gui_app.py:18-26` 的 `__init__`:

```python
class StockAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("A股数据分析工具")
        self.root.geometry("900x600")

        self.all_data = None
        self.filtered_data = None
        self.current_filter: str = "filter1"   # 修复 P0 #1
        self.is_collecting: bool = False        # 修复 P0 #7
        self._current_filter_type: str = "price_below_ma"  # for export

        self._build_ui()
```

### Step 15.2: 修改 `_on_collect` 加防重入

替换 `gui_app.py:119-126`:

```python
def _on_collect(self):
    if self.is_collecting:
        messagebox.showinfo("提示", "数据收集中,请稍候")
        return
    self.is_collecting = True
    self.btn_collect.configure(state=tk.DISABLED)
    self.status_var.set("正在收集数据,请稍候...")
    self.progress.configure(value=0)
    self._log("开始收集 A 股数据...")

    thread = threading.Thread(target=self._collect_task, daemon=True)
    thread.start()
```

### Step 15.3: 替换 `_on_collect_done` 释放标志

替换 `gui_app.py:181-188`:

```python
def _on_collect_done(self):
    self.is_collecting = False
    self.progress.configure(value=100)
    self.btn_collect.configure(state=tk.NORMAL)
    self.btn_filter.configure(state=tk.NORMAL)
    self.btn_export_all.configure(state=tk.NORMAL)
    self.status_var.set(f"数据收集完成,共 {len(self.all_data)} 条记录")
    self._log("数据收集完成!")
    self._populate_tree(self.all_data)


def _on_collect_error(self, error_msg):
    self.is_collecting = False
    self.progress.configure(value=0)
    self.btn_collect.configure(state=tk.NORMAL)
    self.status_var.set("数据收集失败")
    self._log(f"错误: {error_msg}")
    messagebox.showerror("错误", f"数据收集失败:\n{error_msg}")
```

### Step 15.4: 修复 `_on_filter` 记录 current_filter

替换 `gui_app.py:197-222`:

```python
def _on_filter(self):
    if self.all_data is None:
        messagebox.showwarning("警告", "请先收集数据")
        return

    filter_map = {
        "filter1": ("价格低于20日均线", "price_below_ma",
                    {"type": "price_below_ma", "ma_window": 20, "vs_index": "csi300"}),
        "filter2": ("换手率>30日最高", "turnover_above_max",
                    {"type": "turnover_above_max", "window": 30, "vs_index": "csi300"}),
        "filter3": ("换手率<30日最低", "turnover_below_min",
                    {"type": "turnover_below_min", "window": 30, "vs_index": "csi300"}),
    }
    key = self.filter_var.get()
    name, ftype, criteria = filter_map.get(key, filter_map["filter1"])
    self.current_filter = key
    self._current_filter_type = ftype

    self.status_var.set(f"正在筛选: {name}...")
    self._log(f"开始筛选: {name}")
    from data_exporter import filter_stocks
    self.filtered_data = filter_stocks(self.all_data, criteria)
    self._log(f"筛选完成,找到 {len(self.filtered_data)} 只符合条件的股票")
    if not self.filtered_data.empty:
        self.btn_export_filtered.configure(state=tk.NORMAL)
        self._populate_tree(self.filtered_data)
    else:
        self._log("没有股票符合筛选条件")
```

### Step 15.5: 修复 `_on_export_filtered` 使用 `self._current_filter_type`

替换 `gui_app.py:237-256`:

```python
def _on_export_filtered(self):
    if self.filtered_data is None or self.filtered_data.empty:
        messagebox.showwarning("警告", "没有筛选数据可导出")
        return
    filepath = filedialog.asksaveasfilename(
        defaultextension=".xlsx",
        filetypes=[("Excel files", "*.xlsx")],
        initialfile=f"filtered_{self._current_filter_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    )
    if filepath:
        from data_exporter import filter_export
        filter_export(self.filtered_data, filepath, filter_type=self._current_filter_type)
        self._log(f"筛选结果已导出: {filepath}")
        messagebox.showinfo("成功", f"筛选结果已导出到:\n{filepath}")
```

### Step 15.6: 跑现有测试,确保没破坏

Run: `python -m pytest tests/ -v`
Expected: all previous tests pass

> GUI 代码主要靠端到端测试。检查 `python -c "import gui_app"` 能成功导入即视为通过。

Run: `python -c "import gui_app; print('ok')`
Expected: `ok`

---

## Task 16: gui_app - 进度回调接 pipeline + 阶段日志

**Files:**
- Modify: `gui_app.py`

### Step 16.1: 重写 `_collect_task` 调 `run_pipeline`

替换 `gui_app.py:128-159`:

```python
def _collect_task(self):
    try:
        from cache import StockCache
        from data_collector import run_pipeline

        cache = StockCache(base_dir=Path(__file__).parent / "data_cache")

        def _progress(done: int, total: int, msg: str):
            pct = min(100, int(done / total * 100)) if total else 0
            self.root.after(0, lambda: self.progress.configure(value=pct))
            if msg:
                self.root.after(0, lambda m=msg: self._log(m))

        result = run_pipeline(cache, force_refresh=False, progress_callback=_progress)
        self.all_data = result["all_data"]
        self.root.after(0, self._on_collect_done)

    except Exception as e:
        self.root.after(0, lambda: self._on_collect_error(str(e)))
```

### Step 16.2: 添加 `Path` import 到 `gui_app.py` 顶部

替换 `gui_app.py:1-13` 的 imports:

```python
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
from pathlib import Path
from datetime import datetime
import pandas as pd

from data_collector import run_pipeline
from data_exporter import filter_stocks, export_to_excel, filter_export
from cache import StockCache
```

### Step 16.3: 移除 `from data_collector import get_all_a_stocks_realtime, process_stock_data, process_index_data`(旧的已废弃)

> 已在 16.2 替换。

### Step 16.4: 跑 import smoke test

Run: `python -c "import gui_app; print('ok')"`
Expected: `ok`

---

## Task 17: gui_app - Treeview 分页(200 行/页)

**Files:**
- Modify: `gui_app.py`

### Step 17.1: 在 `_build_ui` 添加分页按钮

在 `gui_app.py:90-95` 的 log_frame 之前添加:

```python
# Pagination
pg_frame = ttk.Frame(self.root, padding=(10, 0))
pg_frame.pack(side=tk.TOP, fill=tk.X)
self._pg_state = {"offset": 0, "page_size": 200, "df": None}
self.btn_prev = ttk.Button(pg_frame, text="<< 上一页", command=self._on_prev_page, state=tk.DISABLED)
self.btn_prev.pack(side=tk.LEFT, padx=5)
self.pg_label = ttk.Label(pg_frame, text="")
self.pg_label.pack(side=tk.LEFT, padx=5)
self.btn_next = ttk.Button(pg_frame, text="下一页 >>", command=self._on_next_page, state=tk.DISABLED)
self.btn_next.pack(side=tk.LEFT, padx=5)
```

### Step 17.2: 重写 `_populate_tree` + 新增分页方法

替换 `gui_app.py:112-117`:

```python
def _populate_tree(self, df: pd.DataFrame):
    self._pg_state["df"] = df
    self._pg_state["offset"] = 0
    self._render_page()

def _render_page(self):
    df = self._pg_state["df"]
    if df is None:
        return
    offset = self._pg_state["offset"]
    page = df.iloc[offset: offset + self._pg_state["page_size"]]
    self.tree.delete(*self.tree.get_children())
    self._set_columns(df)
    for _, row in page.iterrows():
        values = ["" if pd.isna(v) else v for v in row]
        self.tree.insert("", tk.END, values=values)
    total = len(df)
    end = min(offset + self._pg_state["page_size"], total)
    self.pg_label.configure(text=f"第 {offset+1}-{end} 行 / 共 {total} 行")
    self.btn_prev.configure(state=(tk.NORMAL if offset > 0 else tk.DISABLED))
    self.btn_next.configure(state=(tk.NORMAL if end < total else tk.DISABLED))

def _on_prev_page(self):
    self._pg_state["offset"] = max(0, self._pg_state["offset"] - self._pg_state["page_size"])
    self._render_page()

def _on_next_page(self):
    df = self._pg_state["df"]
    if df is None: return
    new_offset = self._pg_state["offset"] + self._pg_state["page_size"]
    if new_offset < len(df):
        self._pg_state["offset"] = new_offset
        self._render_page()
```

### Step 17.3: smoke test

Run: `python -c "import gui_app; print('ok')"`
Expected: `ok`

---

## Task 18: main.py 调统一管线

**Files:**
- Modify: `main.py`

### Step 18.1: 完整重写

```python
"""
Main entry point for the A-Stock Data Analysis Tool.

Usage:
    python main.py           # Launch GUI
    python main.py --cli     # Run in command-line mode
    python main.py --clear   # Clear all cached data
"""
import sys
from pathlib import Path


def main():
    if "--clear" in sys.argv:
        from cache import StockCache
        cache = StockCache(base_dir=Path(__file__).parent / "data_cache")
        cache.clear()
        print("缓存已清空")
        return

    if "--cli" in sys.argv:
        _run_cli()
    else:
        _run_gui()


def _run_gui():
    from gui_app import main as gui_main
    gui_main()


def _run_cli():
    """Command-line mode: 5-stage pipeline with progress."""
    from cache import StockCache
    from data_collector import run_pipeline
    from data_exporter import filter_stocks, export_to_excel, filter_export

    print("=" * 60)
    print("A股数据分析工具 - 命令行模式")
    print("=" * 60)

    cache = StockCache(base_dir=Path(__file__).parent / "data_cache")
    last_msg = None

    def _progress(done: int, total: int, msg: str):
        nonlocal last_msg
        if msg and msg != last_msg:
            print(f"\n[{msg}]")
            last_msg = msg
        if total:
            print(f"\r  进度: {done}/{total} ({done*100//total}%)", end="", flush=True)

    try:
        result = run_pipeline(cache, progress_callback=_progress)
    except KeyboardInterrupt:
        print("\n\n已中断,已抓数据已落盘,下次运行自动续传")
        return

    print(f"\n\n[完成] 共 {len(result['all_data'])} 条记录")

    all_path = export_to_excel(result["all_data"])
    print(f"[导出] 全部数据: {all_path}")

    print("\n[筛选] 价格<20日均线 且 涨幅>沪深300")
    filtered = filter_stocks(result["all_data"], {
        "type": "price_below_ma", "ma_window": 20, "vs_index": "csi300"
    })
    if not filtered.empty:
        path = filter_export(filtered, filter_type="price_below_ma")
        print(f"[导出] 筛选结果: {path}")
        cols = ["名称", "代码", "最新价", "涨跌幅", "20日均价"]
        print("\n符合条件的股票:")
        print(filtered[cols].to_string(index=False))
    else:
        print("没有股票符合筛选条件")


if __name__ == "__main__":
    main()
```

### Step 18.2: 跑 import smoke + CLI help

Run: `python main.py --clear`
Expected: `缓存已清空`

Run: `python -c "import main; print('ok')"`
Expected: `ok`

---

## Task 19: requirements.txt 更新

**Files:**
- Modify: `requirements.txt`

### Step 19.1: 完整替换

```
akshare>=1.13.0
pandas>=2.0.0
openpyxl>=3.1.0
xlsxwriter>=3.1.0
pyarrow>=14.0.0
tenacity>=8.2.0
requests>=2.31.0
pytest>=7.4.0
```

### Step 19.2: 安装依赖

Run: `pip install -r requirements.txt`
Expected: 全部安装成功

---

## Task 20: 端到端验证

**Files:** (无新增,验收)

### Step 20.1: 跑完整测试套件

Run: `python -m pytest tests/ -v`
Expected: 全部通过(应 ≥ 27 个用例)

### Step 20.2: 真实跑一次 CLI(需要网络)

Run: `python main.py --clear`
Expected: `缓存已清空`

Run: `python main.py --cli`
Expected:
- 输出 `[阶段1: 股票清单]` ~ `[阶段5]` 各阶段进度
- 阶段 3 进度条从 0 → 5300(约 5000+ 股票)
- 整个流程 < 5 分钟(目标 < 2 分钟)
- 末尾打印 `[完成] 共 N 条` + `[导出] 全部数据: ...xlsx` + `[筛选] ...` + 命中股票列表

### Step 20.3: 第二次跑验证缓存

Run: `python main.py --cli`
Expected:
- < 30 秒完成
- 阶段 3 进度立刻跳到 100%(没有 pending 股票)
- 阶段 1-2 也走缓存

### Step 20.4: 验证 Excel 数字格式

Run: `python -c "from openpyxl import load_workbook; wb=load_workbook('<刚导出的xlsx>'); ws=wb.active; print(ws['C2'].value, type(ws['C2'].value).__name__, ws['C2'].number_format)"`
Expected: 类似 `1.5 float 0.00"%"` — 数字仍是 float,带百分比格式

### Step 20.5: GUI smoke test

Run: `python -c "import gui_app; root=__import__('tkinter').Tk(); app=gui_app.StockAnalyzerApp(root); print('GUI initialized')"`
Expected: `GUI initialized` (无异常)

> 不实际打开窗口(交互式),仅确认无 import 错误。

### Step 20.6: 验收清单

| 验收项 | 验证命令 | 通过标准 |
|---|---|---|
| 4 个 P0 Bug 修复 | `pytest tests/` | 全绿 |
| 数据源切 akshare | Task 11 测试中 `patch("data_collector.ak")` | 旧 HTTP 函数已删除 |
| 断点续传 | Step 20.3 第二次 < 30s | 阶段 3 进度立刻 100% |
| 进度提示 | Step 20.2 CLI 输出 | 5 个阶段都有 `[阶段X: ...]` 日志 |
| Excel 数字保持数值 | Step 20.4 openpyxl 检查 | 百分比列仍是 float,带 num_format |
| GUI 启动 | Step 20.5 | 无 import 错误 |

---

## 自审报告

**Spec 覆盖**:
- §2 5 阶段管道 → Task 6-11 ✓
- §3.1 cache.py → Task 1-5 ✓
- §3.2 data_collector 重写 + akshare + 并发 + 重试 → Task 6-11 ✓
- §3.3 data_exporter xlsxwriter + 统一 filter → Task 12-14 ✓
- §3.4 gui_app 4 P0 + 进度回调 + 分页 → Task 15-17 ✓
- §3.5 main.py 统一管线 → Task 18 ✓
- §3.6 requirements.txt → Task 19 ✓
- §6 测试 → 散落在各 Task 的 `_test_*.py` 中,合并 ≥ 27 用例 ✓

**占位符扫描**: 无 TBD/TODO/模糊表述。

**类型一致性**:
- `StockCache(base_dir=...)` ✓
- `get_stock_list() -> list[str]` ✓
- `get_realtime_quotes() -> pd.DataFrame` ✓
- `get_kline_batch(codes, progress_callback, max_workers, on_success) -> dict[str, pd.DataFrame]` ✓
- `compute_indicators(rt, kline_map, progress) -> pd.DataFrame` ✓
- `run_pipeline(cache, force_refresh, progress, max_workers) -> dict` ✓
- `filter_stocks(df, criteria) -> pd.DataFrame` ✓
- `export_to_excel(df, filepath, sheet_name) -> str` ✓
- `filter_export(df, filepath, filter_type) -> str` ✓

**准备开始执行。**
