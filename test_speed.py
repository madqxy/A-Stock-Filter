"""
对比测试：串行 vs 并发拉取 K 线数据
"""
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# 测试股票池（20 只真实股票）
TEST_CODES = [
    "000001", "000002", "000063", "000333", "000651",
    "000725", "000776", "000858", "002230", "002415",
    "300750", "600000", "600009", "600016", "600019",
    "600028", "600029", "600030", "600031", "600036",
]

def fetch_kline(code, start_date="20260101"):
    """直接 HTTP 请求腾讯 K 线接口"""
    prefix = "sh" if code.startswith("6") else "sz"
    sym = f"{prefix}{code}"
    end = datetime.now().strftime("%Y-%m-%d")
    start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,{start},{end},300,qfq"

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"

    r = session.get(url, timeout=10)
    data = r.json().get("data", {}).get(sym, {})
    bars = data.get("qfqday") or data.get("day") or []
    return len(bars)


def test_serial(codes):
    """串行模式：逐个请求，无间隔"""
    print(f"\n【串行测试】{len(codes)} 只股票，max_workers=1，无间隔")
    start = time.time()
    success = 0
    for i, code in enumerate(codes):
        try:
            n = fetch_kline(code)
            if n > 0:
                success += 1
        except Exception as e:
            pass
    elapsed = time.time() - start
    rate = len(codes) / elapsed if elapsed > 0 else 0
    print(f"  耗时：{elapsed:.2f}s")
    print(f"  成功：{success}/{len(codes)}")
    print(f"  速率：{rate:.1f} 只/秒")
    print(f"  平均：{elapsed/len(codes)*1000:.0f} ms/只")
    return elapsed, success


def test_concurrent(codes, max_workers=8, delay=0.1):
    """并发模式：批量请求 + 间隔"""
    print(f"\n【并发测试】{len(codes)} 只股票，max_workers={max_workers}，间隔{delay}s")
    start = time.time()
    success = 0

    def job(code):
        try:
            n = fetch_kline(code)
            return n > 0
        except:
            return False

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        items = list(codes)
        for i in range(0, len(items), max_workers):
            batch = items[i:i+max_workers]
            futures = [pool.submit(job, c) for c in batch]
            for fut in futures:
                if fut.result():
                    success += 1
            if i + max_workers < len(items):
                time.sleep(delay)

    elapsed = time.time() - start
    rate = len(codes) / elapsed if elapsed > 0 else 0
    print(f"  耗时：{elapsed:.2f}s")
    print(f"  成功：{success}/{len(codes)}")
    print(f"  速率：{rate:.1f} 只/秒")
    print(f"  平均：{elapsed/len(codes)*1000:.0f} ms/只")
    return elapsed, success


if __name__ == "__main__":
    print("=" * 60)
    print("K 线拉取速度对比测试：串行 vs 并发")
    print("=" * 60)

    # 先跑串行（避免并发触发限流影响后续测试）
    serial_time, serial_ok = test_serial(TEST_CODES)

    # 等待几秒让 API 冷却
    print("\n等待 3 秒...")
    time.sleep(3)

    # 再跑并发
    concurrent_time, concurrent_ok = test_concurrent(TEST_CODES, max_workers=8, delay=0.1)

    # 总结
    print("\n" + "=" * 60)
    print("【结论】")
    if serial_time < concurrent_time:
        print(f"✓ 串行更快 ({serial_time:.2f}s vs {concurrent_time:.2f}s)")
        speedup = concurrent_time / serial_time
        print(f"  串行比并发快 {speedup:.2f} 倍")
    else:
        print(f"✓ 并发更快 ({concurrent_time:.2f}s vs {serial_time:.2f}s)")
        speedup = serial_time / concurrent_time
        print(f"  并发比串行快 {speedup:.2f} 倍")

    print(f"\n推算 2071 只股票耗时:")
    print(f"  串行：{serial_time/len(TEST_CODES)*2071:.0f}s ({serial_time/len(TEST_CODES)*2071/60:.1f}分钟)")
    print(f"  并发：{concurrent_time/len(TEST_CODES)*2071:.0f}s ({concurrent_time/len(TEST_CODES)*2071/60:.1f}分钟)")
    print("=" * 60)
