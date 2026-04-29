# A股板块主线雷达 Project Memory

## Product Decisions

- Phase 1 data source: Tushare.
- First release scope: daily close review only; no intraday or real-time monitoring.
- Initial theme system: automatic aggregation first, manual override can be added later.
- Sentiment vendor: none for now. MVP uses placeholders and keeps the model interface.
- Target user: personal use.
- Client: Web.
- Backtest horizon: 5 years.
- Watchlist and portfolio risk: required.
- Natural-language review report: required.
- Export: Excel required; PDF is out of current scope.

## MVP Implementation Bias

- Prefer a local runnable demo over a dependency-heavy stack.
- Use static Web UI plus a Python HTTP API for the first demo.
- Keep Tushare behind an adapter so API token and quota issues do not block demo startup.
- Use sample data to demonstrate scoring, risk explanation, automatic theme aggregation, reporting, watchlist/portfolio risk, and Excel export.

## Current Demo Boundaries

- Scoring uses deterministic sample sector metrics, not live Tushare data yet.
- Automatic aggregation uses branch/category hints, core stock overlap, and keyword similarity.
- Sentiment scores are simulated fields in sample data until a provider or scraping source is selected.
- Backtest endpoint returns a shaped MVP result for UI/API wiring; real 5-year replay is a Phase 3 task.

