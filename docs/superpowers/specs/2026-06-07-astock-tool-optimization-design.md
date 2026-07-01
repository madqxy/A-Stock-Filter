# A股数据分析工具 — 全线优化设计

**日期**: 2026-06-07
**项目路径**: `D:\AI-Projects\A股数据分析\`
**状态**: Approved → 进入实施计划

## 1. 背景与目标

当前工具已能用,但存在 **4 个 P0 Bug**(会导致程序崩溃或数据错乱)、**1 个未声明的依赖**(`akshare` 在 `requirements.txt` 但代码未用)、**5+ 分钟串行抓取**、**断网后无任何恢复**。本设计在不破坏现有 CLI/GUI 入口的前提下完成全线优化。

**目标**:
- 修复全部 4 个 P0 Bug。
- 数据源切换到 akshare(在受限网络下稳定性显著优于手写腾讯 HTTP)。
- 引入 SQLite 缓存,二次运行从 ~5min 压到 <30s。
- 5 阶段管道化,每阶段独立可调用,带进度回调。
- 全量加 `logging`,并修复 Excel 导出把数字存成字符串的副作用。
- 加单元测试覆盖解析/指标/筛选/缓存。

**非目标(YAGNI)**:
- 不引入 Web UI / 图表 / 自选股管理 / 自动刷新定时器(后续可单独 spec)。
- 不重写为 PyQt,继续用 tkinter。
- 不引入数据库迁移工具,SQLite schema 用 `CREATE TABLE IF NOT EXISTS` 幂等创建。

## 2. 架构

### 2.1 五阶段管道

```
[1] 股票代码清单 ──→ cache.py(stock_list.json, TTL=7d)
        ↓
[2] 实时行情批量 ──→ cache.py(realtime_<YYYYMMDD>.parquet, TTL=当日)
        ↓
[3] 历史 K 线分批 ──→ cache.py(SQLite kline 表, 永久)
        ↓
[4] 指标计算(MA20/60/120, 5/30 日量均线, 5/30 日换手率极值)
        ↓
[5] 筛选 + 导出 Excel
```

每个阶段签名: `stage_X(input, cache, progress_callback) -> (df, stats)`,失败不中断整体,错误累加到 `stats["errors"]`。

### 2.2 文件结构

保持现有 4 文件 + 新增 `cache.py`:

```
D:\AI-Projects\A股数据分析\
├── main.py             # 入口,CLI 模式调统一管线,GUI 模式调 gui_app
├── data_collector.py   # akshare 封装 + 5 阶段函数 + run_pipeline
├── data_exporter.py    # xlsxwriter 导出 + filter 统一入口
├── gui_app.py          # tkinter,接 progress_callback
├── cache.py            # 【新】StockCache: SQLite + parquet
├── requirements.txt    # +akshare, +tenacity, +xlsxwriter, +pyarrow, +requests
├── tests/              # 【新】pytest
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_indicators.py
│   ├── test_filters.py
│   ├── test_cache.py
│   └── test_parser.py
└── docs/superpowers/specs/2026-06-07-astock-tool-optimization-design.md
```

## 3. 关键模块设计

### 3.1 `cache.py`(新)

**`class StockCache`**,封装:

- `data/` 目录(相对于项目根):
  - `stock_list.json` — 股票代码清单,带 `fetched_at` 字段,7 天 TTL。
  - `realtime_YYYYMMDD.parquet` — 当日实时行情,日期切换即失效。
- `data/history.db` — SQLite:
  - 表 `kline(code TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL, volume REAL, PRIMARY KEY(code, date))`。

**方法**:

| 方法 | 签名 | 行为 |
|---|---|---|
| `get_stock_list(force_refresh=False)` | `() -> list[str]` | TTL 内返回缓存,否则调 akshare 拉 |
| `save_realtime(df, date=None)` | `(df, date) -> Path` | 落 parquet |
| `load_realtime(date=None)` | `(date) -> Optional[DataFrame]` | None=今日 |
| `is_realtime_fresh()` | `() -> bool` | 当日文件存在且非空 |
| `get_kline(code)` | `(code) -> DataFrame` | 读 SQLite,空表示未抓 |
| `save_kline(code, df)` | `(code, df) -> None` | 写 SQLite,`INSERT OR REPLACE` |
| `has_kline(code)` | `(code) -> bool` | 至少 1 行即视为有 |
| `completed_codes()` | `() -> set[str]` | 所有有 K 线数据的 code |

**`run_pipeline` 启动时**:
- 调 `completed_codes()` 得到"已完成的 code 集合",只在剩余 code 上跑阶段 3。

### 3.2 `data_collector.py`(重写)

**移除**: `_generate_a_stock_codes`、`_fetch_tencent_batch`、`_parse_tencent_line`、`get_index_realtime`(旧的 HTTP 版本)、`get_stock_history_tencent`、`get_index_history`(旧版)。

**新增**:

```python
def get_stock_list(progress_callback=None) -> pd.DataFrame
def get_realtime_quotes(progress_callback=None) -> pd.DataFrame
def get_kline_batch(codes: list[str], progress_callback=None,
                    max_workers=8) -> dict[str, pd.DataFrame]
