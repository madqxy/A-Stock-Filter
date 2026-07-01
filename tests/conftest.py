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
