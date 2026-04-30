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
| `backend/load_eastmoney_csv.py` | 将 C 导出的东方财富 CSV 装载进本地 SQLite |
| `backend/theme_universe.py` | 当前可维护的主题/成分配置 |
| `backend/real_scoring.py` | 基于 SQLite 日线计算主线评分、风险、置信度和回测 |
| `backend/model_config_store.py` | 保存和读取本地模型参数版本 |
| `backend/review_store.py` | 保存单日复盘评分、风险、置信度和报告 |
| `backend/audit_store.py` | 保存本地审计日志 |
| `backend/catalyst_store.py` | 保存人工新闻催化和等级修正 |
| `backend/permissions.py` | 定义本地角色和权限 |
| `backend/sector_store.py` | 查询东方财富真实板块和成分股 |
| `backend/server.py` | 本地 HTTP 服务、API 路由、静态 UI |
| `backend/scoring.py` | 热度、延续性、风险、置信度、自动聚合 |
| `backend/sample_data.py` | Demo 市场、板块、自选股、持仓数据 |
| `backend/tushare_adapter.py` | Tushare 后续备用入口 |
| `frontend/index.html` | Web 看板结构 |
| `frontend/styles.css` | Web 样式 |
| `frontend/app.js` | API 调用与页面渲染 |

## MVP 评分

Theme score 默认配置：

```text
theme_score = 0.4 * heat_score + 0.6 * continuation_score - risk_penalty
```

Risk penalty is capped at 20. Confidence uses liquidity, top theme score spread, risk stability, market breadth, and theme consistency.

当前 Web 端已支持调整主公式权重和风险扣分上限，参数写入 SQLite `local_model_config`，榜单和详情计算读取当前生效配置。

## 数据源策略

第一阶段优先使用东方财富本地客户端数据，默认路径为 `C:\eastmoney`。二进制文件读取由 C 程序 `tools/eastmoney_import.c` 负责，Python 后端只读取 C 导出的 CSV 或后续 SQLite 结果。

当前 C 导入器读取：

- `C:\eastmoney\swc8\data\SHANGHAI\DayData_SH_V43.dat`
- `C:\eastmoney\swc8\data\SHENZHEN\DayData_SZ_V43.dat`
- `C:\eastmoney\swc8\data\hs_bk_crc_data_new.dat`
- `StkQuoteList_V10_1.dat`、`StkQuoteList_V10_0.dat` 股票名称文件，兼容 `StkQuoteList` 与 `StkQuoteListNsl` 目录

输出：

- `backend\data\eastmoney\stocks.csv`
- `backend\data\eastmoney\daily_quotes.csv`
- `backend\data\eastmoney\sector_constituents.csv`
- `backend\data\radar.db`

Tushare 保留为备用或补充数据源，后续可用于交易日历、行业分类、指数数据等。

## 舆情策略

当前没有舆情供应商。MVP 将 `sentiment_momentum`、`sentiment_heat`、`sentiment_overheat` 作为可选字段。如果缺失，模型使用中性值或通过配置降低舆情权重。

## 持久化

当前 demo 仍使用本地样例板块数据完成主线评分演示。东方财富 C 导入器已经可以导出个股日线 CSV，且 `backend/load_eastmoney_csv.py` 已能将 CSV 装载进本地 SQLite 数据库 `backend/data/radar.db`。

当前 SQLite 表：

- `import_batch`：导入批次记录。
- `em_stock`：东方财富股票列表。
- `em_daily_quote`：东方财富个股日线。
- `em_sector`：东方财富板块列表。
- `em_sector_constituent_history`：东方财富板块成分关系。
- `local_theme_score_daily`：本地保存的主线评分结果。
- `local_risk_signal_daily`：本地保存的风险信号。
- `local_confidence_daily`：本地保存的置信度结果。
- `local_daily_report`：本地保存的自然语言复盘报告。
- `local_watchlist`：本地自选股。
- `local_position`：本地持仓。
- `local_model_config`：本地模型参数版本。
- `local_audit_log`：本地 API、参数和人工操作审计日志。
- `local_catalyst_event`：本地新闻催化事件和人工等级。

