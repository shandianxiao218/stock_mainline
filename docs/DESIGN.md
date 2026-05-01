# MVP 技术设计

## 范围

第一版 demo 是个人使用的 A 股主线雷达日度复盘系统，重点覆盖收盘后排名、解释、风险提醒、自选股/持仓风险、自然语言复盘和 Excel 导出。

MVP 和后续个人版明确不实现盘中实时监测；只做收盘复盘、历史回测和本地研究。暂不包含交易下单、公开投资建议、PDF 导出和全自动新闻解读。

## 安全约束

本系统仅供本地单人使用。HTTP 服务无认证、无加密，**不得暴露到公网或不可信局域网**。服务仅绑定 `127.0.0.1:8000`，禁止修改为 `0.0.0.0` 或其他开放绑定。本系统为个人研究辅助工具，所有数据、评分和排序仅供学习参考，不构成任何投资建议。

## 架构

```text
东方财富C导入器 / AKShare补充数据
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
| `backend/sentiment_store.py` | 融合 AKShare 东财热度排行和行情代理，输出舆情绝对热度、边际变化和过热信号 |
| `backend/cluster_store.py` | 保存自动聚合结果、主线分支组成和递增版本 |
| `backend/load_akshare_data.py` | 同步 AKShare 龙虎榜和东财热度排行数据 |
| `backend/data_quality.py` | 生成数据覆盖、数据质量和无未来函数风险检查 |
| `backend/backtest_store.py` | 保存同步/异步回测任务、状态、指标、样本和错误 |
| `backend/snapshot_store.py` | 保存榜单、矩阵、详情、风险历史、置信度历史和因子有效性快照 |
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

当前 Web 端已支持调整主公式权重和风险扣分上限，参数写入 SQLite `local_model_config`，榜单和详情计算读取当前生效配置。催化强度和催化持续性已按 S/A/B/C 等级及 20 日线性衰减入模；舆情当前为 AKShare 东财热度排行 + 行情代理增强混合，不等同完整社媒、搜索和新闻舆情。

## 性能目标

已导入 5 年以上东方财富日线后，Web 页面刷新目标为 100ms 内完成首屏核心数据返回。该目标不能依赖请求时逐日重算，必须采用以下策略：

- 数据导入或收盘任务阶段预计算主线榜单、主线详情摘要、近 20 日矩阵、置信度历史、风险历史和常用成分股指标。
- 页面刷新 API 优先读取 `local_theme_ranking_snapshot`、`local_theme_matrix_snapshot`、`local_theme_detail_snapshot`、`local_confidence_history_snapshot`、`local_risk_history_snapshot`、`local_factor_effectiveness_snapshot` 等本地快照表；请求时只做轻量筛选、排序和 JSON 组装。
- 首屏渲染不得被矩阵、因子有效性、置信度历史、审计、催化和预警等重计算模块阻塞；这些模块必须后台异步加载，失败时只影响对应面板。
- 评分引擎保留按需重算能力，用于模型调试、参数实验和回测任务，不作为页面刷新默认路径。
- SQLite 必须为 `trade_date`、`theme_id`、`sector_code`、`symbol`、`rank` 等查询路径建立索引；5 年数据导入后已经通过服务端快照读取性能检查，后续仍需覆盖冷构建和端到端浏览器渲染。
- 回测任务支持同步和 `async=true` 异步执行，不纳入 100ms 页面刷新目标。

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

AKShare 当前用于补充东方财富本地数据缺口，已接入东财热度排行和龙虎榜。Tushare 保留为备用或补充数据源，后续可用于交易日历、行业分类、指数数据等。

## 舆情策略

当前没有完整舆情供应商，但已接入 AKShare 东财热度排行。MVP 使用 `sentiment_store.enhanced_sentiment_scores` 将东财热度排行、成交放大、涨停率和涨幅融合为舆情绝对热度、边际变化和过热/背离信号；当 `ak_hot_rank_daily` 缺失时降级为行情代理。UI/API 必须标注该信号为 `akshare+proxy`，不能等同完整讨论量、搜索量或新闻提及量。

## 催化事件策略

人工催化事件保存到 `local_catalyst_event`，等级支持 S/A/B/C。评分中 S/A/B/C 基础分分别为 85/70/50/30，并按 20 日线性衰减；热度分使用当日衰减催化强度，延续性分使用近 5 日衰减均值。当前缺口是自动新闻分类、来源可信度和人工修正审计质量控制。

## 持久化

当前 demo 已使用东方财富真实日线、真实板块和成分股驱动主线评分。东方财富 C 导入器导出个股日线、股票名称、板块和成分 CSV，`backend/load_eastmoney_csv.py` 将 CSV 装载进本地 SQLite 数据库 `backend/data/radar.db`。

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
- `local_sector_snapshot_daily`：板块日度行情快照。
- `local_limit_signal_daily`：涨停、触板、炸板、连板近似信号。
- `local_theme_ranking_snapshot`：主线榜单预计算快照。
- `local_theme_matrix_snapshot`：近 20 日主线矩阵预计算快照。
- `local_theme_detail_snapshot`：主线详情预计算快照。
- `local_confidence_history_snapshot`：置信度历史预计算快照。
- `local_risk_history_snapshot`：风险历史预计算快照。
- `local_factor_effectiveness_snapshot`：因子有效性预计算快照。
- `local_snapshot_build_log`：快照构建日志。
- `local_auto_theme_cluster`：自动主线聚合结果、组成板块和版本。
- `local_backtest_run`：回测任务、异步状态、指标、样本和错误。
- `ak_hot_rank_daily`：AKShare 东财热度排行。
- `ak_dragon_tiger_daily`：AKShare 龙虎榜数据。

后续需要在此基础上补齐独立交易日历、快照失效重建队列、真实舆情供应商表、回测逐日快照稳定生成和主线阶段状态机。`docs/database.sql` 是长期 PostgreSQL 迁移草案，个人本地版本以 SQLite 为准快速迭代。

## 当前可用版本

- 主线榜单：无人工映射时从东方财富真实板块动态候选中评分输出；`GET /api/v1/themes/ranking` 默认返回前 10 个板块，`limit` 支持 `100` 和 `all`；5 年数据下优先读取预计算快照，服务端快照读取已达 100ms 内。
- 主线详情：展示评分拆解、风险信号、强分支、核心股和成分股表现。
- 持仓/自选风险：按 `backend/theme_universe.py` 中的成分代码匹配当前主线风险。
- 回测：按 SQLite 可用交易日逐日重放，排名只使用当日及以前数据，收益验证使用后续持有期数据；支持同步执行和 `async=true` 异步任务轮询。
- 复盘落库：`POST /api/v1/reviews/save?date=YYYY-MM-DD` 保存当日评分和报告。
- 主线矩阵：`GET /api/v1/themes/matrix?date=YYYY-MM-DD&days=20&limit=10` 返回近 20 个交易日主线分矩阵，默认只显示目标日期有数据的前 10 个板块；`limit` 支持 `20`、`30`、`50`、`100`、`all`。
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
- 催化事件：`GET/POST /api/v1/catalysts` 管理人工催化事件和 S/A/B/C 等级，并按等级和 20 日衰减进入热度/延续性评分。
- 数据覆盖和质量：`GET /api/v1/data/quality`、`/api/v1/data/coverage`、`/api/v1/data/no-future-guard` 返回数据质量、5 年覆盖和无未来函数风险检查。
- 自动聚合版本：`GET /api/v1/themes/auto-clusters` 查询 `local_auto_theme_cluster` 中的自动聚合版本。
- 异步任务：`GET /api/v1/tasks/status` 查询任务状态，`GET /api/v1/backtest/runs/{task_id}` 轮询异步回测结果。
- 真实板块：`GET /api/v1/sectors` 和 `GET /api/v1/sectors/{sector_code}/constituents` 查看东方财富板块与成分。
- 股票名称：`tools/eastmoney_import.c` 从东方财富 `StkQuoteList`/`StkQuoteListNsl` 读取 GBK 名称并输出 UTF-8 `stocks.csv`；名称索引按 `market + symbol` 建立，避免 `000001` 等沪深同码污染。
- Excel 导出：包含主线榜单、风险明细、置信度、复盘报告、20 日矩阵和成分股明细。

## 与 SRS 的差异决策记录

原始 SRS v1.0 文件为 `docs/a股板块主线雷达_软件需求规格说明书_v_1.md`，该文件作为需求基准保留，不直接修改。后续所有与 SRS 不一致的产品、技术或实现决策，统一记录在本章节。

| 日期 | 决策 | 与 SRS 的差异点 | 原因 | 影响范围 |
| --- | --- | --- | --- | --- |
| 2026-04-29 | 第一阶段优先使用东方财富本地客户端数据，Tushare 作为后续备用/补充源 | SRS 待确认问题中原答复为第一阶段使用 Tushare；当前实现改为东方财富优先 | 本机已有 `C:\eastmoney` 本地数据，且用户要求参考现有东方财富导入方式；可更快跑通本地数据链路 | 数据接入、导入器、后续快照入库 |
| 2026-04-29 | 东方财富二进制 `.dat` 文件只能由 C 程序读取，Python 不解析二进制 | SRS 未限定导入器语言和二进制解析边界 | 用户明确要求“读取二进制文件不要用 py，就直接用 c 实现” | 数据导入边界、后端数据读取方式 |
| 2026-04-29 | 当前 demo 使用静态 Web + Python 标准库 HTTP 服务，暂未引入完整后端框架 | SRS 只描述 API 能力，未限定框架；原建议可走 FastAPI | 降低本地启动依赖，先验证主线榜单、详情、风险、报告和 Excel 导出链路 | Demo 服务层、后续框架替换计划 |
| 2026-04-29 | 早期主线评分曾使用样例板块指标，后续已替换为东方财富真实板块动态候选 | SRS 目标是基于真实行情、板块、涨停、舆情等数据评分 | 早期用于跑通闭环；当前已由东方财富真实日线、板块、成分和快照链路替代 | 作为历史决策保留，当前实现以真实板块为准 |
| 2026-04-29 | 个人 demo 持久化优先使用本地 SQLite，长期设计保留 PostgreSQL 草案 | SRS 的数据库设计以核心表概要为主，未明确个人版落地数据库；当前实现先用 SQLite | 个人使用场景下 SQLite 部署简单、无需额外服务，适合快速跑通真实数据链路 | 持久化层、导入脚本、后续回测执行 |
| 2026-04-29 | 早期主题/成分先使用 `backend/theme_universe.py` 可维护配置，当前已由真实板块动态候选替代 | SRS 希望底层板块计算、上层主线自动聚合，并最终支持自动聚类 | 早期用于跑通真实评分闭环；当前已解析东方财富真实板块成分并接入自动聚合版本落库 | 作为历史决策保留，当前实现以 `em_sector_constituent_history` 和 `local_auto_theme_cluster` 为准 |
| 2026-04-30 | 成分股表先用日线近似“是否炸板”，游资参与字段已由 AKShare 龙虎榜补充 | SRS 要求区分触板、炸板、封板质量，并可参考龙虎榜/游资数据 | 炸板仍为日线近似；龙虎榜已在 2026-05-01 / B3 接入，席位细分待增强 | 成分股明细、风险扣分准确性、短线情绪指标 |
| 2026-04-30 | 因子有效性先输出动态权重建议，不自动改写评分因子权重 | SRS 设计了最终因子权重动态修正机制 | 当前本地样本只覆盖少量交易日，直接自动改权重容易放大样本噪声；先作为研究页面展示 | 因子分析页、后续模型配置联动 |
| 2026-04-30 | 人工催化事件先落库展示，当前已在 2026-05-01 / A1 按 S/A/B/C 等级和 20 日衰减进入评分 | SRS 期望催化强度进入热度和延续性评分 | 早期先完成可追溯事件库；当前缺口转为自动新闻分类、来源可信度和人工修正审计 | 催化页面、评分因子、后续自动分类 |
| 2026-04-30 | 东方财富真实板块成分先入库，评分暂未替换人工主题配置 | SRS 要求底层板块计算、上层主线输出 | 已解析本地板块成分，但主线聚合映射需要重新设计，直接替换会改变当前 demo 行为 | 数据导入、后续主线聚合 |
| 2026-04-30 | 无人工主线映射时，评分回退到 `theme_universe.py` 控制集合，不再全量评分 1000+ 东方财富板块 | SRS 目标是底层板块计算、上层主线自动聚合；当前 demo 仍需先保证首页、矩阵、回测可用 | 直接把所有真实板块送入逐日评分会让 20 日矩阵、置信度历史和因子有效性接口重复计算并超时，导致基础页面无法加载 | 评分引擎、主线矩阵、回测、因子分析；真实板块仍可通过板块浏览 API 查看，进入评分前需先建立主线映射或聚合裁剪 |
| 2026-04-30 | 无真实舆情源时，舆情代理分和所有因子分必须限制在 0-100；无涨停时短线情绪不再给固定底分，样例成分不足进入风险扣分 | SRS 要求因子满分 100，并强调涨停/短线情绪、板块广度和风险解释 | 发现代理舆情边际分可超过 100，且无涨停板块仍获得较高短线情绪底分，容易把小样本大市值板块排得过高 | 评分引擎、风险扣分、主线详情解释图表 |
| 2026-04-30 | 无人工主线映射时，改用内置“主线 -> 东方财富真实板块代码”白名单评分，不再使用 `theme_universe.py` 样例成分 | SRS 要求底层板块计算、上层主线输出；此前临时回退到样例配置只适合 demo | 用户要求成分来源改为东方财富真实数据；白名单映射可避免全量 1000+ 板块超时，同时让详情页显示完整真实成分 | 评分输入、主线详情、成分股列表、矩阵和回测性能 |
| 2026-05-01 | 个人版不实现盘中实时监测；5 年数据下服务端快照读取目标为 100ms 内 | SRS Phase 4 包含盘中版本，性能需求原为首页 3 秒、榜单 2 秒 | 用户明确要求实时监测不用实现，并提出 5 年数据后的页面刷新 100ms 目标；当前已通过快照读取 benchmark，后续继续补冷构建和端到端渲染 | 范围裁剪、数据导入、评分任务、API 缓存、SQLite 索引、性能测试 |
| 2026-05-01 | 无人工主线映射时，不再使用固定 7 条主线白名单，改为东方财富真实板块动态候选 | SRS 要求底层板块计算、上层主线输出；固定白名单会让页面看起来仍是模拟数据 | 用户指出矩阵仍显示早期模拟主线名；动态候选按当日成交、涨幅、广度和涨停近似筛选真实板块，并排除地域、指数、涨停池、新高池等非主线标签 | 主线榜单、20 日矩阵、详情页、回测候选池；自动聚合结果落库仍待实现 |
| 2026-05-01 | 近 20 日主线矩阵默认显示目标日期有数据的前 10 个板块，并提供 20/30/50/100/全部下拉选择 | SRS 只要求展示主线分布图和主线矩阵，未规定默认展示数量；当前真实板块候选较多，部分板块只在历史窗口局部日期有数据 | 用户反馈板块列表太多且很多日期没有数据；有限数量模式只展示目标日期有数据的板块，选择“全部”时保留完整历史覆盖 | 首页矩阵、矩阵 API、Excel 导出；Excel 仍导出全部矩阵行 |
| 2026-05-01 | 主线榜单默认显示前 10 个板块，并提供前 100 和全部下拉选择 | SRS 要求前 10 主线榜单输出，但未限制真实候选池的完整查看方式 | 真实东方财富候选板块较多，默认全量展示不利于阅读和 100ms 页面目标；保留前 100/全部用于展开检查 | 主线榜单 API、首页榜单、前端筛选；Excel 导出和复盘报告仍使用完整榜单 |
| 2026-05-01 | 首页首屏改为分阶段加载，矩阵、因子、置信度历史等重模块不再阻塞总览和榜单渲染 | SRS 未规定前端加载编排；此前所有模块并行等待导致慢接口拖垮整页 | 近 20 日矩阵冷启动仍可能需要数十秒，放在首屏 `Promise.all` 中会表现为空白页 | 首页加载流程、错误隔离；后续仍需预计算快照解决根本性能问题 |
| 2026-05-01 | 接入 AKShare 东财热度排行作为舆情增强信号 | SRS 要求完整舆情数据；当前未接入完整供应商，只用 AKShare 热度排行 + 行情代理 | 个人版先用低成本可获取数据改善舆情因子，同时明确标注来源不是完整舆情 | 舆情评分、风险过热、数据可信度展示 |
| 2026-05-01 | 接入 AKShare 龙虎榜数据并进入龙虎榜热度和游资参与字段 | SRS 要求龙虎榜和游资席位数据；当前先接 AKShare 龙虎榜，席位细分仍待增强 | 先补齐游资参与的真实数据来源，避免继续显示未接入 | 热度因子、成分股表、风险解释 |
| 2026-05-01 | 自动聚合结果保存到 `local_auto_theme_cluster` 并使用递增版本 | SRS 要求主线定义版本管理；此前自动聚合只在内存中生成 | 支持复盘解释、版本查询和后续回测绑定历史聚合版本 | 主线聚合、回测复现、审计 |
| 2026-05-01 | 回测支持 `async=true` 异步任务和任务状态轮询 | SRS 要求回测异步执行和可追溯；此前为同步 demo | 5 年数据和长周期回测不应阻塞页面请求 | 回测 API、前端轮询、任务持久化 |

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
