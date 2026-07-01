"""Verify: does fetching 60 daily bars (vs 130) actually speed up Tencent TX?"""
import time
from datetime import datetime, timedelta
import akshare as ak

CODES = ["000001", "600519", "300750", "688981", "000876",
         "600036", "002415", "601398", "000333", "300059"]


def fetch_range(code, calendar_days):
    sym = f"{'sh' if code.startswith('6') else 'sz'}{code}"
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=calendar_days)).strftime("%Y%m%d")
    df = ak.stock_zh_a_hist_tx(symbol=sym, start_date=start, end_date=end, adjust="qfq")
    return len(df) if df is not None and not df.empty else 0


# 130 trading days ≈ 180 calendar days (current: 270 days with buffer)
# 60 trading days  ≈  90 calendar days (target: 120 days with buffer)
RANGES = [
    ("130 bars (current)", 270),
    ("60 bars  (proposed)", 120),
]

for label, days in RANGES:
    t0 = time.perf_counter()
    rows_total = 0
    for code in CODES:
        try:
            rows_total += fetch_range(code, days)
        except Exception as e:
            print(f"  {code}: {type(e).__name__}")
    elapsed = time.perf_counter() - t0
    print(f"  [{label:24s}] {len(CODES)} stocks, total rows={rows_total}, "
          f"{elapsed:.2f}s  ({elapsed/len(CODES):.2f}s/stock)")
    time.sleep(2)  # cool down between scenarios
