# A股数据分析工具 - Wiki

欢迎使用 A股数据分析工具 Wiki！

## 快速导航

- [[安装指南]] - 环境配置和依赖安装
- [[GUI使用指南]] - 图形界面使用说明
- [[CLI使用指南]] - 命令行使用说明
- [[架构设计]] - 技术架构和数据流
- [[筛选策略]] - 8种筛选器详解
- [[数据源说明]] - API数据源和字段说明
- [[缓存机制]] - 三级缓存策略
- [[更新日志]] - 版本变更记录

## 项目概述

A股数据分析工具是一个基于 Python 的 A 股筛选分析工具，具备以下特性：

- **5阶段数据流水线**：股票清单 → 实时行情 → 历史K线 → 指标计算 → 筛选导出
- **智能缓存**：JSON/Parquet/SQLite 三级缓存，增量更新，滚动清理
- **8种筛选策略**：放量双金叉、换手率极值、均线多头、KDJ/MACD金叉等
- **双模式**：GUI 图形界面 + CLI 命令行
- **高性能**：腾讯HTTP直连，批量并发，比 akshare 快 20 倍

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 GUI
python main.py

# CLI 模式
python main.py --cli

# 自定义参数
python main.py --cli --volume-multiplier 2.0 --pe-max 200
```

## 系统要求

- Python 3.10+
- Windows / macOS / Linux
- 网络连接（用于拉取行情数据）
