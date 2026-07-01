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
    assert isinstance(ws["B2"].value, (int, float))
    assert isinstance(ws["C2"].value, (int, float))
    assert isinstance(ws["D2"].value, (int, float))
    assert "%" in (ws["C2"].number_format or "")


def test_export_filename_default():
    df = pd.DataFrame({"a": [1]})
    path = export_to_excel(df)
    try:
        assert Path(path).exists()
        assert path.startswith("stock_data_")
        assert path.endswith(".xlsx")
    finally:
        Path(path).unlink(missing_ok=True)
