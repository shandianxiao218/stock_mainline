# MVP 技术设计

## 范围

第一版 demo 是个人使用的 A 股主线雷达日度复盘系统，重点覆盖收盘后排名、解释、风险提醒、自选股/持仓风险、自然语言复盘和 Excel 导出。

MVP 暂不包含盘中刷新、交易下单、公开投资建议、PDF 导出和全自动新闻解读。

## 架构

```text
东方财富C导入器 / 样例数据
        |
        v
日度快照标准化
        |
        v
底层板块评分引擎
  - 热度分
  - 延续性分
  - 风险扣分
        |
        v
自动主线聚合
  - 核心股重叠
  - 关键词相似
  - 分支/类别归并
        |
        v
主线评分与置信度
        |
        +--> Web看板
        +--> API响应
        +--> Excel导出
        +--> 日度复盘文本
```

## 模块规划

| 模块 | 职责 |
| --- | --- |
| `tools/eastmoney_import.c` | 读取东方财富本地二进制日线文件并导出 CSV |
| `backend/eastmoney_data.py` | 读取 C 导出的 CSV 元信息和数据源状态 |
| `backend/server.py` | 本地 HTTP 服务、API 路由、静态 UI |
| `backend/scoring.py` | 热度、延续性、风险、置信度、自动聚合 |
| `backend/sample_data.py` | Demo 市场、板块、自选股、持仓数据 |
| `backend/tushare_adapter.py` | Tushare 后续备用入口 |
| `frontend/index.html` | Web 看板结构 |
| `frontend/styles.css` | Web 样式 |
| `frontend/app.js` | API 调用与页面渲染 |

## MVP 评分

Theme score:

```text
theme_score = 0.4 * heat_score + 0.6 * continuation_score - risk_penalty
```

Risk penalty is capped at 20. Confidence uses liquidity, top theme score spread, risk stability, market breadth, and theme consistency.

## 数据源策略

第一阶段优先使用东方财富本地客户端数据，默认路径为 `C:\eastmoney`。二进制文件读取由 C 程序 `tools/eastmoney_import.c` 负责，Python 后端只读取 C 导出的 CSV 或后续 SQLite 结果。

当前 C 导入器读取：

- `C:\eastmoney\swc8\data\SHANGHAI\DayData_SH_V43.dat`
- `C:\eastmoney\swc8\data\SHENZHEN\DayData_SZ_V43.dat`
- `StkQuoteList_V10_1.dat`、`StkQuoteList_V10_0.dat` 股票名称文件，兼容 `StkQuoteList` 与 `StkQuoteListNsl` 目录

输出：

- `backend\data\eastmoney\stocks.csv`
- `backend\data\eastmoney\daily_quotes.csv`

Tushare 保留为备用或补充数据源，后续可用于交易日历、行业分类、指数数据等。

## 舆情策略

当前没有舆情供应商。MVP 将 `sentiment_momentum`、`sentiment_heat`、`sentiment_overheat` 作为可选字段。如果缺失，模型使用中性值或通过配置降低舆情权重。

## 持久化

当前 demo 仍使用本地样例板块数据完成主线评分演示，东方财富 C 导入器已经可以导出个股日线 CSV。后续应把 CSV 装载进 SQLite/PostgreSQL，再生成板块日度快照。`docs/database.sql` 是 PostgreSQL 草案，也可改造为个人本地 SQLite。

## 与 SRS 的差异决策记录

原始 SRS v1.0 文件为 `docs/a股板块主线雷达_软件需求规格说明书_v_1.md`，该文件作为需求基准保留，不直接修改。后续所有与 SRS 不一致的产品、技术或实现决策，统一记录在本章节。

| 日期 | 决策 | 与 SRS 的差异点 | 原因 | 影响范围 |
| --- | --- | --- | --- | --- |
| 2026-04-29 | 第一阶段优先使用东方财富本地客户端数据，Tushare 作为后续备用/补充源 | SRS 待确认问题中原答复为第一阶段使用 Tushare；当前实现改为东方财富优先 | 本机已有 `C:\eastmoney` 本地数据，且用户要求参考现有东方财富导入方式；可更快跑通本地数据链路 | 数据接入、导入器、后续快照入库 |
| 2026-04-29 | 东方财富二进制 `.dat` 文件只能由 C 程序读取，Python 不解析二进制 | SRS 未限定导入器语言和二进制解析边界 | 用户明确要求“读取二进制文件不要用 py，就直接用 c 实现” | 数据导入边界、后端数据读取方式 |
| 2026-04-29 | 当前 demo 使用静态 Web + Python 标准库 HTTP 服务，暂未引入完整后端框架 | SRS 只描述 API 能力，未限定框架；原建议可走 FastAPI | 降低本地启动依赖，先验证主线榜单、详情、风险、报告和 Excel 导出链路 | Demo 服务层、后续框架替换计划 |
| 2026-04-29 | 当前主线评分仍使用样例板块指标，东方财富日线先导出为结构化 CSV | SRS 目标是基于真实行情、板块、涨停、舆情等数据评分 | 东方财富个股日线已接入，但板块成分、涨停、舆情和快照入库尚未完成 | 评分输入、回测真实性、模型验收 |

## 运行

```powershell
python backend/server.py
```

然后打开：

```text
http://127.0.0.1:8000
```
