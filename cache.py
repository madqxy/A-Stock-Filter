"""
Stock data cache layer: SQLite for K-line history, parquet for daily snapshots.

The SQLite connection is kept open for the lifetime of the StockCache
instance, with WAL journal_mode for better concurrent-read performance.
Call `close()` to release the connection (e.g. on app shutdown).
"""
import json
import sqlite3
import threading
import time
from datetime import datetime, date as _date, timezone as _tz, timedelta as _td
from pathlib import Path
from typing import Optional

import pandas as pd


_CST = _tz(_td(hours=8))


def _now_cst() -> datetime:
    """Current wall-clock time in China Standard Time (UTC+8), tz-aware."""
    return datetime.now(_CST)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS kline (
    code     TEXT NOT NULL,
    date     TEXT NOT NULL,
    open     REAL,
    close    REAL,
    high     REAL,
    low      REAL,
    volume   REAL,
    is_index INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_kline_code ON kline(code);

CREATE TABLE IF NOT EXISTS stock_info (
    code         TEXT PRIMARY KEY,
    total_shares REAL,
    updated_at   TEXT
);
"""

_MIGRATIONS = [
    # idempotent: ALTER TABLE ADD COLUMN fails if column already exists
    "ALTER TABLE kline ADD COLUMN is_index INTEGER NOT NULL DEFAULT 0",
]


class StockCache:
    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "history.db"
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    def _get_conn(self) -> sqlite3.Connection:
        """Return the singleton connection, creating it lazily. NOT thread-safe —
        callers must hold self._lock."""
        if self._conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA cache_size=-8000")  # 8 MB
            self._conn = conn
        return self._conn

    def close(self):
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Time helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _now_cst() -> datetime:
        return _now_cst()

    @staticmethod
    def market_now_open() -> bool:
        """A-share market hours (CST): 9:30-11:30, 13:00-15:00 on weekdays."""
        now = _now_cst()
        if now.weekday() >= 5:
            return False
        t = now.hour * 60 + now.minute
        return (570 <= t <= 690) or (780 <= t <= 900)

    @staticmethod
    def market_today_close() -> datetime:
        """Return today's 15:00 CST as a tz-aware datetime."""
        return _now_cst().replace(hour=15, minute=0, second=0, microsecond=0)

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------
    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            conn.executescript(_SCHEMA)
            for sql in _MIGRATIONS:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        raise
            conn.commit()

    # ------------------------------------------------------------------
    # Stock list
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Realtime parquet snapshots
    # ------------------------------------------------------------------
    def _realtime_path(self, day: Optional[_date] = None) -> Path:
        d = day or _now_cst().date()
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
        """Fresh if market closed and cache was saved after close (CST >= 15:05),
        or market is open and cache exists from today."""
        path = self._realtime_path()
        if not path.exists():
            return False
        now = _now_cst()
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=_CST)
        if mtime.date() != now.date():
            return False
        if self.market_now_open():
            return True
        # Market closed: cache only fresh if saved after close (15:05+)
        return mtime.hour > 15 or (mtime.hour == 15 and mtime.minute >= 5)

    # ------------------------------------------------------------------
    # K-line
    # ------------------------------------------------------------------
    def save_kline(self, code: str, df: pd.DataFrame, is_index: bool = False, append_only: bool = False):
        if df.empty:
            return
        flag = 1 if is_index else 0
        rows = [
            (code, str(r.date), float(r.open), float(r.close),
             float(r.high), float(r.low), float(r.volume), flag)
            for r in df.itertuples(index=False)
        ]
        op = "INSERT OR IGNORE" if append_only else "INSERT OR REPLACE"
        with self._lock:
            conn = self._get_conn()
            conn.executemany(
                f"{op} INTO kline "
                f"(code, date, open, close, high, low, volume, is_index) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()

    def save_kline_batch(
        self,
        data: dict[str, pd.DataFrame],
        is_index: bool = False,
        append_only: bool = False,
    ):
        """Bulk-insert K-line rows for many codes in a single transaction."""
        if not data:
            return
        flag = 1 if is_index else 0
        rows = []
        for code, df in data.items():
            if df.empty:
                continue
            for r in df.itertuples(index=False):
                rows.append((code, str(r.date), float(r.open), float(r.close),
                             float(r.high), float(r.low), float(r.volume), flag))
        if not rows:
            return
        op = "INSERT OR IGNORE" if append_only else "INSERT OR REPLACE"
        with self._lock:
            conn = self._get_conn()
            conn.executemany(
                f"{op} INTO kline "
                f"(code, date, open, close, high, low, volume, is_index) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()

    def get_kline(self, code: str) -> Optional[pd.DataFrame]:
        with self._lock:
            cur = self._get_conn().execute(
                "SELECT date, open, close, high, low, volume FROM kline "
                "WHERE code = ? ORDER BY date",
                (code,),
            )
            rows = cur.fetchall()
        if not rows:
            return None
        return pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])

    def has_kline(self, code: str, is_index: Optional[bool] = None) -> bool:
        with self._lock:
            if is_index is None:
                cur = self._get_conn().execute(
                    "SELECT 1 FROM kline WHERE code = ? LIMIT 1", (code,)
                )
            else:
                cur = self._get_conn().execute(
                    "SELECT 1 FROM kline WHERE code = ? AND is_index = ? LIMIT 1",
                    (code, 1 if is_index else 0),
                )
            return cur.fetchone() is not None

    def trim_kline(self, keep_bars: int = 200, is_index: bool = False) -> int:
        """Trim K-line cache to keep only the last `keep_bars` per stock.
        
        Removes old data that's no longer needed for MA calculations.
        Returns number of rows deleted.
        """
        flag = 1 if is_index else 0
        total_deleted = 0
        with self._lock:
            conn = self._get_conn()
            # Get all codes
            codes = [row[0] for row in conn.execute(
                "SELECT DISTINCT code FROM kline WHERE is_index = ?", (flag,)
            ).fetchall()]
            
            for code in codes:
                # Delete rows beyond keep_bars (oldest first)
                cur = conn.execute(
                    f"DELETE FROM kline WHERE code = ? AND is_index = ? AND date <= ("
                    f"  SELECT date FROM kline "
                    f"  WHERE code = ? AND is_index = ? "
                    f"  ORDER BY date DESC LIMIT 1 OFFSET ?"
                    f")",
                    (code, flag, code, flag, keep_bars - 1),
                )
                total_deleted += cur.rowcount
            conn.commit()
        return total_deleted

    def completed_codes(self, include_index: bool = False) -> set[str]:
        with self._lock:
            if include_index:
                cur = self._get_conn().execute("SELECT DISTINCT code FROM kline")
            else:
                cur = self._get_conn().execute(
                    "SELECT DISTINCT code FROM kline WHERE is_index = 0"
                )
            return {row[0] for row in cur.fetchall()}

    def max_kline_date(self, codes: Optional[list[str]] = None, include_index: bool = False) -> Optional[str]:
        """Latest date across cached K-lines. Optionally filter by codes list."""
        with self._lock:
            conn = self._get_conn()
            where = ["is_index = 0"] if not include_index else []
            params: list = []
            if codes:
                placeholders = ",".join("?" for _ in codes)
                where.append(f"code IN ({placeholders})")
                params.extend(codes)
            clause = (" WHERE " + " AND ".join(where)) if where else ""
            cur = conn.execute(f"SELECT MAX(date) FROM kline{clause}", params)
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def stale_kline_codes(
        self,
        cutoff_date: str,
        codes: Optional[list[str]] = None,
        include_index: bool = False,
    ) -> set[str]:
        """Return codes whose latest cached K-line date < cutoff_date. Optionally filter by codes list."""
        with self._lock:
            conn = self._get_conn()
            where = ["is_index = 0"] if not include_index else []
            params: list = []
            if codes:
                placeholders = ",".join("?" for _ in codes)
                where.append(f"code IN ({placeholders})")
                params.extend(codes)
            params.append(cutoff_date)
            clause = (" WHERE " + " AND ".join(where)) if where else ""
            cur = conn.execute(
                f"SELECT code, MAX(date) FROM kline{clause} "
                f"GROUP BY code HAVING MAX(date) < ?",
                params,
            )
            return {row[0] for row in cur.fetchall()}

    def cached_weeks(self) -> int:
        """Count distinct ISO weeks in the stock (non-index) K-line cache.

        Used by the pipeline to decide whether a wide initial fetch is needed
        to populate long-period weekly MAs (e.g. 24周均价).
        """
        with self._lock:
            cur = self._get_conn().execute(
                "SELECT MIN(date), MAX(date) FROM kline WHERE is_index = 0"
            )
            row = cur.fetchone()
        if not row or not row[0] or not row[1]:
            return 0
        try:
            d_min = datetime.strptime(row[0], "%Y-%m-%d").date()
            d_max = datetime.strptime(row[1], "%Y-%m-%d").date()
        except ValueError:
            return 0
        iso_min = d_min.isocalendar()
        iso_max = d_max.isocalendar()
        # Rough week-delta; ISO year rollover is handled by counting total weeks.
        weeks = (iso_max[0] - iso_min[0]) * 52 + (iso_max[1] - iso_min[1]) + 1
        return max(0, weeks)

    def max_kline_date_per_code(
        self, codes: list[str], include_index: bool = False
    ) -> dict[str, str]:
        """Return {code: MAX(date)} in a single SQL statement.

        Codes with no cached rows are omitted from the result.
        """
        if not codes:
            return {}
        with self._lock:
            conn = self._get_conn()
            placeholders = ",".join("?" for _ in codes)
            idx_clause = "" if include_index else " AND is_index = 0"
            cur = conn.execute(
                f"SELECT code, MAX(date) FROM kline "
                f"WHERE code IN ({placeholders}){idx_clause} "
                f"GROUP BY code",
                codes,
            )
            return {row[0]: row[1] for row in cur.fetchall() if row[1]}

    def latest_trade_date(self) -> _date:
        """Latest (possibly today's) trading date in CST, weekend-aware.

        - Weekday + market closed (>= 15:00): returns today
        - Weekday + market still open: returns previous weekday (intraday data incomplete)
        - Weekend: returns the previous Friday
        - Does NOT account for public holidays; callers tolerate harmless empty fetches.
        """
        now = _now_cst()
        d = now.date()
        # Market closes at 15:00 CST; before that today's bar is incomplete.
        if now.weekday() < 5 and not (now.hour > 15 or (now.hour == 15 and now.minute >= 5)):
            d = d - _td(days=1)
        # Roll back weekends
        while d.weekday() >= 5:
            d = d - _td(days=1)
        return d

    # ------------------------------------------------------------------
    # Stock info (total shares, etc.)
    # ------------------------------------------------------------------
    def save_total_shares(self, code: str, total_shares: float):
        """Save total shares for a stock."""
        now_str = _now_cst().isoformat()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO stock_info (code, total_shares, updated_at) "
                "VALUES (?, ?, ?)",
                (code, total_shares, now_str),
            )
            conn.commit()

    def save_total_shares_batch(self, data: dict[str, float]):
        """Batch save total shares for multiple stocks."""
        if not data:
            return
        now_str = _now_cst().isoformat()
        rows = [(code, shares, now_str) for code, shares in data.items()]
        with self._lock:
            conn = self._get_conn()
            conn.executemany(
                "INSERT OR REPLACE INTO stock_info (code, total_shares, updated_at) "
                "VALUES (?, ?, ?)",
                rows,
            )
            conn.commit()

    def get_total_shares(self, code: str) -> Optional[float]:
        """Get cached total shares for a stock."""
        with self._lock:
            cur = self._get_conn().execute(
                "SELECT total_shares FROM stock_info WHERE code = ?",
                (code,),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def get_total_shares_batch(self, codes: list[str]) -> dict[str, float]:
        """Get cached total shares for multiple stocks."""
        if not codes:
            return {}
        with self._lock:
            conn = self._get_conn()
            placeholders = ",".join("?" for _ in codes)
            cur = conn.execute(
                f"SELECT code, total_shares FROM stock_info WHERE code IN ({placeholders})",
                codes,
            )
            return {row[0]: row[1] for row in cur.fetchall()}

    def clear(self):
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM kline")
            conn.execute("DELETE FROM stock_info")
            conn.commit()
        for p in self.data_dir.glob("realtime_*.parquet"):
            p.unlink()
        list_path = self._stock_list_path()
        if list_path.exists():
            list_path.unlink()
