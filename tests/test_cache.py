import unittest.mock
import pytest
from cache import StockCache


def test_cache_creates_data_dir(tmp_path):
    cache = StockCache(base_dir=tmp_path)
    assert (tmp_path / "data").exists()
    assert (tmp_path / "data" / "history.db").exists()


def test_cache_idempotent_init(tmp_path):
    StockCache(base_dir=tmp_path)
    StockCache(base_dir=tmp_path)
    assert (tmp_path / "data" / "history.db").exists()


def test_get_stock_list_empty_when_no_cache(tmp_cache):
    assert tmp_cache.get_stock_list() == []


def test_save_and_load_stock_list(tmp_cache):
    codes = ["000001", "600000", "688001"]
    tmp_cache.save_stock_list(codes)
    assert tmp_cache.get_stock_list() == codes


def test_get_stock_list_ttl_respected(tmp_cache):
    tmp_cache.save_stock_list(["000001"])
    assert tmp_cache.get_stock_list(ttl_days=0) == []
    assert tmp_cache.get_stock_list(ttl_days=7) == ["000001"]


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
    # Mock market closed and file saved after 15:05 CST
    from datetime import datetime, timezone, timedelta
    import os
    cst = timezone(timedelta(hours=8))
    mock_now = datetime.now(cst).replace(hour=16, minute=0, second=0)
    mock_mtime = mock_now.timestamp()
    
    mock_stat = unittest.mock.MagicMock()
    mock_stat.st_mtime = mock_mtime
    
    with unittest.mock.patch.object(StockCache, "market_now_open", return_value=False), \
         unittest.mock.patch("cache._now_cst", return_value=mock_now), \
         unittest.mock.patch("pathlib.Path.stat", return_value=mock_stat):
        assert tmp_cache.is_realtime_fresh() is True


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
    assert len(loaded) == 130


def test_has_kline(tmp_cache, sample_kline_df):
    assert tmp_cache.has_kline("000001") is False
    tmp_cache.save_kline("000001", sample_kline_df)
    assert tmp_cache.has_kline("000001") is True


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


def test_schema_migration_clears_poisoned_stock_info(tmp_path):
    """Re-opening a v1 DB (user_version < 2) must invalidate stock_info,
    since total_shares were cached with a 100x unit bug."""
    cache = StockCache(base_dir=tmp_path)
    cache.save_total_shares("000001", 1e10)
    cache.close()
    # Simulate an old DB that predates the v2 migration.
    import sqlite3
    conn = sqlite3.connect(tmp_path / "data" / "history.db")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    cache2 = StockCache(base_dir=tmp_path)
    assert cache2.get_total_shares("000001") is None
    cache2.close()

    # And the version is now bumped so the migration is idempotent.
    conn = sqlite3.connect(tmp_path / "data" / "history.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    conn.close()
