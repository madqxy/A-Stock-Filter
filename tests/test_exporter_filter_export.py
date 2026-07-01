import pandas as pd
from pathlib import Path
from data_exporter import filter_export


def test_filter_export_creates_file(tmp_path):
    df = pd.DataFrame({"代码": ["000001"], "最新价": [10.0]})
    path = filter_export(df, str(tmp_path / "out.xlsx"), filter_type="price_below_ma")
    assert Path(path).exists()
