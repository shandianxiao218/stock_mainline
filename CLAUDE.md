# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作时提供指引。

## 项目概述

A股板块主线雷达 — 个人使用的 A 股板块主线雷达 MVP，用于日度收盘后复盘。从东方财富本地二进制文件导入真实行情数据，对板块/主线进行评分排名，通过 Web 看板展示。

**范围**：仅收盘后使用（无盘中）。个人使用（非投资建议）。本地优先，SQLite 存储。

## 常用命令

### 启动服务
```bash
python backend/server.py
```
访问 `http://127.0.0.1:8000`。

### 运行测试
```bash
cd backend && python -m unittest test_scoring -v
```
测试依赖 `backend/data/radar.db`（不存在则跳过）。测试日期硬编码为 `"2026-04-29"`，需按实际情况更新。

### 运行单个测试
```bash
cd backend && python -m unittest test_scoring.RealScoringSmokeTest.test_ranking_has_theme_scores -v
```

### 构建 C 数据导入器
```powershell
clang --target=x86_64-w64-windows-gnu --sysroot=C:\ProgramData\mingw64\mingw64 -O2 -std=c11 -Wall -Wextra -o tools\eastmoney_import.exe tools\eastmoney_import.c
```

### 导入东方财富数据
```powershell
tools\eastmoney_import.exe C:\eastmoney backend\data\eastmoney 20200101
python backend/load_eastmoney_csv.py
```
输出 `backend/data/eastmoney/stocks.csv` 和 `daily_quotes.csv`，然后装载进 SQLite。

## 架构

```
tools/eastmoney_import.c    → 读取东方财富 .dat 二进制文件 → CSV
backend/load_eastmoney_csv.py → 将 CSV 装载进 SQLite (backend/data/radar.db)
backend/real_scoring.py     → 基于 SQLite 的评分引擎（生产路径）
backend/scoring.py          → 无 SQLite 时的 demo 模式回退
backend/server.py           → ThreadingHTTPServer，API 路由，静态前端服务
frontend/                   → 静态 HTML/CSS/JS 看板
```

**数据流**：东方财富 `.dat` → C 导入器 → CSV → SQLite 装载 → 评分引擎 → HTTP API → 前端看板。

服务优先加载 `real_scoring`（需要 SQLite）；`ImportError` 时回退到 `scoring.py`（demo 数据）。板块数据优先使用 SQLite 真实板块（通过 `local_theme` 映射或 `em_sector` 直接查询），无数据时回退到 `theme_universe.py`。

## 评分公式

默认：`theme_score = 0.4 * heat_score + 0.6 * continuation_score - risk_penalty`

权重和风险上限可通过模型参数配置 API 调整，持久化在 SQLite `local_model_config` 表中。动态因子权重按 SRS 10.1 公式 `0.85 × 基础 + 0.15 × 动态` 自动应用。

## 关键模块

| 模块 | 职责 |
|---|---|
| `real_scoring.py` | 核心引擎：榜单、详情、回测、风险、置信度、K 线、因子有效性、接力断裂、舆情代理 |
| `scoring.py` | Demo 模式回退，使用样例数据 |
| `theme_universe.py` | 人工主题/成分定义（无真实板块时的回退） |
| `theme_store.py` | 主线 CRUD、映射管理、版本审计（FR-003） |
| `sector_store.py` | 真实板块查询、成分历史版本、差异对比（FR-002） |
| `sentiment_store.py` | 行情代理舆情评分、过热检测、背离检测（SRS 9.7） |
| `alert_store.py` | 预警信号检测（FR-015） |
| `model_config_store.py` | 模型参数版本管理，含动态因子权重 |
| `review_store.py` | 日度复盘结果存储 |
| `audit_store.py` | API 访问和操作审计日志 |
| `catalyst_store.py` | 新闻催化事件追踪 |
| `watchlist_store.py` | 自选股和持仓管理 |
| `permissions.py` | 角色权限：访客、普通用户、研究员、管理员、审计员 |
| `data_quality.py` | 数据完整性监控 |

## 约束

- **原始 SRS** 位于 `docs/a股板块主线雷达_软件需求规格说明书_v_1.md`，禁止修改、格式化、重命名。
- 与 SRS v1.0 不一致的产品/技术决策必须记录到 `docs/DESIGN.md` 的"与 SRS 的差异决策记录"章节。
- `MEMORY.md` 记录当前决策和长期约束；`TODO.md` 记录可执行任务。
- 每完成一个明确步骤后提交一次 Git。不提交运行产物、缓存、日志、编译 exe 或本地导出的行情数据。
- Python 3.12，pandas 是唯一的外部依赖，无 requirements 文件，需手动安装。
- 数据库为 SQLite，路径 `backend/data/radar.db`。