def compute_indicators(realtime_df: pd.DataFrame,
                       kline_map: dict[str, pd.DataFrame],
                       progress_callback=None) -> pd.DataFrame
def get_index_quotes() -> pd.DataFrame
def get_index_kline(code: str) -> pd.DataFrame
def run_pipeline(cache: StockCache,
                 force_refresh: bool = False,
                 progress_callback=None) -> dict
```

**关键实现要点**:

1. **股票清单**:`akshare.stock_info_a_code_name()` 单次调用,过滤掉 ST(可选)、退市、停牌。
2. **实时行情**:`akshare.stock_zh_a_spot()` 单次调用全市场。返回字段映射到本项目列名。
3. **历史 K 线**:`akshare.stock_zh_a_hist(symbol=code, period='daily', adjust='qfq')`,**`ThreadPoolExecutor(max_workers=8)`** 并发,每只股票用 `tenacity.Retry(stop=3, wait=exponential 0.5/1/4)` 包一层。失败计入 `stats["kline_failures"]`。
4. **重试装饰器**:
   ```python
   @retry(stop=stop_after_attempt(3),
          wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
          retry=retry_if_exception_type((requests.RequestException, KeyError)),
          reraise=True)
   ```
5. **进度回调签名**(统一三段式):
   ```python
   progress_callback(done: int, total: int, message: str = "")
   ```
   - `done/total` 给进度条
   - `message` 给日志

6. **市值单位**:akshare 行情接口返回"市值"字段单位是**元**。存到表里时**保持原样(元)**,Excel 导出时按用户偏好格式化(默认"亿元",保留 2 位小数)。这是当前代码混淆的根因(腾讯字段 44 注释和代码逻辑矛盾),切到 akshare 后**只在一处定义**单位换算。

### 3.3 `data_exporter.py`(重写)

**修复**:

- `_format_for_export` 不再把数值列转字符串。改为返回 `(df, format_map)`,`format_map` 是 `{列名: xlsxwriter 数字格式}`。
- `export_to_excel(df, filepath, format_map=None)` 内部用 `pd.ExcelWriter(engine='xlsxwriter')` + `worksheet.set_column()` + `cell_format = workbook.add_format({'num_format': '0.00%'})`。
- `_get_csi300_change` 改为精确匹配 `df["代码"] == "000300"`。
- 新增 `filter_stocks(df, criteria: dict) -> DataFrame`,统一入口。`criteria` 格式:
  ```python
  {"type": "price_below_ma", "ma_window": 20, "vs_index": "csi300"}
  {"type": "turnover_above_max", "window": 30, "vs_index": "csi300"}
  {"type": "turnover_below_min", "window": 30, "vs_index": "csi300"}
  ```
  GUI 用 3 个 Radiobutton 选 type,CLI 默认用 price_below_ma20 vs csi300。

### 3.4 `gui_app.py`(修)

- `self.current_filter: str = "filter1"` 解决 P0 #1。
- `self.is_collecting: bool` 解决 P0 #7 防重入。
- 进度条分配:阶段 1-2 占 5%,阶段 3(历史 K 线)占 90%,阶段 4-5 占 5%。
- 日志:阶段切换打 `[1/5] 获取股票清单...` 这种行,阶段 3 内部每 50 只打一行。
- Treeview 默认只显示前 200 行,加「加载更多」按钮翻页 200 行。
- 启动时调 `cache.is_realtime_fresh()` + `cache.completed_codes()` 提示"今日已缓存 N 只股票,继续抓取剩余 M 只"。

### 3.5 `main.py`(修)

- 删 `__import__("pandas")`,顶部 import pandas。
- `_run_cli` 调 `run_pipeline(StockCache(), progress_callback=_cli_progress)`。
- `_cli_progress(done, total, msg)` 打印 `\r[3/5] 历史 K 线: {done}/{total} {msg}`,完成后 `\n`。
- 捕获 `KeyboardInterrupt`,打印"已中断,已抓数据已落盘,下次运行自动续传"。

### 3.6 `requirements.txt`(更新)

```
akshare>=1.13.0
pandas>=2.0.0
openpyxl>=3.1.0
xlsxwriter>=3.1.0
pyarrow>=14.0.0
tenacity>=8.2.0
requests>=2.31.0
pytest>=7.4.0
```

## 4. 数据流详图

```
run_pipeline(cache, force_refresh=False, progress_cb=None)
│
├─ 阶段 1: codes = cache.get_stock_list(force_refresh)
│           progress_cb(1, 5, f"获取股票清单: {len(codes)} 只")
│
├─ 阶段 2: if not cache.is_realtime_fresh() or force_refresh:
│              realtime = get_realtime_quotes(progress_cb)
│              cache.save_realtime(realtime)
│           else:
│              realtime = cache.load_realtime()
│           progress_cb(2, 5, f"实时行情: {len(realtime)} 只")
│
├─ 阶段 3: pending = set(codes) - cache.completed_codes()
│           if force_refresh: pending = set(codes)
│           kline_map = get_kline_batch(list(pending), progress_cb)
│           # progress_cb 在阶段内映射到 done/total,前缀 "历史 K 线"
│           # 每只股票完成后立刻 cache.save_kline(code, df),不攒批
│
├─ 阶段 4: kline_map += {c: cache.get_kline(c) for c in codes - pending}
│           indicators = compute_indicators(realtime, kline_map, progress_cb)
│           index_df = build_index_block()  # 包含 4 个指数的实时+MA
│
└─ 阶段 5: combined = concat([index_df, indicators])
           filtered = filter_stocks(combined, criteria)
           all_path = export_to_excel(combined, "all", criteria=None)
           filtered_path = export_to_excel(filtered, "filtered", criteria)
           return {"all": all_path, "filtered": filtered_path,
                   "stats": stats}
