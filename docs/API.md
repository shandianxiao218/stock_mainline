# API Draft

Base URL:

```text
http://127.0.0.1:8000
```

## Theme Ranking

```http
GET /api/v1/themes/ranking?date=2026-04-29&period=short
```

Returns daily theme ranking, confidence, market summary, and ranked items.

## Theme Detail

```http
GET /api/v1/themes/{theme_id}/detail?date=2026-04-29
```

Returns theme score breakdown, branches, core stocks, risks, factor contribution, and next-day validation points.

## Theme Risks

```http
GET /api/v1/themes/{theme_id}/risks?date=2026-04-29
```

Returns risk penalty details and triggered signals.

## Factor Contribution

```http
GET /api/v1/themes/{theme_id}/factor-contribution?date=2026-04-29
```

Returns heat, continuation, and risk components.

## Daily Report

```http
GET /api/v1/reports/daily?date=2026-04-29
```

Returns a natural-language daily review report.

## Watchlist And Portfolio Risk

```http
GET /api/v1/portfolio/risk?date=2026-04-29
```

Returns watchlist exposure, portfolio exposure, and high-risk theme overlap.

## Backtest

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

Returns a demo-shaped 5-year backtest summary. Real historical replay is a follow-up task.

## Excel Export

```http
GET /api/v1/export/themes.xlsx?date=2026-04-29
```

Downloads the theme ranking and risk details as an Excel file.

