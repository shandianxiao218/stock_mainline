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

## 风险明细

```http
GET /api/v1/themes/{theme_id}/risks?date=2026-04-29
```

返回风险扣分明细和触发原因。

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

## 自选股与持仓风险

```http
GET /api/v1/portfolio/risk?date=2026-04-29
```

返回自选股暴露、持仓暴露和高风险主线重合情况。

## 东方财富数据源状态

```http
GET /api/v1/data/eastmoney/status
```

返回东方财富本地路径、C 导入器、源文件存在性、CSV 导出行数、SQLite 入库状态和推荐构建/导入/装载命令。Python 后端只读取 C 导出的 CSV 与 SQLite 数据库，不读取东方财富二进制文件。

## 回测

```http
POST /api/v1/backtest/run
Content-Type: application/json

{
  "start_date": "2021-04-29",
  "end_date": "2026-04-29",
  "model_version": "v1.0",
  "holding_period": 3,
  "top_n": 5
}
```

返回基于 SQLite 可用交易日的真实逐日重放结果。若当前只导入了部分历史，则回测区间会自动受本地数据覆盖范围限制。

## 保存日度复盘

```http
POST /api/v1/reviews/save?date=2026-04-29
```

将当日主线评分、风险信号、模型置信度和自然语言复盘报告保存到本地 SQLite。

## Excel 导出

```http
GET /api/v1/export/themes.xlsx?date=2026-04-29
```

下载主线榜单和风险明细 Excel 文件。