后续需要在此基础上增加板块成分、板块行情快照、涨停情绪指标、主线评分结果、风险信号和置信度结果。`docs/database.sql` 是长期 PostgreSQL 草案，个人本地版本优先使用 SQLite 快速迭代。

## 当前可用版本

- 主线榜单：基于 `em_daily_quote` 实时计算，支持请求日期自动回退到最近可用交易日。
- 主线详情：展示评分拆解、风险信号、强分支、核心股和成分股表现。
- 持仓/自选风险：按 `backend/theme_universe.py` 中的成分代码匹配当前主线风险。
- 回测：按 SQLite 可用交易日逐日重放，排名只使用当日及以前数据，收益验证使用后续持有期数据。
- 复盘落库：`POST /api/v1/reviews/save?date=YYYY-MM-DD` 保存当日评分和报告。
- 主线矩阵：`GET /api/v1/themes/matrix?date=YYYY-MM-DD&days=20` 返回近 20 个交易日主线分矩阵。
- 成分股详情：显示全部成分股，支持按 OCHL、成交量、成交额、涨幅、近 5 日涨幅、炸板、游资参与排序。
- K 线：双击成分股后通过 `GET /api/v1/stocks/{symbol}/kline` 显示本地日 K。
- 自选股/持仓：分别使用 `local_watchlist` 和 `local_position` 持久化。
- 模型配置：`GET/POST /api/v1/model/config` 管理当前生效参数，主线评分公式即时读取。
- 因子分析：`GET /api/v1/factors/effectiveness` 计算 5 日/20 日 IC、Rank IC、双窗口方向和动态权重建议。
- 置信度历史：`GET /api/v1/confidence/history` 返回近 N 日置信度、五个拆解维度和第一主线。
- 日志审计：`GET /api/v1/audit/logs` 返回 API 访问、参数修改、复盘保存、回测和本地自选/持仓变更记录。
- 风险历史：`GET /api/v1/themes/{theme_id}/risk-history` 返回单主线近 N 日风险扣分、状态和主要风险项。
- 回测页面：支持模型版本、起止日期、持有期、Top N 参数配置和样本 CSV 下载。
- 权限角色：`GET /api/v1/auth/roles` 返回访客、普通用户、研究员、管理员、审计员权限；个人版默认本地管理员。
- 催化事件：`GET/POST /api/v1/catalysts` 管理人工催化事件和 S/A/B/C 等级。
- 真实板块：`GET /api/v1/sectors` 和 `GET /api/v1/sectors/{sector_code}/constituents` 查看东方财富板块与成分。
- Excel 导出：包含主线榜单、风险明细、置信度、复盘报告、20 日矩阵和成分股明细。

## 与 SRS 的差异决策记录

原始 SRS v1.0 文件为 `docs/a股板块主线雷达_软件需求规格说明书_v_1.md`，该文件作为需求基准保留，不直接修改。后续所有与 SRS 不一致的产品、技术或实现决策，统一记录在本章节。

