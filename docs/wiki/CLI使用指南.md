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

可选值：
- `volume_breakout_golden_profit` - 放量双金叉盈利（默认）
- `turnover_above_max` - 当前换手率N日最高
- `turnover_below_min` - 当前换手率N日最低
- `right_corner_buy` - 右侧拐点买入
- `ma_bullish` - 均线多头排列
- `volume_breakout` - 放量突破
- `kdj_golden` - KDJ金叉
- `macd_golden` - MACD金叉

### 参数自定义

| 参数 | 说明 | 默认值 | 适用筛选器 |
|------|------|--------|-----------|
| `--volume-multiplier N` | 放量倍数 | 1.5 | volume_* |
| `--pe-max N` | 市盈率上限 | 200 | volume_breakout_golden_profit |
| `--window N` | 时间窗口（日） | 20 | turnover_* |
| `--ma-window N` | 均线周期（日） | 20 | volume_breakout, right_corner_buy |
| `--ma-short N` | 短期均线 | 5 | ma_bullish |
| `--ma-medium N` | 中期均线 | 20 | ma_bullish |
| `--ma-long N` | 长期均线 | 60 | ma_bullish |
| `--vs-index INDEX` | 对比基准 | csi300 | 所有 |

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

使用默认筛选器（放量双金叉盈利）和默认参数运行。

### 示例2：自定义放量和PE

```bash
python main.py --cli --volume-multiplier 2.0 --pe-max 150
```

筛选放量2倍以上、PE在0-150之间的股票。

### 示例3：换手率筛选

```bash
python main.py --cli --filter turnover_above_max --window 30
```

筛选当前换手率为30日最高的股票。

### 示例4：均线多头

```bash
python main.py --cli --filter ma_bullish --ma-short 10 --ma-medium 30 --ma-long 60
```

筛选10日>30日>60日均线多头排列的股票。

### 示例5：对比中证1000

```bash
python main.py --cli --vs-index csi1000
```

筛选跑赢中证1000的股票。

### 示例6：组合参数

```bash
python main.py --cli --volume-multiplier 1.8 --pe-max 180 --vs-index csi1000
```

组合多个参数：放量1.8倍、PE<180、跑赢中证1000。

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
