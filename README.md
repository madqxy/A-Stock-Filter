# A股数据分析工具

A-share stock screening & analysis tool. 5-stage pipeline with smart caching, 5 filter types, CLI + GUI.

## Quick Start

```bash
python main.py           # Launch GUI
python main.py --cli     # CLI mode: collect + export all data
python main.py --clear   # Clear all caches
```

Or double-click `启动工具.bat`.

### CLI with Custom Parameters

```bash
# Use default parameters
python main.py --cli

# Custom volume multiplier and PE limit
python main.py --cli --volume-multiplier 2.0 --pe-max 200

# Change comparison index to CSI500
python main.py --cli --vs-index csi500

# Custom MA periods for ma_bullish filter
python main.py --cli --filter 均线多头排列 --ma-short 10 --ma-medium 30 --ma-long 60

# Use 止跌缩量 filter with downtrend requirement
python main.py --cli --filter 止跌缩量 --require-downtrend true

# Combine multiple parameters
python main.py --cli --volume-multiplier 1.8 --pe-max 180 --vs-index csi1000
```

**Available parameters**: `--volume-multiplier`, `--pe-max`, `--window`, `--ma-window`, `--ma-short`, `--ma-medium`, `--ma-long`, `--vs-index`, `--filter`, `--fluctuation-pct`, `--volume-ratio`, `--require-downtrend`, `--golden-mode`

## Pipeline (5 Stages)

| Stage | Description | Data Source |
|---|---|---|
| **1. 股票清单** | Fetch ~5500 A-share codes | `akshare.stock_info_a_code_name()` |
| **2. 实时行情** | Realtime quotes + ST/退市/市值<80亿 filter | Tencent batch API (`qt.gtimg.cn`) |
| **3. 历史K线** | ~168 trading days daily K-line, batch mode (4 workers + 0.1s delay) | Tencent HTTP direct (`web.ifzq.gtimg.cn`) |
| **4. 指标计算** | MA5/10/20/60/120, volume MA (万手), turnover extremes (5/10/20/30/60日), daily amplitude (5/10/20/30/60日), KDJ/MACD golden cross, total shares caching | Computed from K-line + realtime |
| **5. 筛选导出** | Apply filter (customizable parameters) + export to Excel | |

**第二运行** (cached): 跳过已缓存数据,仅补最新交易日。盘中拉取的数据闭市后自动重新拉取收盘价。

## Filters (5 Types)

所有过滤器支持参数自定义（GUI参数设置对话框 / CLI命令行参数）。

| Filter | Logic | Customizable Parameters |
|---|---|---|
| **右侧买入** | 价>MA20, MA5>MA20, 量>N倍均量, KDJ/MACD金叉(可配置双/单), PE>0且<上限, 跑赢大盘 | 金叉模式(双/单), 放量倍数, 市盈率上限, 对比基准 |
| **均线多头排列** | MA短期 > MA中期 > MA长期, 跑赢大盘 | 短/中/长期均线天数, 对比基准 |
| **放量突破** | 价>MA, 量>N倍均量, 跑赢大盘 | 放量倍数, 均线周期, 对比基准 |
| **止跌缩量** | 盈利(PE>0且<上限), 止跌(N日波幅<阈值), 缩量(量<倍数×均量), 可选要求下跌趋势 | 市盈率上限, 均线周期, 时间窗口, 波幅上限, 缩量倍数, 要求下跌趋势(是/否) |
| **止涨放量下跌** | MA5<MA(止涨), 价<MA, 跌幅<0, 量>N倍均量(放量下跌) | 放量倍数, 均线周期 |

**对比基准选项**: 沪深300, 中证500, 中证1000, 上证指数, 深证成指, 科创50, 创业板指数

## Data Columns