```

## 5. 错误处理

- **网络层**:`tenacity` 重试 3 次 + 指数退避 (0.5s, 1s, 4s)。
- **解析层**:akshare 返回结构变化时 `KeyError` 走重试,3 次后跳过该 code,记入 `stats["parse_failures"]`。
- **阶段内**:任何异常被 `run_pipeline` 顶层 `try/except Exception` 兜住,阶段状态标 `partial`,继续下一阶段。
- **持久化保护**:阶段 3 每只股票 `save_kline` 一次,SQlite 写入瞬时(<10ms),中断后最多丢 1 只。
- **CLI 中断**:`KeyboardInterrupt` 捕获后调 `sys.exit(0)`,不清缓存。
- **GUI 中断**:`daemon=True` 线程 + `try/finally` 恢复按钮状态(其实靠 `after` 切回主线程清理,finally 仅作保险)。

## 6. 测试策略

| 文件 | 覆盖 | 用例 |
|---|---|---|
| `test_indicators.py` | `compute_indicators` 纯函数 | 数据不足 20 天 → MA20=None;刚好 20 天 → 等于均值;120 天同理。换手率极值边界。 |
| `test_filters.py` | `filter_stocks` | 沪深300 涨跌幅为 0/为负/为正 三种场景;空 DF;涨跌为 None 的处理。 |
| `test_cache.py` | `StockCache` | 用 `tmp_path` fixture。`save_kline`+`get_kline` 往返;`has_kline`;`completed_codes`;`is_realtime_fresh` 日期切换。 |
| `test_parser.py` | 解析纯函数 | 样例 line 解析(即使切了 akshare,旧解析函数也保留作回归)。 |
| `conftest.py` | fixture | `tmp_cache(tmp_path)` 返回初始化好的 `StockCache`;`sample_realtime` / `sample_kline` DataFrame。 |

**验收命令**:
```bash
pytest tests/ -v
python main.py --cli   # < 2min 首次, < 30s 二次
```

## 7. 风险与回滚

- **akshare 字段变化**:akhare 大版本升级可能改字段名。`get_realtime_quotes` 内部加一层 `df.rename(columns={...})` 映射,字段名变化只需改映射表一处。
- **akshare 在受限网络下仍超时**:如果实 akshare 也不行,`get_realtime_quotes` / `get_kline_batch` 保留 hook,后续可加 akshare → 腾讯兜底,本设计**不实现**。
- **SQLite 并发写**:akshare + ThreadPoolExecutor 多线程同时写 SQLite,`sqlite3` 默认 `check_same_thread=True`,需在连接里设 `check_same_thread=False`,并用 `threading.Lock` 串行化写入。本设计在 `StockCache.__init__` 里建锁,所有写方法 `with self._lock:`。

## 8. 实施顺序(writing-plans 会展开为详细任务)

1. 加 `cache.py` 骨架 + `tests/test_cache.py`,先 TDD 通过存储层。
2. 重写 `data_collector.py` 的 5 个阶段函数,逐个加单测。
3. 重写 `data_exporter.py` 统一 filter + xlsxwriter 格式化。
4. 修 `gui_app.py` 的 4 个 P0 + 接 progress_callback。
5. 修 `main.py` 调统一管线。
6. 更新 `requirements.txt`。
7. 端到端跑 `--cli` 和 GUI,确认验收标准。
