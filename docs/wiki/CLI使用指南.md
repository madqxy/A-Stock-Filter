# CLI 使用指南

## 基本用法

```bash
# 默认参数运行
python main.py --cli

# 清除缓存后重新拉取
python main.py --cli --clear
```

## 命令行参数

### 筛选器选择

```bash
--filter FILTER_NAME
```

可选值（支持中文名或英文类型名）：
- `右侧买入` / `right_buy` - 右侧买入（默认）
- `均线多头排列` / `ma_bullish` - 均线多头排列
- `放量突破` / `volume_breakout` - 放量突破
- `止跌缩量` / `stabilize_volume_shrink` - 止跌缩量
- `止涨放量下跌` / `stall_volume_drop` - 止涨放量下跌

### 参数自定义

| 参数 | 说明 | 默认值 | 适用筛选器 |
|------|------|--------|-----------|
| `--volume-multiplier N` | 放量倍数 | 1.5 | right_buy, volume_breakout, stall_volume_drop |
| `--pe-max N` | 市盈率上限 | 9999 / 30 | right_buy, stabilize_volume_shrink |
| `--window N` | 时间窗口（日） | 10 | stabilize_volume_shrink |
| `--ma-window N` | 均线周期（日） | 20 | volume_breakout, stabilize_volume_shrink, stall_volume_drop |
| `--ma-short N` | 短期均线 | 5 | ma_bullish |
| `--ma-medium N` | 中期均线 | 20 | ma_bullish |
| `--ma-long N` | 长期均线 | 60 | ma_bullish |
| `--vs-index INDEX` | 对比基准 | csi300 | 所有 |
| `--fluctuation-pct N` | 波幅上限(%) | 3.0 | stabilize_volume_shrink |
| `--volume-ratio N` | 缩量倍数 | 0.8 | stabilize_volume_shrink |
| `--golden-mode MODE` | 金叉模式 | both | right_buy |
| `--require-downtrend BOOL` | 要求下跌趋势 | false | stabilize_volume_shrink |
| `--death-cross-mode MODE` | 死叉模式 | either | stall_volume_drop |

`--golden-mode` 可选值：`both`（双金叉）/ `either`（单金叉）。
`--require-downtrend` 可选值：`true` / `false`。
`--death-cross-mode` 可选值：`both`（双死叉）/ `either`（单死叉）/ `kdj`（KDJ死叉）/ `macd`（MACD死叉）。

### 对比基准选项

| 代码 | 指数名称 |
|------|---------|
| `csi300` | 沪深300 |
| `csi500` | 中证500 |
| `csi1000` | 中证1000 |
| `sh000001` | 上证指数 |
| `sz399001` | 深证成指 |
| `star50` | 科创50 |
| `chinext` | 创业板指数 |

## 使用示例

### 示例1：默认参数

```bash
python main.py --cli
```

使用默认筛选器（右侧买入）和默认参数运行。

### 示例2：自定义放量和PE

```bash
python main.py --cli --filter 右侧买入 --volume-multiplier 2.0 --pe-max 150
```

筛选放量2倍以上、PE在0-150之间的股票。

### 示例3：止跌缩量筛选

```bash
python main.py --cli --filter 止跌缩量 --window 30 --volume-ratio 0.6
```

筛选当前换手率/量能缩至30日均量60%以下、且止跌的股票。

### 示例4：均线多头

```bash
python main.py --cli --filter 均线多头排列 --ma-short 10 --ma-medium 30 --ma-long 60
```

筛选10日>30日>60日均线多头排列的股票。

### 示例5：对比中证1000

```bash
python main.py --cli --vs-index csi1000
```

筛选跑赢中证1000的股票。

### 示例6：组合参数

```bash
python main.py --cli --filter 右侧买入 --volume-multiplier 1.8 --pe-max 180 --golden-mode either --vs-index csi1000
```

组合多个参数：放量1.8倍、PE<180、单金叉、跑赢中证1000。

### 示例7：清除缓存重新拉取

```bash
python main.py --cli --clear
```

清除所有缓存，从头拉取数据（首次运行或数据异常时使用）。

## 输出文件

CLI 模式自动生成两个 Excel 文件：

1. **全量数据**：`stock_data_YYYYMMDD_HHMMSS.xlsx`
   - 包含所有股票的完整数据
   
2. **筛选结果**：`{filter_name}_YYYYMMDD_HHMMSS.xlsx`
   - 仅包含符合筛选条件的股票

文件保存在项目根目录。

## 性能参考

| 场景 | 耗时 |
|------|------|
| 首次运行（无缓存） | 5-10 分钟 |
| 增量更新（有缓存） | 1-3 分钟 |
| 仅筛选导出 | <10 秒 |

## 日志输出

CLI 模式在终端输出详细日志：

```
阶段1: 股票清单
阶段2: 实时行情
   过滤: 5528 → 2062 只 (剔除 3466 只 ST/退市/小市值)
阶段3: 历史 K 线
   K线诊断: 计算最新=2026-07-01, 缓存最新=2026-06-30, ...
   K线缓存清理: 删除 1234 条过期数据
阶段4: 指标计算
   [DIAG] MA数据: 5日均价有效=2050, ...
阶段5: 筛选导出
完成: 筛选出 42 只股票
```

## 故障排查

### 数据拉取失败

```
[WARN] 69/2062 stocks failed: 501 Server Error
```

- 腾讯 API 频率限制，等待几分钟后重试
- 部分股票停牌或代码异常，不影响整体结果

### MA 值为空

```
[DIAG] MA数据: 5日均价有效=99 / 共2066条
```

- 首次运行且K线数据不足，重新运行会改善
- 检查缓存是否正常：`data_cache/data/history.db`

### 内存不足

- 减少并发数（修改 `data_collector.py` 中的 `max_workers`）
- 关闭其他占用内存的程序
