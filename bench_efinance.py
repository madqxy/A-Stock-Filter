"""Benchmark efinance (EastMoney) vs current Tencent TX on the same 5 stocks."""
import time
import pandas as pd

CODES = ["000001", "600519", "300750", "688981", "000876"]

print("=== efinance (EastMoney) benchmark ===\n")

try:
    import efinance as ef
    print(f"efinance version: {ef.__version__ if hasattr(ef, '__version__') else 'unknown'}")
except ImportError as e:
    print(f"efinance not available: {e}")
    raise SystemExit(1)


def bench_efinance_single():
    """Per-stock latency via ef.stock.get_quote_history (single call)."""
    t0 = time.perf_counter()
    ok = fail = 0
    rows_total = 0
    for code in CODES:
        try:
            df = ef.stock.get_quote_history(code, beg="20250801", end="20260615")
            if df is not None and not df.empty:
                ok += 1
                rows_total += len(df)
                print(f"  {code}: {len(df)} rows, cols={list(df.columns)[:6]}")
            else:
                fail += 1
                print(f"  {code}: EMPTY")
        except Exception as e:
            fail += 1
            print(f"  {code}: ERROR {type(e).__name__}: {e}")
    elapsed = time.perf_counter() - t0
    print(f"\n  [efinance single] {ok}/{len(CODES)} ok, total rows={rows_total}, "
          f"{elapsed:.2f}s  ({elapsed/len(CODES):.2f}s/stock)")
    return elapsed / len(CODES) if ok else None


def bench_efinance_batch():
    """Batch fetch via ef.stock.get_quote_history(list)."""
    t0 = time.perf_counter()
    try:
        df = ef.stock.get_quote_history(CODES, beg="20250801", end="20260615")
        elapsed = time.perf_counter() - t0
        if df is not None and not df.empty:
            per_code = df.groupby("股票代码").size() if "股票代码" in df.columns else None
            print(f"\n  [efinance batch] rows={len(df)}, {elapsed:.2f}s  "
                  f"({elapsed/len(CODES):.2f}s/stock effective)")
            if per_code is not None:
                print(f"  rows per code: {dict(per_code)}")
            print(f"  columns: {list(df.columns)}")
            return elapsed / len(CODES)
        else:
            print(f"  [efinance batch] EMPTY after {elapsed:.2f}s")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  [efinance batch] ERROR after {elapsed:.2f}s: {type(e).__name__}: {e}")
    return None


def bench_tencent():
    """Baseline from current implementation."""
    import akshare as ak
    from data_collector import _market_prefix
    t0 = time.perf_counter()
    ok = 0
    for code in CODES:
        try:
            df = ak.stock_zh_a_hist_tx(
                symbol=f"{_market_prefix(code)}{code}",
                start_date="20250801", end_date="20260615", adjust="qfq")
            if df is not None and not df.empty:
                ok += 1
        except Exception as e:
            print(f"  tencent {code}: {type(e).__name__}: {e}")
    elapsed = time.perf_counter() - t0
    print(f"\n  [tencent tx]      {ok}/{len(CODES)} ok, {elapsed:.2f}s  "
          f"({elapsed/len(CODES):.2f}s/stock)")
    return elapsed / len(CODES) if ok else None


print("--- Test 1: efinance single-stock calls ---")
single_t = bench_efinance_single()

print("\n--- Test 2: efinance batch call ---")
batch_t = bench_efinance_batch()

print("\n--- Test 3: tencent tx baseline ---")
tencent_t = bench_tencent()

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  tencent tx (current) : {tencent_t:.2f}s/stock" if tencent_t else "  tencent: FAIL")
print(f"  efinance single      : {single_t:.2f}s/stock" if single_t else "  efinance single: FAIL")
print(f"  efinance batch       : {batch_t:.2f}s/stock (effective)" if batch_t else "  efinance batch: FAIL")
if tencent_t and single_t:
    print(f"\n  speedup (single vs tencent): {tencent_t/single_t:.1f}x")
if tencent_t and batch_t:
    print(f"  speedup (batch vs tencent) : {tencent_t/batch_t:.1f}x")
