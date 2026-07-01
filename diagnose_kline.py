"""Diagnose K-line fetch speed: isolate tool vs data source.

Run: python diagnose_kline.py
"""
import time
import akshare as ak
from data_collector import _fetch_kline_one, _market_prefix

SAMPLE_CODES = [
    "000001", "600519", "000858", "601398", "000333",
    "300750", "600036", "002415", "688981", "300059",
    "601012", "000568", "600276", "002230", "601888",
    "603259", "000651", "600887", "002714", "601899",
    "000002", "600900", "601318", "600309", "002475",
    "600030", "601166", "000725", "002304", "601088",
    "600837", "002594", "601288", "600000", "601668",
    "600016", "601328", "000776", "600104", "601601",
    "002607", "600048", "000661", "601818", "600050",
    "601211", "000876", "601006", "002142", "601229",
]


def main():
    print(f"Sampling {len(SAMPLE_CODES)} stocks via _fetch_kline_one (with retry)\n")
    t0 = time.perf_counter()
    ok = fail = 0
    latencies = []
    for i, code in enumerate(SAMPLE_CODES, 1):
        start = time.perf_counter()
        try:
            df = _fetch_kline_one(code)
            elapsed = time.perf_counter() - start
            if df.empty:
                fail += 1
                status = "EMPTY"
            else:
                ok += 1
                status = f"OK rows={len(df)}"
                latencies.append(elapsed)
        except Exception as e:
            elapsed = time.perf_counter() - start
            fail += 1
            status = f"EXC {type(e).__name__}: {e}"
        print(f"  {i:2d}/{len(SAMPLE_CODES)} {code} {elapsed:6.2f}s  {status}")

    total = time.perf_counter() - t0
    print(f"\n--- Summary ---")
    print(f"  total:      {total:.2f}s")
    print(f"  success:    {ok}/{len(SAMPLE_CODES)}  ({ok*100//len(SAMPLE_CODES)}%)")
    print(f"  fail:       {fail}/{len(SAMPLE_CODES)}")
    if latencies:
        latencies.sort()
        print(f"  per-stock latency (success only):")
        print(f"    min={latencies[0]:.2f}s  p50={latencies[len(latencies)//2]:.2f}s  "
              f"p90={latencies[int(len(latencies)*0.9)]:.2f}s  max={latencies[-1]:.2f}s")
    if fail:
        print(f"\nDiagnosis:")
        if fail >= len(SAMPLE_CODES) * 0.2:
            print("  [!] failure rate >= 20% -> retry backoff (0.5+1+2 = 3.5s per fail)")
            print("      is likely the dominant cost. Tool-level regression confirmed.")
        else:
            print("  failure rate low -> slowdown is mostly data-source side (Tencent slow/blocked).")
            print("      Consider switching provider or raising concurrency with rate limit.")


if __name__ == "__main__":
    main()
