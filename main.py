"""
Main entry point for the A-Stock Data Analysis Tool.

Usage:
    python main.py                    # Launch GUI
    python main.py --cli              # Run in command-line mode
    python main.py --cli --force-refresh  # Force re-fetch all K-line data
    python main.py --cli --filter ma_bullish --ma-short 10 --ma-medium 30 --ma-long 60
    python main.py --clear            # Clear all cached data
"""
import sys
from pathlib import Path


def main():
    if "--clear" in sys.argv:
        from cache import StockCache
        cache = StockCache(base_dir=Path(__file__).parent / "data_cache")
        cache.clear()
        print("缓存已清空")
        return

    if "--cli" in sys.argv:
        _run_cli()
    else:
        _run_gui()


def _run_gui():
    from gui_app import main as gui_main
    gui_main()


def _run_cli():
    """Command-line mode: 5-stage pipeline with progress."""
    import argparse
    from datetime import datetime, timezone, timedelta
    from cache import StockCache
    from data_collector import run_pipeline
    from data_exporter import filter_stocks, export_to_excel, filter_export, FILTER_REGISTRY

    parser = argparse.ArgumentParser(description="A股数据分析工具 - 命令行模式")
    parser.add_argument("--cli", action="store_true", help="运行命令行模式")
    parser.add_argument("--force-refresh", action="store_true", help="强制刷新所有 K 线数据")
    
    # Filter parameters
    parser.add_argument("--filter", type=str, default="volume_breakout_golden_profit",
                       help="筛选类型: " + ", ".join(k for k in FILTER_REGISTRY.keys()))
    parser.add_argument("--volume-multiplier", type=float, help="放量倍数 (如 1.5)")
    parser.add_argument("--pe-max", type=float, help="市盈率上限 (如 150)")
    parser.add_argument("--window", type=int, help="时间窗口天数 (如 20)")
    parser.add_argument("--ma-window", type=int, help="均线周期天数 (如 20)")
    parser.add_argument("--ma-short", type=int, help="短期均线天数 (如 5)")
    parser.add_argument("--ma-medium", type=int, help="中期均线天数 (如 20)")
    parser.add_argument("--ma-long", type=int, help="长期均线天数 (如 60)")
    parser.add_argument("--vs-index", type=str, help="对比基准 (csi300, csi1000, sh000001, sz399001)")
    
    args = parser.parse_args()

    _CST = timezone(timedelta(hours=8))

    print("=" * 60)
    print("A股数据分析工具 - 命令行模式")
    print("=" * 60)

    cache = StockCache(base_dir=Path(__file__).parent / "data_cache")

    force_refresh = args.force_refresh

    # 检查缓存状态
    market_open = cache.market_now_open()
    cache_fresh = cache.is_realtime_fresh()
    now_cst = datetime.now(_CST)
    now_str = now_cst.strftime("%H:%M")
    print(f"\n  当前时间(北京时间): 周{now_cst.isoweekday()} {now_str}")
    print(f"  交易状态: {'盘中' if market_open else '闭市'}")
    print(f"  缓存状态: {'今日闭市后数据, 直接使用' if cache_fresh else '缓存过期或缺失, 重新拉取'}")
    if force_refresh:
        print(f"  强制刷新: 是 (忽略缓存, 重新拉取全部 K 线)")
    print()

    last_msg = None

    def _progress(done: int, total: int, msg: str):
        nonlocal last_msg
        if msg and msg != last_msg:
            print(f"\n[{msg}]")
            last_msg = msg
        if total:
            print(f"\r  进度: {done}/{total} ({done*100//total}%)", end="", flush=True)

    try:
        result = run_pipeline(cache, force_refresh=force_refresh, progress_callback=_progress)
    except KeyboardInterrupt:
        print("\n\n已中断,已抓数据已落盘,下次运行自动续传")
        return

    print(f"\n\n[完成] 共 {len(result['all_data'])} 条记录")

    all_path = export_to_excel(result["all_data"])
    print(f"[导出] 全部数据: {all_path}")

    # Build filter criteria from command-line arguments
    filter_type = args.filter
    if filter_type not in [v[0] for v in FILTER_REGISTRY.values()]:
        # Try to match by display name
        for display_name, (ftype, _) in FILTER_REGISTRY.items():
            if display_name == filter_type:
                filter_type = ftype
                break
    
    # Get default criteria for this filter
    default_criteria = {}
    for display_name, (ftype, criteria) in FILTER_REGISTRY.items():
        if ftype == filter_type:
            default_criteria = criteria.copy()
            break
    
    # Override with command-line arguments
    if args.volume_multiplier is not None:
        default_criteria["volume_multiplier"] = args.volume_multiplier
    if args.pe_max is not None:
        default_criteria["pe_max"] = args.pe_max
    if args.window is not None:
        default_criteria["window"] = args.window
    if args.ma_window is not None:
        default_criteria["ma_window"] = args.ma_window
    if args.ma_short is not None:
        default_criteria["ma_short"] = args.ma_short
    if args.ma_medium is not None:
        default_criteria["ma_medium"] = args.ma_medium
    if args.ma_long is not None:
        default_criteria["ma_long"] = args.ma_long
    if args.vs_index is not None:
        default_criteria["vs_index"] = args.vs_index
    
    print(f"\n[筛选] {filter_type}")
    filtered = filter_stocks(result["all_data"], default_criteria)
    if not filtered.empty:
        path = filter_export(filtered, filter_type=filter_type)
        print(f"[导出] 筛选结果: {path}")
        cols = ["名称", "代码", "最新价", "涨跌幅", "20日均价"]
        cols = [c for c in cols if c in filtered.columns]
        print("\n符合条件的股票:")
        print(filtered[cols].to_string(index=False))
    else:
        print("没有股票符合筛选条件")


if __name__ == "__main__":
    main()