| Column | Description |
|---|---|
| `代码`, `名称` | Stock code & name |
| `最新价`, `涨跌幅` | Price & change % |
| `5/10/20/60/120日均价` | Moving averages (daily bars) |
| `市盈率(TTM)`, `市值(亿)` | PE ratio, market cap (100M yuan) |
| `最新成交量(万手)` | Volume (10k lots, 1万手=10,000手) |
| `5/30日平均成交量(万手)` | Avg volume (10k lots) |
| `最新换手率` | Turnover rate % |
| `5/10日换手率(高/低)` | Turnover rate extremes (displayed) |
| `20/30/60日最高换手率`, `20/30/60日最低换手率` | Turnover rate extremes (computed, for filtering) |
| `5/10/20/30/60日最大日波幅` | Max daily amplitude (computed, for filtering, hidden from display) |
| `KDJ金叉`, `MACD金叉` | Golden cross signals (bool) |

## Architecture

```
main.py ──► run_pipeline()
               ├── Stage 1: get_stock_list() ──► stock_list.json
               ├── Stage 2: get_realtime_quotes() ──► realtime_YYYYMMDD.parquet
               │              └── Tencent batch API (qt.gtimg.cn, 100 stocks/batch)
               ├── Stage 2.5: filter ST/退市/市值<80亿
               ├── Stage 3: get_kline_batch() ──► SQLite (history.db)
               │              └── Tencent HTTP direct (web.ifzq.gtimg.cn)
               │              └── Batch mode: 4 workers + 0.1s delay (rate limiting)
               │              └── Incremental rolling fetch (only missing dates)
               │              └── Rolling cache cleanup (trim_kline, keep 200 bars)
               ├── Stage 4: compute_indicators()
               │              └── Load full K-line history from cache
               │              └── Volume unit: 手 (lots) → 万手 (10k lots)
               │              └── Total shares caching (SQLite stock_info table)
               │              └── Turnover extremes: 5/10/20/30/60 days
               │              └── Daily amplitude: 5/10/20/30/60 days
               │              └── Fallback: fill missing realtime data from K-line
               └── Stage 5: filter_stocks() + export_to_excel()
                              └── Customizable parameters (GUI dialog / CLI args)
                              └── Index rows hidden from display (used for benchmark)

gui_app.py ──► tkinter GUI (pagination, progress, double-click 10jqka, parameter settings)
```

## Caching

| Data | Backend | Freshness |
|---|---|---|
| Stock list | JSON | 7-day TTL |
| Realtime | Parquet (dated) | Market hours: use cache; closed: refetch if cached during market hours (before 15:05) |
| K-line | SQLite | Incremental rolling: only fetch missing dates, append-only mode, auto-cleanup (keep 200 bars per stock) |
| Total shares | SQLite (stock_info table) | Cached for reliable turnover calculation, updated when realtime data available |

**Cache validation**: `is_realtime_fresh()` checks file modification time. If market is closed but cache was saved during market hours, triggers refetch to get closing prices.

**Rolling cleanup**: `trim_kline()` keeps only the last 200 K-line bars per stock, preventing unbounded database growth.

## Dependencies

```
akshare>=1.13.0, pandas>=2.0.0, numpy>=1.24.0, xlsxwriter>=3.1.0,
openpyxl>=3.1.0, pyarrow>=14.0.0, tenacity>=8.2.0,
requests>=2.31.0
```

Dev-only: `pip install -r requirements-dev.txt` (adds pytest).

## Testing

```bash
pytest tests/     # 47 tests
```

## Recent Improvements (2026-07-02)

### Filter Consolidation

| Change | Description |
|---|---|
| **5 filters** | Consolidated from 8 to 5 filters, removed redundant ones |
| **右侧买入** | Merged "放量双金叉盈利" and "右侧拐点买入", added golden_mode parameter (双金叉/单金叉) |
| **止跌缩量** | Merged "左侧拐点买入" and "盈利止跌缩量", added require_downtrend parameter |
| **止涨放量下跌** | New filter for bearish reversal signal |
| **Removed** | KDJ金叉, MACD金叉 (standalone), 当前换手率N日最高/最低 |

### MA10 Addition

| Change | Description |
|---|---|
| **MA10 calculation** | Added 10-day moving average calculation and display |
| **MA periods** | Now calculate MA5, MA10, MA20, MA60, MA120 |

### GUI Parameter Improvements

