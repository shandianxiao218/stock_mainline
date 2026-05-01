# API 草案

基础地址：

```text
http://127.0.0.1:8000
```

## 主线榜单

```http
GET /api/v1/themes/ranking?date=2026-04-29&period=short
```

返回日度主线榜单、模型置信度、市场摘要和排序项。

## 主线详情

```http
GET /api/v1/themes/{theme_id}/detail?date=2026-04-29
```

返回主线评分拆解、强分支、核心股、风险项、因子贡献和次日验证点。

## 资金接力断裂

```http
GET /api/v1/themes/{theme_id}/relay-break?date=2026-04-29
```

返回领涨延续率、涨停重合率、核心股偏离度、断裂信号和扣分说明。

## 自动聚合版本

```http
GET /api/v1/themes/auto-clusters?date=2026-04-29&limit=100
```

返回 `local_auto_theme_cluster` 中的自动聚合版本、主线名称、组成板块、版本号和生成时间。

## 东方财富真实板块

```http
GET /api/v1/sectors?limit=100&q=融资
GET /api/v1/sectors/{sector_code}/constituents?limit=500
GET /api/v1/sectors/{sector_code}/dates
GET /api/v1/sectors/{sector_code}/diff?from_date=2026-04-28&to_date=2026-04-29
```

返回东方财富真实板块列表、成分数量、指定板块成分股、可用成分日期和两个日期的成分差异。

## 风险明细

```http
GET /api/v1/themes/{theme_id}/risks?date=2026-04-29
```

返回风险扣分明细和触发原因。

## 风险历史

```http
GET /api/v1/themes/{theme_id}/risk-history?date=2026-04-29&days=20
```

返回单条主线近 N 日风险扣分、状态和主要风险项。

## 因子贡献

```http
GET /api/v1/themes/{theme_id}/factor-contribution?date=2026-04-29
```

返回热度、延续性和风险因子拆解。

## 日度复盘报告

```http
GET /api/v1/reports/daily?date=2026-04-29
```

返回自然语言日度复盘报告。

## 数据质量与覆盖

```http
GET /api/v1/data/quality?date=2026-04-29
GET /api/v1/data/coverage?required_years=5
GET /api/v1/data/no-future-guard
```

- `data/quality` 返回数据源状态、缺失项、快照命中和降级说明。
- `data/coverage` 返回日线覆盖起止日期、交易日数量、股票数量和是否满足 5 年覆盖。
- `data/no-future-guard` 返回回测无未来函数相关检查，包括行情读取约束、成分历史风险和聚合版本风险。

## 预警

```http
GET /api/v1/alerts?date=2026-04-29
```

返回新晋主线、排名快速上升、风险扣分快速上升、核心股炸板、资金接力断裂、舆情过热等页面内预警。

## 新闻催化事件

```http
GET /api/v1/catalysts?date=2026-04-29&limit=100
POST /api/v1/catalysts
Content-Type: application/json

{
  "trade_date": "2026-04-29",
  "theme_name": "资源涨价",
  "level": "A",
  "title": "价格上行催化",
  "source": "人工录入",
  "note": "可选备注"
}
```

保存或查看人工催化事件。等级支持 S/A/B/C。

## 自选股与持仓风险

```http
GET /api/v1/portfolio/risk?date=2026-04-29
```

返回自选股暴露、持仓暴露和高风险主线重合情况。

## 近20日主线矩阵

```http
GET /api/v1/themes/matrix?date=2026-04-29&days=20
```

返回近 N 个交易日的主线分、排名、风险和状态矩阵。

## 股票 K 线

```http
GET /api/v1/stocks/{symbol}/kline?date=2026-04-29&window=80
```

返回指定股票在目标日期之前的本地日 K 数据。

## 自选股管理

```http
GET /api/v1/watchlist
POST /api/v1/watchlist
DELETE /api/v1/watchlist/{symbol}
```

自选股保存到本地 SQLite。

## 持仓管理

```http
GET /api/v1/positions
POST /api/v1/positions
DELETE /api/v1/positions/{symbol}
```

