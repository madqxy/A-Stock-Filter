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
