from unittest.mock import patch

import pandas as pd

from data_collector import _INDICES, get_index_kline, get_index_quotes


def _quote_line(sym: str, code: str, name: str, price: str, chg: str) -> str:
    fields = ["1", name, code, price, "0", "0", "0", "0", "0", "0", "0", "0",
              "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
              "0", "0", "0", "0", "0", "0", "0", "0", chg]
    while len(fields) < 40:
        fields.append("0")
    return f'v_{sym}="{ "~".join(fields) }";'


class _QuoteResp:
    def __init__(self, text: str):
        self.text = text


class _KlineResp:
    def __init__(self, bars):
        self._bars = bars

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": {"sh000300": {"qfqday": self._bars}}}


class _Session:
    def __init__(self, resp):
        self._resp = resp
        self.url = None

    def get(self, url, timeout=None):
        self.url = url
        return self._resp


def test_get_index_quotes_parses_all_seven_indices():
    lines = []
    for name, code in _INDICES.items():
        pref = "sz" if code.startswith("399") else "sh"
        lines.append(_quote_line(f"{pref}{code}", code, name,
                                 "3000.00" if code != "399001" else "10000.00",
                                 "0.50" if code != "399001" else "1.00"))
    with patch("data_collector.requests.get",
               return_value=_QuoteResp(";".join(lines))) as m:
        df = get_index_quotes()
    assert len(df) == 7
    assert sorted(df["代码"].tolist()) == sorted(_INDICES.values())
    assert all(df["名称"].str.startswith("[指数]"))
    syms = m.call_args.args[0]
    assert "sh000001" in syms and "sh000905" in syms
    assert "sz399001" in syms and "sz399006" in syms


def test_get_index_quotes_returns_empty_on_http_error():
    with patch("data_collector.requests.get", side_effect=OSError("boom")):
        df = get_index_quotes()
    assert df.empty


def test_get_index_kline_normalizes_columns():
    bars = [[f"2025-01-0{i}", 1.0, 2.0, 3.0, 0.5, 100.0] for i in range(1, 6)]
    with patch("data_collector._http_session",
               return_value=_Session(_KlineResp(bars))):
        df = get_index_kline("000300", days=130)
    assert list(df.columns) == ["date", "open", "close", "high", "low", "volume"]
    assert len(df) == 5


def test_get_index_kline_returns_empty_on_missing_data():
    with patch("data_collector._http_session",
               return_value=_Session(_KlineResp([]))):
        df = get_index_kline("000300")
    assert df.empty
    assert list(df.columns) == ["date", "open", "close", "high", "low", "volume"]