持仓保存到本地 SQLite，并参与持仓风险提示。

## 模型参数配置

```http
GET /api/v1/model/config
POST /api/v1/model/config
Content-Type: application/json

{
  "model_version": "v1.0-local",
  "config_version": "default",
  "heat_weight": 0.4,
  "continuation_weight": 0.6,
  "risk_cap": 20
}
```

返回或保存本地模型参数版本。保存时会将热度权重和延续性权重归一化，并将该版本设为当前生效配置。

## 因子有效性

```http
GET /api/v1/factors/effectiveness?date=2026-04-29&holding_period=3
```

返回因子 5 日/20 日 IC、Rank IC、双窗口方向、基础权重、建议权重和调整动作。当前建议仅用于研究展示，不会自动改写评分权重。

## 置信度历史

```http
GET /api/v1/confidence/history?date=2026-04-29&days=20
```

返回近 N 日模型置信度、置信度分、流动性、主线分差、风险稳定性、市场广度、主线一致性和当日第一主线。

## 日志审计

```http
GET /api/v1/audit/logs?limit=100
```

返回本地审计日志，包括 API 访问、参数修改、复盘保存、回测、自选股和持仓变更。

## 权限角色

```http
GET /api/v1/auth/roles
```

返回本地角色定义和当前角色。个人版默认当前角色为 `admin`，写操作可通过请求头 `X-User-Role` 做权限校验。

## 东方财富数据源状态

```http
GET /api/v1/data/eastmoney/status
```

返回东方财富本地路径、C 导入器、源文件存在性、CSV 导出行数、SQLite 入库状态和推荐构建/导入/装载命令。Python 后端只读取 C 导出的 CSV 与 SQLite 数据库，不读取东方财富二进制文件。

当前状态中包含 `sector_constituents_csv`、`database.sector_count` 和 `database.sector_constituent_count`，用于验证东方财富真实板块成分导入情况。

## 任务状态

```http
GET /api/v1/tasks/status
```

返回快照构建、异步回测等后台任务的状态、耗时、错误和最近更新时间。

## 回测

```http
POST /api/v1/backtest/run
Content-Type: application/json

{
  "start_date": "2021-04-29",
  "end_date": "2026-04-29",
  "model_version": "v1.0",
  "holding_period": 3,
  "top_n": 5,
  "async": true
}
```

返回基于 SQLite 可用交易日的真实逐日重放结果。`async=true` 或查询参数 `?async=true` 时创建异步任务并返回 `task_id`；未传异步参数时同步返回结果。若当前只导入了部分历史，则回测区间会自动受本地数据覆盖范围限制。

Web 回测页面支持配置模型版本、起止日期、持有期和 Top N，并可将逐日样本下载为 CSV。

## 异步回测状态

```http
GET /api/v1/backtest/runs/{task_id}
GET /api/v1/backtest/runs?limit=20
```

返回异步回测任务状态、参数、指标、样本、错误信息和完成时间。

## 保存日度复盘

```http
POST /api/v1/reviews/save?date=2026-04-29
```

将当日主线评分、风险信号、模型置信度和自然语言复盘报告保存到本地 SQLite。

## 主线管理

```http
GET /api/v1/themes/manage
GET /api/v1/themes/manage/{theme_id}/history
POST /api/v1/themes/manage
POST /api/v1/themes/merge
POST /api/v1/themes/archive
```

用于本地人工主线创建、编辑、历史查看、合并和归档。写操作需要具备模型管理权限，个人版默认可通过 `X-User-Role` 指定本地角色。

## 自定义板块

```http
GET /api/v1/custom-sectors
POST /api/v1/custom-sectors
DELETE /api/v1/custom-sectors/{sector_id}
```

用于维护本地自定义板块和成分股，供研究员补充东方财富板块体系不足。

## Excel 导出

```http
GET /api/v1/export/themes.xlsx?date=2026-04-29
```

下载 Excel 文件。当前包含主线榜单、风险明细、置信度、复盘报告、20 日矩阵和成分股明细。