| 日期 | 决策 | 与 SRS 的差异点 | 原因 | 影响范围 |
| --- | --- | --- | --- | --- |
| 2026-04-29 | 第一阶段优先使用东方财富本地客户端数据，Tushare 作为后续备用/补充源 | SRS 待确认问题中原答复为第一阶段使用 Tushare；当前实现改为东方财富优先 | 本机已有 `C:\eastmoney` 本地数据，且用户要求参考现有东方财富导入方式；可更快跑通本地数据链路 | 数据接入、导入器、后续快照入库 |
| 2026-04-29 | 东方财富二进制 `.dat` 文件只能由 C 程序读取，Python 不解析二进制 | SRS 未限定导入器语言和二进制解析边界 | 用户明确要求“读取二进制文件不要用 py，就直接用 c 实现” | 数据导入边界、后端数据读取方式 |
| 2026-04-29 | 当前 demo 使用静态 Web + Python 标准库 HTTP 服务，暂未引入完整后端框架 | SRS 只描述 API 能力，未限定框架；原建议可走 FastAPI | 降低本地启动依赖，先验证主线榜单、详情、风险、报告和 Excel 导出链路 | Demo 服务层、后续框架替换计划 |
| 2026-04-29 | 当前主线评分仍使用样例板块指标，东方财富日线先导出为结构化 CSV | SRS 目标是基于真实行情、板块、涨停、舆情等数据评分 | 东方财富个股日线已接入，但板块成分、涨停、舆情和快照入库尚未完成 | 评分输入、回测真实性、模型验收 |
| 2026-04-29 | 个人 demo 持久化优先使用本地 SQLite，长期设计保留 PostgreSQL 草案 | SRS 的数据库设计以核心表概要为主，未明确个人版落地数据库；当前实现先用 SQLite | 个人使用场景下 SQLite 部署简单、无需额外服务，适合快速跑通真实数据链路 | 持久化层、导入脚本、后续回测执行 |
| 2026-04-29 | 当前主题/成分先使用 `backend/theme_universe.py` 可维护配置 | SRS 希望底层板块计算、上层主线自动聚合，并最终支持自动聚类；当前尚未解析东方财富真实板块成分 | 东方财富个股日线已可用，但板块成分二进制/本地文件解析尚未完成；先用配置跑通真实评分闭环 | 主线成分来源、评分覆盖范围、自动聚合质量 |
| 2026-04-30 | 成分股表先用日线近似“是否炸板”，游资参与显示为“未接入” | SRS 要求区分触板、炸板、封板质量，并可参考龙虎榜/游资数据 | 当前只接入东方财富日线，尚无逐笔/触板/龙虎榜数据；先把字段和交互打通，后续接真实数据源 | 成分股明细、风险扣分准确性、短线情绪指标 |
| 2026-04-30 | 因子有效性先输出动态权重建议，不自动改写评分因子权重 | SRS 设计了最终因子权重动态修正机制 | 当前本地样本只覆盖少量交易日，直接自动改权重容易放大样本噪声；先作为研究页面展示 | 因子分析页、后续模型配置联动 |
| 2026-04-30 | 人工催化事件先落库展示，暂不自动影响评分 | SRS 期望催化强度进入热度和延续性评分 | 当前事件来源为人工录入，尚未建立主题归因质量控制；先完成可追溯事件库 | 催化页面、后续评分接入 |
| 2026-04-30 | 东方财富真实板块成分先入库，评分暂未替换人工主题配置 | SRS 要求底层板块计算、上层主线输出 | 已解析本地板块成分，但主线聚合映射需要重新设计，直接替换会改变当前 demo 行为 | 数据导入、后续主线聚合 |
| 2026-04-30 | 无人工主线映射时，评分回退到 `theme_universe.py` 控制集合，不再全量评分 1000+ 东方财富板块 | SRS 目标是底层板块计算、上层主线自动聚合；当前 demo 仍需先保证首页、矩阵、回测可用 | 直接把所有真实板块送入逐日评分会让 20 日矩阵、置信度历史和因子有效性接口重复计算并超时，导致基础页面无法加载 | 评分引擎、主线矩阵、回测、因子分析；真实板块仍可通过板块浏览 API 查看，进入评分前需先建立主线映射或聚合裁剪 |
| 2026-04-30 | 无真实舆情源时，舆情代理分和所有因子分必须限制在 0-100；无涨停时短线情绪不再给固定底分，样例成分不足进入风险扣分 | SRS 要求因子满分 100，并强调涨停/短线情绪、板块广度和风险解释 | 发现代理舆情边际分可超过 100，且无涨停板块仍获得较高短线情绪底分，容易把小样本大市值板块排得过高 | 评分引擎、风险扣分、主线详情解释图表 |
| 2026-04-30 | 无人工主线映射时，改用内置“主线 -> 东方财富真实板块代码”白名单评分，不再使用 `theme_universe.py` 样例成分 | SRS 要求底层板块计算、上层主线输出；此前临时回退到样例配置只适合 demo | 用户要求成分来源改为东方财富真实数据；白名单映射可避免全量 1000+ 板块超时，同时让详情页显示完整真实成分 | 评分输入、主线详情、成分股列表、矩阵和回测性能 |

## 运行

```powershell
python backend/server.py
```

然后打开：

```text
http://127.0.0.1:8000
```

## 本地测试

```powershell
python backend/test_scoring.py
```

该烟测依赖 `backend/data/radar.db`，覆盖榜单评分、风险上限、置信度组件、主线矩阵和因子有效性。
