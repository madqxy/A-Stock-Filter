"""Compare K-line data sources speed and quality on the same 5 stocks."""
import time
import akshare as ak


CODES = ["000001", "600519", "300750", "688981", "000876"]


def bench(label, fn):
    t0 = time.perf_counter()
    ok = fail = 0
    rows_total = 0
    for code in CODES:
        try:
            df = fn(code)
            if df is not None and not df.empty:
                ok += 1
                rows_total += len(df)
            else:
                fail += 1
        except Exception as e:
            fail += 1
            print(f"  [{label}] {code} ERROR: {type(e).__name__}: {e}")
    elapsed = time.perf_counter() - t0
    print(f"  [{label:22s}] {ok}/{len(CODES)} ok, rows={rows_total}, {elapsed:.2f}s  ({elapsed/len(CODES):.2f}s/stock)")


print("=== Per-source benchmark (5 stocks) ===\n")

# 1. 腾讯镜像 (current)
bench("tencent tx (current)", lambda c: ak.stock_zh_a_hist_tx(
    symbol=f"{'sh' if c.startswith('6') else 'sz'}{c}",
    start_date="20250801", end_date="20260615", adjust="qfq"))

# 2. 东方财富 (em) - the one README says is blocked
try:
    bench("eastmoney (em)", lambda c: ak.stock_zh_a_hist(
        symbol=c, period="daily", start_date="20250801",
        end_date="20260615", adjust="qfq"))
except Exception as e:
    print(f"  [eastmoney] SKIP: {e}")

# 3. 网易 (163)
try:
    bench("163 / netease", lambda c: ak.stock_zh_a_hist_163(
        symbol=c, start_date="20250801", end_date="20260615"))
except Exception as e:
    print(f"  [163] SKIP: {type(e).__name__}: {e}")

# 4. baostock (需登录,但免费稳定)
try:
    import baostock as bs
    lg = bs.login()
    def _bs(code):
        prefix = "sh" if code.startswith("6") else "sz"
        rs = bs.query_history_k_data_plus(
            f"{prefix}.{code}",
            "date,open,high,low,close,volume",
            start_date="2025-08-01", end_date="2026-06-15",
            frequency="d", adjustflag="2")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        import pandas as pd
        return pd.DataFrame(rows, columns=rs.fields)
    bench("baostock", _bs)
    bs.logout()
except ImportError:
    print("  [baostock] SKIP: not installed (pip install baostock)")
except Exception as e:
    print(f"  [baostock] SKIP: {type(e).__name__}: {e}")