| Change | Description |
|---|---|
| **All parameters configurable** | All filter parameters now have appropriate input controls |
| **Dropdowns** | vs_index, window, ma_window, ma_short/medium/long, golden_mode, require_downtrend |
| **Text inputs** | volume_multiplier, pe_max, fluctuation_pct, volume_ratio |
| **Removed invalid options** | ma_period dropdown no longer includes 30天 (we don't calculate MA30) |

## Recent Improvements (2026-07-01)

### K线缓存与MA计算修复

| Change | Description |
|---|---|
| **Stage 4 从缓存加载完整K线** | 增量拉取只获取新数据，MA计算从缓存加载完整历史，避免重复拉取 |
| **滚动缓存清理** | `trim_kline()` 每只股票保留最近200根K线，自动清理陈旧数据 |
| **日期逻辑修复** | `effective_latest = max(计算最新, 缓存最新)` 处理节假日/特殊交易日 |
| **实时数据回退** | 非交易时间实时数据缺失时，从K线补充成交量，从总股本×价格计算市值 |

### GUI优化

| Change | Description |
|---|---|
| **指数行不在GUI显示** | 4个指数（上证/深证/沪深300/中证1000）保留用于筛选基准比对，但不在表格和导出中显示 |
| **列名统一** | 指数行与股票行使用相同列名（市值(亿)、最新成交量(万手)），消除重复列 |

### Bug Fixes (2026-07-01)

| Bug | Symptom | Fix |
|---|---|---|
| **MA值首次运行为空** | 增量拉取只返回1根K线，无法计算MA | Stage 4 从缓存加载完整历史数据 |
| **GUI出现重复列** | "市值"和"市值(亿)"同时出现，前者为空 | 统一指数行列名与股票一致 |
| **非交易时间数据缺失** | 市值、成交量在GUI为空 | 从K线和缓存总股本补充 |
| **501错误(start>end)** | 增量拉取日期构造错误 | 添加 `next_day > today` 保护 |
| **trim_kline卡死** | 关联子查询O(n²)性能问题 | 改为逐股票DELETE+OFFSET |

## Recent Improvements (2026-06-19)

### Performance Optimization

| Change | Before | After | Impact |
|---|---|---|---|
| **Direct HTTP for K-line** | akshare wrapper (~2s/stock) | Direct Tencent API (~0.1s/stock) | 20x faster |
| **Batch mode with rate limiting** | 12 workers, no delay | 4 workers + 0.1s delay | Avoids rate limiting, more reliable |
| **Unified Tencent data source** | Sina (realtime) + Tencent (K-line) | Tencent only | Consistent data, simpler architecture |
| **Incremental rolling fetch** | Re-fetch 60-120 days every run | Only fetch missing dates | 90%+ reduction in daily fetch volume |

### Data Quality

| Feature | Description |
|---|---|
| **Volume unit standardization** | All volume data in 万手 (10k lots), no more unit confusion |
| **Total shares caching** | Reliable turnover calculation, works even when realtime unavailable |
| **Closing price refetch** | Auto-refetch after market close if cached during market hours |
| **Extended turnover windows** | 5/10/20/30/60 days (5/10 displayed, all available for filtering) |
| **MA columns** | Changed from 12周/24周均价 to 60日/120日均价 (standard technical analysis) |

### User Experience

| Feature | Description |
|---|---|
| **GUI parameter settings** | Dialog for customizing filter parameters (dropdowns for discrete options) |
| **CLI parameter support** | Command-line arguments for all customizable parameters |
| **7 index options** | CSI300, CSI500, CSI1000, Shanghai Composite, Shenzhen Component, STAR50, ChiNext |
| **Better cache validation** | File modification time check, prevents using intraday data as closing prices |

### Bug Fixes

| Bug | Fix |
|---|---|
| **Volume unit mismatch** | Tencent APIs return 手 (lots), not 股 (shares). Fixed conversion logic |
| **Turnover rate = 0** | Small volumes rounded to 0 when converted to 亿股. Changed to 万手 unit |
| **Warning not visible** | Added warning for high failure rate (>50%) with detailed breakdown |
| **GUI shows stale data** | Improved cache freshness check to detect intraday vs post-close data |
| **MA data empty on holidays** | Probe one stock to detect new trading day: skip refetch if no new data, works for any holiday length |
